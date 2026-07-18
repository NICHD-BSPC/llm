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
import atexit
import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


AWS_EXPORT_PROFILE = "llm-export"
AWS_CREDENTIALS_JSON = Path.home() / ".aws" / "credentials.json"
AWS_STATIC_CREDENTIAL_ENV_VARS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_CREDENTIAL_EXPIRATION",
}

# Hard-coded credential and config paths.
CREDENTIAL_PATHS = {
    "codex": ("~/.codex",),  # ~/.codex/auth.json has credentials
    "claude": (
        "~/.claude",
        "~/.claude.json",
    ),
    "pi": ("~/.pi",),
    "aws": ("~/.aws",),
}

# Unique config for each subcommand
SUBCOMMAND_CONFIG = {
    "shell": {
        "command": ["/bin/bash"],
        "credentials": ["codex", "claude", "pi"],
    },
    "codex": {
        "command": ["codex", "--sandbox", "danger-full-access"],
        "credentials": ["codex"],
    },
    "claude": {
        "command": ["claude"],
        "credentials": ["claude"],
    },
    "pi": {
        "command": ["pi"],
        "credentials": ["pi"],
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

# Per-harness "latest" tags. Images are rebuilt daily, but these tags only move
# when the harness's own version changes, so launching a given harness does not
# pull a fresh image every day when that harness's version is unchanged. The
# "shell" subcommand has no single harness, so it falls back to the overall
# "latest" tag. Override with --tag to pin a specific tag (e.g. --tag latest).
DEFAULT_IMAGE_TAGS = {
    "shell": "latest",
    "codex": "codex-latest",
    "claude": "claude-latest",
    "pi": "pi-latest",
}
DEFAULT_CERTS_ENV_VAR = "LLM_DEVCONTAINER_CERTS"
DEFAULT_MOUNTS_ENV_VAR = "LLM_DEVCONTAINER_MOUNTS"
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


def split_image_tag(reference):
    """Split an image reference into (name, tag), where tag is None if absent.

    Only a ':' in the final path segment counts as a tag separator, so registry
    ports (localhost:5000/foo) and URI schemes (oras://...) are not mistaken
    for tags.
    """
    last_segment = reference.rpartition("/")[2]
    if ":" in last_segment:
        name, _, tag = reference.rpartition(":")
        return name, tag
    return reference, None


def resolve_image_reference(reference, explicit_tag, cmd, default_base):
    """Apply the effective tag to a registry image reference.

    Precedence:
      1. an explicit --tag always wins;
      2. otherwise, only our own default image base gets the per-harness
         default tag (e.g. codex-latest);
      3. any other (custom) reference is left untouched, so a tag baked into it
         is respected and an untagged custom image lets the runtime default to
         ``:latest`` as before.
    """
    name, _ = split_image_tag(reference)
    if explicit_tag:
        return f"{name}:{explicit_tag}"
    if reference == default_base:
        return f"{name}:{DEFAULT_IMAGE_TAGS[cmd]}"
    return reference


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
        """Given a list of (host, container, readonly) tuples, build the
        arguments for the container to mount them all."""
        mount_args = []
        for host_path, container_path, readonly in mounts:
            spec = f"{host_path}:{container_path}"
            if readonly:
                spec += ":ro"
            mount_args.extend([self.mount_flag, spec])
        return mount_args

    def check_availability(self):
        "Ensure the container runtime is available."
        if shutil.which(self.command) is None:
            fatal(f"missing command '{self.command}' in PATH.")

    def build_mask_args(self, mask_targets):
        """Shadow each masked container path with an empty, read-only directory.

        The empty directory is created under the user's home directory on the
        host, with the prefix `.llm-mask-`. It is mounted as read-only, so it
        will continue to be empty. If multiple mask targets were provided, the
        same empty directory is used for all of them.
        """
        if not mask_targets:
            return []

        empty_dir = tempfile.mkdtemp(prefix=".llm-mask-", dir=Path.home())
        atexit.register(shutil.rmtree, empty_dir, ignore_errors=True)

        mask_args = []
        for target in mask_targets:
            mask_args.extend([self.mount_flag, f"{empty_dir}:{target}:ro"])
        return mask_args

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
        """Check that the podman image exists, pulling the default on demand."""
        result = subprocess.run(
            [self.command, "image", "exists", self.args.image_name],
            capture_output=True,
        )
        if result.returncode == 0:
            return

        if not self.args.image_name.startswith(DEFAULT_PODMAN_IMAGE + ":"):
            fatal(
                f"podman image '{self.args.image_name}' not found. "
                "Build it first or specify a different image with --image-name."
            )

        LOGGER.info("pulling default podman image '%s'", self.args.image_name)
        try:
            subprocess.run(
                [self.command, "pull", self.args.image_name],
                check=True,
            )
        except subprocess.CalledProcessError:
            fatal(
                f"failed to pull default podman image '{self.args.image_name}'. "
                "Check your network or try 'podman pull' manually."
            )

    def build_command(self, env_vars, mounts, command_args):
        args = self.args

        env_args = self.build_env_args(env_vars)
        mount_args = self.build_mount_args(mounts)
        mask_args = self.build_mask_args(getattr(args, "mask_targets", []))

        # The image bakes its home directory and dotfiles as UID/GID 1000
        # (see USER_UID/USER_GID in the Dockerfile). Map the current host user
        # onto that same 1000:1000 inside the user namespace and run as it, so
        # the runtime user actually owns its home directory. Using the raw host
        # UID here instead would leave the process unable to write to a home
        # owned by 1000 whenever the host UID differs.This works both on
        # rootless Linux (CI) and with Podman Desktop on macOS.
        userns_arg = "--userns=keep-id:uid=1000,gid=1000"
        user_arg = "--user=1000:1000"

        # fmt: off
        return [
            self.command, "run", "--rm", "-it",
            "--platform", args.arch,
            userns_arg,
            user_arg,
            *env_args,
            *mount_args,
            *mask_args,
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
        if self.args.sif_path.startswith("oras://"):
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

        # Notes on Singularity arguments:
        #
        # We want a clean home directory inside the container that still accepts
        # mounts under $HOME.
        #
        # Passing HOME through the environment (--env HOME=/home/devuser) triggers a
        # Singularity warning
        #
        # --no-home avoids mounting the host's home, but preserves the image's baked-in home contents.
        #
        # --contain avoids mounting the host's home as well as the host's entire /tmp
        #
        # Here we use --home <src>:<dest> to mount an empty temp dir into which
        # other dirs (like `./claude`) can be mounted.
        #
        home = env_vars.pop("HOME")
        tmp = tempfile.mkdtemp()

        env_args = self.build_env_args(env_vars)

        mount_args = self.build_mount_args(mounts)
        mask_args = self.build_mask_args(getattr(args, "mask_targets", []))

        # fmt: off
        return [
            self.command, "exec",
            *env_args,
            *mount_args,
            *mask_args,
            "--home", f"{tmp}:{home}", # creates an empty dir; we can mount into it.
            "--contain",  # avoid mounting /tmp
            "--cleanenv", # don't inherit ALL of the env
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

        # If mounting a conda env, needs to exist and have a bin dir.
        # A value without "/" is treated as a named env and resolved via conda.
        if args.conda_env is not None:
            if "/" not in args.conda_env:
                args.conda_env = self._resolve_named_conda_env(args.conda_env)
            conda_path = Path(str(args.conda_env)).expanduser().resolve()
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
            self._check_conda_env_arch(conda_path)

        if args.certs:
            certs_path = Path(args.certs).expanduser().resolve()
            if not certs_path.exists():
                fatal(f"--certs file not found: {args.certs}")
            if not certs_path.is_file():
                fatal(f"--certs must point to a file, got: {args.certs}")
            args.certs = str(certs_path)

        env_mount_specs = self._parse_mounts_env_var(DEFAULT_MOUNTS_ENV_VAR)
        cli_mount_specs = list(args.mount)
        args.extra_mounts = [
            self._parse_mount_spec(mount_spec)
            for mount_spec in [*env_mount_specs, *cli_mount_specs]
        ]

        self._resolve_masks()
        self._resolve_ro_mounts()

        if args.path_prepend and PurePosixPath(args.path_prepend).is_absolute():
            if not self._container_path_is_mounted(args.path_prepend):
                fatal(
                    f"--path-prepend path '{args.path_prepend}' is absolute but is "
                    "not available in the container. Add a matching --mount or "
                    "use a workspace-relative path."
                )

    def setup_codex_config(self):
        """Create default ~/.codex dir"""
        codex_dir = Path.home() / ".codex"
        if not codex_dir.exists():
            codex_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info("Created directory: %", codex_dir)

    def setup_claude_config(self):
        """Create default ~/.claude.json and ~/.claude/ if needed to prevent Claude Code from hanging."""
        claude_dir = Path.home() / ".claude"
        if not claude_dir.exists():
            claude_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info("Created directory: %s", claude_dir)

        claude_config = Path.home() / ".claude.json"
        if not claude_config.exists():
            claude_config.write_text("{}\n")
            LOGGER.info("Created default config: %s", claude_config)

    def setup_pi_config(self):
        """Create pi dirs if needed"""
        pi_dir = Path.home() / ".pi"
        if not pi_dir.exists():
            pi_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info("Created directory: %s", pi_dir)

    def _check_conda_env_arch(self, conda_path):
        """Fail if the env's python is a Mach-O binary (won't run in Linux container)."""
        python_bin = conda_path / "bin" / "python"
        if not python_bin.is_file():
            return
        try:
            with open(python_bin, "rb") as f:
                magic = f.read(4)
        except OSError:
            return
        # Mach-O magic numbers (32/64-bit, both endiannesses, fat binaries).
        mach_o_magics = {
            b"\xfe\xed\xfa\xce",
            b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        }
        if magic in mach_o_magics:
            fatal(
                f"--conda-env '{conda_path}' contains macOS (Mach-O) binaries, "
                "which won't run inside the Linux container. "
            )

    def _resolve_named_conda_env(self, name):
        """Resolve a named conda env to its path using `conda env list`."""
        conda = shutil.which("conda")
        if conda is None:
            fatal(
                f"--conda-env '{name}' looks like a named env but 'conda' "
                "is not in PATH."
            )
        try:
            conda = str(conda)
            result = subprocess.run(
                [conda, "env", "list", "--json"],
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            fatal(f"failed to list conda envs: {exc.stderr.strip() or exc}")

        envs = json.loads(result.stdout).get("envs", [])
        for env_path in envs:
            if Path(env_path).name == name:
                return env_path
        fatal(f"--conda-env named '{name}' not found in 'conda env list'.")

    def _resolve_masks(self):
        """Resolve --mask paths to container targets to be shadowed.

        Each mask is a path (relative to cwd, or an absolute path inside cwd)
        pointing at a subdirectory of the mounted workspace whose contents
        should be hidden from the container.
        """
        args = self.args
        host_cwd = os.getcwd()
        container_workspace = args.workspace_mount or host_cwd

        args.mask_targets = []

        if not args.mask:
            return

        for spec in args.mask:
            host_path = Path(spec).expanduser()
            if not host_path.is_absolute():
                host_path = Path(host_cwd) / host_path
            host_path = host_path.resolve()

            if not self._is_path_inside_workspace(host_path, host_cwd):
                fatal(
                    f"--mask path '{spec}' must be inside the current working "
                    f"directory ('{host_cwd}')."
                )
            if host_path == Path(host_cwd).resolve():
                fatal("--mask cannot mask the entire working directory.")
            if not host_path.exists():
                fatal(f"--mask path not found: {spec}")

            rel = os.path.relpath(host_path, host_cwd)
            container_target = str(PurePosixPath(container_workspace) / rel)
            if container_target not in args.mask_targets:
                args.mask_targets.append(container_target)

    def _resolve_ro_mounts(self):
        """Mount workspace subdirectories read-only over the otherwise-rw
        workspace.

        Each supplied --ro path points at a subdirectory of the mounted
        workspace whose contents should be readable but not writable from the
        container. Its real contents are bind-mounted read-only on top of the
        read-write workspace mount.

        Order matters, we need this ro mount to happen *after* the rw mount.

        The respective container targets are recorded in
        ``args.nested_ok_targets`` and exempt from the nested-mount warning --
        since after all we are intentionally nesting mounts.
        """
        args = self.args
        host_cwd = os.getcwd()
        container_workspace = args.workspace_mount or host_cwd

        if not hasattr(args, "nested_ok_targets"):
            args.nested_ok_targets = set(getattr(args, "mask_targets", []))

        if not args.ro:
            return

        for spec in args.ro:
            host_path = Path(spec).expanduser()
            if not host_path.is_absolute():
                host_path = Path(host_cwd) / host_path
            host_path = host_path.resolve()

            if not self._is_path_inside_workspace(host_path, host_cwd):
                fatal(
                    f"--ro path '{spec}' must be inside the current working "
                    f"directory ('{host_cwd}')."
                )
            if host_path == Path(host_cwd).resolve():
                fatal(
                    "--ro cannot cover the entire working directory "
                    "(use --global-read-only)."
                )
            if not host_path.exists():
                fatal(f"--ro path not found: {spec}")

            rel = os.path.relpath(host_path, host_cwd)
            container_target = str(PurePosixPath(container_workspace) / rel)
            args.extra_mounts.append((str(host_path), container_target, True))
            args.nested_ok_targets.add(container_target)

    def _is_path_inside_workspace(self, path, host_cwd):
        """Check if a path is inside the workspace directory."""
        return Path(path).is_relative_to(host_cwd)

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
            (host_cwd, container_workspace, args.read_only),
        ]

        mounts.extend(args.extra_mounts)

        if args.conda_env:
            conda_path = args.conda_env
            if not self._is_path_inside_workspace(conda_path, host_cwd):
                mounts.append((conda_path, conda_path, False))

        if args.certs:
            mounts.append((args.certs, CONTAINER_CERTS_PATH, True))

        return mounts

    def _container_path_is_mounted(self, container_path):
        """Return True when a container path is reachable via the mount set."""
        target = PurePosixPath(container_path)
        for _, mount_target, _ in self._static_mounts():
            mount_path = PurePosixPath(mount_target)
            if target == mount_path or target.is_relative_to(mount_path):
                return True
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

    def _host_env_with_prefixes(self, *prefixes):
        """Return host env vars matching any of the provided prefixes."""
        return {
            key: value for key, value in os.environ.items() if key.startswith(prefixes)
        }

    def _has_static_aws_credentials(self, env):
        """Return True when the env contains direct AWS access key credentials."""
        return bool(env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"))

    def _proxy_env_vars(self):
        """Resolve proxy env vars from the host environment.

        These can be set as uppercase or lowercase versions.

        For each protocol (http, https), if only one case variant is set on the
        host, use its value for both variants inside the container.  If both are
        set, pass them through as-is.
        """
        env = {}

        https_lower = os.environ.get("https_proxy")
        https_upper = os.environ.get("HTTPS_PROXY")
        if https_lower or https_upper:
            value = https_lower or https_upper
            env["https_proxy"] = https_lower if https_lower else value
            env["HTTPS_PROXY"] = https_upper if https_upper else value

        http_lower = os.environ.get("http_proxy")
        http_upper = os.environ.get("HTTP_PROXY")
        if http_lower or http_upper:
            value = http_lower or http_upper
            env["http_proxy"] = http_lower if http_lower else value
            env["HTTP_PROXY"] = http_upper if http_upper else value

        return env

    def _bedrock_enabled(self, env):
        """Return True when the effective env enables Amazon Bedrock."""
        if self.args.cmd == "pi":
            return env.get("PI_USE_BEDROCK") == "1"
        if self.args.cmd == "claude":
            return env.get("CLAUDE_CODE_USE_BEDROCK") == "1"
        if self.args.cmd == "shell":
            return (
                env.get("CLAUDE_CODE_USE_BEDROCK") == "1"
                or env.get("PI_USE_BEDROCK") == "1"
            )
        return False

    def _has_exported_aws_profile(self):
        """Return True when ~/.aws/credentials.json exists."""
        return AWS_CREDENTIALS_JSON.is_file()

    def _validate_bedrock_env(self, env):
        """Validate Bedrock-related environment requirements once."""
        has_exported_creds = self._has_exported_aws_profile()
        if (
            self._bedrock_enabled(env)
            and not env.get("AWS_PROFILE")
            and not self._has_static_aws_credentials(env)
            and not has_exported_creds
        ):
            if self.args.cmd == "pi":
                required_flag = "PI_USE_BEDROCK=1"
            elif self.args.cmd == "shell":
                required_flag = "CLAUDE_CODE_USE_BEDROCK=1 or PI_USE_BEDROCK=1"
            else:
                required_flag = "CLAUDE_CODE_USE_BEDROCK=1"
            fatal(
                f"AWS_PROFILE must be set for {self.args.cmd} when "
                f"{required_flag}. Inherit it from the host or pass "
                "--env AWS_PROFILE=..., or create the llm-export profile with "
                "refresh.py."
            )

    def build_env_vars(self):
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

        if self.args.cmd in {"claude", "shell"}:
            env.update(self._host_env_with_prefixes("CLAUDE_CODE", "ANTHROPIC_"))
        if self.args.cmd in {"pi", "shell"}:
            env.update(self._host_env_with_prefixes("PI_"))

        # Pass through proxy env vars
        env.update(self._proxy_env_vars())

        # Args on the command line win over launcher defaults and inherited
        # tool-specific host env.
        env.update(user_env)

        if self._bedrock_enabled(env):
            has_exported_profile = self._has_exported_aws_profile()
            suppress_static_aws_creds = (
                bool(env.get("AWS_PROFILE")) or has_exported_profile
            )
            for key, value in self._host_env_with_prefixes("AWS_").items():
                if suppress_static_aws_creds and key in AWS_STATIC_CREDENTIAL_ENV_VARS:
                    continue
                env.setdefault(key, value)
            if "AWS_PROFILE" not in env and has_exported_profile:
                env["AWS_PROFILE"] = AWS_EXPORT_PROFILE

        if args.certs:
            for var_name in CERT_FILE_ENV_VARS:
                env.setdefault(var_name, CONTAINER_CERTS_PATH)

        self._validate_bedrock_env(env)
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
        container_targets = {}
        normalized = []

        for host_path, container_path, readonly in mounts:
            existing = container_targets.get(container_path)
            if existing == (host_path, readonly):
                continue

            if existing is not None and existing[0] != host_path:
                fatal(
                    "conflicting mounts for container path "
                    f"'{container_path}': '{existing[0]}' and '{host_path}'."
                )

            container_targets[container_path] = (host_path, readonly)
            normalized.append((host_path, container_path, readonly))

        return normalized

    def _warn_nested_mounts(self, mounts):
        """Warn when one container mount target nests inside another.

        Mounts whose container target is an intentionally-nested target, from
        --ro or --mask, are ignored since nesting is their whole purpose.
        """
        # --mask and --ro paths should have been added to self.nested_ok_targets
        nested_ok = getattr(self.args, "nested_ok_targets", set())
        for index, (host_path, container_path, _) in enumerate(mounts):
            for other_host_path, other_container_path, _ in mounts[index + 1 :]:
                # nested_container is (parent, child)
                nested_container = self._nested_path_pair(
                    PurePosixPath(container_path),
                    PurePosixPath(other_container_path),
                )

                if not nested_container:
                    continue

                if nested_container[1] in nested_ok:
                    continue

                LOGGER.warning(
                    "nested mounts detected between '%s:%s' and '%s:%s' "
                    "(container paths '%s' and '%s'). "
                    "Nested mounts can mask each other and cause confusing "
                    "container behavior.",
                    host_path,
                    container_path,
                    other_host_path,
                    other_container_path,
                    nested_container[0],
                    nested_container[1],
                )

    def _nested_path_pair(self, first, second):
        """Return (parent, child) when one path is nested inside the other."""
        if first == second:
            return None

        if second.is_relative_to(first):
            return str(first), str(second)

        if first.is_relative_to(second):
            return str(second), str(first)

        return None

    def _credential_mounts(self, tool):
        """
        Returns list of (host_path, container_path) tuples for the given tool.

        Only returns paths that actually exist on the host.
        """
        mounts = []
        if tool not in CREDENTIAL_PATHS:
            known_tools = ", ".join(sorted(CREDENTIAL_PATHS))
            fatal(
                f"unknown credential config '{tool}'. "
                f"Known credential configs: {known_tools}."
            )
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
                mounts.append((str(host_path), container_path, False))
                if self.args.verbose:
                    LOGGER.info("Mounting credential: %s", path_str)
            elif self.args.verbose:
                LOGGER.info("Skipping missing credential: %s", path_str)

        return mounts

    def _parse_mount_spec(self, spec):
        """Parse mount spec: 'HOST', 'HOST:CONTAINER', or 'HOST:CONTAINER:ro'."""
        if not spec or spec == ":":
            fatal(f"invalid mount specification '{spec}'.")

        parts = spec.split(":")
        readonly = False

        if parts[-1] == "ro":
            readonly = True
            parts = parts[:-1]

        if len(parts) == 1:
            resolved = str(Path(parts[0]).resolve())
            host = container = resolved
        elif len(parts) == 2:
            host, container = parts
            if not host or not container:
                fatal(
                    f"invalid mount specification '{spec}'. "
                    "Both host and container paths must be non-empty."
                )
            host = str(Path(host).resolve())
        else:
            fatal(f"invalid mount specification '{spec}'.")

        return host, container, readonly

    def _parse_mounts_env_var(self, env_var_name):
        """Parse a shell-style env var containing default mount specs."""
        value = os.environ.get(env_var_name)
        if not value:
            return []

        try:
            return shlex.split(value)
        except ValueError as exc:
            fatal(f"failed to parse ${env_var_name}: {exc}")
            return []

    def run(self):
        """Main entry point for launching a container."""
        args = self.args

        if not args.dry_run:
            if args.cmd in {"claude", "shell"}:
                self.setup_claude_config()
            if args.cmd in {"pi", "shell"}:
                self.setup_pi_config()
            self.backend.check_availability()
            self.backend.validate_image()

        # Config for this subcommand (claude, codex, shell)
        subcommand_config = SUBCOMMAND_CONFIG[args.cmd]
        env_vars = self.build_env_vars()
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
        "--tag",
        default=None,
        help=(
            "Image tag to use for the default registry images. By default each "
            "harness uses its own latest tag (e.g. 'codex-latest'), which only "
            "moves when that harness's version changes. Pass e.g. '--tag latest' "
            "to use the latest overall image, or a pinned tag like "
            "'codex-0.125.0'. Ignored for custom local --image-name/--sif-path "
            "values that already include a tag."
        ),
    )
    parser.add_argument(
        "--arch",
        default=(
            "linux/arm64"
            if platform.machine().lower() in ("arm64", "aarch64")
            else "linux/amd64"
        ),
        help="Container platform for podman (default: %(default)s, needs to match arch given to build.py)",
    )
    parser.add_argument(
        "--sif-path",
        default=DEFAULT_SINGULARITY_IMAGE,
        help="Singularity image path. Relative paths resolved relative to this script (default: %(default)s)",
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
        help=(
            "Additional mount: HOST_PATH, HOST_PATH:CONTAINER_PATH, or "
            "HOST_PATH:CONTAINER_PATH:ro (repeatable). Defaults from "
            f"${DEFAULT_MOUNTS_ENV_VAR} are also applied when set."
        ),
    )
    parser.add_argument(
        "--global-read-only",
        dest="read_only",
        action="store_true",
        default=False,
        help=(
            "Mount the current working directory as read-only inside the container. "
            "See --ro if you want to selectively set subdirectories to read-only."
        ),
    )
    parser.add_argument(
        "--ro",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Protect a subdirectory of the working directory by re-mounting it "
            "read-only on top of the read-write workspace. PATH is relative to "
            "the current working directory (or an absolute path inside it). "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--mask",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Hide a subdirectory of the working directory from the container by "
            "shadowing it with an empty read-only directory. PATH is relative to "
            "the current working directory (or an absolute path inside it). "
            "Repeatable."
        ),
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

    parser.add_argument(
        "cmd",
        choices=tuple(SUBCOMMAND_CONFIG),
        help="Tool to run inside the container",
    )
    parser.add_argument(
        "tool_args",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )

    return parser


def parse_args(argv):
    """Parse command-line arguments."""
    args = build_parser().parse_args(argv)

    # An optional separator can make the launcher/tool argument boundary clear.
    if args.tool_args[:1] == ["--"]:
        args.tool_args = args.tool_args[1:]

    # Resolve the effective image tag. Our own default registry images get a
    # per-harness "latest" tag (or whatever --tag specifies); custom images are
    # left as-is unless --tag is given. The singularity reference is only
    # treated as a registry image when it uses the oras:// scheme; a local .sif
    # path is never rewritten.
    args.image_name = resolve_image_reference(
        args.image_name, args.tag, args.cmd, DEFAULT_PODMAN_IMAGE
    )
    if args.sif_path.startswith("oras://"):
        args.sif_path = resolve_image_reference(
            args.sif_path, args.tag, args.cmd, DEFAULT_SINGULARITY_IMAGE
        )

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
