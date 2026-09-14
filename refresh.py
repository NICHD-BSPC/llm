#!/usr/bin/env python3

import argparse
import base64
import getpass
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
AWS_MANAGED_BUNDLE_DIR = Path.home() / ".aws" / AWS_EXPORT_PROFILE
AWS_CREDENTIALS_JSON = AWS_MANAGED_BUNDLE_DIR / "credentials.json"
AWS_CONFIG_PATH = AWS_MANAGED_BUNDLE_DIR / "config"
MANAGED_AWS_CONFIG = """[profile llm-export]
credential_process = sh -c 'cat ~/.aws/llm-export/credentials.json'
"""

# This is public information; we can use it to rotate tokens ourselves rather
# than shell out to `codex login`. Still need `codex login` for if refresh
# token is missing.
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

# Refresh when the access token has less than this much life left.
CODEX_REFRESH_WINDOW = timedelta(days=1)

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
        "auth": ("~/.aws/llm-export",),
        "config": ("~/.claude/settings.json", "~/.claude.json"),
        "full": (
            "~/.claude/settings.json",
            "~/.claude.json",
            "~/.claude/skills",
            "~/.aws/llm-export",
        ),
    },
    "pi": {
        # Include auth.json to support ChatGPT Enterprise login, where we
        # convert the codex login auth.json into something that Pi can use
        "auth": ("~/.pi/agent/auth.json", "~/.aws/llm-export"),
        "config": ("~/.pi/agent/settings.json",),
        "full": (
            "~/.pi/agent/skills",
            "~/.pi/agent/settings.json",
            "~/.pi/agent/extensions",
            "~/.pi/agent/auth.json",
            "~/.aws/llm-export",
        ),
    },
}


def write_private_text(path, content):
    """Write a private file, creating its parent directory if needed."""
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed:
        os.chmod(path.parent, 0o700)

    # open(path, "w") leaves an existing file's mode unchanged; since these are
    # credentials we're keeping the permissions 600 all the time.
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
        "w",
        encoding="utf-8",
    ) as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(content)


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

    LOGGER.info(
        "rsyncing these paths to %s:~/...\n\n  %s", remote_host, "\n  ".join(paths)
    )

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


def resolve_source_profile(cli_profile=None):
    """Resolve the AWS source profile for this run.

    ``--aws-profile`` or env var ``AWS_PROFILE`` can override default
    "llm-export" profile.
    """
    for candidate in (cli_profile, os.environ.get("AWS_PROFILE")):
        if candidate and candidate.strip():
            return candidate
    return None


def refresh_aws_sso(profile=None):
    """Check AWS SSO credentials and refresh if needed, using ``profile`` if given."""
    try:
        expiration = aws_credential_expiration(profile)
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
        cmd = ["aws", "sso", "login"]
        if profile:
            cmd.extend(["--profile", profile])
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as login_error:
            raise RuntimeError(
                "Unable to refresh AWS SSO credentials. Run 'aws configure sso' "
                "if this profile is not configured, then retry."
            ) from login_error


def refresh_codex(path):
    """Ensure the Codex auth file holds a currently valid access token.

    ``codex login status`` reports success when an auth.json exists but doesn't
    (currently) check expiration. So here we check the JWT expiration directly
    to be sure.
    """
    try:
        auth = json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        auth = {}

    # No refresh token, so defer to codex login
    if not auth.get("tokens", {}).get("refresh_token"):
        LOGGER.warning("Codex: no refresh token in %s, running codex login...", path)
        subprocess.run(["codex", "login"], check=True)
        return

    access = auth.get("tokens", {}).get("access_token")
    claims = decode_jwt_payload(access) if access else None
    exp = claims.get("exp") if claims else None
    expiry = datetime.fromtimestamp(exp, timezone.utc) if exp else None
    if expiry and expiry - datetime.now(timezone.utc) > CODEX_REFRESH_WINDOW:
        LOGGER.info("Codex: access token valid until %s", expiry)
        return

    LOGGER.info("Codex: access token expires at %s, refreshing...", expiry)
    # This uses Python directly
    try:
        auth = refresh_codex_tokens(path)
    except urllib.error.HTTPError as error:
        if error.code not in (400, 401, 403):
            raise
        body = error.read().decode("utf-8", "replace")
        LOGGER.warning(
            "Codex: refresh token rejected (%s): %s; running codex login...",
            error.code,
            body,
        )
        subprocess.run(["codex", "login"], check=True)
        return

    access = auth.get("tokens", {}).get("access_token")
    claims = decode_jwt_payload(access) if access else None
    exp = claims.get("exp") if claims else None
    expiry = datetime.fromtimestamp(exp, timezone.utc) if exp else None
    LOGGER.info("Codex: refreshed, now valid until %s", expiry)


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


def refresh_codex_tokens(path):
    """Refresh Codex OAuth tokens and save them to ``path``.

    A refresh token can be used only once, so make sure we get its replacement
    from the response.
    """
    auth = json.loads(path.read_text())
    request = urllib.request.Request(
        CODEX_TOKEN_URL,
        data=json.dumps(
            {
                "client_id": CODEX_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": auth["tokens"]["refresh_token"],
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())

    for field in ("id_token", "access_token", "refresh_token"):
        if payload.get(field):
            auth["tokens"][field] = payload[field]
    auth["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    write_private_text(path, json.dumps(auth, indent=2) + "\n")
    return auth


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
            raise ValueError(
                f"Existing Pi auth.json must contain a JSON object: {dest}"
            )

    pi_data["openai-codex"] = {
        "type": "oauth",
        "access": access,
        "refresh": refresh,
        "expires": expires,
    }
    if account_id:
        pi_data["openai-codex"]["accountId"] = account_id

    write_private_text(dest, json.dumps(pi_data, indent=2) + "\n")


def aws_credential_expiration(profile=None):
    """Return the AWS credential expiration string from the AWS CLI."""
    cmd = ["aws", "configure", "export-credentials"]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    creds = json.loads(result.stdout)
    return creds.get("Expiration")


def validate_aws_process_credentials(
    creds,
    now=None,
):
    """Validate AWS process-provider credentials returned by the AWS CLI."""
    if not isinstance(creds, dict):
        raise ValueError("AWS credential export must be a JSON object")
    if type(creds.get("Version")) is not int or creds["Version"] != 1:
        raise ValueError("AWS credential export has an unsupported Version")
    for field in ("AccessKeyId", "SecretAccessKey", "SessionToken"):
        value = creds.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"AWS credential export requires a non-empty {field}")

    expiration = creds.get("Expiration")
    if not isinstance(expiration, str) or not expiration.strip():
        raise ValueError("AWS credential export requires Expiration")
    try:
        expires_at = parse_timestamp(expiration)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "AWS credential export Expiration must be a timezone-aware timestamp"
        ) from exc
    if expires_at <= (now or datetime.now(timezone.utc)):
        raise ValueError("AWS credential export is expired")
    return creds


def export_aws_profile(profile=None):
    """Export AWS credentials as JSON and configure the llm-export profile.

    ``profile`` is the *source* profile to read credentials from; the
    destination profile is always the managed ``llm-export`` one.
    """

    # Capture the credentails with the AWS CLI, dump to json that we can mount
    # inside container
    cmd = ["aws", "configure", "export-credentials", "--format", "process"]
    if profile:
        cmd.extend(["--profile", profile])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    creds = validate_aws_process_credentials(json.loads(result.stdout))

    aws_root = AWS_MANAGED_BUNDLE_DIR.parent
    aws_root_existed = aws_root.exists()
    aws_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not aws_root_existed:
        os.chmod(aws_root, 0o700)

    write_private_text(AWS_CREDENTIALS_JSON, json.dumps(creds, indent=2) + "\n")
    write_private_text(AWS_CONFIG_PATH, MANAGED_AWS_CONFIG)
    LOGGER.info(
        "Exported AWS credentials from source profile %s to %s",
        profile or "(AWS CLI default)",
        AWS_CREDENTIALS_JSON,
    )
    LOGGER.info(
        "Configured credential_process in %s [profile %s]",
        AWS_CONFIG_PATH,
        AWS_EXPORT_PROFILE,
    )


def parse_timestamp(expiration: str) -> datetime:
    """Parse an AWS credential expiration timestamp into an aware datetime."""
    normalized = expiration.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
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


class _SessionCredentialProvider:
    """
    Translate between aws-bedrock-token-generator package (which expects an
    object with .load()) and botocore, which provides credentials with
    .get_credentials()
    """

    def __init__(self, session):
        self._session = session

    def load(self):
        return self._session.get_credentials()


def bedrock_token(profile, expiry):
    """Generate a Bedrock bearer token, scoped to ``profile`` when resolved."""
    try:
        from aws_bedrock_token_generator import provide_token
    except ImportError as exc:
        raise RuntimeError(
            "aws-bedrock-token-generator is not installed. Install it with "
            "'pip install aws-bedrock-token-generator' or from "
            "https://github.com/aws/aws-bedrock-token-generator-python."
        ) from exc

    if not profile:
        return provide_token(expiry=expiry)

    # botocore ships with the token generator; a per-profile session keeps the
    # selected profile's credentials and region out of global os.environ.
    from botocore.session import Session

    session = Session(profile=profile)
    return provide_token(
        region=session.get_config_variable("region") or os.environ.get("AWS_REGION"),
        aws_credentials_provider=_SessionCredentialProvider(session),
        expiry=expiry,
    )


def bedrock_export_command(profile=None):
    """Return a shell command that exports a fresh Bedrock bearer token."""
    try:
        import aws_bedrock_token_generator  # noqa: F401
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

    token = bedrock_token(profile, requested_expiry)
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
        "--aws-profile",
        help=(
            "AWS source profile to read credentials from. Overrides an "
            "inherited AWS_PROFILE; without either, normal AWS CLI default "
            "profile behavior applies."
        ),
    )
    ap.add_argument(
        "--no-export-creds",
        action="store_true",
        help="Skip exporting AWS credentials into ~/.aws/llm-export",
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


def transfer_paths(kind: str, full: bool, include_aws_export: bool = True) -> list[str]:
    """Return the credential/config paths selected for a remote transfer."""
    kinds = CREDENTIAL_PATHS.keys() if kind == "all" else [kind]
    category = "full" if full else "auth"
    paths = {
        path for selected in kinds for path in CREDENTIAL_PATHS[selected][category]
    }
    if not include_aws_export:
        paths.discard("~/.aws/llm-export")
    return sorted(paths)


def main() -> int:
    args = parse_args()
    configure_logging()
    source_profile = resolve_source_profile(args.aws_profile)

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

    if args.kind in ("all", "claude", "pi", "bedrock"):
        LOGGER.info(
            "AWS source profile: %s; destination profile: %s",
            source_profile or "(AWS CLI default)",
            AWS_EXPORT_PROFILE,
        )

    if args.kind in ("all", "claude", "pi"):
        refresh_aws_sso(source_profile)
        if not args.no_export_creds:
            export_aws_profile(source_profile)
    if args.kind in ("all", "codex", "pi"):
        refresh_codex()
        update_pi_codex_auth()
    if args.kind == "bedrock":
        try:
            refresh_aws_sso(source_profile)
            print(bedrock_export_command(source_profile))
        except RuntimeError as e:
            LOGGER.error("%s", e)
            return 1
        return 0

    paths = transfer_paths(
        args.kind,
        args.full,
        include_aws_export=not args.no_export_creds,
    )

    if args.remote:
        rsync_paths(paths=paths, user=args.user, remote=args.remote)
    else:
        LOGGER.info("No --remote specified; skipping push.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
