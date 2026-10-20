# AI-generated regression tests. They pass, and are kept here to hopefully
# prevent future regressions, but they have NOT been fully evaluated.
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agentsview


class AgentsviewTests(unittest.TestCase):
    def test_no_paths_does_not_start_podman(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(agentsview.Path, "home", return_value=Path(home)), mock.patch.object(agentsview.shutil, "which", return_value="/bin/podman"), mock.patch.object(agentsview.subprocess, "run") as run:
            self.assertEqual(agentsview.main([]), 1)
            run.assert_not_called()

    def test_partial_mounts_and_port(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            for path in (".omp/agent/sessions", ".codex/archived_sessions"):
                (root / path).mkdir(parents=True)
            (root / ".codex/auth.json").write_text("secret")
            cmd = agentsview.build_podman_command(root, agentsview.existing_sources(root), 9000, "image", "data", "name")
            self.assertIn("127.0.0.1:9000:8080", cmd)
            self.assertIn(f"{root}/.omp/agent/sessions:/agents/omp:ro", cmd)
            self.assertIn(f"{root}/.codex/archived_sessions:/agents/codex/archived_sessions:ro", cmd)
            self.assertIn("OMP_DIR=/agents/omp", cmd)
            self.assertIn("CODEX_HOME=/agents/codex", cmd)
            self.assertNotIn("PI_DIR=/agents/pi", cmd)
            self.assertNotIn(".codex/auth.json", " ".join(cmd))

    def test_telemetry_disabled_unless_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".pi/agent/sessions").mkdir(parents=True)
            for value, expected in ((None, "0"), ("0", "0"), ("other", "0"), ("1", "1")):
                with self.subTest(value=value), mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("AGENTSVIEW_TELEMETRY_ENABLED", None)
                    if value is not None:
                        os.environ["AGENTSVIEW_TELEMETRY_ENABLED"] = value
                    cmd = agentsview.build_podman_command(Path(home), agentsview.existing_sources(Path(home)), 8080, "image", "data", "name")
                    self.assertIn(f"AGENTSVIEW_TELEMETRY_ENABLED={expected}", cmd)

    def test_codex_sidecars_alone_do_not_start_podman(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            (root / ".codex").mkdir()
            (root / ".codex/history.jsonl").touch()
            with self.assertRaisesRegex(ValueError, "no agent session paths"):
                agentsview.require_sessions(agentsview.existing_sources(root))
            with mock.patch.object(agentsview.shutil, "which", return_value="/bin/ssh"), mock.patch.object(agentsview.subprocess, "run", return_value=mock.Mock(stdout=".codex/history.jsonl\n")) as run:
                self.assertEqual(agentsview.main(["--remote", "host", "--dry-run"]), 1)
                self.assertEqual(run.call_count, 1)

    def test_local_defaults_and_detach(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".pi/agent/sessions").mkdir(parents=True)
            with mock.patch.object(agentsview.Path, "home", return_value=Path(home)), mock.patch.object(agentsview.shutil, "which", return_value="/bin/podman"), mock.patch.object(agentsview.subprocess, "run") as run:
                self.assertEqual(agentsview.main(["-d"]), 0)
                cmd = run.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--name") + 1], "agentsview")
                self.assertIn("agentsview-data:/data", cmd)
                self.assertIn("-d", cmd)

    def test_local_foreground_waits_without_run_killing_podman(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".pi/agent/sessions").mkdir(parents=True)
            with mock.patch.object(agentsview.Path, "home", return_value=Path(home)), mock.patch.object(agentsview.shutil, "which", return_value="/bin/podman"), mock.patch.object(agentsview.subprocess, "run") as run, mock.patch.object(agentsview.subprocess, "Popen") as popen:
                process = popen.return_value.__enter__.return_value
                for result, expected in ((0, 0), (1, 1), (KeyboardInterrupt(), 130)):
                    with self.subTest(result=result):
                        process.wait.side_effect = result if isinstance(result, BaseException) else None
                        process.wait.return_value = result
                        self.assertEqual(agentsview.main([]), expected)
                run.assert_not_called()
                cmd = popen.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--name") + 1], "agentsview")
                self.assertNotIn("-d", cmd)

    def remote_run(self, effect=None, argv=None):
        paths = ".pi/agent/sessions\n.codex/archived_sessions\n"
        tmp = tempfile.mkdtemp(prefix="agentsview-test-")
        # mkdtemp inside main is mocked so the test owns cleanup of its parent.
        with mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=tmp), mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), mock.patch.object(agentsview.subprocess, "run") as run, mock.patch.object(agentsview.subprocess, "Popen") as popen:
            def respond(cmd, **kwargs):
                if cmd[0] == "ssh":
                    return mock.Mock(stdout=paths)
                if cmd[0] == "rsync":
                    path = cmd[-2].split(":./", 1)[1].rstrip("/")
                    (Path(tmp) / path).mkdir(parents=True)
                return mock.Mock()
            run.side_effect = respond
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = effect
            process.wait.return_value = 0
            result = agentsview.main(["--remote", "host", "--user", "alice"] + (argv or []))
            calls = [call.args[0] for call in run.call_args_list] + [popen.call_args.args[0]]
        self.assertFalse(Path(tmp).exists())
        return result, calls, tmp

    def test_remote_probe_sync_and_cleanup(self):
        result, calls, tmp = self.remote_run()
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][:2], ["ssh", "alice@host"])
        rsync = [cmd for cmd in calls if cmd[0] == "rsync"]
        self.assertEqual([cmd[-2] for cmd in rsync], ["alice@host:./.pi/agent/sessions/", "alice@host:./.codex/archived_sessions/"])
        cmd = calls[-1]
        self.assertEqual(cmd[cmd.index("--name") + 1], "agentsview-host")
        self.assertIn("agentsview-data-host:/data", cmd)
        self.assertIn(f"{Path(tmp).resolve()}/.pi/agent/sessions:/agents/pi:ro", cmd)

    def test_remote_cleanup_after_podman_failure_or_interrupt(self):
        for effect, expected in ((subprocess.CalledProcessError(1, ["podman"]), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(effect=effect):
                result, _, _ = self.remote_run(effect)
                self.assertEqual(result, expected)

    def test_dry_run_local_does_not_execute(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".claude/projects").mkdir(parents=True)
            with mock.patch.object(agentsview.Path, "home", return_value=Path(home)), mock.patch.object(agentsview.subprocess, "run") as run, mock.patch.object(agentsview.shutil, "which", return_value=None), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(agentsview.main(["--dry-run"]), 0)
                self.assertIn("podman run", output.getvalue())
                run.assert_not_called()

    def test_remote_dry_run_only_probes(self):
        with mock.patch.object(agentsview.shutil, "which", return_value="/bin/ssh"), mock.patch.object(agentsview.subprocess, "run", return_value=mock.Mock(stdout=".pi/agent/sessions\n")) as run, mock.patch.object(agentsview.tempfile, "mkdtemp") as mkdtemp, mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(agentsview.main(["--remote", "host", "--dry-run"]), 0)
            self.assertEqual(run.call_count, 1)
            self.assertIn("rsync -a --relative", output.getvalue())
            mkdtemp.assert_not_called()

    def test_remote_rsync_failure_removes_temp(self):
        tmp = tempfile.mkdtemp(prefix="agentsview-test-")
        def respond(cmd, **kwargs):
            if cmd[0] == "ssh":
                return mock.Mock(stdout=".pi/agent/sessions\n")
            raise subprocess.CalledProcessError(1, cmd)
        with mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=tmp), mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), mock.patch.object(agentsview.subprocess, "run", side_effect=respond):
            self.assertEqual(agentsview.main(["--remote", "host"]), 1)
        self.assertFalse(Path(tmp).exists())

    def test_remote_logs_sources_once(self):
        with self.assertLogs("agentsview", level="INFO") as logs:
            self.remote_run()
        self.assertEqual(sum("pi: mounting" in line for line in logs.output), 1)

    def test_rsync_follows_top_level_symlinks(self):
        self.assertEqual(agentsview.rsync_command("u@h", ".pi/agent/sessions", False, "/tmp/x/"),
                         ["rsync", "-a", "--relative", "u@h:./.pi/agent/sessions/", "/tmp/x/"])
        self.assertEqual(agentsview.rsync_command("u@h", ".codex/history.jsonl", True, "/tmp/x/"),
                         ["rsync", "-a", "--relative", "-L", "u@h:./.codex/history.jsonl", "/tmp/x/"])

    def test_pulled_symlink_outside_temp_is_not_served(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as local:
            root = Path(tmp).resolve()
            (root / ".claude").mkdir()
            (root / ".claude/projects").symlink_to(local)
            sources = [source for source in agentsview.SOURCES if source[0] == "claude"]
            with self.assertRaisesRegex(ValueError, "links outside"):
                agentsview.check_pulled(root, sources)
            (root / ".claude/projects").unlink()
            (root / ".claude/projects").mkdir()
            agentsview.check_pulled(root, sources)

    def test_remote_symlink_outside_temp_never_starts_podman(self):
        tmp = tempfile.mkdtemp(prefix="agentsview-test-")
        local = tempfile.mkdtemp(prefix="agentsview-local-")
        self.addCleanup(shutil.rmtree, local)
        def respond(cmd, **kwargs):
            if cmd[0] == "ssh":
                return mock.Mock(stdout=".pi/agent/sessions\n")
            (Path(tmp) / ".pi/agent").mkdir(parents=True)
            (Path(tmp) / ".pi/agent/sessions").symlink_to(local)
            return mock.Mock()
        with mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=tmp), mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), mock.patch.object(agentsview.subprocess, "run", side_effect=respond), mock.patch.object(agentsview.subprocess, "Popen") as popen:
            self.assertEqual(agentsview.main(["--remote", "host"]), 1)
            popen.assert_not_called()
        self.assertFalse(Path(tmp).exists())
        self.assertTrue(Path(local).exists())

    def test_remote_hostname_validated(self):
        for host in ("alice@host", "host:22", "::1", "-oProxyCommand=x", ""):
            with self.subTest(host=host), self.assertRaises(SystemExit), mock.patch("sys.stderr", new_callable=io.StringIO):
                agentsview.parse_args(["--remote", host])
        self.assertEqual(agentsview.parse_args(["--remote", "my-host.example_1.org"]).remote, "my-host.example_1.org")

    def test_remote_detach_rejected(self):
        with self.assertRaises(SystemExit):
            agentsview.parse_args(["--remote", "host", "-d"])


if __name__ == "__main__":
    unittest.main()
