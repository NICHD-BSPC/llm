#!/usr/bin/env python3
"""
Launches an LLM dev container via podman or singularity.
"""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


CREDENTIAL_PATHS = {
    "codex": {
        "auth": ("~/.codex/auth.json",),
        "config": ("~/.codex/config.toml",),
        "full": ("~/.codex",),
    },
    "claude": {
        "auth": ("~/.aws/config", "~/.aws/sso/cache"),
        "config": ("~/.claude/settings.json", "~/.claude.json"),
        "full": ("~/.claude", "~/.aws"),
    },
}


def ensure_mount_target(path: Path, is_dir: bool) -> None:
    """Create a mount target on the host when it is expected to exist."""
    if is_dir:
        path.mkdir(parents=True, exist_ok=True)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def setup_host_paths(container_home_host_dir, container_local_host_dir) -> None:
    """
    Makes sure that directories and files mounted into the container exist.
    """
    # Claude Code wants at least a symlink to itself in ~/.local/bin.
    (Path(container_local_host_dir) / "bin").mkdir(parents=True, exist_ok=True)

    # Persistent container home.
    container_home = Path(container_home_host_dir)
    container_home.mkdir(parents=True, exist_ok=True)

    # Mount targets used by the tool-specific configs and auth-only mode.
    seen = set()
    for credential_paths in CREDENTIAL_PATHS.values():
        for path in (
            *credential_paths["auth"],
            *credential_paths["config"],
            *credential_paths["full"],
        ):
            if path in seen:
                continue
            seen.add(path)
            expanded = Path(path).expanduser()
            if expanded.exists():
                is_dir = expanded.is_dir()
            elif path in credential_paths["auth"] or path in credential_paths["config"]:
                # Auth/config mounts can be individual files even without an
                # extension, such as ~/.aws/config.
                is_dir = False
            elif path in credential_paths["full"]:
                is_dir = True
            else:
                is_dir = not expanded.suffix
            ensure_mount_target(expanded, is_dir=is_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch an LLM dev container via podman or singularity. "
            "Mounts the current working directory into the same absolute path "
            "inside the container by default; use --mount to include additional "
            "directories, --conda-env to mount environments (and add them to the PATH), "
            "and --env to pass environment variables into the container."
        ),
    )

    parser.add_argument(
        "--backend",
        choices=("podman", "singularity"),
        default="podman" if platform.system() == "Darwin" else "singularity",
        help="Container backend to use (default: %(default)s)",
    )
    parser.add_argument(
        "--image-name",
        default="llm-devcontainer",
        help="Container image name for the podman backend (default: %(default)s)",
    )
    parser.add_argument(
        "--arch",
        default="linux/amd64",
        help="Container platform for the podman backend (default: %(default)s)",
    )
    parser.add_argument(
        "--sif-path",
        default=str(Path(__file__).resolve().with_name("llm.sif")),
        help="Singularity image path for the singularity backend. If relative path, it is interpreted as relative to this calling file (default: %(default)s)",
    )
    parser.add_argument(
        "--container-username",
        default="devuser",
        help="Username inside the container (default: %(default)s). "
        "Needs to match Dockerfile expectations.",
    )
    parser.add_argument(
        "--container-home",
        default="/home/devuser",
        help="Home directory inside the container (default: %(default)s). "
        "Needs to match Dockerfile expectations.",
    )
    parser.add_argument(
        "--container-home-host-dir",
        default=str(Path.home() / ".local/share/llm-devcontainer/home"),
        help="Host directory mounted as the container home (default: %(default)s).",
    )
    parser.add_argument(
        "--container-local-host-dir",
        default=str(Path.home() / ".local/share/llm-devcontainer/home/.local"),
        help="Host directory used for the container's ~/.local data (default: %(default)s)",
    )
    parser.add_argument(
        "--workspace-mount",
        help=(
            "Workspace path inside the container "
            "(default: host current working directory)"
        ),
    )
    parser.add_argument(
        "--aws-region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region passed into Claude-enabled containers (default: %(default)s)",
    )
    parser.add_argument(
        "--aws-profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS profile passed into Claude-enabled containers (default: %(default)s)",
    )

    parser.add_argument(
        "--path-prepend",
        help="Path, relative to current working directory, to prepend to the container's $PATH",
    )

    parser.add_argument(
        "--conda-env",
        help=(
            "Path to a conda environment on the host. Its bin/ directory is prepended "
            "to the container's $PATH. If the path is outside the current working "
            "directory, it is automatically bind-mounted into the container."
        ),
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Environment variable to pass into the container. "
            "Can be specified multiple times."
        ),
    )

    parser.add_argument(
        "--mount",
        action="append",
        default=[],
        help=(
            "Additional directory to bind-mount into the container. "
            "Format: HOST_PATH or HOST_PATH:CONTAINER_PATH "
            "(if CONTAINER_PATH is omitted, the host path is used). "
            "Can be specified multiple times."
        ),
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help=(
            "Mount only the auth files needed by the selected tool instead of "
            "the full tool config directories."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the container command without executing it",
    )

    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("shell", help="Launch an interactive shell").set_defaults(
        tool_args=[]
    )

    for command, help_text in (
        ("codex", "Run codex in the container"),
        ("claude", "Run claude in the container (requires --aws-profile)"),
    ):
        subparsers.add_parser(command, help=help_text).set_defaults(tool_args=[])

    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)

    if args.cmd == "shell" and remainder:
        parser.error(f"unrecognized arguments: {' '.join(remainder)}")

    args.tool_args = remainder

    return args


def warn_if_backend_unavailable(command):
    if shutil.which(command) is None:
        print(
            f"Error: missing command '{command}' in PATH.",
            file=sys.stderr,
        )
        sys.exit(1)


def parse_mount(spec: str) -> tuple[str, str]:
    """Parse a mount spec 'host_path' or 'host_path:container_path'."""
    if ":" in spec:
        host, container = spec.split(":", 1)
    else:
        host = container = spec
    host = str(Path(host).resolve())
    return host, container


def build_mount_args(
    backend_mount_flag: str,
    mounts: list[tuple[Path, str]],
) -> list[str]:
    args: list[str] = []
    for host_path, container_path in mounts:
        args.extend([backend_mount_flag, f"{host_path}:{container_path}"])
    return args


def build_env_args(env_vars: list[str]) -> list[str]:
    args: list[str] = []
    for env_var in env_vars:
        args.extend(["--env", env_var])
    return args


def host_and_container_path(path: str, container_home: str) -> tuple[Path, str]:
    if not path.startswith("~/"):
        raise ValueError(f"Expected home-relative path, got: {path}")
    suffix = path[2:]
    return Path(path).expanduser(), f"{container_home}/{suffix}"


def build_container_command(
    backend,
    arch,
    runtime_target,
    tool,
    extra_run_args,
    cmd_args,
    container_username,
    container_home,
    container_home_host_dir,
    workspace_mount,
    path_prepend,
    extra_mounts=(),
    env_path=None,
    user_env_vars=(),
) -> list[str]:

    pwd = os.getcwd()
    container_workspace = workspace_mount or pwd
    uid = os.getuid()
    gid = os.getgid()
    PATH = (
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:"
        f"{container_home}/.local/bin"
    )
    if path_prepend is not None:
        PATH = f"{container_workspace}/{path_prepend}:{PATH}"

    if env_path is not None:
        env_resolved = str(Path(env_path).resolve())
        if env_resolved.startswith(pwd + "/") or env_resolved == pwd:
            # Inside the working directory, so it will already be mounted. Use
            # container-relative path (in case the workspace dir was overridden
            # in the command line args)
            rel = os.path.relpath(env_resolved, pwd)
            env_bin = f"{container_workspace}/{rel}/bin"
        else:
            # Outside the working directory — needs its own mount
            extra_mounts = list(extra_mounts) + [(env_resolved, env_resolved)]
            env_bin = f"{env_resolved}/bin"
        PATH = f"{env_bin}:{PATH}"

    # Formatting note: we want arg name and values on the same line, so disable
    # formatting temporarily fmt: off
    env_args = [
        "--env",
        f"USER={container_username}",
        "--env",
        f"LOGNAME={container_username}",
        "--env",
        f"USERNAME={container_username}",
        "--env",
        f"TOOL={tool}",
        "--env",
        f"HOST_MOUNT_DIR={pwd}",
        "--env",
        f"PATH={PATH}",
        *build_env_args(list(user_env_vars)),
    ]
    # fmt: on

    mount_flag = "--volume" if backend == "podman" else "--bind"
    extra_mount_args = []
    for host_path, container_path in extra_mounts:
        extra_mount_args += [mount_flag, f"{host_path}:{container_path}"]

    if backend == "podman":
        # fmt: off
        run_args = [
            "podman", "run", "--rm", "-it", "--platform",
            arch,
            "--user", f"{uid}:{gid}",
            f"--userns=keep-id:uid={uid},gid={gid}",
            "--env", f"HOME={container_home}",
            *env_args,
            *extra_run_args,
            "--volume", f"{container_home_host_dir}:{container_home}",  # fmt: skip
            "--volume", f"{pwd}:{container_workspace}",
            *extra_mount_args,
            "--workdir", container_workspace,
            runtime_target,
            *cmd_args,
        ]
        # fmt: on

    else:
        # fmt: off
        run_args = [
            "singularity", "exec",
            *env_args,
            *extra_run_args,
            "--no-home",
            "--home", f"{container_home_host_dir}:{container_home}",
            "--bind", f"{pwd}:{container_workspace}",
            *extra_mount_args,
            "--pwd", container_workspace,
            runtime_target,
            *cmd_args,
        ]
        # fmt: on

    return run_args


def run_container(*args, dry_run: bool = False, **kwargs) -> None:
    run_args = build_container_command(*args, **kwargs)
    if dry_run:
        print(shlex.join(run_args))
        return
    subprocess.run(run_args, check=True)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    setup_host_paths(args.container_home_host_dir, args.container_local_host_dir)
    backend = args.backend
    if not args.dry_run:
        warn_if_backend_unavailable(backend)
    cmd = args.cmd
    tool_args = getattr(args, "tool_args", [])
    backend_lookup = {
        "podman": ("--volume", args.image_name),
        "singularity": ("--bind", args.sif_path),
    }
    backend_mount_flag, runtime_target = backend_lookup[backend]
    extra_mounts = [parse_mount(m) for m in args.mount]
    mount_mode = "auth" if args.isolated else "full"
    codex_mounts = build_mount_args(
        backend_mount_flag,
        [
            host_and_container_path(path, args.container_home)
            for path in CREDENTIAL_PATHS["codex"][mount_mode]
        ],
    )
    claude_mounts = build_mount_args(
        backend_mount_flag,
        [
            host_and_container_path(path, args.container_home)
            for path in CREDENTIAL_PATHS["claude"][mount_mode]
        ],
    )

    if cmd == "shell":
        run_container(
            backend,
            args.arch,
            runtime_target,
            "shell",
            [
                "--env",
                "CLAUDE_CODE_USE_BEDROCK=1",
                "--env",
                f"AWS_REGION={args.aws_region}",
                "--env",
                f"AWS_PROFILE={args.aws_profile or ''}",
                "--env",
                "DISABLE_AUTOUPDATER=1",
                "--env",
                "DISABLE_INSTALLATION_CHECKS=1",
                *codex_mounts,
                *claude_mounts,
            ],
            ["/bin/bash"],
            args.container_username,
            args.container_home,
            args.container_home_host_dir,
            args.workspace_mount,
            args.path_prepend,
            extra_mounts,
            env_path=args.conda_env,
            user_env_vars=args.env,
            dry_run=args.dry_run,
        )
        return 0

    if cmd == "codex":
        run_container(
            backend,
            args.arch,
            runtime_target,
            "codex",
            codex_mounts,
            ["codex", "--sandbox", "danger-full-access", *tool_args],
            args.container_username,
            args.container_home,
            args.container_home_host_dir,
            args.workspace_mount,
            args.path_prepend,
            extra_mounts,
            env_path=args.conda_env,
            user_env_vars=args.env,
            dry_run=args.dry_run,
        )
        return 0

    if cmd == "claude":
        if not args.aws_profile:
            print("--aws-profile is required for Claude.", file=sys.stderr)
            raise SystemExit(1)

        run_container(
            backend,
            args.arch,
            runtime_target,
            "claude",
            [
                "--env",
                "CLAUDE_CODE_USE_BEDROCK=1",
                "--env",
                f"AWS_REGION={args.aws_region}",
                "--env",
                f"AWS_PROFILE={args.aws_profile}",
                "--env",
                "DISABLE_AUTOUPDATER=1",
                "--env",
                "DISABLE_INSTALLATION_CHECKS=1",
                *claude_mounts,
            ],
            ["claude", *tool_args],
            args.container_username,
            args.container_home,
            args.container_home_host_dir,
            args.workspace_mount,
            args.path_prepend,
            extra_mounts,
            env_path=args.conda_env,
            user_env_vars=args.env,
            dry_run=args.dry_run,
        )
        return 0

    raise AssertionError(f"Unhandled command: {cmd}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
