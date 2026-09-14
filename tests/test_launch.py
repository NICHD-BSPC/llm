# WARNING: AI generated. The models used this for updating tests as they
# worked. They remain un-reviewed, but retained with the assumption that they
# will act as regression tests if something changes.
#
# Since GitHub CI (where these tests are run) has no access to any secrets
# anyway and can't test auth, I consider this low risk.
import contextlib
import io
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launch


class LaunchAwsEnvTests(unittest.TestCase):
    def make_launcher(self, *argv):
        return launch.Launcher(launch.parse_args(list(argv)))

    def write_managed_bundle(self, root, *, credentials=None, config=None, mode=0o600):
        bundle_dir = Path(root) / ".aws" / "llm-export"
        bundle_dir.mkdir(parents=True)
        credentials_path = bundle_dir / "credentials.json"
        credentials_path.write_text(
            json.dumps(
                credentials
                or {
                    "Version": 1,
                    "AccessKeyId": "test-key",
                    "SecretAccessKey": "test-secret",
                    "SessionToken": "test-token",
                    "Expiration": "2999-01-01T00:00:00Z",
                }
            )
            + "\n"
        )
        os.chmod(credentials_path, mode)
        (bundle_dir / "config").write_text(
            config
            or "[profile llm-export]\n"
            "credential_process = sh -c 'cat ~/.aws/llm-export/credentials.json'\n"
        )
        return bundle_dir

    def patch_aws_paths(self, root):
        aws_dir = Path(root) / ".aws"
        bundle_dir = aws_dir / "llm-export"
        return mock.patch.multiple(
            launch,
            AWS_DIR=aws_dir,
            AWS_MANAGED_BUNDLE_DIR=bundle_dir,
            AWS_MANAGED_CONFIG=bundle_dir / "config",
            AWS_MANAGED_CREDENTIALS_JSON=bundle_dir / "credentials.json",
        )

    def test_bedrock_prefers_exported_profile_over_host_aws_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {
                        "PI_USE_BEDROCK": "1",
                        "AWS_PROFILE": "source-profile",
                        "AWS_ACCESS_KEY_ID": "host-key",
                        "AWS_SECRET_ACCESS_KEY": "host-secret",
                        "AWS_SESSION_TOKEN": "host-token",
                        "AWS_REGION": "us-east-1",
                    },
                    clear=True,
                ),
            ):
                launcher = self.make_launcher("pi")
                env = launcher.build_env_vars()
                mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["pi"], env)

        self.assertEqual(env["AWS_PROFILE"], "llm-export")
        self.assertEqual(
            env["AWS_CONFIG_FILE"], launch.CONTAINER_AWS_MANAGED_CONFIG
        )
        self.assertEqual(env["AWS_REGION"], "us-east-1")
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("AWS_SESSION_TOKEN", env)
        self.assertIn(
            (str(bundle_dir), launch.CONTAINER_AWS_MANAGED_BUNDLE_DIR, True),
            mounts,
        )
        self.assertNotIn(launch.CONTAINER_AWS_DIR, [mount[1] for mount in mounts])

    def test_host_profile_is_fallback_without_managed_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir()
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {"PI_USE_BEDROCK": "1", "AWS_PROFILE": "host-profile"},
                    clear=True,
                ),
            ):
                launcher = self.make_launcher("pi")
                env = launcher.build_env_vars()
                mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["pi"], env)

        self.assertEqual(env["AWS_PROFILE"], "host-profile")
        self.assertIn((str(aws_dir), launch.CONTAINER_AWS_DIR, True), mounts)

    def test_explicit_profile_overrides_valid_managed_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {"PI_USE_BEDROCK": "1", "AWS_PROFILE": "host-profile"},
                    clear=True,
                ),
            ):
                env = self.make_launcher(
                    "--env", "AWS_PROFILE=research", "pi"
                ).build_env_vars()

        self.assertEqual(env["AWS_PROFILE"], "research")

    def test_explicit_static_credentials_are_still_allowed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {"PI_USE_BEDROCK": "1", "AWS_PROFILE": "host-profile"},
                    clear=True,
                ),
            ):
                env = self.make_launcher(
                    "--env",
                    "PI_USE_BEDROCK=1",
                    "--env",
                    "AWS_ACCESS_KEY_ID=explicit-key",
                    "--env",
                    "AWS_SECRET_ACCESS_KEY=explicit-secret",
                    "pi",
                ).build_env_vars()

        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "explicit-key")
        self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "explicit-secret")
        self.assertNotIn("AWS_PROFILE", env)

    def test_bedrock_without_credentials_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                with self.assertRaises(SystemExit):
                    self.make_launcher(
                        "--env", "PI_USE_BEDROCK=1", "pi"
                    ).build_env_vars()

    def test_explicit_managed_profile_uses_bundle_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                env = self.make_launcher(
                    "--env",
                    "PI_USE_BEDROCK=1",
                    "--env",
                    "AWS_PROFILE=llm-export",
                    "pi",
                ).build_env_vars()

        self.assertEqual(env["AWS_CONFIG_FILE"], launch.CONTAINER_AWS_MANAGED_CONFIG)

    def test_managed_mode_mounts_only_bundle_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = self.write_managed_bundle(tmpdir)
            with self.patch_aws_paths(tmpdir):
                launcher = self.make_launcher("pi")
                config = launch.SUBCOMMAND_CONFIG["pi"]
                without_bedrock = launcher.build_mounts(config, {})
                with_bedrock = launcher.build_mounts(
                    config,
                    {"PI_USE_BEDROCK": "1", "AWS_PROFILE": "llm-export"},
                )

        self.assertNotIn(
            launch.CONTAINER_AWS_MANAGED_BUNDLE_DIR,
            [mount[1] for mount in without_bedrock],
        )
        aws_mounts = [
            mount for mount in with_bedrock if mount[1].startswith("/home/devuser/.aws")
        ]
        self.assertEqual(
            aws_mounts,
            [
                (
                    str(bundle_dir),
                    launch.CONTAINER_AWS_MANAGED_BUNDLE_DIR,
                    True,
                )
            ],
        )

    def test_explicit_profile_mounts_full_aws_directory_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir()
            with self.patch_aws_paths(tmpdir):
                launcher = self.make_launcher("pi")
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"],
                    {"PI_USE_BEDROCK": "1", "AWS_PROFILE": "research"},
                )

        self.assertIn((str(aws_dir), "/home/devuser/.aws", True), mounts)

    def test_static_mode_does_not_mount_aws_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir()
            with self.patch_aws_paths(tmpdir):
                launcher = self.make_launcher("pi")
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"],
                    {
                        "PI_USE_BEDROCK": "1",
                        "AWS_ACCESS_KEY_ID": "key",
                        "AWS_SECRET_ACCESS_KEY": "secret",
                    },
                )

        self.assertNotIn("/home/devuser/.aws", [mount[1] for mount in mounts])

    def test_legacy_managed_layout_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir()
            (aws_dir / "config").write_text(
                "[profile llm-export]\n"
                "credential_process = sh -c 'cat ~/.aws/credentials.json'\n"
            )
            (aws_dir / "credentials.json").write_text("{}\n")
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {
                        "PI_USE_BEDROCK": "1",
                        "AWS_ACCESS_KEY_ID": "host-key",
                        "AWS_SECRET_ACCESS_KEY": "host-secret",
                    },
                    clear=True,
                ),
            ):
                env = self.make_launcher("pi").build_env_vars()

        self.assertNotIn("AWS_PROFILE", env)
        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "host-key")
        self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "host-secret")

    def test_backends_render_aws_mount_read_only(self):
        mount = [("/host/.aws/llm-export", "/home/devuser/.aws/llm-export", True)]
        for backend, flag in (
            (launch.PodmanBackend, "--volume"),
            (launch.SingularityBackend, "--bind"),
        ):
            with self.subTest(backend=backend.__name__):
                args = mock.Mock()
                rendered = backend(args).build_mount_args(mount)
                self.assertEqual(
                    rendered,
                    [
                        flag,
                        "/host/.aws/llm-export:/home/devuser/.aws/llm-export:ro",
                    ],
                )

    def test_managed_profile_inspection_rejects_invalid_files(self):
        mutations = {
            "missing config": lambda bundle: (bundle / "config").unlink(),
            "missing section": lambda bundle: (bundle / "config").write_text(
                "[default]\nregion = us-east-1\n"
            ),
            "wrong process": lambda bundle: (bundle / "config").write_text(
                "[profile llm-export]\ncredential_process = cat /tmp/credentials\n"
            ),
            "malformed json": lambda bundle: (bundle / "credentials.json").write_text("{"),
            "missing field": lambda bundle: self._replace_managed_credentials(
                bundle, {"Version": 1, "Expiration": "2999-01-01T00:00:00Z"}
            ),
            "unsupported version": lambda bundle: self._update_managed_credentials(
                bundle, Version=2
            ),
            "naive timestamp": lambda bundle: self._update_managed_credentials(
                bundle, Expiration="2999-01-01T00:00:00"
            ),
            "expired": lambda bundle: self._update_managed_credentials(
                bundle, Expiration="2000-01-01T00:00:00Z"
            ),
            "insecure mode": lambda bundle: os.chmod(
                bundle / "credentials.json", 0o640
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                bundle = self.write_managed_bundle(tmpdir)
                mutate(bundle)
                with self.patch_aws_paths(tmpdir):
                    error = self.make_launcher("pi")._validate_managed_aws_profile()
                    self.assertIsNotNone(error)

    def _replace_managed_credentials(self, bundle, credentials):
        path = bundle / "credentials.json"
        path.write_text(json.dumps(credentials) + "\n")
        os.chmod(path, 0o600)

    def _update_managed_credentials(self, bundle, **updates):
        path = bundle / "credentials.json"
        credentials = json.loads(path.read_text())
        credentials.update(updates)
        self._replace_managed_credentials(bundle, credentials)

    def test_valid_managed_profile_is_selected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                env = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1", "pi"
                ).build_env_vars()
        self.assertEqual(env["AWS_PROFILE"], "llm-export")

    def test_invalid_automatic_managed_profile_fails_without_static_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.write_managed_bundle(tmpdir)
            self._update_managed_credentials(bundle, Expiration="expired")
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(
                    launch.os.environ,
                    {
                        "AWS_PROFILE": "host-profile",
                        "AWS_ACCESS_KEY_ID": "host-key",
                        "AWS_SECRET_ACCESS_KEY": "host-secret",
                    },
                    clear=True,
                ),
            ):
                with self.assertRaises(SystemExit):
                    self.make_launcher(
                        "--env", "PI_USE_BEDROCK=1", "pi"
                    ).build_env_vars()

    def test_invalid_managed_files_do_not_block_other_explicit_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = self.write_managed_bundle(tmpdir)
            self._update_managed_credentials(bundle, Expiration="expired")
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                profile_env = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1",
                    "--env", "AWS_PROFILE=research", "pi",
                ).build_env_vars()
                static_env = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1",
                    "--env", "AWS_ACCESS_KEY_ID=key",
                    "--env", "AWS_SECRET_ACCESS_KEY=secret", "pi",
                ).build_env_vars()

        self.assertEqual(profile_env["AWS_PROFILE"], "research")
        self.assertEqual(static_env["AWS_ACCESS_KEY_ID"], "key")
        self.assertNotIn("AWS_PROFILE", static_env)


class AwsCredentialModeMatrixTests(unittest.TestCase):
    make_launcher = LaunchAwsEnvTests.make_launcher
    write_managed_bundle = LaunchAwsEnvTests.write_managed_bundle
    patch_aws_paths = LaunchAwsEnvTests.patch_aws_paths
    _replace_managed_credentials = LaunchAwsEnvTests._replace_managed_credentials
    _update_managed_credentials = LaunchAwsEnvTests._update_managed_credentials

    def test_bedrock_credential_mode_matrix_for_supported_tools(self):
        scenarios = (
            ("valid managed", "valid", None, None, "managed"),
            ("invalid managed", "invalid", None, None, "failure"),
            ("explicit without managed", "absent", "research", None, "profile"),
            ("explicit with managed", "valid", "research", None, "profile"),
            ("static without managed", "absent", None, "complete", "static"),
            ("explicit static with managed", "valid", None, "complete", "static"),
            ("partial static", "absent", None, "partial", "failure"),
        )
        for cmd in ("claude", "pi", "shell"):
            bedrock_key = (
                "CLAUDE_CODE_USE_BEDROCK" if cmd == "claude" else "PI_USE_BEDROCK"
            )
            for name, managed, profile, static, expected in scenarios:
                with (
                    self.subTest(cmd=cmd, scenario=name),
                    tempfile.TemporaryDirectory() as tmpdir,
                ):
                    aws_dir = Path(tmpdir) / ".aws"
                    aws_dir.mkdir()
                    if managed in {"valid", "invalid"}:
                        bundle = self.write_managed_bundle(tmpdir)
                        if managed == "invalid":
                            self._update_managed_credentials(
                                bundle, Expiration="2000-01-01T00:00:00Z"
                            )

                    argv = ["--env", f"{bedrock_key}=1"]
                    if profile:
                        argv.extend(["--env", f"AWS_PROFILE={profile}"])
                    if static:
                        argv.extend(["--env", "AWS_ACCESS_KEY_ID=explicit-key"])
                        if static == "complete":
                            argv.extend(
                                ["--env", "AWS_SECRET_ACCESS_KEY=explicit-secret"]
                            )
                    argv.append(cmd)

                    with (
                        self.patch_aws_paths(tmpdir),
                        mock.patch.dict(launch.os.environ, {}, clear=True),
                    ):
                        launcher = self.make_launcher(*argv)
                        if expected == "failure":
                            with self.assertRaises(SystemExit):
                                launcher.build_env_vars()
                            continue

                        env = launcher.build_env_vars()
                        mounts = launcher.build_mounts(
                            launch.SUBCOMMAND_CONFIG[cmd], env
                        )

                    aws_targets = [
                        target
                        for _, target, _ in mounts
                        if target.startswith(launch.CONTAINER_AWS_DIR)
                    ]
                    if expected == "managed":
                        self.assertEqual(env["AWS_PROFILE"], launch.AWS_EXPORT_PROFILE)
                        self.assertEqual(
                            aws_targets, [launch.CONTAINER_AWS_MANAGED_BUNDLE_DIR]
                        )
                    elif expected == "profile":
                        self.assertEqual(env["AWS_PROFILE"], "research")
                        self.assertEqual(aws_targets, [launch.CONTAINER_AWS_DIR])
                    else:
                        self.assertNotIn("AWS_PROFILE", env)
                        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "explicit-key")
                        self.assertEqual(aws_targets, [])

    def test_codex_does_not_inherit_bedrock_aws_environment(self):
        with mock.patch.dict(
            launch.os.environ,
            {
                "AWS_PROFILE": "research",
                "AWS_ACCESS_KEY_ID": "host-key",
                "AWS_SECRET_ACCESS_KEY": "host-secret",
                "PI_USE_BEDROCK": "1",
            },
            clear=True,
        ):
            launcher = self.make_launcher("codex")
            env = launcher.build_env_vars()
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"], env)

        self.assertNotIn("AWS_PROFILE", env)
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)
        self.assertFalse(
            any(target.startswith(launch.CONTAINER_AWS_DIR) for _, target, _ in mounts)
        )


class SensitiveEnvironmentTests(unittest.TestCase):
    def make_launcher(self, backend="podman", dry_run=False):
        argv = ["--backend", backend]
        if dry_run:
            argv.append("--dry-run")
        argv.append("codex")
        return launch.Launcher(launch.parse_args(argv))

    def run_launcher(self, launcher, env_vars, subprocess_effect=None):
        with (
            mock.patch.object(launcher, "build_env_vars", return_value=env_vars),
            mock.patch.object(launcher, "build_mounts", return_value=[]),
            mock.patch.object(launcher, "setup_codex_config"),
            mock.patch.object(launcher.backend, "check_availability"),
            mock.patch.object(launcher.backend, "validate_image"),
            mock.patch.object(
                launch.subprocess, "run", side_effect=subprocess_effect
            ) as run,
        ):
            launcher.run()
        return run

    def test_both_backends_keep_secrets_out_of_command_arguments(self):
        secrets = {
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
            "AWS_SESSION_TOKEN": "session=token",
            "AWS_SECURITY_TOKEN": "security-token",
            "AWS_BEARER_TOKEN_BEDROCK": "bearer-token",
        }
        for backend in ("podman", "singularity"):
            with self.subTest(backend=backend):
                inspected = {}

                def inspect_command(cmd, check):
                    inspected["cmd"] = cmd
                    env_path = Path(cmd[cmd.index("--env-file") + 1])
                    inspected["path"] = env_path
                    inspected["mode"] = env_path.stat().st_mode & 0o777
                    inspected["dir_mode"] = env_path.parent.stat().st_mode & 0o777
                    inspected["contents"] = env_path.read_text()
                    return mock.Mock(returncode=0)

                env = {"HOME": "/home/devuser", "ORDINARY": "visible", **secrets}
                self.run_launcher(
                    self.make_launcher(backend), env, inspect_command
                )

                command_text = "\0".join(inspected["cmd"])
                for value in secrets.values():
                    self.assertNotIn(value, command_text)
                self.assertIn("ORDINARY=visible", inspected["cmd"])
                self.assertEqual(inspected["mode"], 0o600)
                self.assertEqual(inspected["dir_mode"], 0o700)
                self.assertIn("AWS_SESSION_TOKEN=session=token\n", inspected["contents"])
                self.assertFalse(inspected["path"].exists())
                self.assertFalse(inspected["path"].parent.exists())

    def test_singularity_command_does_not_mutate_environment(self):
        launcher = self.make_launcher("singularity", dry_run=True)
        env = {"HOME": "/home/devuser", "ORDINARY": "visible"}

        launcher.backend.build_command(env, [], ["codex"])

        self.assertEqual(env, {"HOME": "/home/devuser", "ORDINARY": "visible"})

    def test_dry_run_redacts_and_removes_sensitive_file(self):
        secret = "must-not-be-printed"
        launcher = self.make_launcher("podman", dry_run=True)
        stdout = io.StringIO()
        with (
            mock.patch.object(
                launcher,
                "build_env_vars",
                return_value={
                    "HOME": "/home/devuser",
                    "AWS_SECRET_ACCESS_KEY": secret,
                },
            ),
            mock.patch.object(launcher, "build_mounts", return_value=[]),
            contextlib.redirect_stdout(stdout),
        ):
            launcher.run()

        output = stdout.getvalue()
        self.assertNotIn(secret, output)
        command = shlex.split(output)
        env_path = Path(command[command.index("--env-file") + 1])
        self.assertFalse(env_path.exists())
        self.assertFalse(env_path.parent.exists())

    def test_sensitive_file_is_removed_after_launch_failure(self):
        inspected = {}

        def fail(cmd, check):
            inspected["path"] = Path(cmd[cmd.index("--env-file") + 1])
            raise launch.subprocess.CalledProcessError(1, cmd)

        launcher = self.make_launcher("podman")
        with self.assertRaises(launch.subprocess.CalledProcessError):
            self.run_launcher(
                launcher,
                {"HOME": "/home/devuser", "AWS_ACCESS_KEY_ID": "key"},
                fail,
            )
        self.assertFalse(inspected["path"].exists())
        self.assertFalse(inspected["path"].parent.exists())

    def test_sensitive_value_boundary_handling(self):
        launcher = self.make_launcher()
        path, temp_dir = launcher._write_sensitive_env_file(
            {"AWS_SESSION_TOKEN": "value with spaces=and-equals"}
        )
        try:
            self.assertEqual(
                Path(path).read_text(),
                "AWS_SESSION_TOKEN=value with spaces=and-equals\n",
            )
        finally:
            shutil.rmtree(temp_dir)

        for value in ('a"quote', "a'quote", "line\nbreak"):
            with self.subTest(value=repr(value)), self.assertRaises(SystemExit):
                launcher._write_sensitive_env_file({"AWS_SESSION_TOKEN": value})


class ImageTagResolutionTests(unittest.TestCase):
    def parse(self, *argv):
        return launch.parse_args(list(argv))

    def test_default_uses_per_harness_latest_tag(self):
        for cmd, expected in (
            ("pi", "pi-latest"),
            ("codex", "codex-latest"),
            ("claude", "claude-latest"),
            ("shell", "latest"),
        ):
            args = self.parse("--backend", "podman", cmd)
            self.assertEqual(
                args.image_name, f"{launch.DEFAULT_PODMAN_IMAGE}:{expected}"
            )

    def test_explicit_tag_overrides_default(self):
        args = self.parse("--backend", "podman", "--tag", "latest", "codex")
        self.assertEqual(args.image_name, f"{launch.DEFAULT_PODMAN_IMAGE}:latest")

    def test_custom_image_name_left_untouched(self):
        args = self.parse(
            "--backend", "podman", "--image-name", "llm-devcontainer", "codex"
        )
        self.assertEqual(args.image_name, "llm-devcontainer")

    def test_custom_image_pinned_tag_respected(self):
        ref = f"{launch.DEFAULT_PODMAN_IMAGE}:codex-0.125.0"
        args = self.parse("--backend", "podman", "--image-name", ref, "codex")
        self.assertEqual(args.image_name, ref)

    def test_explicit_tag_applies_to_custom_image(self):
        args = self.parse(
            "--backend",
            "podman",
            "--tag",
            "latest",
            "--image-name",
            "llm-devcontainer",
            "codex",
        )
        self.assertEqual(args.image_name, "llm-devcontainer:latest")

    def test_singularity_default_gets_per_harness_tag(self):
        args = self.parse("--backend", "singularity", "pi")
        self.assertEqual(
            args.sif_path, f"{launch.DEFAULT_SINGULARITY_IMAGE}:pi-latest"
        )

    def test_local_sif_path_left_untouched(self):
        args = self.parse("--backend", "singularity", "--sif-path", "/tmp/llm.sif", "pi")
        self.assertEqual(args.sif_path, "/tmp/llm.sif")


class MaskTests(unittest.TestCase):
    def make_launcher(self, tmpdir, *argv):
        with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
            launcher = launch.Launcher(launch.parse_args(list(argv)))
        return launcher

    def test_mask_binds_empty_home_dir_over_subpath(self):
        for backend, flag in (("podman", "--volume"), ("singularity", "--bind")):
            with self.subTest(backend=backend):
                with tempfile.TemporaryDirectory() as tmpdir, \
                        tempfile.TemporaryDirectory() as fake_home:
                    (Path(tmpdir) / "secret").mkdir()
                    with mock.patch.object(launch.os, "getcwd", return_value=tmpdir), \
                            mock.patch.object(
                                launch.Path, "home", return_value=Path(fake_home)
                            ):
                        launcher = launch.Launcher(
                            launch.parse_args(
                                ["--backend", backend, "--mask", "secret", "shell"]
                            )
                        )
                        mask_args = launcher.backend.build_mask_args(
                            launcher.args.mask_targets
                        )

                        self.assertEqual(mask_args[0], flag)
                        src, target, mode = mask_args[1].split(":")
                        self.assertEqual(target, f"{tmpdir}/secret")
                        self.assertEqual(mode, "ro")
                        # Empty shadow dir must live under $HOME so it is shared
                        # into the podman machine VM on macOS.
                        self.assertTrue(Path(src).is_relative_to(fake_home))
                        self.assertTrue(Path(src).is_dir())
                        self.assertEqual(list(Path(src).iterdir()), [])

    def test_mask_missing_path_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit):
                    launch.Launcher(launch.parse_args(["--mask", "nope", "shell"]))

    def test_mask_outside_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit):
                    launch.Launcher(launch.parse_args(["--mask", "/etc", "shell"]))

    def test_no_mask_leaves_targets_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher = self.make_launcher(tmpdir, "shell")
            self.assertEqual(launcher.args.mask_targets, [])
            self.assertEqual(launcher.backend.build_mask_args([]), [])

    def test_ro_remounts_subdir_read_only(self):
        for backend, flag in (("podman", "--volume"), ("singularity", "--bind")):
            with self.subTest(backend=backend):
                with tempfile.TemporaryDirectory() as tmpdir:
                    (Path(tmpdir) / "data").mkdir()
                    resolved = str(Path(tmpdir).resolve())
                    with mock.patch.object(
                        launch.os, "getcwd", return_value=resolved
                    ):
                        launcher = launch.Launcher(
                            launch.parse_args(
                                ["--backend", backend, "--ro", "data", "shell"]
                            )
                        )
                        container_target = f"{resolved}/data"
                        self.assertIn(
                            (f"{resolved}/data", container_target, True),
                            launcher.args.extra_mounts,
                        )
                        # The subdir mount is intentionally nested; recorded so
                        # it is exempt from the nested-mount warning.
                        self.assertIn(
                            container_target, launcher.args.nested_ok_targets
                        )

    def test_ro_missing_path_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit):
                    launch.Launcher(launch.parse_args(["--ro", "nope", "shell"]))

    def test_ro_outside_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit):
                    launch.Launcher(launch.parse_args(["--ro", "/etc", "shell"]))

    def test_ro_whole_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = str(Path(tmpdir).resolve())
            with mock.patch.object(launch.os, "getcwd", return_value=resolved):
                with self.assertRaises(SystemExit):
                    launch.Launcher(launch.parse_args(["--ro", ".", "shell"]))

    def test_ro_subdir_does_not_warn_nested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "data").mkdir()
            resolved = str(Path(tmpdir).resolve())
            with mock.patch.object(launch.os, "getcwd", return_value=resolved):
                launcher = launch.Launcher(
                    launch.parse_args(["--ro", "data", "shell"])
                )
                config = launch.SUBCOMMAND_CONFIG["shell"]
                with mock.patch.object(launch.LOGGER, "warning") as warn:
                    launcher.build_mounts(config, env_vars={})
                    warn.assert_not_called()

    def test_mask_and_ro_targets_do_not_warn_nested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "secret").mkdir()
            (Path(tmpdir) / "data").mkdir()
            resolved = str(Path(tmpdir).resolve())
            with mock.patch.object(launch.os, "getcwd", return_value=resolved):
                launcher = launch.Launcher(
                    launch.parse_args(
                        ["--mask", "secret", "--ro", "data", "shell"]
                    )
                )
                config = launch.SUBCOMMAND_CONFIG["shell"]
                with mock.patch.object(launch.LOGGER, "warning") as warn:
                    launcher.build_mounts(config, env_vars={})
                    warn.assert_not_called()

    def test_global_read_only_marks_workspace_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher = self.make_launcher(tmpdir, "--global-read-only", "shell")
            self.assertTrue(launcher.args.read_only)


if __name__ == "__main__":
    unittest.main()
