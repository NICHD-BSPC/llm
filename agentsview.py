#!/usr/bin/env python3

"""Serve an agentsview instance (https://github.com/kenn-io/agentsview) under
Podman to search, browse, analyze current and historical sessions across
multiple agent harnesses."""

import argparse
import getpass
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

LOGGER = logging.getLogger("agentsview")

# Configure what gets mounted and how to tell agentsview about it.
#
# Tuples are (
#   agent,
#   path under home,
#   path inside container,
#   env override,
#   is_file
# )
SOURCES = (
    (
        "claude",
        ".claude/projects",
        "/agents/claude",
        "CLAUDE_PROJECTS_DIR=/agents/claude",
        False,
    ),
    ("pi", ".pi/agent/sessions", "/agents/pi", "PI_DIR=/agents/pi", False),
    ("omp", ".omp/agent/sessions", "/agents/omp", "OMP_DIR=/agents/omp", False),
    # agentsview handles CODEX_HOME a little differently; this keeps archived
    # sessions and title files discoverable. Only paths are mounted so we don't
    # inadvertently expose auth.json.
    (
        "codex",
        ".codex/sessions",
        "/agents/codex/sessions",
        "CODEX_HOME=/agents/codex",
        False,
    ),
    (
        "codex",
        ".codex/archived_sessions",
        "/agents/codex/archived_sessions",
        "CODEX_HOME=/agents/codex",
        False,
    ),
    (
        "codex",
        ".codex/session_index.jsonl",
        "/agents/codex/session_index.jsonl",
        "CODEX_HOME=/agents/codex",
        True,
    ),
    (
        "codex",
        ".codex/history.jsonl",
        "/agents/codex/history.jsonl",
        "CODEX_HOME=/agents/codex",
        True,
    ),
)


def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def existing_sources(home):
    return [
        source
        for source in SOURCES
        if ((home / source[1]).is_file() if source[4] else (home / source[1]).is_dir())
    ]


def log_sources(sources):
    for agent in dict.fromkeys(source[0] for source in SOURCES):
        paths = [source[1] for source in sources if source[0] == agent]
        if paths:
            LOGGER.info("%s: mounting %s", agent, ", ".join(paths))
        else:
            LOGGER.info("%s: skipping (no session paths found)", agent)


def require_sessions(sources):
    log_sources(sources)
    # Codex title/history sidecars alone do not contain sessions to serve.
    if not any(not source[4] for source in sources):
        raise ValueError("no agent session paths found; not starting an empty server")


def rsync_command(target, path, is_file, destination):
    # The probe's -f/-d follow symlinks, but rsync -a copies a top-level
    # symlink as a link that would then resolve on *this* machine. A trailing
    # slash makes rsync follow a symlinked directory; -L does the same for a
    # single file without following links inside session trees.
    source = f"{target}:./{path}" if is_file else f"{target}:./{path}/"
    return (
        ["rsync", "-a", "--relative"]
        + (["-L"] if is_file else [])
        + [source, destination]
    )


def check_pulled(tmp, sources):
    """
    Refuse to mount pulled paths that are missing or resolve outside tmp. This
    is further protection against improperly-handled symlinks.
    """
    for _, path, _, _, is_file in sources:
        pulled = (tmp / path).resolve()
        if not pulled.is_relative_to(tmp) or not (
            pulled.is_file() if is_file else pulled.is_dir()
        ):
            raise ValueError(
                f"pulled {path} is missing or links outside {tmp}; not serving it"
            )


def build_podman_command(home, sources, port, image, volume, name, detached=False):
    """Build the container command to run agentsview in podman from a local
    home or a pulled remote snapshot.

    Parameters
    ----------
    home : Path
        Root containing the agent paths in SOURCES; for remote runs, the
        temporary rsync destination rather than the user's actual home.
    sources : list
        Entries of SOURCES present under ``home``, already checked with
        ``require_sessions``.
    port : int
        Host loopback port. agentsview still listens on 8080 in the container.
    image : str
        Container image to run.
    volume : str
        Podman volume holding agentsview's persistent data and auth token.
    name : str
        Container name used for Podman commands such as token lookup.
    detached : bool
        Run in the background; the CLI only permits this for local sessions.
    """
    cmd = ["podman", "run", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:8080"]
    if detached:
        cmd.append("-d")
    cmd += ["-v", f"{volume}:/data"]

    # This makes telemetry opt *IN*
    telemetry = "1" if os.environ.get("AGENTSVIEW_TELEMETRY_ENABLED") == "1" else "0"
    cmd += ["-e", f"AGENTSVIEW_TELEMETRY_ENABLED={telemetry}"]

    for _, path, destination, _, _ in sources:
        cmd += ["-v", f"{home / path}:{destination}:ro"]
    for env in dict.fromkeys(source[3] for source in sources):
        cmd += ["-e", env]
    return cmd + [image]


def probe_remote(target):
    """Figure out which files/dirs are present on the remote"""

    script = "\n".join(
        f'if [ {"-f" if is_file else "-d"} "$HOME/{path}" ]; then printf "%s\\n" {shlex.quote(path)}; fi'
        for _, path, _, _, is_file in SOURCES
    )
    result = subprocess.run(
        ["ssh", target, "sh -c " + shlex.quote(script)],
        check=True,
        capture_output=True,
        text=True,
    )
    found = set(result.stdout.splitlines())
    return [source for source in SOURCES if source[1] in found]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=8080, help="host port (default: 8080)"
    )
    parser.add_argument(
        "--remote", help="pull sessions from this host instead of local home"
    )
    parser.add_argument("--user", default=getpass.getuser(), help="remote username")
    parser.add_argument("--image", default="ghcr.io/kenn-io/agentsview:latest")
    parser.add_argument(
        "--volume", help="Podman data volume (default: agentsview-data[-HOST])"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show command without starting Podman"
    )
    parser.add_argument(
        "--detach", "-d", action="store_true", help="run in background (local only)"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    # The host is also used in Podman volume and container names.
    if args.remote is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.remote
    ):
        parser.error(
            "--remote must be a plain hostname (letters, digits, '.', '_', '-'); use --user for the username"
        )
    if args.remote and args.detach:
        parser.error(
            "--detach cannot be used with --remote (remote files need cleanup)"
        )
    return args


def main(argv=None):
    configure_logging()
    args = parse_args(argv)
    # Agentsview archives sessions in /data; separate volumes keep remote
    # archives out of the local one.
    volume = args.volume or (
        f"agentsview-data-{args.remote}" if args.remote else "agentsview-data"
    )
    name = f"agentsview-{args.remote}" if args.remote else "agentsview"
    try:
        if args.remote:
            tools = ["ssh"] if args.dry_run else ["ssh", "rsync", "podman"]
        else:
            tools = [] if args.dry_run else ["podman"]
        for tool in tools:
            if not shutil.which(tool):
                raise ValueError(f"required executable not found: {tool}")
        if args.remote:
            target = f"{args.user}@{args.remote}" if args.user else args.remote
            sources = probe_remote(target)
            require_sessions(sources)
            if args.dry_run:
                for _, path, _, _, is_file in sources:
                    print(
                        shlex.join(
                            rsync_command(target, path, is_file, "<temporary-home>/")
                        )
                    )
                LOGGER.info(
                    "would serve copied sessions from a temporary directory; no files pulled"
                )
                return 0

            # On macOS /var is a symlink; Podman's VM needs the resolved /private path for bind mounts.
            tmp = Path(tempfile.mkdtemp(prefix="agentsview-")).resolve()
            os.chmod(tmp, 0o700)

            # NOTE: Ctrl-C (KeyboardInterrupt) and errors reach the `finally`
            # below, which removes tmp. But SIGTERM (`kill PID`, `timeout`)
            # will leave the temp files and leave podman running because Python
            # exits without running `finally`.
            try:
                # One source per call works with both GNU rsync and macOS openrsync.
                for _, path, _, _, is_file in sources:
                    subprocess.run(
                        rsync_command(target, path, is_file, str(tmp) + "/"), check=True
                    )
                check_pulled(tmp, sources)
                cmd = build_podman_command(
                    tmp, sources, args.port, args.image, volume, name
                )
                LOGGER.info(
                    "Open http://127.0.0.1:%s; token: podman exec %s grep auth_token /data/config.toml",
                    args.port,
                    name,
                )
                # subprocess.run() will send a sigkill if the process takes too
                # long with Ctrl-C. Using Popen here instead to give podman
                # more time to clean up.
                with subprocess.Popen(cmd) as process:
                    returncode = process.wait()
                    if returncode:
                        raise subprocess.CalledProcessError(returncode, cmd)
            finally:
                LOGGER.info("removing temporary sessions from %s", tmp)
                shutil.rmtree(tmp)
        else:
            sources = existing_sources(Path.home())
            require_sessions(sources)
            cmd = build_podman_command(
                Path.home(), sources, args.port, args.image, volume, name, args.detach
            )
            if args.dry_run:
                print(shlex.join(cmd))
            else:
                LOGGER.info(
                    "Open http://127.0.0.1:%s; token: podman exec %s grep auth_token /data/config.toml",
                    args.port,
                    name,
                )
                if args.detach:
                    subprocess.run(cmd, check=True)
                else:
                    with subprocess.Popen(cmd) as process:
                        returncode = process.wait()
                        if returncode:
                            raise subprocess.CalledProcessError(returncode, cmd)
    except (ValueError, subprocess.CalledProcessError) as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
