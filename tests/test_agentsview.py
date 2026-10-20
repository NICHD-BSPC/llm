# AI-generated regression tests. They pass, and are kept here to hopefully
# prevent future regressions, but they have NOT been fully evaluated.
import io
import os
import shlex
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
            self.assertEqual(cmd[cmd.index("--hostname") + 1], "local")
            self.assertIn(f"{root}/.omp/agent/sessions:/agents/omp:ro", cmd)
            self.assertIn(f"{root}/.codex/archived_sessions:/agents/codex/archived_sessions:ro", cmd)
            self.assertIn("OMP_DIR=/agents/omp", cmd)
            self.assertIn("CODEX_HOME=/agents/codex", cmd)
            self.assertNotIn("PI_DIR=/agents/pi", cmd)
            self.assertNotIn(".codex/auth.json", " ".join(cmd))
            self.assertIn("AGENTSVIEW_REQUIRE_AUTH=false", cmd)
            self.assertEqual(cmd[-4:], ["--host", "0.0.0.0", "--public-url", "http://127.0.0.1:9000"])

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
                self.assertEqual(agentsview.main(["--remote-only", "host"]), 1)
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
                self.assertEqual(run.call_count, 3)  # config writes
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
                    (Path(cmd[-1]) / path).mkdir(parents=True)
                return mock.Mock()
            run.side_effect = respond
            process = popen.return_value.__enter__.return_value
            process.wait.side_effect = effect
            process.wait.return_value = 0
            result = agentsview.main(["--remote-only", "host", "--user", "alice"] + (argv or []))
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
        self.assertEqual(cmd[cmd.index("--hostname") + 1], "host")
        self.assertIn(f"{Path(tmp).resolve()}/host/.pi/agent/sessions:/agents/pi:ro", cmd)

    def test_remote_cleanup_after_podman_failure_or_interrupt(self):
        for effect, expected in ((subprocess.CalledProcessError(1, ["podman"]), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(effect=effect):
                result, _, _ = self.remote_run(effect)
                self.assertEqual(result, expected)

    def test_verbose_logs_each_command(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".claude/projects").mkdir(parents=True)
            with mock.patch.object(agentsview.Path, "home", return_value=Path(home)), mock.patch.object(agentsview.subprocess, "run"), mock.patch.object(agentsview.subprocess, "Popen") as popen, mock.patch.object(agentsview.shutil, "which", return_value="/bin/podman"):
                popen.return_value.__enter__.return_value.wait.return_value = 0
                with self.assertLogs("agentsview", level="DEBUG") as logs:
                    self.assertEqual(agentsview.main(["--verbose"]), 0)
                commands = [line for line in logs.output if line.startswith("DEBUG:agentsview:+ ")]
                self.assertEqual(len(commands), 2)
                self.assertIn("cat > /data/config.toml", commands[0])
                self.assertIn(shlex.join(popen.call_args.args[0]), commands[1])
                with self.assertLogs("agentsview", level="DEBUG") as logs:
                    agentsview.main([])
                self.assertFalse([line for line in logs.output if line.startswith("DEBUG:")])

    def test_remote_rsync_failure_removes_temp(self):
        tmp = tempfile.mkdtemp(prefix="agentsview-test-")
        def respond(cmd, **kwargs):
            if cmd[0] == "ssh":
                return mock.Mock(stdout=".pi/agent/sessions\n")
            if cmd[0] == "rsync":
                raise subprocess.CalledProcessError(1, cmd)
            return mock.Mock()
        with mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=tmp), mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), mock.patch.object(agentsview.subprocess, "run", side_effect=respond):
            self.assertEqual(agentsview.main(["--remote-only", "host"]), 1)
        self.assertFalse(Path(tmp).exists())

    def test_remote_logs_sources_once(self):
        with self.assertLogs("agentsview", level="INFO") as logs:
            self.remote_run()
        self.assertEqual(sum("pi: mounting" in line for line in logs.output), 1)
        self.assertIn("host: rsyncing .pi/agent/sessions", "\n".join(logs.output))
        self.assertIn("host: finished rsyncing .pi/agent/sessions", "\n".join(logs.output))

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
            if cmd[0] == "rsync":
                (Path(cmd[-1]) / ".pi/agent").mkdir(parents=True)
                (Path(cmd[-1]) / ".pi/agent/sessions").symlink_to(local)
            return mock.Mock()
        with mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=tmp), mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), mock.patch.object(agentsview.subprocess, "run", side_effect=respond), mock.patch.object(agentsview.subprocess, "Popen") as popen:
            self.assertEqual(agentsview.main(["--remote-only", "host"]), 1)
            popen.assert_not_called()
        self.assertFalse(Path(tmp).exists())
        self.assertTrue(Path(local).exists())

    def test_remote_hostname_validated(self):
        for host in ("alice@host", "host:22", "::1", "-oProxyCommand=x", ""):
            with self.subTest(host=host), self.assertRaises(SystemExit), mock.patch("sys.stderr", new_callable=io.StringIO):
                agentsview.parse_args(["--remote", host])
        self.assertEqual(agentsview.parse_args(["--remote", "my-host.example_1.org"]).remote, ["my-host.example_1.org"])

    def test_remote_detach_rejected(self):
        with self.assertRaises(SystemExit):
            agentsview.parse_args(["--remote", "host", "-d"])


class CombinedTests(unittest.TestCase):
    def test_config_and_destinations(self):
        pi = agentsview.SOURCES[1]
        codex = agentsview.SOURCES[3:]
        self.assertEqual(agentsview.render_config("local", []),
                         '# Managed by agentsview.py; rewritten on every run.\nlocal_machine_name = "local"\n')
        self.assertEqual(agentsview.render_config("box", []),
                         '# Managed by agentsview.py; rewritten on every run.\nlocal_machine_name = "box"\n')
        text = agentsview.render_config("local", [("box", [pi] + list(codex)), ("hpc", [pi])])
        self.assertEqual(text.count("[[session_sources]]"), 4)
        self.assertIn('dir = "/remote/box/codex/archived_sessions"', text)
        self.assertIn('dir = "/remote/box/codex/sessions"', text)
        self.assertIn('machine = "hpc"', text)
        self.assertNotIn("history.jsonl", text)
        self.assertNotIn("session_index.jsonl", text)
        destinations = [source[2] for source in agentsview.SOURCES]
        for host in ("box", "hpc"):
            mapped = [agentsview.remote_destination(host, dest) for dest in destinations]
            self.assertEqual(mapped, [f"/remote/{host}/{dest.removeprefix('/agents/')}" for dest in destinations])
            self.assertFalse(set(mapped) & set(destinations))
        self.assertNotEqual(agentsview.remote_destination("box", destinations[0]),
                            agentsview.remote_destination("hpc", destinations[0]))
        self.assertEqual(agentsview.write_config_command("vol", "image"),
                         ["podman", "run", "--rm", "-i", "-v", "vol:/data", "--entrypoint", "sh", "image", "-c", "cat > /data/config.toml"])

    def test_command_and_cli(self):
        local = agentsview.SOURCES[1:2]
        remote = agentsview.SOURCES[0:1] + agentsview.SOURCES[3:4]
        cmd = agentsview.build_podman_command(Path("/home/local"), local, 9000, "image", "vol", "name",
                                              remotes=[("box", Path("/tmp/box"), remote)])
        self.assertIn("/home/local/.pi/agent/sessions:/agents/pi:ro", cmd)
        self.assertIn("/tmp/box/.claude/projects:/remote/box/claude:ro", cmd)
        self.assertIn("/tmp/box/.codex/sessions:/remote/box/codex/sessions:ro", cmd)
        self.assertIn("PI_DIR=/agents/pi", cmd)
        self.assertEqual(cmd[cmd.index("--hostname") + 1], "local")
        self.assertNotIn("CLAUDE_PROJECTS_DIR=/agents/claude", cmd)
        self.assertNotIn("CODEX_HOME=/agents/codex", cmd)
        self.assertEqual(cmd[-2:], ["--public-url", "http://127.0.0.1:9000"])
        self.assertEqual(agentsview.parse_args(["--remote", "box", "--remote", "hpc"]).remote, ["box", "hpc"])
        for argv in (["--remote", "box", "--remote", "box"],
                     ["--remote", "box", "--remote-only", "hpc"],
                     ["--remote", "box", "--detach"],
                     ["--remote-only", "box", "--detach"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), mock.patch("sys.stderr", new_callable=io.StringIO):
                agentsview.parse_args(argv)

    def combined_run(self, paths, effect=None, local=False):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            if local:
                (root / ".pi/agent/sessions").mkdir(parents=True)
            tmp = root / "scratch"
            tmp.mkdir()
            events = []
            def respond(cmd, **kwargs):
                events.append((cmd, kwargs))
                if cmd[0] == "ssh":
                    return mock.Mock(stdout=paths[cmd[1].split("@")[-1]])
                if cmd[0] == "rsync":
                    path = cmd[-2].split(":./", 1)[1].rstrip("/")
                    (Path(cmd[-1]) / path).mkdir(parents=True)
                return mock.Mock()
            with mock.patch.object(agentsview.Path, "home", return_value=root), \
                 mock.patch.object(agentsview.tempfile, "mkdtemp", return_value=str(tmp)) as mkdtemp, \
                 mock.patch.object(agentsview.shutil, "which", return_value="/bin/tool"), \
                 mock.patch.object(agentsview.subprocess, "run", side_effect=respond), \
                 mock.patch.object(agentsview.subprocess, "Popen") as popen:
                popen.return_value.__enter__.return_value.wait.side_effect = effect
                popen.return_value.__enter__.return_value.wait.return_value = 0
                result = agentsview.main(["--remote", "box", "--remote", "hpc"])
                command = popen.call_args.args[0] if popen.called else None
                if mkdtemp.called:
                    self.assertFalse(tmp.exists())
            return result, events, command, str(tmp)

    def test_combined_flow(self):
        paths = {"box": ".claude/projects\n.codex/history.jsonl\n", "hpc": ".pi/agent/sessions\n"}
        for effect, expected in ((None, 0), (subprocess.CalledProcessError(1, ["podman"]), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(effect=effect):
                result, events, cmd, tmp = self.combined_run(paths, effect)
                self.assertEqual(result, expected)
                self.assertEqual([c[0][0] for c in events], ["ssh", "ssh", "podman", "rsync", "rsync"])
                self.assertEqual([c[0][-1] for c in events if c[0][0] == "rsync"], [tmp + "/box/", tmp + "/hpc/"])
                self.assertIn("/remote/box/claude:ro", " ".join(cmd))
                self.assertNotIn("history.jsonl", " ".join(cmd) + str(events[3:]))
                self.assertIn('machine = "box"', events[2][1]["input"])

    def test_empty_host(self):
        paths = {"box": "", "hpc": ".pi/agent/sessions\n"}
        with self.assertLogs("agentsview", level="WARNING") as logs:
            result, events, cmd, _ = self.combined_run(paths)
        self.assertEqual(result, 0)
        self.assertIn("box: no session paths found", str(logs.output))
        self.assertEqual(len([c for c, _ in events if c[0] == "rsync"]), 1)
        result, events, cmd, _ = self.combined_run({"box": "", "hpc": ""})
        self.assertEqual(result, 1)
        self.assertEqual([c[0][0] for c in events], ["ssh", "ssh"])
        self.assertIsNone(cmd)
        result, _, cmd, _ = self.combined_run({"box": "", "hpc": ""}, local=True)
        self.assertEqual(result, 0)
        self.assertIsNotNone(cmd)


if __name__ == "__main__":
    unittest.main()
