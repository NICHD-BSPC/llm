#!/usr/bin/env python3
"""
Launches an LLM dev container via podman or singularity.

Overview of the flow:
    - user command (e.g., claude)
    - parse args to select subcommand config
      - e.g., config for claude has credential files, env vars, aws requirements
    - build container environment
      - e.g., PATH, env vars, mounts
      - argparse object is used to pass along info
    - choose backend (podman / singularity)
      - Backend-specific classes handle details
    - launch container in backend
"""


import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


# Hard-coded credential and config paths.
CREDENTIAL_PATHS = {
    "codex": ("~/.codex",),  # ~/.codex/auth.json has credentials
    "claude": (
        "~/.claude",
        "~/.claude.json",
        "~/.aws",
    ),  # ~/.aws/sso and ~/.aws/config have credentials
}

# Unique config for each subcommand
SUBCOMMAND_CONFIG = {
    "shell": {
        "command": ["/bin/bash"],
        "credentials": ["codex", "claude"],
        "extra_env": {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_INSTALLATION_CHECKS": "1",
        },
        "include_aws_env": True,
    },
    "codex": {
        "command": ["codex", "--sandbox", "danger-full-access"],
        "credentials": ["codex"],
        "extra_env": {},
        "include_aws_env": False,
    },
    "claude": {
        "command": ["claude"],
        "credentials": ["claude"],
        "extra_env": {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_NO_FLICKER": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_INSTALLATION_CHECKS": "1",
        },
        "include_aws_env": True,
        "require_aws_profile": True,
    },
}


class Backend:
    """Base class for container backends.

    Subclasses should set:
    - command: str (e.g., "podman", "singularity")
    - mount_flag: str (e.g., "--volume", "--bind")
    """

    command = ""
    mount_flag = ""

    def __init__(self, args):
        self.args = args

    def build_env_args(self, env_vars):
        env_args = []
        for key, value in env_vars.items():
            env_args.extend(["--env", f"{key}={value}"])
        return env_args

    def build_mount_args(self, mounts):
        mount_args = []
        for host_path, container_path in mounts:
            mount_args.extend([self.mount_flag, f"{host_path}:{container_path}"])
        return mount_args

    def check_availability(self):
        if shutil.which(self.command) is None:
            print(f"Error: missing command '{self.command}' in PATH.", file=sys.stderr)
            sys.exit(1)

    def validate_image(self):
        """Validate that the container image exists. Override in subclasses."""
        pass

    def build_command(self, env_vars, mounts, command_args):
        raise NotImplementedError


class PodmanBackend(Backend):
    """Podman backend implementation."""

    command = "podman"
    mount_flag = "--volume"

    def validate_image(self):
        """Check that the podman image exists."""
        result = subprocess.run(
            [self.command, "image", "exists", self.args.image_name],
            capture_output=True,
        )
        if result.returncode != 0:
            print(
                f"Error: podman image '{self.args.image_name}' not found.",
                file=sys.stderr,
            )
            print(
                "Build it first or specify a different image with --image-name.",
                file=sys.stderr,
            )
            sys.exit(1)

    def build_command(self, env_vars, mounts, command_args):
        args = self.args
        uid = os.getuid()

        env_args = self.build_env_args(env_vars)
        mount_args = self.build_mount_args(mounts)

        # fmt: off
        return [
            self.command, "run", "--rm", "-it",
            "--platform", args.arch,
            #
            # "--userns=keep-id",
            # "--user", str(uid),
            *env_args,
            *mount_args,
            "--workdir", args.workspace_mount or os.getcwd(),
            args.image_name,
            *command_args,
        ]
        # fmt: on


class SingularityBackend(Backend):
    """Singularity backend implementation."""

    command = "singularity"
    mount_flag = "--bind"

    def validate_image(self):
        """Check that the singularity .sif file exists."""
        sif_path = Path(self.args.sif_path)
        if not sif_path.exists():
            print(
                f"Error: singularity image '{self.args.sif_path}' not found.",
                file=sys.stderr,
            )
            print(
                "Build it first or specify a different path with --sif-path.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not sif_path.is_file():
            print(
                f"Error: singularity image '{self.args.sif_path}' is not a file.",
                file=sys.stderr,
            )
            sys.exit(1)

    def build_command(self, env_vars, mounts, command_args):
        args = self.args

        env_args = self.build_env_args(env_vars)
        mount_args = self.build_mount_args(mounts)

        # fmt: off
        return [
            self.command, "exec",
            "--no-home",  # Prevent auto-mounting real $HOME
            *env_args,
            *mount_args,
            "--pwd", args.workspace_mount or os.getcwd(),
            args.sif_path,
            *command_args,
        ]
        # fmt: on


class Launcher:
    """Main orchestrator for container launches."""

    def __init__(self, args):
        self.args = args
        self._validate_args()

        # Decide which backend subclass to use
        if args.backend == "podman":
            self.backend = PodmanBackend(args)
        elif args.backend == "singularity":
            self.backend = SingularityBackend(args)
        else:
            raise ValueError(f"Unknown backend: {args.backend}")

    def _validate_args(self):
        """Validate command-line arguments."""

        args = self.args  # for convenience in this method...

        # a relative --workspace-mount doesn't make sense (what would it be relative to?)
        if args.workspace_mount and not Path(args.workspace_mount).is_absolute():
            print(
                f"Error: --workspace-mount must be an absolute path, got: {args.workspace_mount}",
                file=sys.stderr,
            )
            sys.exit(1)

        # If mounting a conda env, needs to exist and have a bin dir
        if args.conda_env:
            conda_path = Path(args.conda_env).expanduser().resolve()
            if (
                not conda_path.exists()
                or not conda_path.is_dir()
                or not (conda_bin / "bin").is_dir()
            ):
                print(
                    f"Error: --conda-env path needs to be a directory containing a bin/ directory. Got: {args.conda_env}",
                    file=sys.stderr,
                )
                sys.exit(1)
            args.conda_env = str(conda_path)

    def setup_host_paths(self):
        """Create necessary host directories before launch."""
        bin_dir = Path(self.args.container_local_host_dir).expanduser() / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

    def _is_path_inside_workspace(self, path, host_cwd):
        """Check if a path is inside the workspace directory."""
        path_str = str(path)
        return path_str.startswith(host_cwd + "/") or path_str == host_cwd

    def _resolve_conda_path_in_container(
        self, conda_path, host_cwd, container_workspace
    ):
        """
        Resolve conda environment path for use in container PATH.

        Returns the path to conda's bin directory as it should appear
        inside the container
        """
        # Determine if conda env is inside or outside the workspace
        if self._is_path_inside_workspace(conda_path, host_cwd):
            # Inside workspace - use relative path
            rel = os.path.relpath(conda_path, host_cwd)
            return f"{container_workspace}/{rel}/bin"
        else:
            # Outside workspace - use absolute path
            return f"{conda_path}/bin"

    def build_path(self):
        """
        Construct the container PATH environment variable based on command-line
        args like --env and --path-prepend.

        Precedence (highest to lowest):
        1. conda env bin
        2. path-prepend
        3. base PATH
        """
        args = self.args
        host_cwd = os.getcwd()
        container_workspace = args.workspace_mount or host_cwd

        path = (
            # This initial path comes from running a bare ubuntu container and
            # inspecting its default PATH
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:"
            # Claude Code will complain if this is not in the path
            "/home/devuser/.local/bin"
        )

        # Add path-prepend if specified
        if args.path_prepend:
            path = f"{container_workspace}/{args.path_prepend}:{path}"

        # Add conda env if specified (takes highest precedence)
        if args.conda_env:
            conda_path = Path(args.conda_env)
            conda_bin = self._resolve_conda_path_in_container(
                conda_path, host_cwd, container_workspace
            )
            path = f"{conda_bin}:{path}"

        return path

    def build_env_vars(self, subcommand_config):
        """Build all environment variables for the container."""
        args = self.args

        # Base environment
        env = {
            "HOME": "/home/devuser",
            "USER": "devuser",
            "LOGNAME": "devuser",
            "USERNAME": "devuser",
            "TOOL": args.cmd,
            "HOST_MOUNT_DIR": os.getcwd(),
            "PATH": self.build_path(),
        }

        # Add subcommand-specific env
        env.update(subcommand_config["extra_env"])

        # Add AWS env if needed
        if subcommand_config.get("include_aws_env"):
            env["AWS_REGION"] = args.aws_region
            env["AWS_PROFILE"] = args.aws_profile or ""

        # Add user-provided env vars (these come last)
        for env_var in args.env:
            if "=" not in env_var:
                print(
                    f"Error: invalid environment variable format '{env_var}'. "
                    f"Expected KEY=VALUE.",
                    file=sys.stderr,
                )
                sys.exit(1)
            key, value = env_var.split("=", 1)
            env[key] = value

        return env

    def build_mounts(self, subcommand_config):
        """Build all mounts for the container."""
        args = self.args
        host_cwd = os.getcwd()
        container_workspace = args.workspace_mount or host_cwd

        # Configure mounts as (host_path, container_path) tuples
        mounts = [
            # Container's .local directory
            (
                str(Path(args.container_local_host_dir).expanduser()),
                "/home/devuser/.local",
            ),
            # Workspace
            (host_cwd, container_workspace),
        ]

        # Add user-provided mounts
        for mount_spec in args.mount:
            host_path, container_path = self._parse_mount_spec(mount_spec)
            mounts.append((host_path, container_path))

        # Add conda env mount if needed (and outside workspace)
        if args.conda_env:
            conda_path = args.conda_env
            if not self._is_path_inside_workspace(conda_path, host_cwd):
                mounts.append((conda_path, conda_path))

        # Add credential mounts
        for tool in subcommand_config["credentials"]:
            mounts.extend(self._credential_mounts(tool))

        return self._normalize_mounts(mounts)

    def _normalize_mounts(self, mounts):
        """Deduplicate identical mounts and reject conflicting container paths."""
        seen_mounts = set()
        container_targets = {}
        normalized = []

        for host_path, container_path in mounts:
            mount_key = (host_path, container_path)
            if mount_key in seen_mounts:
                continue

            existing_host_path = container_targets.get(container_path)
            if existing_host_path is not None and existing_host_path != host_path:
                print(
                    "Error: conflicting mounts for container path "
                    f"'{container_path}': '{existing_host_path}' and '{host_path}'.",
                    file=sys.stderr,
                )
                sys.exit(1)

            seen_mounts.add(mount_key)
            container_targets[container_path] = host_path
            normalized.append((host_path, container_path))

        return normalized

    def _credential_mounts(self, tool):
        """
        Returns list of (host_path, container_path) tuples for the given tool.

        Only returns paths that actually exist on the host.
        """
        mounts = []
        paths = CREDENTIAL_PATHS[tool]

        for path_str in paths:
            if not path_str.startswith("~/"):
                raise ValueError(f"Expected home-relative path, got: {path_str}")

            # Expand ~ to actual home directory
            host_path = Path(path_str).expanduser()
            path_under_home = Path(path_str[2:])  # Remove "~/"

            # Map to container home
            container_path = f"/home/devuser/{path_under_home}"

            # Only mount if it exists
            if host_path.exists():
                mounts.append((str(host_path), container_path))
                if self.args.verbose:
                    print(f"Mounting credential: {path_str}", file=sys.stderr)
            elif self.args.verbose:
                print(f"Skipping missing credential: {path_str}", file=sys.stderr)

        return mounts

    def _parse_mount_spec(self, spec):
        """Parse mount spec: 'HOST' or 'HOST:CONTAINER'."""
        if not spec or spec == ":":
            print(f"Error: invalid mount specification '{spec}'.", file=sys.stderr)
            sys.exit(1)

        if ":" not in spec:
            # Single path: resolve it and use for both host and container
            resolved = str(Path(spec).resolve())
            host = container = resolved
        else:
            host, container = spec.split(":", 1)
            if not host or not container:
                print(
                    f"Error: invalid mount specification '{spec}'. "
                    f"Both host and container paths must be non-empty.",
                    file=sys.stderr,
                )
                sys.exit(1)
            # Resolve only host path to absolute (can't resolve container path
            # unless inside container)
            host = str(Path(host).resolve())

        return host, container

    def run(self):
        """Main entry point for launching a container."""
        args = self.args

        self.setup_host_paths()
        if not args.dry_run:
            self.backend.check_availability()
            self.backend.validate_image()

        # Config for this subcommand (claude, codex, shell)
        subcommand_config = SUBCOMMAND_CONFIG[args.cmd]

        if subcommand_config.get("require_aws_profile"):
            if not args.aws_profile:
                print(
                    f"Error: --aws-profile is required for {args.cmd}.",
                    file=sys.stderr,
                )
                sys.exit(1)

        env_vars = self.build_env_vars(subcommand_config)
        mounts = self.build_mounts(subcommand_config)

        # Build command args (subcommand command + any tool args from command line)
        # Special handling for shell: if args provided, use -c to execute them
        if args.cmd == "shell" and args.tool_args:
            command_args = ["/bin/bash", "-c", " ".join(args.tool_args)]
        else:
            command_args = subcommand_config["command"] + args.tool_args

        # Build and execute command
        cmd = self.backend.build_command(env_vars, mounts, command_args)

        if args.dry_run:
            print(shlex.join(cmd))
        else:
            subprocess.run(cmd, check=True)


def build_parser():
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Launch an LLM dev container via podman or singularity. "
            "Mounts the current working directory into the container."
        ),
    )

    # Backend options
    parser.add_argument(
        "--backend",
        choices=("podman", "singularity"),
        default="podman" if platform.system() == "Darwin" else "singularity",
        help="Container backend to use (default macOS is podman; otherwise singularity)",
    )
    parser.add_argument(
        "--image-name",
        default="localhost/llm-devcontainer:latest",
        help="Container image name for podman (default: %(default)s, needs to match name given to build.py)",
    )
    parser.add_argument(
        "--arch",
        default="linux/amd64",
        help="Container platform for podman (default: %(default)s, needs to match arch given to build.py)",
    )
    parser.add_argument(
        "--sif-path",
        default=str(Path(__file__).resolve().with_name("llm.sif")),
        help="Singularity image path. Relative paths resolved relative to this script (default: %(default)s)",
    )

    parser.add_argument(
        "--container-local-host-dir",
        default=str(Path.home() / ".local/share/llm-devcontainer/home/.local"),
        help="Host directory mounted as container's ~/.local (default: %(default)s)",
    )

    # Workspace
    parser.add_argument(
        "--workspace-mount",
        help="Override workspace path inside the container (default: same as host cwd)",
    )

    # AWS configuration
    parser.add_argument(
        "--aws-region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region for Claude (default: %(default)s)",
    )
    parser.add_argument(
        "--aws-profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS profile for Claude (default: %(default)s)",
    )

    # Path configuration
    parser.add_argument(
        "--path-prepend",
        help="Path relative to workspace to prepend to container PATH",
    )
    parser.add_argument(
        "--conda-env",
        help="Path to conda environment. Its bin/ is prepended to PATH",
    )

    # Mounts and environment
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Environment variable to pass into container (repeatable)",
    )
    parser.add_argument(
        "--mount",
        action="append",
        default=[],
        help="Additional mount: HOST_PATH or HOST_PATH:CONTAINER_PATH (repeatable)",
    )

    # Execution mode
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the container command without executing it",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose output including credential mount status",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    subparsers.add_parser(
        "shell",
        help="Launch an interactive bash shell",
    )

    subparsers.add_parser(
        "codex",
        help="Run codex in the container",
    )

    subparsers.add_parser(
        "claude",
        help="Run claude in the container (requires --aws-profile)",
    )

    return parser


def parse_args(argv):
    """Parse command-line arguments."""
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)

    # All subcommands forward extra arguments
    args.tool_args = remainder

    # Resolve --sif-path relative to this script if it's a relative path
    sif_path = Path(args.sif_path)
    if not sif_path.is_absolute():
        script_dir = Path(__file__).resolve().parent
        args.sif_path = str(script_dir / sif_path)

    return args


def main(argv):
    """Main entry point."""
    args = parse_args(argv)
    launcher = Launcher(args)
    launcher.run()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
