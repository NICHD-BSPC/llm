# WARNING: AI generated. The models used this for updating tests as they
# worked. They remain un-reviewed, but retained with the assumption that they
# will act as regression tests if something changes.
#
# Since GitHub CI (where these tests are run) has no access to any secrets
# anyway and can't test auth, I consider this low risk.
import json
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

import refresh


def valid_credentials(**overrides):
    credentials = {
        "Version": 1,
        "AccessKeyId": "test-key",
        "SecretAccessKey": "test-secret",
        "SessionToken": "test-token",
        "Expiration": "2999-01-01T00:00:00Z",
    }
    credentials.update(overrides)
    return credentials


class RefreshAwsTests(unittest.TestCase):
    def test_aws_export_credentials_uses_process_format_and_profile(self):
        credentials = valid_credentials()
        result = mock.Mock(stdout=json.dumps(credentials))

        with mock.patch.object(refresh.subprocess, "run", return_value=result) as run:
            exported = refresh.aws_export_credentials("source profile")

        self.assertEqual(exported, credentials)
        run.assert_called_once_with(
            [
                "aws",
                "configure",
                "export-credentials",
                "--format",
                "process",
                "--profile",
                "source profile",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_export_aws_profile_writes_managed_files_to_patched_paths(self):
        credentials = valid_credentials()
        result = mock.Mock(stdout=json.dumps(credentials))

        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            bundle_dir = aws_dir / "llm-export"
            credentials_path = bundle_dir / "credentials.json"
            config_path = bundle_dir / "config"
            with (
                mock.patch.object(refresh, "AWS_MANAGED_BUNDLE_DIR", bundle_dir),
                mock.patch.object(refresh, "AWS_CREDENTIALS_JSON", credentials_path),
                mock.patch.object(refresh, "AWS_CONFIG_PATH", config_path),
                mock.patch.object(refresh.subprocess, "run", return_value=result) as run,
            ):
                refresh.export_aws_profile()

            self.assertEqual(json.loads(credentials_path.read_text()), credentials)
            self.assertEqual(credentials_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(aws_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(bundle_dir.stat().st_mode & 0o777, 0o700)
            config = config_path.read_text()
            self.assertIn("[profile llm-export]", config)
            self.assertIn(
                "credential_process = sh -c 'cat ~/.aws/llm-export/credentials.json'",
                config,
            )
            self.assertEqual(list(bundle_dir.glob(".*.tmp")), [])

        run.assert_called_once_with(
            ["aws", "configure", "export-credentials", "--format", "process"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_export_does_not_change_existing_aws_directory_mode(self):
        credentials = valid_credentials()
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir(mode=0o750)
            bundle_dir = aws_dir / "llm-export"
            credentials_path = bundle_dir / "credentials.json"
            config_path = bundle_dir / "config"
            with (
                mock.patch.object(refresh, "AWS_MANAGED_BUNDLE_DIR", bundle_dir),
                mock.patch.object(refresh, "AWS_CREDENTIALS_JSON", credentials_path),
                mock.patch.object(refresh, "AWS_CONFIG_PATH", config_path),
                mock.patch.object(
                    refresh, "aws_export_credentials", return_value=credentials
                ),
            ):
                refresh.export_aws_profile()

            self.assertEqual(aws_dir.stat().st_mode & 0o777, 0o750)
            self.assertEqual(bundle_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(credentials_path.stat().st_mode & 0o777, 0o600)

    def test_atomic_replace_is_visible_through_stable_bundle_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir) / ".aws" / "llm-export"
            credentials_path = bundle_dir / "credentials.json"
            refresh.atomic_write_text(
                credentials_path,
                '{"state": "old"}\n',
                file_mode=0o600,
                new_parent_mode=0o700,
            )
            bundle_inode = bundle_dir.stat().st_ino

            refresh.atomic_write_text(
                credentials_path,
                '{"state": "new"}\n',
                file_mode=0o600,
            )

            self.assertEqual(bundle_dir.stat().st_ino, bundle_inode)
            self.assertEqual(credentials_path.read_text(), '{"state": "new"}\n')

    def test_remote_paths_include_bundle_and_exclude_sso_cache(self):
        paths = {
            path
            for credential_paths in refresh.CREDENTIAL_PATHS.values()
            for category in ("auth", "full")
            for path in credential_paths[category]
        }

        self.assertIn("~/.aws/llm-export", paths)
        self.assertNotIn("~/.aws/sso", paths)
        self.assertNotIn("~/.aws/config", paths)
        self.assertNotIn("~/.aws/credentials.json", paths)

    def test_atomic_refresh_is_always_complete_for_concurrent_reader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "credentials.json"
            refresh.atomic_write_text(
                destination, json.dumps(valid_credentials(AccessKeyId="key-0")) + "\n",
                file_mode=0o600,
            )
            done = threading.Event()
            errors = []

            def read_repeatedly():
                while not done.is_set():
                    try:
                        credentials = json.loads(destination.read_text())
                        refresh.validate_aws_process_credentials(credentials)
                    except BaseException as exc:
                        errors.append(exc)
                        done.set()

            reader = threading.Thread(target=read_repeatedly)
            reader.start()
            try:
                for index in range(100):
                    refresh.atomic_write_text(
                        destination,
                        json.dumps(valid_credentials(AccessKeyId=f"key-{index + 1}"))
                        + "\n",
                        file_mode=0o600,
                    )
            finally:
                done.set()
                reader.join()

            self.assertEqual(errors, [])

    def test_atomic_write_failure_preserves_destination_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "credentials.json"
            destination.write_text('{"state": "old"}\n')

            with mock.patch.object(
                refresh.os, "replace", side_effect=OSError("simulated failure")
            ):
                with self.assertRaisesRegex(OSError, "simulated failure"):
                    refresh.atomic_write_text(
                        destination,
                        '{"state": "new"}\n',
                        file_mode=0o600,
                    )

            self.assertEqual(destination.read_text(), '{"state": "old"}\n')
            self.assertEqual(list(Path(tmpdir).glob(".credentials.json.*.tmp")), [])

    def test_upsert_ini_section_preserves_unmanaged_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config"
            config_path.write_text(
                "# keep this comment\n"
                "[default]\n"
                "region = us-east-1\n\n"
                "[profile llm-export]\n"
                "credential_process = old-command\n"
                "region = us-west-2\n\n"
                "[profile another]\n"
                "output = json\n"
            )

            refresh.upsert_ini_section(
                config_path,
                "profile llm-export",
                {"credential_process": "new-command"},
            )

            config = config_path.read_text()
            self.assertIn("# keep this comment", config)
            self.assertIn("[default]\nregion = us-east-1", config)
            self.assertIn("[profile another]\noutput = json", config)
            self.assertEqual(config.count("[profile llm-export]"), 1)
            self.assertIn("credential_process = new-command", config)
            self.assertNotIn("old-command", config)
            self.assertNotIn("region = us-west-2", config)
            self.assertEqual(list(Path(tmpdir).glob(".config.*.tmp")), [])

    def test_pi_auth_uses_private_atomic_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "codex-auth.json"
            destination = root / ".pi" / "agent" / "auth.json"
            source.write_text(
                json.dumps(
                    {
                        "tokens": {
                            "access_token": "test-access",
                            "refresh_token": "test-refresh",
                        }
                    }
                )
            )

            refresh.convert_codex_auth_to_pi(source, destination)

            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                json.loads(destination.read_text())["openai-codex"]["access"],
                "test-access",
            )
            self.assertEqual(list(destination.parent.glob(".auth.json.*.tmp")), [])

    def test_process_credentials_validation_rejects_invalid_exports(self):
        invalid = (
            [],
            valid_credentials(Version=2),
            valid_credentials(AccessKeyId=""),
            valid_credentials(SecretAccessKey=None),
            valid_credentials(SessionToken=""),
            valid_credentials(Expiration="2999-01-01T00:00:00"),
            valid_credentials(Expiration="2000-01-01T00:00:00Z"),
        )
        for credentials in invalid:
            with self.subTest(credentials=credentials):
                with self.assertRaises(ValueError):
                    refresh.validate_aws_process_credentials(credentials)

    def test_failed_export_validation_preserves_previous_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir) / ".aws" / "llm-export"
            bundle_dir.mkdir(parents=True)
            credentials_path = bundle_dir / "credentials.json"
            credentials_path.write_text(json.dumps(valid_credentials()) + "\n")
            old_contents = credentials_path.read_text()
            result = mock.Mock(stdout=json.dumps(valid_credentials(Expiration="expired")))

            with (
                mock.patch.object(refresh, "AWS_MANAGED_BUNDLE_DIR", bundle_dir),
                mock.patch.object(refresh, "AWS_CREDENTIALS_JSON", credentials_path),
                mock.patch.object(refresh, "AWS_CONFIG_PATH", bundle_dir / "config"),
                mock.patch.object(refresh.subprocess, "run", return_value=result),
            ):
                with self.assertRaises(ValueError):
                    refresh.export_aws_profile()

            self.assertEqual(credentials_path.read_text(), old_contents)

    def test_remote_transfer_sets_and_no_export_behavior(self):
        auth_paths = refresh.transfer_paths("all", full=False)
        full_paths = refresh.transfer_paths("all", full=True)

        self.assertIn("~/.aws/llm-export", auth_paths)
        self.assertIn("~/.aws/llm-export", full_paths)
        self.assertNotIn("~/.aws/sso", auth_paths + full_paths)
        self.assertIn("~/.codex/auth.json", auth_paths)
        self.assertIn("~/.pi/agent/extensions", full_paths)
        self.assertNotIn("~/.pi/agent/extensions", auth_paths)

        for full in (False, True):
            with self.subTest(full=full):
                paths = refresh.transfer_paths(
                    "all", full=full, include_aws_export=False
                )
                self.assertNotIn("~/.aws/llm-export", paths)

    def test_no_export_creds_does_not_sync_stale_managed_bundle(self):
        args = mock.Mock(
            show_files=False,
            aws_profile=None,
            kind="all",
            no_export_creds=True,
            full=True,
            remote="remote.example",
            user="tester",
        )
        with (
            mock.patch.object(refresh, "parse_args", return_value=args),
            mock.patch.dict(refresh.os.environ, {}, clear=True),
            mock.patch.object(refresh, "refresh_aws_sso"),
            mock.patch.object(refresh, "export_aws_profile") as export,
            mock.patch.object(refresh, "refresh_codex"),
            mock.patch.object(refresh, "update_pi_codex_auth"),
            mock.patch.object(refresh, "rsync_paths") as rsync,
        ):
            self.assertEqual(refresh.main(), 0)

        export.assert_not_called()
        self.assertNotIn("~/.aws/llm-export", rsync.call_args.kwargs["paths"])

    def test_refresh_aws_sso_logs_in_when_credential_check_fails(self):
        check_error = subprocess.CalledProcessError(1, ["aws"])
        with (
            mock.patch.object(
                refresh, "aws_credential_expiration", side_effect=check_error
            ),
            mock.patch.object(refresh.subprocess, "run") as run,
        ):
            refresh.refresh_aws_sso()

        run.assert_called_once_with(["aws", "sso", "login"], check=True)


class RefreshProfileSelectionTests(unittest.TestCase):
    def test_cli_profile_overrides_inherited_env_profile(self):
        with mock.patch.dict(refresh.os.environ, {"AWS_PROFILE": "env-profile"}):
            self.assertEqual(refresh.resolve_source_profile("cli-profile"), "cli-profile")

    def test_inherited_profile_used_when_no_cli_option(self):
        with mock.patch.dict(refresh.os.environ, {"AWS_PROFILE": "env-profile"}):
            self.assertEqual(refresh.resolve_source_profile(None), "env-profile")

    def test_no_profile_preserves_aws_cli_default_behavior(self):
        env = {k: v for k, v in refresh.os.environ.items() if k != "AWS_PROFILE"}
        with mock.patch.dict(refresh.os.environ, env, clear=True):
            self.assertIsNone(refresh.resolve_source_profile(None))
        self.assertEqual(
            refresh.with_profile(["aws", "configure", "export-credentials"], None),
            ["aws", "configure", "export-credentials"],
        )

    def test_blank_profile_values_are_ignored(self):
        with mock.patch.dict(refresh.os.environ, {"AWS_PROFILE": "  "}):
            self.assertIsNone(refresh.resolve_source_profile(""))

    def test_profile_with_metacharacters_stays_a_separate_argument(self):
        self.assertEqual(
            refresh.with_profile(["aws", "sso", "login"], "weird profile; rm -rf /"),
            ["aws", "sso", "login", "--profile", "weird profile; rm -rf /"],
        )

    def test_cli_parses_aws_profile_option(self):
        self.assertEqual(
            refresh.parse_args(["--aws-profile", "source profile"]).aws_profile,
            "source profile",
        )
        self.assertIsNone(refresh.parse_args([]).aws_profile)

    def test_selected_profile_reaches_check_and_login_paths(self):
        check_error = subprocess.CalledProcessError(1, ["aws"])
        with (
            mock.patch.object(
                refresh, "aws_credential_expiration", side_effect=check_error
            ) as check,
            mock.patch.object(refresh.subprocess, "run") as run,
        ):
            refresh.refresh_aws_sso("source profile")

        check.assert_called_once_with("source profile")
        run.assert_called_once_with(
            ["aws", "sso", "login", "--profile", "source profile"], check=True
        )

    def test_credential_expiration_passes_profile(self):
        result = mock.Mock(stdout=json.dumps({"Expiration": "2026-01-01T00:00:00Z"}))
        with mock.patch.object(refresh.subprocess, "run", return_value=result) as run:
            expiration = refresh.aws_credential_expiration("source profile")

        self.assertEqual(expiration, "2026-01-01T00:00:00Z")
        self.assertEqual(
            run.call_args.args[0],
            ["aws", "configure", "export-credentials", "--profile", "source profile"],
        )

    def test_export_aws_profile_passes_profile_to_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_dir = Path(tmpdir) / ".aws" / "llm-export"
            with (
                mock.patch.object(refresh, "AWS_MANAGED_BUNDLE_DIR", bundle_dir),
                mock.patch.object(
                    refresh, "AWS_CREDENTIALS_JSON", bundle_dir / "credentials.json"
                ),
                mock.patch.object(refresh, "AWS_CONFIG_PATH", bundle_dir / "config"),
                mock.patch.object(
                    refresh, "aws_export_credentials", return_value={"Version": 1}
                ) as export,
            ):
                refresh.export_aws_profile("source profile")

        export.assert_called_once_with("source profile")

    def test_bedrock_token_scopes_generation_to_profile(self):
        session = mock.Mock()
        session.get_config_variable.return_value = "us-east-1"
        session.get_credentials.return_value = "creds"
        provide_token = mock.Mock(return_value="test-token")
        generator = types.ModuleType("aws_bedrock_token_generator")
        generator.provide_token = provide_token
        botocore_session = types.ModuleType("botocore.session")
        botocore_session.Session = mock.Mock(return_value=session)
        env = {k: v for k, v in refresh.os.environ.items() if k != "AWS_PROFILE"}

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "aws_bedrock_token_generator": generator,
                    "botocore.session": botocore_session,
                },
            ),
            mock.patch.dict(refresh.os.environ, env, clear=True),
        ):
            token = refresh.bedrock_token("source profile", timedelta(hours=12))
            # Global environment must not be mutated to select the profile.
            self.assertNotIn("AWS_PROFILE", refresh.os.environ)

        self.assertEqual(token, "test-token")
        botocore_session.Session.assert_called_once_with(profile="source profile")
        kwargs = provide_token.call_args.kwargs
        self.assertEqual(kwargs["region"], "us-east-1")
        self.assertEqual(kwargs["expiry"], timedelta(hours=12))
        self.assertEqual(kwargs["aws_credentials_provider"].load(), "creds")

    def test_bedrock_token_without_profile_uses_default_chain(self):
        provide_token = mock.Mock(return_value="test-token")
        generator = types.ModuleType("aws_bedrock_token_generator")
        generator.provide_token = provide_token

        with mock.patch.dict(sys.modules, {"aws_bedrock_token_generator": generator}):
            token = refresh.bedrock_token(None, timedelta(hours=12))

        self.assertEqual(token, "test-token")
        provide_token.assert_called_once_with(expiry=timedelta(hours=12))

    def test_bedrock_export_command_threads_profile_through(self):
        with (
            mock.patch.object(
                refresh, "aws_credential_expiration", return_value=None
            ) as check,
            mock.patch.object(refresh, "bedrock_token", return_value="test-token") as token,
            mock.patch.dict(
                sys.modules,
                {
                    "aws_bedrock_token_generator": types.ModuleType(
                        "aws_bedrock_token_generator"
                    )
                },
            ),
        ):
            command = refresh.bedrock_export_command("source profile")

        self.assertEqual(command, "export AWS_BEARER_TOKEN_BEDROCK=test-token")
        check.assert_called_once_with("source profile")
        self.assertEqual(token.call_args.args[0], "source profile")


if __name__ == "__main__":
    unittest.main()
