# WARNING: AI generated. The models used this for updating tests as they
# worked. They remain un-reviewed, but retained with the assumption that they
# will act as regression tests if something changes.
#
# Since GitHub CI (where these tests are run) has no access to any secrets
# anyway and can't test auth, I consider this low risk.
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import launch
import refresh


def access_token(expires_in=timedelta(days=10)):
    """Build an unsigned JWT whose ``exp`` claim is ``expires_in`` from now."""
    exp = int((datetime.now(timezone.utc) + expires_in).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


def codex_auth(expires_in=timedelta(days=10), **tokens):
    auth = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": "old-id",
            "access_token": access_token(expires_in),
            "refresh_token": "old-refresh",
            "account_id": "acct-123",
        },
    }
    auth["tokens"].update(tokens)
    return auth


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
    def patch_managed_paths(self, root):
        bundle = Path(root) / ".aws" / "llm-export"
        return mock.patch.multiple(
            refresh,
            AWS_MANAGED_BUNDLE_DIR=bundle,
            AWS_CREDENTIALS_JSON=bundle / "credentials.json",
            AWS_CONFIG_PATH=bundle / "config",
        )

    def test_credential_paths_only_define_consumed_categories(self):
        for paths in refresh.CREDENTIAL_PATHS.values():
            self.assertEqual(set(paths), {"auth", "full"})

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

    def test_process_credentials_validation_rejects_invalid_exports(self):
        with self.assertRaises(TypeError):
            refresh.validate_aws_process_credentials([])
        for credentials in (
            valid_credentials(Version=2),
            valid_credentials(AccessKeyId=""),
            valid_credentials(SecretAccessKey=None),
            valid_credentials(SessionToken=""),
            valid_credentials(Expiration="2999-01-01T00:00:00"),
            valid_credentials(Expiration="2000-01-01T00:00:00Z"),
        ):
            with self.subTest(credentials=credentials), self.assertRaises(ValueError):
                refresh.validate_aws_process_credentials(credentials)

    def test_successful_export_calls_aws_once_without_login(self):
        result = mock.Mock(stdout=json.dumps(valid_credentials()))
        with mock.patch.object(refresh.subprocess, "run", return_value=result) as run:
            credentials = refresh.ensure_aws_credentials("source")
        self.assertEqual(credentials, valid_credentials())
        run.assert_called_once_with(
            ["aws", "configure", "export-credentials", "--format", "process", "--profile", "source"],
            capture_output=True, text=True, check=True,
        )

    def test_failed_export_logs_in_and_retries_once_with_profile(self):
        failure = subprocess.CalledProcessError(1, ["aws"])
        success = mock.Mock(stdout=json.dumps(valid_credentials()))
        with mock.patch.object(refresh.subprocess, "run", side_effect=[failure, None, success]) as run:
            credentials = refresh.ensure_aws_credentials("source profile")
        self.assertEqual(credentials, valid_credentials())
        self.assertEqual(run.call_args_list[0].args[0][-2:], ["--profile", "source profile"])
        self.assertEqual(
            run.call_args_list[1],
            mock.call(["aws", "sso", "login", "--profile", "source profile"], check=True),
        )
        self.assertEqual(run.call_args_list[2].args[0][-2:], ["--profile", "source profile"])

    def test_invalid_initial_credentials_login_then_invalid_retry_propagates(self):
        invalid = mock.Mock(stdout=json.dumps(valid_credentials(Expiration="expired")))
        with mock.patch.object(refresh.subprocess, "run", side_effect=[invalid, None, invalid]) as run:
            with self.assertRaises(ValueError):
                refresh.ensure_aws_credentials()
        self.assertEqual(run.call_count, 3)

    def test_bundle_write_is_private_atomic_and_preserves_aws_mode(self):
        credentials = valid_credentials()
        with tempfile.TemporaryDirectory() as tmpdir:
            aws_dir = Path(tmpdir) / ".aws"
            aws_dir.mkdir(mode=0o750)
            with self.patch_managed_paths(tmpdir):
                refresh.write_managed_aws_bundle(credentials)
                bundle = refresh.AWS_MANAGED_BUNDLE_DIR
                credentials_path = refresh.AWS_CREDENTIALS_JSON
                config_path = refresh.AWS_CONFIG_PATH
                self.assertEqual(json.loads(credentials_path.read_text()), credentials)
                self.assertEqual(config_path.read_text(), refresh.MANAGED_AWS_CONFIG)
                self.assertEqual(bundle.stat().st_mode & 0o777, 0o700)
                self.assertEqual(credentials_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(aws_dir.stat().st_mode & 0o777, 0o750)

    def test_new_aws_and_bundle_directories_are_private(self):
        with tempfile.TemporaryDirectory() as tmpdir, self.patch_managed_paths(tmpdir):
            refresh.write_managed_aws_bundle(valid_credentials())
            self.assertEqual(refresh.AWS_MANAGED_BUNDLE_DIR.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(refresh.AWS_MANAGED_BUNDLE_DIR.stat().st_mode & 0o777, 0o700)

    def test_interrupted_atomic_write_preserves_destination_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "credentials.json"
            path.write_text("old")
            before = set(path.parent.iterdir())
            with mock.patch.object(refresh.os, "replace", side_effect=OSError("stop")):
                with self.assertRaises(OSError):
                    refresh.atomic_write_private_text(path, "new")
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(set(path.parent.iterdir()), before)

    def test_written_bundle_is_accepted_by_launcher(self):
        with tempfile.TemporaryDirectory() as tmpdir, self.patch_managed_paths(tmpdir):
            refresh.write_managed_aws_bundle(valid_credentials())
            aws_dir = Path(tmpdir) / ".aws"
            bundle = aws_dir / "llm-export"
            with (
                mock.patch.multiple(
                    launch,
                    AWS_DIR=aws_dir,
                    AWS_MANAGED_BUNDLE_DIR=bundle,
                    AWS_MANAGED_CONFIG=bundle / "config",
                    AWS_MANAGED_CREDENTIALS_JSON=bundle / "credentials.json",
                ),
                mock.patch.dict(launch.os.environ, {}, clear=True),
            ):
                launcher = launch.Launcher(
                    launch.parse_args(["--env", "PI_USE_BEDROCK=1", "pi"])
                )
                environment, aws_mounts = launcher.build_runtime_environment()
                mounts = launcher.build_mounts(
                    launch.SUBCOMMAND_CONFIG["pi"], aws_mounts
                )

        self.assertEqual(environment["AWS_PROFILE"], "llm-export")
        self.assertEqual(
            environment["AWS_CONFIG_FILE"], launch.CONTAINER_AWS_MANAGED_CONFIG
        )
        self.assertEqual(
            [mount for mount in mounts if mount[1].startswith(launch.CONTAINER_AWS_DIR)],
            [(str(bundle), launch.CONTAINER_AWS_MANAGED_BUNDLE_DIR, True)],
        )

    def test_pi_auth_uses_private_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "codex-auth.json"
            destination = root / ".pi" / "agent" / "auth.json"
            source.write_text(json.dumps(codex_auth()))
            refresh.convert_codex_auth_to_pi(source, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)

    def test_remote_transfer_sets_and_no_export_behavior(self):
        self.assertIn("~/.aws/llm-export", refresh.transfer_paths("all", False))
        self.assertNotIn(
            "~/.aws/llm-export",
            refresh.transfer_paths("all", True, include_aws_export=False),
        )

    def test_no_export_creds_checks_but_does_not_write_or_transfer_bundle(self):
        args = mock.Mock(show_files=False, bedrock_export=False, aws_profile=None,
                         kind="all", no_export_creds=True, full=True,
                         remote="remote.example", user="tester")
        credentials = valid_credentials()
        with (
            mock.patch.object(refresh, "parse_args", return_value=args),
            mock.patch.dict(refresh.os.environ, {}, clear=True),
            mock.patch.object(refresh, "ensure_aws_credentials", return_value=credentials) as ensure,
            mock.patch.object(refresh, "write_managed_aws_bundle") as write,
            mock.patch.object(refresh, "refresh_codex"),
            mock.patch.object(refresh, "convert_codex_auth_to_pi"),
            mock.patch.object(refresh, "rsync_paths") as rsync,
        ):
            self.assertEqual(refresh.main(), 0)
        ensure.assert_called_once_with(None)
        write.assert_not_called()
        self.assertNotIn("~/.aws/llm-export", rsync.call_args.kwargs["paths"])

    def test_normal_refresh_passes_acquired_credentials_to_writer(self):
        args = mock.Mock(show_files=False, bedrock_export=False, aws_profile="source",
                         kind="claude", no_export_creds=False, full=False,
                         remote=None, user="tester")
        credentials = valid_credentials()
        with (
            mock.patch.object(refresh, "parse_args", return_value=args),
            mock.patch.object(refresh, "ensure_aws_credentials", return_value=credentials) as ensure,
            mock.patch.object(refresh, "write_managed_aws_bundle") as write,
        ):
            self.assertEqual(refresh.main(), 0)
        ensure.assert_called_once_with("source")
        write.assert_called_once_with(credentials)


class RefreshProfileSelectionTests(unittest.TestCase):
    def test_cli_parses_aws_profile_option(self):
        self.assertEqual(refresh.parse_args(["--aws-profile", "source profile"]).aws_profile, "source profile")
        self.assertIsNone(refresh.parse_args([]).aws_profile)

    def test_bedrock_export_is_not_a_kind(self):
        args = refresh.parse_args(["--bedrock-export", "--kind", "pi"])
        self.assertTrue(args.bedrock_export)
        with self.assertRaises(SystemExit):
            refresh.parse_args(["--kind", "bedrock"])

    def test_show_files_exits_successfully(self):
        args = mock.Mock(show_files=True)
        with mock.patch.object(refresh, "parse_args", return_value=args), mock.patch("sys.stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                refresh.main()
        self.assertEqual(error.exception.code, 0)

    def test_bedrock_export_reuses_acquired_expiration(self):
        args = mock.Mock(show_files=False, bedrock_export=True, aws_profile="source",
                         kind="pi", no_export_creds=False, full=True,
                         remote="remote.example", user="tester")
        credentials = valid_credentials()
        with (
            mock.patch.object(refresh, "parse_args", return_value=args),
            mock.patch.object(refresh, "ensure_aws_credentials", return_value=credentials) as ensure,
            mock.patch.object(refresh, "bedrock_export_command", return_value="export TOKEN=value") as command,
            mock.patch.object(refresh, "rsync_paths") as rsync,
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(refresh.main(), 0)
        ensure.assert_called_once_with("source")
        command.assert_called_once_with("source", credentials["Expiration"])
        rsync.assert_not_called()

    def test_bedrock_export_scopes_generation_to_profile(self):
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
            mock.patch.dict(sys.modules, {"aws_bedrock_token_generator": generator, "botocore.session": botocore_session}),
            mock.patch.dict(refresh.os.environ, env, clear=True),
        ):
            command = refresh.bedrock_export_command("source profile", "2999-01-01T00:00:00Z")
            self.assertNotIn("AWS_PROFILE", refresh.os.environ)
        self.assertEqual(command, "export AWS_BEARER_TOKEN_BEDROCK=test-token")
        botocore_session.Session.assert_called_once_with(profile="source profile")
        kwargs = provide_token.call_args.kwargs
        self.assertEqual(kwargs["region"], "us-east-1")
        self.assertEqual(kwargs["expiry"], timedelta(hours=12))
        self.assertEqual(kwargs["aws_credentials_provider"].load(), "creds")

    def test_bedrock_export_without_profile_uses_default_chain(self):
        provide_token = mock.Mock(return_value="test-token")
        generator = types.ModuleType("aws_bedrock_token_generator")
        generator.provide_token = provide_token
        with mock.patch.dict(sys.modules, {"aws_bedrock_token_generator": generator}):
            command = refresh.bedrock_export_command(None, None)
        self.assertEqual(command, "export AWS_BEARER_TOKEN_BEDROCK=test-token")
        provide_token.assert_called_once_with(expiry=timedelta(hours=12))


class RefreshCodexTokenTests(unittest.TestCase):
    def test_malformed_auth_falls_back_to_login(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text("not json")

            with mock.patch.object(refresh.subprocess, "run") as run:
                refresh.refresh_codex(path)

            run.assert_called_once_with(["codex", "login"], check=True)

    def test_refresh_skipped_while_access_token_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text(json.dumps(codex_auth()))

            with (
                mock.patch.object(refresh, "refresh_codex_tokens") as rotate,
                mock.patch.object(refresh.subprocess, "run") as run,
            ):
                refresh.refresh_codex(path)

            rotate.assert_not_called()
            run.assert_not_called()

    def test_expired_access_token_triggers_refresh_not_login(self):
        """``codex login status`` would have reported success here."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text(json.dumps(codex_auth(expires_in=-timedelta(days=2))))

            with (
                mock.patch.object(
                    refresh, "refresh_codex_tokens", return_value=codex_auth()
                ) as rotate,
                mock.patch.object(refresh.subprocess, "run") as run,
            ):
                refresh.refresh_codex(path)

            rotate.assert_called_once_with(path)
            run.assert_not_called()

    def test_reused_refresh_token_falls_back_to_login(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text(json.dumps(codex_auth(expires_in=-timedelta(days=2))))
            rejected = urllib.error.HTTPError(
                refresh.CODEX_TOKEN_URL,
                401,
                "Unauthorized",
                {},
                mock.Mock(read=lambda: b'{"error": "refresh_token_reused"}'),
            )

            with (
                mock.patch.object(
                    refresh, "refresh_codex_tokens", side_effect=rejected
                ),
                mock.patch.object(refresh.subprocess, "run") as run,
            ):
                refresh.refresh_codex(path)

            run.assert_called_once_with(["codex", "login"], check=True)

    def test_server_error_is_not_treated_as_a_login_problem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text(json.dumps(codex_auth(expires_in=-timedelta(days=2))))
            unavailable = urllib.error.HTTPError(
                refresh.CODEX_TOKEN_URL, 503, "Unavailable", {}, None
            )

            with (
                mock.patch.object(
                    refresh, "refresh_codex_tokens", side_effect=unavailable
                ),
                mock.patch.object(refresh.subprocess, "run") as run,
            ):
                with self.assertRaises(urllib.error.HTTPError):
                    refresh.refresh_codex(path)

            run.assert_not_called()

    def test_rotation_preserves_fields_absent_from_the_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auth.json"
            path.write_text(json.dumps(codex_auth(expires_in=-timedelta(days=2))))
            rotated = access_token()
            response = mock.MagicMock()
            response.read.return_value = json.dumps(
                {"access_token": rotated, "refresh_token": "new-refresh"}
            ).encode()
            response.__enter__.return_value = response

            with mock.patch.object(
                refresh.urllib.request, "urlopen", return_value=response
            ) as urlopen:
                refresh.refresh_codex_tokens(path)

            request = urlopen.call_args.args[0]
            self.assertEqual(
                json.loads(request.data),
                {
                    "client_id": refresh.CODEX_CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": "old-refresh",
                },
            )

            auth = json.loads(path.read_text())
            self.assertEqual(auth["tokens"]["access_token"], rotated)
            self.assertEqual(auth["tokens"]["refresh_token"], "new-refresh")
            self.assertEqual(auth["tokens"]["id_token"], "old-id")
            self.assertEqual(auth["tokens"]["account_id"], "acct-123")
            self.assertIn("OPENAI_API_KEY", auth)
            self.assertTrue(auth["last_refresh"].endswith("Z"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_pi_auth_rejects_expired_codex_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "codex-auth.json"
            destination = root / "auth.json"

            source.write_text(json.dumps(codex_auth(expires_in=-timedelta(days=2))))
            with self.assertRaisesRegex(ValueError, "expired"):
                refresh.convert_codex_auth_to_pi(source, destination)
            self.assertFalse(destination.exists())

    def test_pi_auth_allows_switching_from_a_newer_credential(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "codex-auth.json"
            destination = root / "auth.json"
            source_auth = codex_auth(
                expires_in=timedelta(days=1), account_id="new-account"
            )
            source.write_text(json.dumps(source_auth))
            destination.write_text(
                json.dumps(
                    {
                        "openai-codex": {
                            "type": "oauth",
                            "access": "old-access",
                            "refresh": "old-refresh",
                            "expires": int(
                                (
                                    datetime.now(timezone.utc) + timedelta(days=9)
                                ).timestamp()
                                * 1000
                            ),
                            "accountId": "old-account",
                        }
                    }
                )
            )

            refresh.convert_codex_auth_to_pi(source, destination)

            updated = json.loads(destination.read_text())["openai-codex"]
            self.assertEqual(updated["access"], source_auth["tokens"]["access_token"])
            self.assertEqual(updated["accountId"], "new-account")


if __name__ == "__main__":
    unittest.main()
