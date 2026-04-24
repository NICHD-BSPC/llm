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
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath


# Hard-coded credential and config paths.
CREDENTIAL_PATHS = {
    "codex": ("~/.codex",),  # ~/.codex/auth.json has credentials
    "claude": (
        "~/.claude",
        "~/.claude.json",
    ),
    "aws": ("~/.aws",),  # ~/.aws/sso and ~/.aws/config have credentials
}

# Unique config for each subcommand
SUBCOMMAND_CONFIG = {
    "shell": {
        "command": ["/bin/bash"],
        "credentials": ["codex", "claude"],
        "extra_env": {},
    },
    "codex": {
        "command": ["codex", "--sandbox", "danger-full-access"],
        "credentials": ["codex"],
        "extra_env": {},
    },
    "claude": {
        "command": ["claude"],
        "credentials": ["claude"],
        "extra_env": {},
    },
}

# If certs provided, mount them here inside the container.
CONTAINER_CERTS_PATH = "/tmp/llm-devcontainer-cert.pem"

# The various env vars tools might look at for additional certs. We'll add them
# all to the container to cover all the bases.
CERT_FILE_ENV_VARS = (
    "SSL_CERT_FILE",
    "GIT_SSL_CAINFO",
    "AWS_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "CURL_CA_BUNDLE",
)

DEFAULT_PODMAN_IMAGE = "ghcr.io/nichd-bspc/llm"
DEFAULT_SINGULARITY_IMAGE = "oras://ghcr.io/nichd-bspc/llm-sif"
DEFAULT_CERTS_ENV_VAR = "LLM_DEVCONTAINER_CERTS"
LOGGER = logging.getLogger("launch")
SCRIPT_DIR = Path(__file__).resolve().parent


def configure_logging(verbose=False):
    """Configure CLI logging."""
    LOGGER.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO if verbose else logging.WARNING)
    LOGGER.propagate = False


def fatal(message):
    """Log an error message and exit."""
    LOGGER.error(message)
    raise SystemExit(1)


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
        """Given a dict of env vars, build the arguments for the container
        runtime to add the env vars to the container."""
        env_args = []
        for key, value in env_vars.items():
            env_args.extend(["--env", f"{key}={value}"])
        return env_args

    def build_mount_args(self, mounts):
        """Given a dict of mounts, build the arguments for the container to
        mount them all. """
        mount_args = []
        for host_path, container_path in mounts:
            mount_args.extend([self.mount_flag, f"{host_path}:{container_path}"])
        return mount_args

    def check_availability(self):
        "Ensure the container runtime is available."
        if shutil.which(self.command) is None:
            fatal(f"missing command '{self.command}' in PATH.")

    def validate_image(self):
        """Validate that the container image exists. Override in subclasses."""
        raise NotImplementedError

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
            fatal(
                f"podman image '{self.args.image_name}' not found. "
                "Build it first or specify a different image with --image-name."
            )

    def build_command(self, env_vars, mounts, command_args):
        args = self.args
        uid = os.getuid()

        env_args = self.build_env_args(env_vars)
        mount_args = self.build_mount_args(mounts)

        # On CI platforms like GitHub Actions, podman runs rootless on a Linux
        # host, so we don't have Podman Desktop to intercept and gracefully
        # handle permssion issues.
        if os.getenv("CI") == "true":
            userns_arg = "--userns=keep-id:uid=1000,gid=1000"
            user_arg = "--user=1000:1000"

        else:
            userns_arg = "--userns=keep-id"
            user_arg = f"--user={uid}"

        # fmt: off
        return [
            self.command, "run", "--rm", "-it",
            "--platform", args.arch,
            userns_arg,
            user_arg,
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
        if self.args.sif_path.startswith('oras://'):
            return
        sif_path = Path(self.args.sif_path)
        if not sif_path.exists():
            fatal(
                f"singularity image '{self.args.sif_path}' not found. "
                "Build it first or specify a different path with --sif-path."
            )
        if not sif_path.is_file():
            fatal(f"singularity image '{self.args.sif_path}' is not a file.")

    def build_command(self, env_vars, mounts, command_args):
        args = self.args

        env_vars = dict(env_vars)
        home_dir = env_vars.pop("HOME", None)
        env_args = self.build_env_args(env_vars)
        mount_args = self.build_mount_args(mounts)
        home_arg = []

        if home_dir:
            host_home = str(Path(args.container_local_host_dir).expanduser().parent)
            home_arg = ["--home", f"{host_home}:{home_dir}"]

        # fmt: off
        return [
            self.command, "exec",
            *home_arg,
            *env_args,
            *mount_args,
            "--cleanenv",
            "--pwd", args.workspace_mount or os.getcwd(),
            args.sif_path,
            *command_args,
        ]
        # fmt: on


class Launcher:
    """Main orchestrator for container launches."""

    def __init__(self, args):
        self.args = args
        configure_logging(args.verbose)
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

        if args.sif_path and not args.sif_path.startswith("oras://"):
            sif_path = Path(args.sif_path).expanduser()
            if not sif_path.is_absolute():
                sif_path = SCRIPT_DIR / sif_path
            args.sif_path = str(sif_path.resolve())

        # a relative --workspace-mount doesn't make sense (what would it be relative to?)
        if args.workspace_mount and not Path(args.workspace_mount).is_absolute():
            fatal(
                f"--workspace-mount must be an absolute path, got: {args.workspace_mount}"
            )

        # If mounting a conda env, needs to exist and have a bin dir
        if args.conda_env:
            conda_path = Path(args.conda_env).expanduser().resolve()
            if (
                not conda_path.exists()
                or not conda_path.is_dir()
                or not (conda_path / "bin").is_dir()
            ):
                fatal(
                    "--conda-env path needs to be a directory containing a "
                    f"bin/ directory. Got: {args.conda_env}"
                )
            args.conda_env = str(conda_path)

        if args.certs:
            certs_path = Path(args.certs).expanduser().resolve()
            if not certs_path.exists():
                fatal(f"--certs file not found: {args.certs}")
            if not certs_path.is_file():
                fatal(f"--certs must point to a file, got: {args.certs}")
            args.certs = str(certs_path)

        if args.path_prepend and PurePosixPath(args.path_prepend).is_absolute():
            if not self._container_path_is_mounted(args.path_prepend):
                fatal(
                    f"--path-prepend path '{args.path_prepend}' is absolute but is "
                    "not available in the container. Add a matching --mount or "
                    "use a workspace-relative path."
                )

    def setup_host_paths(self):
        """Create necessary host directories before launch."""
        local_dir = Path(self.args.container_local_host_dir).expanduser()
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "bin").mkdir(parents=True, exist_ok=True)

    def setup_claude_config(self):
        """Create default ~/.claude.json and ~/.claude/ if needed to prevent Claude Code from hanging."""
        if self.args.cmd != "claude":
            return

        claude_dir = Path.home() / ".claude"
        if not claude_dir.exists():
            claude_dir.mkdir(parents=True, exist_ok=True)
            if self.args.verbose:
                LOGGER.info("Created directory: %s", claude_dir)

        claude_config = Path.home() / ".claude.json"
        if not claude_config.exists():
            claude_config.write_text("{}\n")
            if self.args.verbose:
                LOGGER.info("Created default config: %s", claude_config)

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

    def _static_mounts(self):
        """Return mounts known before runtime env calculation."""
        args = self.args
        host_cwd = os.getcwd()
        container_workspace = args.workspace_mount or host_cwd

        mounts = [
            (
                str(Path(args.container_local_host_dir).expanduser()),
                "/home/devuser/.local",
            ),
            (host_cwd, container_workspace),
        ]

        for mount_spec in args.mount:
            mounts.append(self._parse_mount_spec(mount_spec))

        if args.conda_env:
            conda_path = args.conda_env
            if not self._is_path_inside_workspace(conda_path, host_cwd):
                mounts.append((conda_path, conda_path))

        if args.certs:
            mounts.append((args.certs, CONTAINER_CERTS_PATH))

        return self._normalize_mounts(mounts)

    def _container_path_is_mounted(self, container_path):
        """Return True when a container path is reachable via the mount set."""
        target = PurePosixPath(container_path)
        for _, mount_target in self._static_mounts():
            mount_path = PurePosixPath(mount_target)
            if target == mount_path:
                return True
            try:
                target.relative_to(mount_path)
                return True
            except ValueError:
                continue
        return False

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
            path_prepend = PurePosixPath(args.path_prepend)
            if path_prepend.is_absolute():
                prepend_path = str(path_prepend)
            else:
                prepend_path = str(PurePosixPath(container_workspace) / path_prepend)
            path = f"{prepend_path}:{path}"

        # Add conda env if specified (takes highest precedence)
        if args.conda_env:
            conda_path = Path(args.conda_env)
            conda_bin = self._resolve_conda_path_in_container(
                conda_path, host_cwd, container_workspace
            )
            path = f"{conda_bin}:{path}"

        return path

    def _parse_user_env(self):
        """Parse repeatable --env values into a dict."""
        env = {}
        for env_var in self.args.env:
            if "=" not in env_var:
                fatal(
                    f"invalid environment variable format '{env_var}'. "
                    "Expected KEY=VALUE."
                )
            key, value = env_var.split("=", 1)
            env[key] = value
        return env

    def _host_env_with_prefix(self, prefix):
        """Return host env vars matching a prefix."""
        return {
            key: value for key, value in os.environ.items() if key.startswith(prefix)
        }

    def _host_env_with_prefixes(self, *prefixes):
        """Return host env vars matching any of the provided prefixes."""
        env = {}
        for prefix in prefixes:
            env.update(self._host_env_with_prefix(prefix))
        return env

    def _bedrock_enabled(self, env):
        """Return True when the effective env enables Claude Bedrock."""
        return env.get("CLAUDE_CODE_USE_BEDROCK") == "1"

    def build_env_vars(self, subcommand_config):
        """Build all environment variables for the container."""
        args = self.args
        user_env = self._parse_user_env()

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

        if self.args.cmd in {"claude", "shell"}:
            env.update(self._host_env_with_prefixes("CLAUDE_CODE", "ANTHROPIC_"))

        effective_env = dict(env)

        # args on the command line win
        effective_env.update(user_env)

        if self._bedrock_enabled(effective_env):
            env.update(self._host_env_with_prefix("AWS_"))

        if args.certs:
            for var_name in CERT_FILE_ENV_VARS:
                env[var_name] = CONTAINER_CERTS_PATH

        # Add user-provided env vars (these come last)
        env.update(user_env)

        return env

    def build_mounts(self, subcommand_config, env_vars=None):
        """Build all mounts for the container."""
        mounts = list(self._static_mounts())

        for tool in subcommand_config["credentials"]:
            mounts.extend(self._credential_mounts(tool))

        if self._bedrock_enabled(env_vars or {}):
            mounts.extend(self._credential_mounts("aws"))

        normalized_mounts = self._normalize_mounts(mounts)
        self._warn_nested_mounts(normalized_mounts)
        return normalized_mounts

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
                fatal(
                    "conflicting mounts for container path "
                    f"'{container_path}': '{existing_host_path}' and '{host_path}'."
                )

            seen_mounts.add(mount_key)
            container_targets[container_path] = host_path
            normalized.append((host_path, container_path))

        return normalized

    def _warn_nested_mounts(self, mounts):
        """Warn when one mount path nests inside another mount path."""
        for index, (host_path, container_path) in enumerate(mounts):
            for other_host_path, other_container_path in mounts[index + 1 :]:
                nested_host = self._nested_path_pair(Path(host_path), Path(other_host_path))
                nested_container = self._nested_path_pair(
                    PurePosixPath(container_path),
                    PurePosixPath(other_container_path),
                )

                if not nested_host and not nested_container:
                    continue

                details = []
                if nested_host:
                    details.append(
                        f"host paths '{nested_host[0]}' and '{nested_host[1]}'"
                    )
                if nested_container:
                    details.append(
                        f"container paths '{nested_container[0]}' and '{nested_container[1]}'"
                    )

                LOGGER.warning(
                    "nested mounts detected between '%s:%s' and '%s:%s' (%s). "
                    "Nested mounts can mask each other and cause confusing "
                    "container behavior.",
                    host_path,
                    container_path,
                    other_host_path,
                    other_container_path,
                    "; ".join(details),
                )

    def _nested_path_pair(self, first, second):
        """Return (parent, child) when one path is nested inside the other."""
        if first == second:
            return None

        try:
            second.relative_to(first)
            return str(first), str(second)
        except ValueError:
            pass

        try:
            first.relative_to(second)
            return str(second), str(first)
        except ValueError:
            return None

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
                    LOGGER.info("Mounting credential: %s", path_str)
            elif self.args.verbose:
                LOGGER.info("Skipping missing credential: %s", path_str)

        return mounts

    def _parse_mount_spec(self, spec):
        """Parse mount spec: 'HOST' or 'HOST:CONTAINER'."""
        if not spec or spec == ":":
            fatal(f"invalid mount specification '{spec}'.")

        if ":" not in spec:
            # Single path: resolve it and use for both host and container
            resolved = str(Path(spec).resolve())
            host = container = resolved
        else:
            host, container = spec.split(":", 1)
            if not host or not container:
                fatal(
                    f"invalid mount specification '{spec}'. "
                    "Both host and container paths must be non-empty."
                )
            # Resolve only host path to absolute (can't resolve container path
            # unless inside container)
            host = str(Path(host).resolve())

        return host, container

    def run(self):
        """Main entry point for launching a container."""
        args = self.args

        if not args.dry_run:
            self.setup_host_paths()
            self.setup_claude_config()
            self.backend.check_availability()
            self.backend.validate_image()

        # Config for this subcommand (claude, codex, shell)
        subcommand_config = SUBCOMMAND_CONFIG[args.cmd]
        env_vars = self.build_env_vars(subcommand_config)

        if self._bedrock_enabled(env_vars) and not env_vars.get("AWS_PROFILE"):
            fatal(
                f"AWS_PROFILE must be set for {args.cmd} when "
                "CLAUDE_CODE_USE_BEDROCK=1. Inherit it from the host or pass "
                "--env AWS_PROFILE=..."
            )

        mounts = self.build_mounts(subcommand_config, env_vars)

        # Build command args (subcommand command + any tool args from command line)
        # Special handling for shell: if args provided, use -c to execute them
        if args.cmd == "shell" and args.tool_args:
            command_args = ["/bin/bash", "-c", shlex.join(args.tool_args)]
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
        default=DEFAULT_PODMAN_IMAGE,
        help="Container image name for podman (default: %(default)s, needs to match name given to build.py)",
    )
    parser.add_argument(
        "--arch",
        default="linux/amd64",
        help="Container platform for podman (default: %(default)s, needs to match arch given to build.py)",
    )
    parser.add_argument(
        "--sif-path",
        default=DEFAULT_SINGULARITY_IMAGE,
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

    # Path configuration
    parser.add_argument(
        "--path-prepend",
        help="Path relative to workspace to prepend to container PATH",
    )
    parser.add_argument(
        "--conda-env",
        help="Path to conda environment. Its bin/ is prepended to PATH",
    )
    parser.add_argument(
        "--certs",
        default=os.environ.get(DEFAULT_CERTS_ENV_VAR),
        help=(
            "Path to a PEM certificate bundle to mount into the container and "
            "export via SSL_CERT_FILE, REQUESTS_CA_BUNDLE, "
            "NODE_EXTRA_CA_CERTS, and CURL_CA_BUNDLE. "
            f"Defaults to ${DEFAULT_CERTS_ENV_VAR} when set."
        ),
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
        help="Run claude in the container",
    )

    return parser


def parse_args(argv):
    """Parse command-line arguments."""
    parser = build_parser()
    args, remainder = parser.parse_known_args(argv)

    # All subcommands forward extra arguments
    args.tool_args = remainder

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
