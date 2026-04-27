#!/usr/bin/env python3

import argparse
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
IMAGE_NAME = "localhost/llm-devcontainer:latest"
ARCH = "linux/amd64"
CONTAINER_USERNAME = "devuser"
DEFAULT_REPOSITORY_URL = "https://github.com/nichd-bspc/llm"


def run(cmd, cwd=None, dry_run=False):
    "Print the command in cyan and then run it"
    print(f"\033[36m$ {shlex.join(cmd)}\033[0m")
    if dry_run:
        return
    subprocess.run(cmd, check=True, cwd=cwd)


def build_image(
    image_name,
    arch,
    *args,
    certs_path=None,
    dry_run=False,
    tool_versions=None,
    repository_url=DEFAULT_REPOSITORY_URL,
):
    "Build podman image"

    cmd = [
        "podman",
        "build",
        "--build-arg",
        f"USERNAME={CONTAINER_USERNAME}",
        "--build-arg",
        f"REPOSITORY_URL={repository_url}",
        "--platform",
        arch,
    ]
    if tool_versions is not None:
        cmd.extend(
            [
                "--build-arg",
                f"CLAUDE_VERSION={tool_versions['claude']}",
                "--build-arg",
                f"CODEX_VERSION={tool_versions['codex']}",
                "--build-arg",
                f"PI_VERSION={tool_versions['pi']}",
            ]
        )
    if certs_path is not None:
        certs_path = certs_path.expanduser().resolve()
        if not certs_path.is_file():
            raise SystemExit(f"Certificate bundle not found: {certs_path}")
        cmd.extend(["--secret", f"id=mitm_ca_bundle,src={certs_path}"])
    cmd.extend(
        [
            "-t",
            image_name,
            "-f",
            str(REPO_ROOT / "Dockerfile"),
            str(REPO_ROOT),
            *args,
        ]
    )
    run(cmd, dry_run=dry_run)


def build_parser():
    """Create the command-line parser for building the llm devcontainer image."""

    parser = argparse.ArgumentParser(
        description="Build the llm devcontainer image.",
    )
    parser.add_argument(
        "--image-name",
        default=IMAGE_NAME,
        help="Container image name (default: %(default)s)",
    )
    parser.add_argument(
        "--arch",
        default=ARCH,
        help="Container platform (default: %(default)s)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Don't use cache for podman build (useful to force update of agent harnesses)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print commands without running them",
    )
    parser.add_argument(
        "--certs",
        type=Path,
        default=None,
        help=(
            "Optional PEM bundle passed to podman build as the "
            "'mitm_ca_bundle' secret for temporary TLS interception trust"
        ),
    )
    parser.add_argument(
        "--repository-url",
        default=DEFAULT_REPOSITORY_URL,
        help="Repository URL recorded in image metadata (default: %(default)s)",
    )
    parser.add_argument(
        "--claude-version",
        default=None,
        help="Claude Code version to embed in the image metadata and install",
    )
    parser.add_argument(
        "--codex-version",
        default=None,
        help="Codex version to embed in the image metadata and install",
    )
    parser.add_argument(
        "--pi-version",
        default=None,
        help="Pi version to embed in the image metadata and install",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    no_cache_args = ["--no-cache"] if args.no_cache else []
    provided_versions = (
        args.claude_version or None,
        args.codex_version or None,
        args.pi_version or None,
    )

    if all(provided_versions):
        tool_versions = {
            "claude": args.claude_version,
            "codex": args.codex_version,
            "pi": args.pi_version,
        }
    elif any(provided_versions):
        raise SystemExit(
            "--claude-version, --codex-version, and --pi-version must be provided together"
        )
    else:
        tool_versions = None

    build_image(
        args.image_name,
        args.arch,
        *no_cache_args,
        certs_path=args.certs,
        dry_run=args.dry_run,
        tool_versions=tool_versions,
        repository_url=args.repository_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
