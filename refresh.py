#!/usr/bin/env python3

import argparse
from configparser import RawConfigParser
from datetime import datetime, timedelta, timezone
import json
import getpass
from io import StringIO
import os
import subprocess
import sys
from typing import Optional

AWS_EXPORT_PROFILE = "llm-export"

CREDENTIAL_PATHS = {
    "codex": {
        "auth": ("~/.codex/auth.json",),
        "config": ("~/.codex/config.toml",),
        "full": (
            "~/.codex/config.toml",
            "~/.codex/auth.json",
            "~/.codex/skills",
            "~/.codex/memories",
        ),
    },
    "claude": {
        "auth": ("~/.aws/config", "~/.aws/sso/cache"),
        "config": ("~/.claude/settings.json", "~/.claude.json"),
        "full": (
            "~/.claude/settings.json",
            "~/.claude.json",
            "~/.claude/skills",
            "~/.aws/config",
            "~/.aws/sso/cache",
        ),
    },
    "pi": {
        "auth": ("~/.aws/config", "~/.aws/sso/cache"),
        "config": ("~/.pi/agent/settings.json",),
        "full": (
            "~/.pi/agent/skills",
            "~/.pi/agent/settings.json",
            "~/.pi/agent/extensions",
            "~/.pi/agent/auth.json",
            "~/.aws/config",
            "~/.aws/sso/cache",
        ),
    },
}


def home_relative_path(path):
    """Return a path relative to the user's home directory.

    Used for batching together rsync calls.
    """
    local_path = os.path.expanduser(path)
    home_dir = os.path.abspath(os.path.expanduser("~"))
    absolute_path = os.path.abspath(local_path)
    if os.path.commonpath([home_dir, absolute_path]) != home_dir:
        raise ValueError(
            f"Path must be inside the home directory for batched rsync: {path}"
        )
    return os.path.relpath(absolute_path, home_dir)


def rsync_paths(paths, user, remote):
    """Copy multiple local paths to the remote home directory in one rsync call."""

    if not paths:
        return

    remote_host = f"{user}@{remote}" if user else remote
    relative_paths = []
    skipped_paths = []

    for path in paths:
        local_path = os.path.expanduser(path)
        if not os.path.exists(local_path):
            skipped_paths.append(path)
            continue
        relative_paths.append(home_relative_path(path))

    for path in skipped_paths:
        print(f"skipping missing path: {path}", file=sys.stderr)

    if not relative_paths:
        print("no existing paths to rsync", file=sys.stderr)
        return

    print(f"rsyncing these paths to {remote_host}:~/...\n\n ", "\n  ".join(paths))

    subprocess.run(
        [
            "rsync",
            "-arv",
            "--relative",
            *relative_paths,
            f"{remote_host}:~/",
        ],
        check=True,
        cwd=os.path.expanduser("~"),
    )


def refresh_aws_sso(profile=None):
    """Check AWS SSO credentials and refresh if needed."""
    try:
        expiration = aws_credential_expiration(profile)
        if expiration:
            print(f"AWS SSO credentials expire at: {expiration}", file=sys.stderr)
        else:
            print("AWS SSO credentials have no expiration set.", file=sys.stderr)
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as e:
        print(
            f"AWS credential check failed ({e}), running aws sso login...",
            file=sys.stderr,
        )
        try:
            cmd = ["aws", "sso", "login"]
            if profile:
                cmd.extend(["--profile", profile])
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as login_error:
            raise RuntimeError(
                "Unable to refresh AWS SSO credentials. Run 'aws configure sso' "
                "if this profile is not configured, then retry."
            ) from login_error


def refresh_codex():
    """Check codex login status and login if needed."""
    result = subprocess.run(
        ["codex", "login", "status"],
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip() or result.stderr.strip()
    if output == "Logged in using ChatGPT":
        print("Codex: already logged in.", file=sys.stderr)
    else:
        print(
            f"Codex: not logged in ({output!r}), running codex login...",
            file=sys.stderr,
        )
        subprocess.run(["codex", "login"], check=True)


def aws_credential_expiration(profile=None) -> Optional[str]:
    """Return the AWS credential expiration string from the AWS CLI."""
    cmd = ["aws", "configure", "export-credentials"]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    creds = json.loads(result.stdout)
    return creds.get("Expiration")


def parse_timestamp(expiration: str) -> datetime:
    """Parse an AWS credential expiration timestamp into an aware datetime."""
    normalized = expiration.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_duration(duration: timedelta) -> str:
    """Format a duration into a compact human-readable form."""
    total_seconds = max(0, int(duration.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def bedrock_export_command(profile=None) -> str:
    """Return a shell command that exports a fresh Bedrock bearer token."""
    try:
        from aws_bedrock_token_generator import provide_token
    except ImportError as exc:
        raise RuntimeError(
            "aws-bedrock-token-generator is not installed. Install it with "
            "'pip install aws-bedrock-token-generator' or from "
            "https://github.com/aws/aws-bedrock-token-generator-python."
        ) from exc

    requested_expiry = timedelta(hours=12)
    expiration = aws_credential_expiration(profile)
    if expiration:
        expires_at = parse_timestamp(expiration)
        remaining = expires_at - datetime.now(timezone.utc)
        effective = min(requested_expiry, max(remaining, timedelta()))
        print(
            "Bedrock token request: 12h; "
            f"AWS credentials expire at {expiration}; "
            f"max possible token duration: {format_duration(effective)}",
            file=sys.stderr,
        )
    else:
        print(
            "Bedrock token request: 12h; AWS credentials have no reported expiration.",
            file=sys.stderr,
        )

    token = provide_token(expiry=requested_expiry)
    return f"export AWS_BEARER_TOKEN_BEDROCK={shlex.quote(token)}"


def aws_export_region() -> str:
    """Return the region to use for exported AWS credentials."""
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )

def _read_ini_text(text: str) -> RawConfigParser:
    """Parse INI text into a config parser."""
    parser = RawConfigParser()
    if text.strip():
        parser.read_string(text)
    return parser


def _write_ini_text(parser: RawConfigParser) -> str:
    """Serialize a config parser back to INI text."""
    stream = StringIO()
    parser.write(stream)
    return stream.getvalue()


def upsert_aws_export_profile(config_text: str, region: str) -> str:
    """Insert or replace the exported-credentials profile in AWS config text."""
    parser = _read_ini_text(config_text)
    section = f"profile {AWS_EXPORT_PROFILE}"
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, "region", region)
    return _write_ini_text(parser)


def upsert_aws_credentials_profile(
    credentials_text: str, exported_creds: dict[str, str]
) -> str:
    """Insert or replace the exported-credentials profile in AWS credentials."""
    parser = _read_ini_text(credentials_text)
    section = AWS_EXPORT_PROFILE
    if not parser.has_section(section):
        parser.add_section(section)
    access_key = exported_creds.get("AccessKeyId")
    secret_key = exported_creds.get("SecretAccessKey")
    if not access_key or not secret_key:
        raise RuntimeError("exported AWS credentials are missing required keys")
    parser.set(section, "aws_access_key_id", access_key)
    parser.set(section, "aws_secret_access_key", secret_key)
    session_token = exported_creds.get("SessionToken")
    if session_token:
        parser.set(section, "aws_session_token", session_token)
    elif parser.has_option(section, "aws_session_token"):
        parser.remove_option(section, "aws_session_token")
    return _write_ini_text(parser)


def read_remote_text(remote_host: str, path: str) -> str:
    """Return remote file contents, or an empty string when the file is missing."""
    result = subprocess.run(
        ["ssh", remote_host, f"if [ -f {path} ]; then cat {path}; fi"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def export_aws_credentials(profile=None) -> dict[str, str]:
    """Run `aws configure export-credentials` and return the parsed JSON."""
    cmd = ["aws", "configure", "export-credentials"]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def write_exported_aws_profile_remote(remote, user=None, profile=None):
    """Export AWS credentials and write the llm-export profile on the remote host."""
    exported_creds = export_aws_credentials(profile)
    remote_host = f"{user}@{remote}" if user else remote
    remote_config = read_remote_text(remote_host, "~/.aws/config")
    remote_credentials = read_remote_text(remote_host, "~/.aws/credentials")
    aws_config = upsert_aws_export_profile(remote_config, region=aws_export_region())
    aws_credentials = upsert_aws_credentials_profile(
        remote_credentials, exported_creds
    )
    print(f"updating AWS export profile on {remote_host}:~/.aws/", file=sys.stderr)
    subprocess.run(
        ["ssh", remote_host, "mkdir -p ~/.aws && cat > ~/.aws/config"],
        input=aws_config,
        text=True,
        check=True,
    )
    subprocess.run(
        ["ssh", remote_host, "mkdir -p ~/.aws && cat > ~/.aws/credentials && chmod 600 ~/.aws/credentials"],
        input=aws_credentials,
        text=True,
        check=True,
    )


def write_exported_aws_profile_locally(profile=None):
    """Export AWS credentials and write the llm-export profile locally."""
    exported_creds = export_aws_credentials(profile)

    aws_dir = os.path.expanduser("~/.aws")
    os.makedirs(aws_dir, exist_ok=True)
    aws_config = os.path.join(aws_dir, "config")
    try:
        with open(aws_config) as f:
            existing_config = f.read()
    except FileNotFoundError:
        existing_config = ""
    updated_config = upsert_aws_export_profile(existing_config, aws_export_region())
    with open(aws_config, "w") as f:
        f.write(updated_config)
    print(
        f"updated AWS config with profile '{AWS_EXPORT_PROFILE}' in {aws_config}",
        file=sys.stderr,
    )
    aws_credentials = os.path.join(aws_dir, "credentials")
    try:
        with open(aws_credentials) as f:
            existing_credentials = f.read()
    except FileNotFoundError:
        existing_credentials = ""
    updated_credentials = upsert_aws_credentials_profile(
        existing_credentials, exported_creds
    )
    with open(aws_credentials, "w") as f:
        f.write(updated_credentials)
    os.chmod(aws_credentials, 0o600)
    print(
        f"updated AWS credentials with profile '{AWS_EXPORT_PROFILE}' in {aws_credentials}",
        file=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    user = getpass.getuser()
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", help="remote hostname")
    ap.add_argument(
        "--full",
        help="When pushing to remote, transfer the full config (rather than just the auth files). Run with --show-files to see what will be pushed.",
        action="store_true",
    )
    ap.add_argument(
        "--show-files",
        help="Show the files that will be pushed to remote, and then exit",
        action="store_true",
    )
    ap.add_argument(
        "--kind",
        choices=("claude", "codex", "pi", "all", "bedrock"),
        default="all",
        help="Which credential set to sync (default: %(default)s)",
    )
    ap.add_argument(
        "--bedrock-export",
        action="store_true",
        help=(
            "Print a shell command that exports AWS_BEARER_TOKEN_BEDROCK "
            "using aws-bedrock-token-generator"
        ),
    )
    ap.add_argument(
        "--user",
        default=user,
        help="username for remote, defaults to %(default)s",
    )
    ap.add_argument(
        "--export-creds",
        action="store_true",
        help=(
            "Export AWS credentials into ~/.aws/credentials under the "
            f"'{AWS_EXPORT_PROFILE}' profile (pushed to --remote if given, "
            "otherwise written locally). Re-run to refresh."
        ),
    )
    ap.add_argument(
        "--aws-profile",
        metavar="PROFILE",
        help=(
            "AWS profile to use for SSO refresh, Bedrock token export, and "
            "credential export"
        ),
    )
    args = ap.parse_args()
    if args.bedrock_export:
        args.kind = "bedrock"
    return args


def main() -> int:
    args = parse_args()

    if args.show_files:
        print(
            "Auth paths that will be refreshed if needed, and pushed to remote if using --remote:"
        )
        for k, paths in CREDENTIAL_PATHS.items():
            print(f"  {k}:")
            for path in paths["auth"]:
                print(f"    {path}")
        print("Full paths (will be transferred if using --full):")
        for k, paths in CREDENTIAL_PATHS.items():
            print(f"  {k}:")
            for path in paths["full"]:
                print(f"    {path}")
        sys.exit(0)

    if args.export_creds:
        refresh_aws_sso(args.aws_profile)
        if args.remote:
            write_exported_aws_profile_remote(
                remote=args.remote, user=args.user, profile=args.aws_profile
            )
        else:
            write_exported_aws_profile_locally(profile=args.aws_profile)
        return 0

    if args.kind in ("all", "claude", "pi"):
        refresh_aws_sso(args.aws_profile)
    if args.kind in ("all", "codex"):
        refresh_codex()
    if args.kind == "bedrock":
        try:
            refresh_aws_sso(args.aws_profile)
            print(bedrock_export_command(args.aws_profile))
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0

    kinds = CREDENTIAL_PATHS.keys() if args.kind == "all" else [args.kind]
    paths = sorted(set([path for kind in kinds for path in CREDENTIAL_PATHS[kind]["auth"]]))
    if args.full:
        paths = sorted(set([path for kind in kinds for path in CREDENTIAL_PATHS[kind]["full"]]))

    if args.remote:
        rsync_paths(paths=paths, user=args.user, remote=args.remote)
    else:
        print("No --remote specified; skipping push.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
