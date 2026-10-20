#!/usr/bin/env python3

"""Serve an agentsview instance (https://github.com/kenn-io/agentsview) under
Podman to search, browse, analyze current and historical sessions across
multiple agent harnesses."""

import argparse
import getpass
import json
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


def configure_logging(verbose=False):
    logging.basicConfig(format="%(levelname)s: %(message)s")
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)


def run(cmd, **kwargs):
    """subprocess.run with check=True, logging the command for --verbose."""
    LOGGER.debug("+ %s", shlex.join(cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def run_foreground(cmd):
    LOGGER.debug("+ %s", shlex.join(cmd))
    # Popen gives podman time to clean up on Ctrl-C (unlike subprocess.run).
    with subprocess.Popen(cmd) as process:
        returncode = process.wait()
        if returncode:
            raise subprocess.CalledProcessError(returncode, cmd)


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
    # If we only have Codex title/history files (the only things marked as
    # "file") those don't have sessions so nothing to show.
    if not any(not source[4] for source in sources):
        raise ValueError("no agent session paths found; not starting an empty server")


def rsync_command(target, path, is_file, destination):
    # When checking for existence on the remote, symlinks are followed. But
    # rsync -a copies a top-level symlink as a link that would then resolve on
    # *this* machine. A trailing slash makes rsync follow a symlinked directory
    # and -L does the same for a single file without following links inside
    # session trees.
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


def remote_destination(host, destination):
    # we don't want it in /agents, we want to keep it in /remote
    return f"/remote/{host}/{destination.removeprefix('/agents/')}"


def render_config(local_name, remotes):
    """
    Render agentsview's /data/config.toml so sessions will display machine
    labels.

    The file is rewritten every run.

    Parameters
    ----------
    local_name : str
        ``local_machine_name``: the label for sessions found via the env-var
        dirs (see SOURCES) under /agents. In --remote-only mode this is the
        remote host, since its pulled sessions are mounted at the local /agents
        paths.
    remotes : list of (str, list)
        Identified ``(host, sources)`` pairs to expose as
        ``[[session_sources]]``. Empty for local-only and --remote-only runs.

    """
    # json.dumps quoting is valid TOML here: every value is a fixed name/path
    # or a hostname that parse_args restricted to plain ASCII.
    lines = ["# Managed by agentsview.py; rewritten on every run.",
             f"local_machine_name = {json.dumps(local_name)}"]
    for host, sources in remotes:
        for agent, _, destination, _, is_file in sources:
            # The Codex sidecar files have no session_sources equivalent.
            if is_file:
                continue
            lines.extend(["", "[[session_sources]]", f"agent = {json.dumps(agent)}",
                          f"dir = {json.dumps(remote_destination(host, destination))}",
                          f"machine = {json.dumps(host)}"])
    return "\n".join(lines) + "\n"


def write_config_command(volume, image):
    # The config must live inside the named volume (agentsview reads it only
    # from $AGENTSVIEW_DATA_DIR), and on macOS the volume lives in Podman's VM,
    # so write it from a throwaway container fed on stdin. This also creates
    # the volume on first run. The entrypoint override bypasses agentsview.
    return ["podman", "run", "--rm", "-i", "-v", f"{volume}:/data",
            "--entrypoint", "sh", image, "-c", "cat > /data/config.toml"]


def build_podman_command(home, sources, port, image, volume, name, detached=False, remotes=(), local_name="local"):
    """Build the container command to run agentsview in podman from a local
    home or a pulled remote snapshot.

    Parameters
    ----------
    home : Path
        Root containing the agent paths in SOURCES; for remote runs, the
        temporary rsync destination rather than the user's actual home.
    sources : list
        Entries of SOURCES present under ``home``, mounted at their /agents
        paths with their env overrides. May be empty in combined mode when
        only remotes have sessions.
    port : int
        Host loopback port. agentsview still listens on 8080 in the container.
    image : str
        Container image to run.
    volume : str
        Podman volume holding agentsview's persistent data.
    name : str
        Container name.
    detached : bool
        Run in the background; the CLI only permits this for local sessions.
    remotes : iterable of (str, Path, list)
        ``(host, root, sources)`` triples from ``pull_remotes`` for combined
        mode. Only directories are mounted, at ``remote_destination`` paths
        that must match the ``[[session_sources]]`` in ``render_config``.
    local_name : str
        Label for sessions under /agents; also used as the container hostname.
    """
    # Match the config label even if agentsview falls back to the container
    # hostname (which is typically a hash generated by podman)
    cmd = ["podman", "run", "--rm", "--name", name, "--hostname", local_name,
           "-p", f"127.0.0.1:{port}:8080"]
    if detached:
        cmd.append("-d")
    cmd += ["-v", f"{volume}:/data"]

    # agentsview has telemetry enabled by default. This makes telemetry opt *IN*
    telemetry = "1" if os.environ.get("AGENTSVIEW_TELEMETRY_ENABLED") == "1" else "0"
    cmd += ["-e", f"AGENTSVIEW_TELEMETRY_ENABLED={telemetry}",
            "-e", "AGENTSVIEW_REQUIRE_AUTH=false"]

    for _, path, destination, _, _ in sources:
        cmd += ["-v", f"{home / path}:{destination}:ro"]
    for env in dict.fromkeys(source[3] for source in sources):
        cmd += ["-e", env]
    for host, root, remote_sources in remotes:
        for _, path, destination, _, is_file in remote_sources:
            if not is_file:
                cmd += ["-v", f"{root / path}:{remote_destination(host, destination)}:ro"]

    # This adds the host-side port to agentsview so we can use ports other than 8080.
    return cmd + [image, "--host", "0.0.0.0", "--public-url", f"http://127.0.0.1:{port}"]


def ssh_target(user, host):
    return f"{user}@{host}" if user else host


def probe_remote(target):
    """Return the SOURCES entries present under the remote user's $HOME.

    ``target`` is an ssh destination (``user@host`` or ``host``).
    """
    # NOTE: wrapped in `sh -c` to ensure remote command is interpreted by sh.
    # $HOME expands remotely here.

    script = "\n".join(
        f'if [ {"-f" if is_file else "-d"} "$HOME/{path}" ]; then printf "%s\\n" {shlex.quote(path)}; fi'
        for _, path, _, _, is_file in SOURCES
    )
    result = run(["ssh", target, "sh -c " + shlex.quote(script)], capture_output=True, text=True)
    found = set(result.stdout.splitlines())
    return [source for source in SOURCES if source[1] in found]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=8080, help="host port (default: 8080)"
    )
    remote_group = parser.add_mutually_exclusive_group()
    remote_group.add_argument(
        "--remote", action="append", help="add sessions from this host (repeatable)"
    )
    remote_group.add_argument(
        "--remote-only", help="serve only sessions from this host"
    )
    parser.add_argument("--user", default=getpass.getuser(), help="remote username")
    parser.add_argument("--image", default="ghcr.io/kenn-io/agentsview:latest")
    parser.add_argument(
        "--volume", help="Podman data volume (default: agentsview-data[-HOST])"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="log each command before running it"
    )
    parser.add_argument(
        "--detach", "-d", action="store_true", help="run in background (local only)"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    # Hosts also become path components, and remote-only uses one in Podman
    # names. So we need to sanitize them.
    for host in (args.remote or []) + ([args.remote_only] if args.remote_only is not None else []):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host) or host in (".", ".."):
            parser.error("--remote/--remote-only must be a plain hostname (letters, digits, '.', '_', '-'); use --user for the username")
    if args.remote and len(set(args.remote)) != len(args.remote):
        parser.error("--remote hosts must be unique")
    if (args.remote or args.remote_only) and args.detach:
        parser.error("--detach cannot be used with --remote or --remote-only (remote files need cleanup)")
    return args


def pull_remotes(user, hosts, tmp, include_files):
    """Pull probed (host, sources) pairs into separate roots under tmp. Then
    agentsview can serve them from there.

    Parameters
    ----------
    user : str
        ``--user`` value used for every host.
    hosts : list of (str, list)
        ``(host, sources)`` pairs from ``probe_remote``, already filtered to
        hosts with at least one session directory.
    tmp : Path
        Resolved private temp dir; each host gets ``tmp / host``.
    include_files : bool
        Also pull the Codex sidecar files. Only useful in --remote-only mode,
        where the snapshot is mounted as CODEX_HOME; combined mode mounts
        remote directories only.

    Returns
    -------
    list of (str, Path, list)
        ``(host, root, pulled_sources)`` triples for ``build_podman_command``.
    """
    pulled = []
    for host, sources in hosts:
        selected = [source for source in sources if include_files or not source[4]]
        root = tmp / host
        root.mkdir()
        # One source per call works with both GNU rsync and macOS openrsync.
        for _, path, _, _, is_file in selected:
            LOGGER.info("%s: rsyncing %s", host, path)
            run(rsync_command(ssh_target(user, host), path, is_file, f"{root}/"))
            LOGGER.info("%s: finished rsyncing %s", host, path)
        check_pulled(root, selected)
        pulled.append((host, root, selected))
    return pulled


def serve(cmd, port, detach):
    LOGGER.info("Open http://127.0.0.1:%s", port)
    if detach:
        run(cmd)
    else:
        run_foreground(cmd)


def main(argv=None):
    args = parse_args(argv)
    configure_logging(args.verbose)
    remote_only = args.remote_only is not None
    hosts = [args.remote_only] if remote_only else (args.remote or [])
    # agentsview archives sessions in /data. Local and combined runs share a
    # volume (machine labels keep them apart, and remote sessions archived
    # during a combined run stay searchable later); --remote-only gets its own.
    volume = args.volume or (f"agentsview-data-{args.remote_only}" if remote_only else "agentsview-data")
    name = f"agentsview-{args.remote_only}" if remote_only else "agentsview"
    local_name = args.remote_only if remote_only else "local"
    try:
        for tool in (["ssh", "rsync"] if hosts else []) + ["podman"]:
            if not shutil.which(tool):
                raise ValueError(f"required executable not found: {tool}")

        probed = [(host, probe_remote(ssh_target(args.user, host))) for host in hosts]
        local_sources = [] if remote_only else existing_sources(Path.home())
        for host, sources in probed:
            if not any(not source[4] for source in sources):
                LOGGER.warning("%s: no session paths found; skipping", host)
            else:
                LOGGER.info("%s: found session paths", host)
        remote_sources = [(host, sources) for host, sources in probed if any(not source[4] for source in sources)]
        require_sessions(local_sources + [source for _, sources in remote_sources for source in sources])

        # Written even for local-only runs, to drop session_sources left by an
        # earlier combined run in the same shared volume.
        config = render_config(local_name, [] if remote_only else remote_sources)
        run(write_config_command(volume, args.image), input=config, text=True)

        if not hosts:
            cmd = build_podman_command(Path.home(), local_sources, args.port, args.image, volume, name,
                                       args.detach, local_name=local_name)
            serve(cmd, args.port, args.detach)
            return 0

        # On macOS /var is a symlink; Podman's VM needs the resolved /private path.
        tmp = Path(tempfile.mkdtemp(prefix="agentsview-")).resolve()
        os.chmod(tmp, 0o700)
        # NOTE: SIGTERM does not run finally; kill/timeout can leave temp files and podman running.
        try:
            pulled = pull_remotes(args.user, remote_sources, tmp, include_files=remote_only)
            if remote_only:
                # The single remote's snapshot stands in for the local home.
                _, home, sources = pulled[0]
                remotes = []
            else:
                home, sources, remotes = Path.home(), local_sources, pulled
            cmd = build_podman_command(home, sources, args.port, args.image, volume, name,
                                       remotes=remotes, local_name=local_name)
            serve(cmd, args.port, detach=False)
        finally:
            LOGGER.info("removing temporary sessions from %s", tmp)
            shutil.rmtree(tmp)
    except (ValueError, subprocess.CalledProcessError) as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
