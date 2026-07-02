#!/usr/bin/env python3

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import getpass
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Optional

LOGGER = logging.getLogger("refresh")


def configure_logging(verbose=False):
    """Configure CLI logging."""
    LOGGER.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.propagate = False

AWS_EXPORT_PROFILE = "llm-export"
AWS_CREDENTIALS_JSON = Path.home() / ".aws" / "credentials.json"
AWS_CONFIG_PATH = Path.home() / ".aws" / "config"
PI_DIR = Path.home() / ".pi"

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
        "auth": ("~/.aws/config", "~/.aws/credentials.json"),
        "config": ("~/.claude/settings.json", "~/.claude.json"),
        "full": (
            "~/.claude/settings.json",
            "~/.claude.json",
            "~/.claude/skills",
            "~/.aws/config",
            "~/.aws/credentials.json",
        ),
    },
    "pi": {
        # Include auth.json to support ChatGPT Enterprise login, where we
        # convert the codex login auth.json into something that Pi can use
        "auth": ("~/.pi/agent/auth.json", "~/.aws/config", "~/.aws/credentials.json"),
        "config": ("~/.pi/agent/settings.json",),
        "full": (
            "~/.pi/agent/skills",
            "~/.pi/agent/settings.json",
            "~/.pi/agent/extensions",
            "~/.pi/agent/auth.json",
            "~/.aws/config",
            "~/.aws/credentials.json",
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
        LOGGER.warning("skipping missing path: %s", path)

    if not relative_paths:
        LOGGER.warning("no existing paths to rsync")
        return

    LOGGER.info("rsyncing these paths to %s:~/...\n\n  %s", remote_host, "\n  ".join(paths))

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


def refresh_aws_sso():
    """Check AWS SSO credentials and refresh if needed."""
    try:
        expiration = aws_credential_expiration()
        if expiration:
            LOGGER.info("AWS SSO credentials expire at: %s", expiration)
        else:
            LOGGER.info("AWS SSO credentials have no expiration set.")
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as e:
        LOGGER.warning("AWS credential check failed (%s), running aws sso login...", e)
        try:
            subprocess.run(["aws", "sso", "login"], check=True)
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
        LOGGER.info("Codex: already logged in.")
    else:
        LOGGER.warning("Codex: not logged in (%r), running codex login...", output)
        subprocess.run(["codex", "login"], check=True)


def decode_jwt_payload(jwt):
    """Decode the payload portion of a JWT token without verifying it."""
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1].replace("-", "+").replace("_", "/")
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.b64decode(payload).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def convert_codex_auth_to_pi(src, dest):
    """
    Upsert Codex OAuth credentials into Pi auth.json.

    Pi auth.json may contain credentials for many providers, so this function
    preserves the existing top-level object and only updates the openai-codex
    entry. If an existing Pi auth file is malformed, fail instead of replacing
    unrelated credentials.
    """
    with open(src, "r") as f:
        codex = json.load(f)

    tokens = codex.get("tokens")
    if not tokens:
        raise ValueError("No 'tokens' key found in Codex auth.json")

    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    account_id = tokens.get("account_id")

    if not access or not refresh:
        raise ValueError(
            "Could not find access_token and refresh_token in Codex auth.json"
        )

    jwt = decode_jwt_payload(access)
    expires = jwt.get("exp", 0) * 1000 if jwt else 0

    pi_data = {}
    if dest.exists():
        try:
            with open(dest, "r") as f:
                pi_data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Existing Pi auth.json is invalid JSON: {dest}") from exc
        if not isinstance(pi_data, dict):
            raise ValueError(f"Existing Pi auth.json must contain a JSON object: {dest}")

    pi_data["openai-codex"] = {
        "type": "oauth",
        "access": access,
        "refresh": refresh,
        "expires": expires,
    }
    if account_id:
        pi_data["openai-codex"]["accountId"] = account_id

    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = dest.with_name(f".{dest.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(pi_data, f, indent=2)
        f.write("\n")

    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def update_pi_codex_auth():
    """Upsert Codex OAuth credentials into Pi auth.json."""
    src = Path(os.environ.get("CODEX_AUTH_PATH", Path.home() / ".codex" / "auth.json"))
    dest = Path(
        os.environ.get("PI_AUTH_PATH", Path.home() / ".pi" / "agent" / "auth.json")
    )
    convert_codex_auth_to_pi(src, dest)
    LOGGER.info("Updated Pi Codex auth at %s", dest)


def aws_credential_expiration() -> Optional[str]:
    """Return the AWS credential expiration string from the AWS CLI."""
    result = subprocess.run(
        ["aws", "configure", "export-credentials"],
        capture_output=True,
        text=True,
        check=True,
    )
    creds = json.loads(result.stdout)
    return creds.get("Expiration")


def aws_export_credentials(profile: Optional[str] = None) -> dict:
    """Return AWS credentials in process-provider JSON format."""
    cmd = ["aws", "configure", "export-credentials", "--format", "process"]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def upsert_ini_section(path: Path, section: str, entries: dict[str, str]) -> None:
    """Replace or append a managed INI section while preserving other sections.

    If ``section`` already exists in the file at ``path``, its contents are
    replaced with ``entries``. If it doesn't exist, it is appended at the end.
    All other sections in the file are left untouched.

    Args:
        path: Path to the INI file (created along with parent dirs if missing).
        section: The section name without brackets, and including "profile", e.g. "profile llm-export".
        entries: Key/value pairs to write under the section header.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        lines = []

    # Note: we're not using configparser because it lowercases keys, strips
    # comments, reorders sections, and doesn't round-trip formatting well — all
    # of which matter for ~/.aws/config files you might also be editing
    # manually.
    section_header = f"[{section}]"
    section_pattern = re.compile(r"^\s*\[.*\]\s*$")
    rendered_section = [
        section_header,
        *[f"{key} = {value}" for key, value in entries.items()],
    ]

    output_lines = []
    index = 0
    replaced = False
    while index < len(lines):
        line = lines[index]
        if line.strip() == section_header:
            replaced = True
            output_lines.extend(rendered_section)
            index += 1
            while index < len(lines) and not section_pattern.match(lines[index]):
                index += 1
            if index < len(lines) and output_lines and output_lines[-1] != "":
                output_lines.append("")
            continue

        output_lines.append(line)
        index += 1

    if not replaced:
        if output_lines and output_lines[-1] != "":
            output_lines.append("")
        output_lines.extend(rendered_section)

    path.write_text("\n".join(output_lines).rstrip() + "\n")


def export_aws_profile() -> None:
    """Export current AWS credentials as JSON and configure the llm-export profile."""
    creds = aws_export_credentials()

    # Write the process-format JSON directly
    AWS_CREDENTIALS_JSON.parent.mkdir(parents=True, exist_ok=True)
    AWS_CREDENTIALS_JSON.write_text(json.dumps(creds, indent=2) + "\n")

    # Configure the profile to use credential_process = cat <json file>
    upsert_ini_section(
        AWS_CONFIG_PATH,
        f"profile {AWS_EXPORT_PROFILE}",
        {
            "credential_process": "sh -c 'cat ~/.aws/credentials.json'",
        },
    )
    LOGGER.info("Exported AWS credentials to %s", AWS_CREDENTIALS_JSON)
    LOGGER.info(
        "Configured credential_process in %s [profile %s]",
        AWS_CONFIG_PATH,
        AWS_EXPORT_PROFILE,
    )


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


def bedrock_export_command() -> str:
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
    expiration = aws_credential_expiration()
    if expiration:
        expires_at = parse_timestamp(expiration)
        remaining = expires_at - datetime.now(timezone.utc)
        effective = min(requested_expiry, max(remaining, timedelta()))
        LOGGER.info(
            "Bedrock token request: 12h; AWS credentials expire at %s; "
            "max possible token duration: %s",
            expiration,
            format_duration(effective),
        )
    else:
        LOGGER.info(
            "Bedrock token request: 12h; AWS credentials have no reported expiration."
        )

    token = provide_token(expiry=requested_expiry)
    return f"export AWS_BEARER_TOKEN_BEDROCK={shlex.quote(token)}"


def parse_args(argv=None) -> argparse.Namespace:
    user = getpass.getuser()
    argv = list(sys.argv[1:] if argv is None else argv)
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
        "--no-export-creds",
        action="store_true",
        help="Skip exporting AWS credentials into ~/.aws/credentials",
    )
    ap.add_argument(
        "--user",
        default=user,
        help="username for remote, defaults to %(default)s",
    )
    args = ap.parse_args(argv)
    if args.bedrock_export:
        args.kind = "bedrock"
    return args


def main() -> int:
    args = parse_args()
    configure_logging()

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

    if args.kind in ("all", "claude", "pi"):
        refresh_aws_sso()
        if not args.no_export_creds:
            export_aws_profile()
    if args.kind in ("all", "codex", "pi"):
        refresh_codex()
        update_pi_codex_auth()
    if args.kind == "bedrock":
        try:
            refresh_aws_sso()
            print(bedrock_export_command())
        except RuntimeError as e:
            LOGGER.error("%s", e)
            return 1
        return 0

    kinds = CREDENTIAL_PATHS.keys() if args.kind == "all" else [args.kind]
    paths = sorted(
        set([path for kind in kinds for path in CREDENTIAL_PATHS[kind]["auth"]])
    )
    if args.full:
        paths = sorted(
            set([path for kind in kinds for path in CREDENTIAL_PATHS[kind]["full"]])
        )

    if args.remote:
        rsync_paths(paths=paths, user=args.user, remote=args.remote)
    else:
        LOGGER.info("No --remote specified; skipping push.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
