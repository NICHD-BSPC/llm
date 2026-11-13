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


class LaunchPolicyMountTests(unittest.TestCase):
    def test_existing_policy_dirs_mount_read_only_for_relevant_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude = Path(tmpdir) / "claude-code"
            codex = Path(tmpdir) / "codex"
            claude.mkdir()
            codex.mkdir()
            paths = {
                "claude": str(claude),
                "codex": str(codex),
            }
            with mock.patch.dict(launch.POLICY_PATHS, paths):
                for command, expected in (
                    ("claude", {str(claude)}),
                    ("codex", {str(codex)}),
                    ("shell", {str(claude), str(codex)}),
                    ("pi", set()),
                    ("omp", set()),
                ):
                    with self.subTest(command=command):
                        launcher = launch.Launcher(launch.parse_args([command]))
                        mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG[command])
                        policy_mounts = {
                            host for host, target, readonly in mounts
                            if target in paths.values() and host == target and readonly
                        }
                        self.assertEqual(policy_mounts, expected)

    def test_no_site_policy_skips_existing_policy_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude = Path(tmpdir) / "claude-code"
            codex = Path(tmpdir) / "codex"
            claude.mkdir()
            codex.mkdir()
            paths = {"claude": str(claude), "codex": str(codex)}
            with mock.patch.dict(launch.POLICY_PATHS, paths):
                for command in ("claude", "codex", "shell"):
                    with self.subTest(command=command):
                        launcher = launch.Launcher(
                            launch.parse_args(["--no-site-policy", command])
                        )
                        mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG[command])
                        self.assertFalse(
                            {target for _, target, _ in mounts} & set(paths.values())
                        )

    def test_missing_or_non_dir_policy_path_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = str(Path(tmpdir) / "missing")
            not_dir = Path(tmpdir) / "file"
            not_dir.write_text("{}\n")
            for path in (missing, str(not_dir)):
                with self.subTest(path=path):
                    with mock.patch.dict(launch.POLICY_PATHS, {"claude": path}):
                        launcher = launch.Launcher(launch.parse_args(["claude"]))
                        mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["claude"])
                    self.assertNotIn(path, [target for _, target, _ in mounts])


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
                env, aws_mounts = launcher.build_runtime_environment()
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"], aws_mounts
                )

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
                mock.patch.object(launch.LOGGER, "warning") as warn,
            ):
                launcher = self.make_launcher("pi")
                env, aws_mounts = launcher.build_runtime_environment()
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"], aws_mounts
                )

        self.assertEqual(env["AWS_PROFILE"], "host-profile")
        self.assertIn((str(aws_dir), launch.CONTAINER_AWS_DIR, True), mounts)
        warn.assert_called_once_with(
            "Managed AWS profile llm-export was not found; using inherited "
            "%s. Run refresh.py --aws-profile PROFILE to create it.",
            "AWS profile 'host-profile'",
        )

    def test_inherited_static_credentials_warn_without_managed_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
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
                mock.patch.object(launch.LOGGER, "warning") as warn,
            ):
                env = self.make_launcher("pi").build_runtime_environment()[0]

        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "host-key")
        warn.assert_called_once_with(
            "Managed AWS profile llm-export was not found; using inherited "
            "%s. Run refresh.py --aws-profile PROFILE to create it.",
            "static AWS credentials",
        )

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
                mock.patch.object(launch.LOGGER, "warning") as warn,
            ):
                env = self.make_launcher(
                    "--env", "AWS_PROFILE=research", "pi"
                ).build_runtime_environment()[0]

        self.assertEqual(env["AWS_PROFILE"], "research")
        warn.assert_not_called()

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
                mock.patch.object(launch.LOGGER, "warning") as warn,
            ):
                env = self.make_launcher(
                    "--env",
                    "PI_USE_BEDROCK=1",
                    "--env",
                    "AWS_ACCESS_KEY_ID=explicit-key",
                    "--env",
                    "AWS_SECRET_ACCESS_KEY=explicit-secret",
                    "pi",
                ).build_runtime_environment()[0]

        self.assertEqual(env["AWS_ACCESS_KEY_ID"], "explicit-key")
        self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "explicit-secret")
        self.assertNotIn("AWS_PROFILE", env)
        warn.assert_not_called()

    def test_bedrock_without_credentials_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    self.make_launcher(
                        "--env", "PI_USE_BEDROCK=1", "pi"
                    ).build_runtime_environment()[0]
                self.assertIn("AWS_PROFILE must be set", error.call_args.args[0])

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
                ).build_runtime_environment()[0]

        self.assertEqual(env["AWS_CONFIG_FILE"], launch.CONTAINER_AWS_MANAGED_CONFIG)

    def test_managed_mode_mounts_only_bundle_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = self.write_managed_bundle(tmpdir)
            with self.patch_aws_paths(tmpdir):
                config = launch.SUBCOMMAND_CONFIG["pi"]
                without_bedrock = self.make_launcher("pi").build_mounts(config, [])
                launcher = self.make_launcher("--env", "PI_USE_BEDROCK=1", "pi")
                _, aws_mounts = launcher.build_runtime_environment()
                with_bedrock = launcher.build_mounts(config, aws_mounts)

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
                launcher = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1",
                    "--env", "AWS_PROFILE=research", "pi",
                )
                _, aws_mounts = launcher.build_runtime_environment()
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"], aws_mounts
                )

        self.assertIn((str(aws_dir), "/home/devuser/.aws", True), mounts)

    def test_static_mode_does_not_mount_aws_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir()
            with self.patch_aws_paths(tmpdir):
                launcher = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1",
                    "--env", "AWS_ACCESS_KEY_ID=key",
                    "--env", "AWS_SECRET_ACCESS_KEY=secret", "pi",
                )
                _, aws_mounts = launcher.build_runtime_environment()
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"], aws_mounts
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
                env = self.make_launcher("pi").build_runtime_environment()[0]

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

    def test_managed_profile_is_validated_once_per_environment_build(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                launcher = self.make_launcher("--env", "PI_USE_BEDROCK=1", "pi")
                with mock.patch.object(
                    launcher,
                    "_validate_managed_aws_profile",
                    wraps=launcher._validate_managed_aws_profile,
                ) as validate:
                    launcher.build_runtime_environment()
        validate.assert_called_once_with()

    def test_valid_managed_profile_is_selected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.write_managed_bundle(tmpdir)
            with (
                self.patch_aws_paths(tmpdir),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                env = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1", "pi"
                ).build_runtime_environment()[0]
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
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    self.make_launcher(
                        "--env", "PI_USE_BEDROCK=1", "pi"
                    ).build_runtime_environment()[0]
                self.assertIn("managed credential Expiration is not a valid timestamp", error.call_args.args[0])

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
                ).build_runtime_environment()[0]
                static_env = self.make_launcher(
                    "--env", "PI_USE_BEDROCK=1",
                    "--env", "AWS_ACCESS_KEY_ID=key",
                    "--env", "AWS_SECRET_ACCESS_KEY=secret", "pi",
                ).build_runtime_environment()[0]

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
        bedrock_keys = {
            "claude": "CLAUDE_CODE_USE_BEDROCK",
            "pi": "PI_USE_BEDROCK",
            "omp": "OMP_USE_BEDROCK",
            "shell": "OMP_USE_BEDROCK",
        }
        for cmd, bedrock_key in bedrock_keys.items():
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
                            with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                                launcher.build_runtime_environment()[0]
                            self.assertTrue(error.called)
                            continue

                        env, aws_mounts = launcher.build_runtime_environment()
                        mounts = launcher.build_mounts(
                            launch.SUBCOMMAND_CONFIG[cmd], aws_mounts
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
            env, aws_mounts = launcher.build_runtime_environment()
            mounts = launcher.build_mounts(
                launch.SUBCOMMAND_CONFIG["codex"], aws_mounts
            )

        self.assertNotIn("AWS_PROFILE", env)
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)
        self.assertFalse(
            any(target.startswith(launch.CONTAINER_AWS_DIR) for _, target, _ in mounts)
        )


class CodexDaemonIsolationTests(unittest.TestCase):
    def test_only_codex_credentialed_commands_get_daemon_overlays(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.Path, "home", return_value=Path(tmpdir)):
                for command in ("codex", "shell", "claude", "pi", "omp"):
                    with self.subTest(command=command):
                        launcher = launch.Launcher(launch.parse_args([command]))
                        targets = {
                            target for _, target, _ in
                            launcher.build_mounts(launch.SUBCOMMAND_CONFIG[command])
                        }
                        has_overlay = (
                            "/home/devuser/.codex/packages/app-server-daemon" in targets
                        )
                        self.assertEqual(has_overlay, command in {"codex", "shell"})

    def test_launches_keep_host_daemon_and_other_containers_separate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            host_home = Path(tmpdir)
            package = host_home / ".codex/packages/app-server-daemon"
            package.mkdir(parents=True)
            marker = package / "host-version"
            marker.write_text("older host installation")

            with (
                mock.patch.object(launch.Path, "home", return_value=host_home),
                mock.patch.dict(launch.os.environ, {"HOME": str(host_home)}),
            ):
                for backend in ("podman", "singularity"):
                    previous_sources = set()
                    for command in ("codex", "shell"):
                        launcher = launch.Launcher(
                            launch.parse_args(["--backend", backend, command])
                        )
                        with mock.patch.object(launch.LOGGER, "warning") as warning:
                            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG[command])
                        warning.assert_not_called()
                        mounted = {target: (Path(source), readonly) for source, target, readonly in mounts}
                        self.assertEqual(
                            mounted["/home/devuser/.codex"], (host_home / ".codex", False)
                        )
                        for relative_path in (
                            "packages/app-server-daemon", "app-server-daemon", "app-server-control"
                        ):
                            source, readonly = mounted[f"/home/devuser/.codex/{relative_path}"]
                            self.assertFalse(readonly)
                            if relative_path == "packages/app-server-daemon":
                                current = source / "current"
                                self.assertEqual(list(source.iterdir()), [current])
                                self.assertEqual(
                                    os.readlink(current), launch.CODEX_DAEMON_PACKAGE
                                )
                            else:
                                self.assertEqual(list(source.iterdir()), [])
                            self.assertFalse(source.is_relative_to(host_home / ".codex"))
                            self.assertNotIn(source, previous_sources)
                            previous_sources.add(source)
                            (source / "container-state").write_text("private")
            self.assertEqual(marker.read_text(), "older host installation")
            self.assertEqual(list(package.iterdir()), [marker])


class SensitiveEnvironmentTests(unittest.TestCase):
    def make_launcher(self, backend="podman", dry_run=False):
        argv = ["--backend", backend]
        if dry_run:
            argv.append("--dry-run")
        argv.append("codex")
        return launch.Launcher(launch.parse_args(argv))

    def run_launcher(self, launcher, env_vars, subprocess_effect=None):
        with (
            mock.patch.object(launcher, "build_runtime_environment", return_value=(env_vars, [])),
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

                def inspect_command(cmd, check, **kwargs):
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

    def run_with_host_env(self, launcher, host_env):
        """Run launcher (non-dry-run) under host_env; return the subprocess.run mock."""
        with (
            mock.patch.dict(launch.os.environ, host_env, clear=True),
            mock.patch.object(
                launcher, "build_runtime_environment",
                return_value=({"HOME": "/home/devuser"}, []),
            ),
            mock.patch.object(
                launcher, "build_mounts", return_value=[("/chosen", "/chosen", True)]
            ),
            mock.patch.object(launcher, "setup_codex_config"),
            mock.patch.object(launcher.backend, "check_availability"),
            mock.patch.object(launcher.backend, "validate_image"),
            mock.patch("builtins.input") as prompt,
            mock.patch.object(launch.subprocess, "run") as run,
        ):
            launcher.run()
            prompt.assert_not_called()
            # Filtering must not leak into this process's environment.
            self.assertEqual(dict(launch.os.environ), host_env)
        return run

    def test_singularity_strips_ambient_bind_vars_without_prompting(self):
        launcher = self.make_launcher("singularity")
        host_vars = {
            name: "/host/secret:/secret" for name in launch.SINGULARITY_BIND_ENV_VARS
        }
        with self.assertLogs("launch", "WARNING") as logs:
            run = self.run_with_host_env(launcher, {**host_vars, "KEEP_ME": "yes"})
        self.assertIn("--allow-host-binds", "\n".join(logs.output))
        cmd = run.call_args.args[0]
        passed_env = run.call_args.kwargs["env"]
        self.assertEqual(passed_env["KEEP_ME"], "yes")
        self.assertTrue(launch.SINGULARITY_BIND_ENV_VARS.isdisjoint(passed_env))
        self.assertEqual(cmd[cmd.index("--no-mount") + 1], "hostfs,cwd")
        self.assertNotIn("/host/secret:/secret", cmd)
        self.assertIn("/chosen:/chosen:ro", cmd)

    def test_singularity_empty_bind_vars_do_not_warn_or_filter(self):
        launcher = self.make_launcher("singularity")
        host_env = {"SINGULARITY_BINDPATH": "", "KEEP_ME": "yes"}
        with self.assertNoLogs("launch", "WARNING"):
            run = self.run_with_host_env(launcher, host_env)
        self.assertIsNone(run.call_args.kwargs["env"])

    def test_singularity_allow_host_binds_keeps_env_and_site_binds(self):
        launcher = launch.Launcher(
            launch.parse_args(["--backend", "singularity", "--allow-host-binds", "codex"])
        )
        host_vars = {
            "SINGULARITY_BINDPATH": "/host/data:/data",
            "APPTAINER_MOUNT": "/host/other:/other",
        }
        with self.assertNoLogs("launch", "WARNING"):
            run = self.run_with_host_env(launcher, host_vars)
        cmd = run.call_args.args[0]
        self.assertIsNone(run.call_args.kwargs["env"])
        self.assertEqual(cmd[cmd.index("--no-mount") + 1], "hostfs,cwd")

    def test_singularity_no_site_binds_only_affects_no_mount(self):
        launcher = launch.Launcher(
            launch.parse_args(["--backend", "singularity", "--no-site-binds", "codex"])
        )
        with self.assertLogs("launch", "WARNING"):
            run = self.run_with_host_env(launcher, {"SINGULARITY_BINDPATH": "/h:/c"})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--no-mount") + 1], "hostfs,cwd,bind-paths")
        self.assertNotIn("SINGULARITY_BINDPATH", run.call_args.kwargs["env"])

    def test_podman_inherits_environment_unchanged(self):
        launcher = self.make_launcher("podman")
        with self.assertNoLogs("launch", "WARNING"):
            run = self.run_with_host_env(launcher, {"SINGULARITY_BINDPATH": "/h:/c"})
        self.assertIsNone(run.call_args.kwargs["env"])

    def test_singularity_dry_run_shows_stripped_vars_as_env_unset(self):
        launcher = self.make_launcher("singularity", dry_run=True)
        host_env = {"SINGULARITY_BINDPATH": "/h:/c", "APPTAINER_BIND": "/x:/y"}
        stdout = io.StringIO()
        with (
            mock.patch.dict(launch.os.environ, host_env, clear=True),
            mock.patch.object(
                launcher, "build_runtime_environment",
                return_value=({"HOME": "/home/devuser"}, []),
            ),
            mock.patch.object(launcher, "build_mounts", return_value=[]),
            mock.patch("builtins.input") as prompt,
            self.assertLogs("launch", "WARNING"),
            contextlib.redirect_stdout(stdout),
        ):
            launcher.run()
        prompt.assert_not_called()
        printed = shlex.split(stdout.getvalue())
        self.assertEqual(
            printed[:6],
            ["env", "-u", "APPTAINER_BIND", "-u", "SINGULARITY_BINDPATH", "singularity"],
        )

    def test_singularity_dry_run_without_bind_vars_has_no_env_prefix(self):
        launcher = self.make_launcher("singularity", dry_run=True)
        stdout = io.StringIO()
        with (
            mock.patch.dict(launch.os.environ, {}, clear=True),
            mock.patch.object(
                launcher, "build_runtime_environment",
                return_value=({"HOME": "/home/devuser"}, []),
            ),
            mock.patch.object(launcher, "build_mounts", return_value=[]),
            contextlib.redirect_stdout(stdout),
        ):
            launcher.run()
        self.assertEqual(shlex.split(stdout.getvalue())[0], "singularity")

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
                "build_runtime_environment",
                return_value=(
                    {
                        "HOME": "/home/devuser",
                        "AWS_SECRET_ACCESS_KEY": secret,
                    },
                    [],
                ),
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

        def fail(cmd, check, **kwargs):
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
            with self.subTest(value=repr(value)), self.assertRaises(SystemExit), \
                    mock.patch.object(launch.LOGGER, "error") as error:
                launcher._write_sensitive_env_file({"AWS_SESSION_TOKEN": value})
            self.assertIn("unsupported newline", error.call_args.args[0])


class ImageTagResolutionTests(unittest.TestCase):
    def parse(self, *argv):
        return launch.parse_args(list(argv))

    def test_default_uses_per_harness_latest_tag(self):
        for cmd, expected in (
            ("pi", "pi-latest"),
            ("codex", "codex-latest"),
            ("claude", "claude-latest"),
            ("omp", "omp-latest"),
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
                    resolved = str(Path(tmpdir).resolve())
                    with mock.patch.object(launch.os, "getcwd", return_value=resolved), \
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
                        self.assertEqual(target, f"{resolved}/secret")
                        self.assertEqual(mode, "ro")
                        # Empty shadow dir must live under $HOME so it is shared
                        # into the podman machine VM on macOS.
                        self.assertTrue(Path(src).is_relative_to(fake_home))
                        self.assertTrue(Path(src).is_dir())
                        self.assertEqual(list(Path(src).iterdir()), [])

    def test_mask_missing_path_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    launch.Launcher(launch.parse_args(["--mask", "nope", "shell"]))
                self.assertIn("--mask path", error.call_args.args[0])

    def test_mask_outside_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    launch.Launcher(launch.parse_args(["--mask", "/etc", "shell"]))
                self.assertIn("must be inside", error.call_args.args[0])

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
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    launch.Launcher(launch.parse_args(["--ro", "nope", "shell"]))
                self.assertIn("--ro path", error.call_args.args[0])

    def test_ro_outside_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(launch.os, "getcwd", return_value=tmpdir):
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    launch.Launcher(launch.parse_args(["--ro", "/etc", "shell"]))
                self.assertIn("must be inside", error.call_args.args[0])

    def test_ro_whole_workspace_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = str(Path(tmpdir).resolve())
            with mock.patch.object(launch.os, "getcwd", return_value=resolved):
                with self.assertRaises(SystemExit), mock.patch.object(launch.LOGGER, "error") as error:
                    launch.Launcher(launch.parse_args(["--ro", ".", "shell"]))
                self.assertIn("cannot cover the entire working directory", error.call_args.args[0])

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
                    launcher.build_mounts(config, aws_mounts=[])
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
                    launcher.build_mounts(config, aws_mounts=[])
                    warn.assert_not_called()

    def test_global_read_only_marks_workspace_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            launcher = self.make_launcher(tmpdir, "--global-read-only", "shell")
            self.assertTrue(launcher.args.read_only)


if __name__ == "__main__":
    unittest.main()
