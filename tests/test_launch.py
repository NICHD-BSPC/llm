import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import launch


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp_path = Path(self.temp_dir.name)
        self.home = self.tmp_path / "home"
        self.home.mkdir()
        self.workspace = self.tmp_path / "workspace"
        self.workspace.mkdir()
        self.container_local = self.tmp_path / "container-local"

        self.original_cwd = os.getcwd()
        os.chdir(self.workspace)
        self.addCleanup(os.chdir, self.original_cwd)

        self.env_patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def make_launcher(self, argv):
        args = launch.parse_args(
            [
                "--dry-run",
                "--container-local-host-dir",
                str(self.container_local),
                *argv,
            ]
        )
        return launch.Launcher(args)

    def touch(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def assert_mount_present(self, mounts, host_path, container_path):
        self.assertIn((str(host_path), container_path), mounts)

    def assert_mount_missing(self, mounts, host_path, container_path):
        self.assertNotIn((str(host_path), container_path), mounts)

    def test_claude_passthrough_disabled_by_default(self):
        for cmd in ("claude", "shell"):
            with self.subTest(cmd=cmd):
                with mock.patch.dict(
                    os.environ,
                    {
                        "AWS_PROFILE": "host-profile",
                        "AWS_REGION": "host-region",
                        "AWS_SECRET_ACCESS_KEY": "host-secret",
                        "CLAUDE_CODE_NO_FLICKER": "1",
                    },
                    clear=False,
                ):
                    os.environ.pop("CLAUDE_CODE_USE_BEDROCK", None)

                    launcher = self.make_launcher([cmd])
                    (self.home / ".aws").mkdir(exist_ok=True)
                    (self.home / ".claude").mkdir(exist_ok=True)
                    self.touch(self.home / ".claude.json")

                    subcommand_config = launch.SUBCOMMAND_CONFIG[cmd]
                    env = launcher.build_env_vars(subcommand_config)
                    mounts = launcher.build_mounts(subcommand_config, env)

                    self.assertEqual(env["CLAUDE_CODE_NO_FLICKER"], "1")
                    self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
                    self.assertNotIn("AWS_PROFILE", env)
                    self.assertNotIn("AWS_REGION", env)
                    self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
                    self.assert_mount_missing(
                        mounts, self.home / ".aws", "/home/devuser/.aws"
                    )

    def test_bedrock_host_env_enables_aws_passthrough_and_mounts(self):
        for cmd in ("claude", "shell"):
            with self.subTest(cmd=cmd):
                with mock.patch.dict(
                    os.environ,
                    {
                        "CLAUDE_CODE_USE_BEDROCK": "1",
                        "CLAUDE_CODE_DISABLE_AUTOUPDATER": "1",
                        "AWS_PROFILE": "host-profile",
                        "AWS_REGION": "host-region",
                        "AWS_SECRET_ACCESS_KEY": "host-secret",
                    },
                    clear=False,
                ):
                    launcher = self.make_launcher([cmd])
                    (self.home / ".aws").mkdir(exist_ok=True)
                    (self.home / ".claude").mkdir(exist_ok=True)
                    self.touch(self.home / ".claude.json")

                    subcommand_config = launch.SUBCOMMAND_CONFIG[cmd]
                    env = launcher.build_env_vars(subcommand_config)
                    mounts = launcher.build_mounts(subcommand_config, env)

                    self.assertEqual(env["CLAUDE_CODE_USE_BEDROCK"], "1")
                    self.assertEqual(env["CLAUDE_CODE_DISABLE_AUTOUPDATER"], "1")
                    self.assertEqual(env["AWS_PROFILE"], "host-profile")
                    self.assertEqual(env["AWS_REGION"], "host-region")
                    self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "host-secret")
                    self.assert_mount_present(
                        mounts, self.home / ".aws", "/home/devuser/.aws"
                    )

    def test_env_override_can_enable_bedrock_and_override_aws_values(self):
        with mock.patch.dict(
            os.environ,
            {
                "AWS_PROFILE": "host-profile",
                "AWS_REGION": "host-region",
                "AWS_SECRET_ACCESS_KEY": "host-secret",
            },
            clear=False,
        ):
            os.environ.pop("CLAUDE_CODE_USE_BEDROCK", None)

            launcher = self.make_launcher(
                [
                    "--env",
                    "CLAUDE_CODE_USE_BEDROCK=1",
                    "--env",
                    "AWS_PROFILE=override-profile",
                    "--env",
                    "AWS_REGION=override-region",
                    "shell",
                ]
            )
            (self.home / ".aws").mkdir(exist_ok=True)

            env = launcher.build_env_vars(launch.SUBCOMMAND_CONFIG["shell"])
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["shell"], env)

            self.assertEqual(env["CLAUDE_CODE_USE_BEDROCK"], "1")
            self.assertEqual(env["AWS_PROFILE"], "override-profile")
            self.assertEqual(env["AWS_REGION"], "override-region")
            self.assertEqual(env["AWS_SECRET_ACCESS_KEY"], "host-secret")
            self.assert_mount_present(mounts, self.home / ".aws", "/home/devuser/.aws")

    def test_env_override_can_disable_bedrock(self):
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "AWS_PROFILE": "host-profile",
                "AWS_REGION": "host-region",
                "AWS_SECRET_ACCESS_KEY": "host-secret",
            },
            clear=False,
        ):
            launcher = self.make_launcher(
                ["--env", "CLAUDE_CODE_USE_BEDROCK=0", "shell"]
            )
            (self.home / ".aws").mkdir(exist_ok=True)

            env = launcher.build_env_vars(launch.SUBCOMMAND_CONFIG["shell"])
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["shell"], env)

            self.assertEqual(env["CLAUDE_CODE_USE_BEDROCK"], "0")
            self.assertNotIn("AWS_PROFILE", env)
            self.assertNotIn("AWS_REGION", env)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
            self.assert_mount_missing(mounts, self.home / ".aws", "/home/devuser/.aws")

    def test_claude_requires_aws_profile_env_only_when_bedrock_enabled(self):
        with mock.patch.dict(
            os.environ, {"CLAUDE_CODE_USE_BEDROCK": "1"}, clear=False
        ):
            os.environ.pop("AWS_PROFILE", None)
            launcher = self.make_launcher(["claude"])

            with self.assertRaises(SystemExit):
                with self.assertLogs(launch.LOGGER, level="ERROR") as logs:
                    launcher.run()

            self.assertIn(
                "AWS_PROFILE must be set for claude when "
                "CLAUDE_CODE_USE_BEDROCK=1. Inherit it from the host or pass "
                "--env AWS_PROFILE=...",
                "\n".join(logs.output),
            )

    def test_claude_without_bedrock_does_not_require_aws_profile(self):
        os.environ.pop("CLAUDE_CODE_USE_BEDROCK", None)
        os.environ.pop("AWS_PROFILE", None)

        launcher = self.make_launcher(["claude"])
        with redirect_stdout(io.StringIO()):
            launcher.run()

    def test_codex_does_not_inherit_claude_or_aws_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_CODE_USE_BEDROCK": "1",
                "CLAUDE_CODE_NO_FLICKER": "1",
                "AWS_PROFILE": "host-profile",
                "AWS_REGION": "host-region",
            },
            clear=False,
        ):
            launcher = self.make_launcher(["codex"])
            (self.home / ".aws").mkdir(exist_ok=True)

            env = launcher.build_env_vars(launch.SUBCOMMAND_CONFIG["codex"])
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"], env)

            self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
            self.assertNotIn("CLAUDE_CODE_NO_FLICKER", env)
            self.assertNotIn("AWS_PROFILE", env)
            self.assertNotIn("AWS_REGION", env)
            self.assert_mount_missing(mounts, self.home / ".aws", "/home/devuser/.aws")

    def test_certs_default_from_launcher_env_var(self):
        certs_path = self.tmp_path / "default-certs.pem"
        certs_path.write_text("cert")

        with mock.patch.dict(
            os.environ,
            {launch.DEFAULT_CERTS_ENV_VAR: str(certs_path)},
            clear=False,
        ):
            launcher = self.make_launcher(["codex"])
            env = launcher.build_env_vars(launch.SUBCOMMAND_CONFIG["codex"])
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"], env)

            self.assertEqual(launcher.args.certs, str(certs_path.resolve()))
            self.assertEqual(env["SSL_CERT_FILE"], launch.CONTAINER_CERTS_PATH)
            self.assertEqual(env["AWS_CA_BUNDLE"], launch.CONTAINER_CERTS_PATH)
            self.assert_mount_present(
                mounts, certs_path.resolve(), launch.CONTAINER_CERTS_PATH
            )

    def test_certs_flag_overrides_launcher_env_var(self):
        default_certs = self.tmp_path / "default-certs.pem"
        override_certs = self.tmp_path / "override-certs.pem"
        default_certs.write_text("default")
        override_certs.write_text("override")

        with mock.patch.dict(
            os.environ,
            {launch.DEFAULT_CERTS_ENV_VAR: str(default_certs)},
            clear=False,
        ):
            launcher = self.make_launcher(["--certs", str(override_certs), "codex"])
            env = launcher.build_env_vars(launch.SUBCOMMAND_CONFIG["codex"])
            mounts = launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"], env)

            self.assertEqual(launcher.args.certs, str(override_certs.resolve()))
            self.assert_mount_present(
                mounts, override_certs.resolve(), launch.CONTAINER_CERTS_PATH
            )
            self.assert_mount_missing(
                mounts, default_certs.resolve(), launch.CONTAINER_CERTS_PATH
            )

    def test_warns_when_host_mount_nests_inside_existing_mount(self):
        launcher = self.make_launcher(
            ["--mount", str(self.home / ".codex" / "files"), "codex"]
        )
        (self.home / ".codex" / "files").mkdir(parents=True)

        with self.assertLogs(launch.LOGGER, level="WARNING") as logs:
            launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"])

        output = "\n".join(logs.output)
        self.assertIn("nested mounts detected", output)
        self.assertIn(str(self.home / ".codex"), output)
        self.assertIn(str(self.home / ".codex" / "files"), output)

    def test_warns_when_container_mount_nests_inside_existing_mount(self):
        external = self.tmp_path / "external"
        external.mkdir()
        launcher = self.make_launcher(
            ["--mount", f"{external}:/home/devuser/.codex/files", "codex"]
        )
        (self.home / ".codex").mkdir()

        with self.assertLogs(launch.LOGGER, level="WARNING") as logs:
            launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"])

        output = "\n".join(logs.output)
        self.assertIn("nested mounts detected", output)
        self.assertIn("/home/devuser/.codex", output)
        self.assertIn("/home/devuser/.codex/files", output)

    def test_warns_when_default_mounts_conflict_with_each_other(self):
        nested_local = self.workspace / "container-local"
        launcher = launch.Launcher(
            launch.parse_args(
                [
                    "--dry-run",
                    "--container-local-host-dir",
                    str(nested_local),
                    "codex",
                ]
            )
        )

        with self.assertLogs(launch.LOGGER, level="WARNING") as logs:
            launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"])

        output = "\n".join(logs.output)
        self.assertIn("nested mounts detected", output)
        self.assertIn(str(self.workspace), output)
        self.assertIn(str(nested_local), output)

    def test_verbose_logs_credential_mount_status(self):
        (self.home / ".codex").mkdir()
        launcher = launch.Launcher(
            launch.parse_args(
                [
                    "--dry-run",
                    "--verbose",
                    "--container-local-host-dir",
                    str(self.container_local),
                    "codex",
                ]
            )
        )

        with self.assertLogs(launch.LOGGER, level="INFO") as logs:
            launcher.build_mounts(launch.SUBCOMMAND_CONFIG["codex"])

        output = "\n".join(logs.output)
        self.assertIn("INFO:launch:Mounting credential: ~/.codex", output)


if __name__ == "__main__":
    unittest.main()
