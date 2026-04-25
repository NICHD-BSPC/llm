#!/usr/bin/env python3

import argparse
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
IMAGE_NAME = "localhost/llm-devcontainer:latest"
ARCH = "linux/amd64"
CONTAINER_USERNAME = "devuser"


def run(cmd, cwd=None, dry_run=False):
    "Print the command in cyan and then run it"
    print(f"\033[36m$ {shlex.join(cmd)}\033[0m")
    if dry_run:
        return
    subprocess.run(cmd, check=True, cwd=cwd)


def build_image(image_name, arch, *args, certs_path=None, dry_run=False):
    "Build podman image"

    cmd = [
        "podman",
        "build",
        "--build-arg",
        f"USERNAME={CONTAINER_USERNAME}",
        "--platform",
        arch,
    ]
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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    no_cache_args = ["--no-cache"] if args.no_cache else []

    build_image(
        args.image_name,
        args.arch,
        *no_cache_args,
        certs_path=args.certs,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
