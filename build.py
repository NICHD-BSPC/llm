#!/usr/bin/env python3

import argparse
import getpass
import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
IMAGE_NAME = "localhost/llm-devcontainer:latest"
ARCH = "linux/amd64"
LOCAL_TAR_PATH = REPO_ROOT / "img.tar"
CONTAINER_USERNAME = "devuser"
DEFAULT_REMOTE_TAR_NAME = "img.tar"
DEFAULT_REMOTE_LAUNCHER_NAME = "launch.py"
DEFAULT_REMOTE_SIF_NAME = "llm.sif"
DRY_RUN = False


def run(cmd, cwd=None):
    "Print the command in cyan and then run it"
    print(f"\033[36m$ {shlex.join(cmd)}\033[0m")
    if DRY_RUN:
        return
    subprocess.run(cmd, check=True, cwd=cwd)


def resolve_remote(target):
    "Fill in the local username when the user passes only a hostname"
    resolved = target or os.environ.get("LLM_REMOTE", "")
    if not resolved:
        raise SystemExit(
            "Remote target is required. Set LLM_REMOTE or pass a host/user@host argument."
        )
    if "@" in resolved:
        return resolved
    return f"{getpass.getuser()}@{resolved}"


def resolve_publish_paths(remote_path, remote_tar, remote_launcher, remote_sif):
    "Resolve remote artifact locations for the publish subcommand."
    base = remote_path.expanduser() if remote_path else None

    resolved_tar = remote_tar.expanduser() if remote_tar else None
    resolved_launcher = remote_launcher.expanduser() if remote_launcher else None
    resolved_sif = remote_sif.expanduser() if remote_sif else None

    if base:
        resolved_tar = resolved_tar or (base / DEFAULT_REMOTE_TAR_NAME)
        resolved_launcher = resolved_launcher or (base / DEFAULT_REMOTE_LAUNCHER_NAME)
        resolved_sif = resolved_sif or (base / DEFAULT_REMOTE_SIF_NAME)

    missing = []
    if resolved_tar is None:
        missing.append("--remote-tar")
    if resolved_launcher is None:
        missing.append("--remote-launcher")
    if resolved_sif is None:
        missing.append("--remote-sif")

    if missing:
        raise SystemExit(
            "Missing remote publish path(s): {}. Pass --remote-path to use default "
            "filenames in a remote directory, or provide the explicit path arguments.".format(
                ", ".join(missing)
            )
        )

    return resolved_tar, resolved_launcher, resolved_sif


def build_image(image_name, arch, *args, certs_path=None):
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
    run(cmd)


def save_image(image_name, tar_path):
    """
    Save podman image as a tar file so it can be transferred to the remote
    and converted to singularity
    """
    run(
        [
            "podman",
            "save",
            "-o",
            str(tar_path),
            "--format",
            "docker-archive",
            image_name,
        ]
    )


def push_artifacts(
    remote,
    local_tar,
    remote_tar,
    remote_launcher,
):
    """
    Push locally saved tar to remote, along with launcher script
    """
    # Quote the remote paths because this string is interpreted by the remote shell.
    mkdir_cmd = "mkdir -p {} {}".format(
        shlex.quote(str(remote_tar.parent)),
        shlex.quote(str(remote_launcher.parent)),
    )
    run(["ssh", remote, mkdir_cmd])
    run(["rsync", "-av", "--progress", str(local_tar), f"{remote}:{remote_tar}"])
    run(
        [
            "rsync",
            "-av",
            "--progress",
            str(REPO_ROOT / "launch.py"),
            f"{remote}:{remote_launcher}",
        ]
    )


def build_remote_sif(
    remote,
    remote_tar,
    remote_sif,
    *,
    force=False,
    tmpdir=None,
):
    """
    After transferring, use singularity on the remote to convert the
    transferred tar to a singularity .sif
    """
    # The singularity invocation must run on the remote machine, so it is
    # passed as a single shell command to ssh.
    build_cmd_parts = ["singularity", "build"]
    if force:
        build_cmd_parts.append("--force")
    build_cmd_parts.extend(
        [
            str(remote_sif),
            # this is how we tell singularity it's coming from
            # a docker-image-turned-into-tarball.
            f"docker-archive:{remote_tar}",
        ]
    )
    build_cmd = shlex.join(build_cmd_parts)
    if tmpdir:
        build_cmd = f"TMPDIR={shlex.quote(str(tmpdir))} {build_cmd}"
    run(["ssh", remote, build_cmd])


def build_parser():
    """Create the command-line parser, split into "build" and "publish" subcommands"""

    # Used by build and publish
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--image-name",
        default=IMAGE_NAME,
        help="Container image name (default: %(default)s)",
    )
    common.add_argument(
        "--arch",
        default=ARCH,
        help="Container platform (default: %(default)s)",
    )
    common.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Don't use cache for podman build (useful to force update of agent harnesses)",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print commands without running them",
    )
    common.add_argument(
        "--certs",
        type=Path,
        default=None,
        help=(
            "Optional PEM bundle passed to podman build as the "
            "'mitm_ca_bundle' secret for temporary TLS interception trust"
        ),
    )


    parser = argparse.ArgumentParser(
        parents=[common],
        description="Build, save, and publish the llm devcontainer image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment:\n"
            "  LLM_REMOTE           Optional fallback remote target when no host or user@host is passed."
        ),
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", parents=[common], help="Build the image")

    publish = sub.add_parser(
        "publish",
        parents=[common],
        help="Build, save, and push artifacts to a remote host",
    )
    publish.add_argument(
        "--local-tar",
        type=Path,
        default=LOCAL_TAR_PATH,
        help="Local tarball path (default: %(default)s)",
    )
    publish.add_argument("remote", nargs="?", help="host or user@host")

    publish.add_argument(
        "--remote-path",
        type=Path,
        required=True,
        help=(
            "Remote directory used as a base for default artifact names: "
            f"{DEFAULT_REMOTE_TAR_NAME}, {DEFAULT_REMOTE_LAUNCHER_NAME}, "
            f"and {DEFAULT_REMOTE_SIF_NAME}."
        ),
    )
    publish.add_argument(
        "--remote-tar",
        type=Path,
        help=(
            "Send the local image tarball (local path controlled via --local-tar) "
            f"to this location on the remote. Defaults to --remote-path/{DEFAULT_REMOTE_TAR_NAME}."
        ),
    )
    publish.add_argument(
        "--remote-launcher",
        type=Path,
        help=(
            "Send the launch.py script to this location on the remote. "
            f"Defaults to --remote-path/{DEFAULT_REMOTE_LAUNCHER_NAME}."
        ),
    )
    publish.add_argument(
        "--remote-sif",
        type=Path,
        help=(
            "When creating singularity container on the remote, save the resulting "
            f"SIF to this location. Defaults to --remote-path/{DEFAULT_REMOTE_SIF_NAME}."
        ),
    )
    publish.add_argument(
        "--force", action="store_true", help="Pass --force to singularity build"
    )
    publish.add_argument(
        "--tmpdir",
        type=Path,
        help="Set TMPDIR on the remote host for singularity build",
    )

    return parser


def main(argv=None):
    global DRY_RUN
    args = build_parser().parse_args(argv)
    DRY_RUN = args.dry_run
    no_cache_args = ["--no-cache"] if getattr(args, "no_cache", False) else []

    if args.cmd == "build":
        build_image(
            args.image_name,
            args.arch,
            *no_cache_args,
            certs_path=args.certs,
        )
        return 0

    if args.cmd == "publish":
        local_tar = args.local_tar.expanduser()
        if not DRY_RUN:
            result = subprocess.run(
                ["ssh-add", "-l"],
                capture_output=True,
            )
            if result.returncode != 0:
                raise SystemExit(
                    "SSH agent is not running or has no keys. "
                    "Start it with: eval $(ssh-agent) && ssh-add"
                )
        else:
            run(["ssh-add", "-l"])
        remote = resolve_remote(getattr(args, "remote", None))
        remote_tar, remote_launcher, remote_sif = resolve_publish_paths(
            args.remote_path,
            args.remote_tar,
            args.remote_launcher,
            args.remote_sif,
        )
        build_image(
            args.image_name,
            args.arch,
            *no_cache_args,
            certs_path=args.certs,
        )
        print(f"Saving image {args.image_name} to {local_tar} ...")
        save_image(args.image_name, local_tar)
        push_artifacts(remote, local_tar, remote_tar, remote_launcher)
        build_remote_sif(
            remote,
            remote_tar,
            remote_sif,
            force=args.force,
            tmpdir=args.tmpdir,
        )
        return 0

    raise AssertionError(f"Unhandled command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
