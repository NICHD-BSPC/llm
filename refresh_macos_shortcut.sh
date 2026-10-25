#!/bin/bash
#
# Refresh LLM credentials on $HOST by running refresh.py, which may pop up
# browser logins (AWS SSO, Codex).
#
# Meant to be launched from macOS Shortcuts' "Run Shell Script" so that you get
# notifications.
#
# Set these in the environment used by Shortcuts before running this script.
# This could be directly in the Shortcut, or in file that is sourced by the
# shortcut.
HOST=${LLM_REMOTE_HOST:?Set LLM_REMOTE_HOST to the remote host}
RUSER=${LLM_REMOTE_USER:-$USER}
SCRIPT=${LLM_REFRESH_SCRIPT:?Set LLM_REFRESH_SCRIPT to the refresh.py path}

LOG="$HOME/Library/Logs/llm-refresh.log" # Logs go here to show if any problems

# Set up the log first so everything after this can report into it.
mkdir -p "$(dirname "$LOG")"
: >"$LOG"

# From here on out, stderr goes to the log
exec 2>>"$LOG"

echo "=== $(date) ===" >>"$LOG"

# Line count after this run's header. Used below to find this run's output.
start=$(wc -l <"$LOG")

# Use the login ssh-agent socket. Only fall back to launchd if it's actually
# set there; exporting an empty SSH_AUTH_SOCK is worse than leaving it unset.
if [[ -z $SSH_AUTH_SOCK ]]; then
  sock=$(launchctl getenv SSH_AUTH_SOCK)
  [[ -n $sock ]] && export SSH_AUTH_SOCK=$sock
fi

# GUI notification. $1 is title, $2 is body. Passes them as `run` arguments to
# avoid quotes or backslashes breaking the AppleScript.
notify() {
  osascript -e 'on run a' -e 'display notification (item 2 of a) with title (item 1 of a)' -e 'end run' "$1" "$2"
  echo "$1" >>"$LOG"
  echo "$2" >>"$LOG"
}

# Load the key into the agent using the passphrase saved in your login keychain
if ! ssh-add --apple-load-keychain -q; then
  echo "warning: ssh-add failed; rsync to $HOST will probably fail" >&2
fi

notify "llm refresh" "Running...a browser may open for login"

# Run it, saving each line to the log and react to login prompts as they happen.
# Notes:
#   - python3 -u = unbuffered output for immediate feedback
#   - </dev/null: there's no terminal, so anything that tries to prompt
#     (y/n, "press Enter") fails immediately and shows up in the log, instead
#     of hanging on Shortcuts' stdin.
#   - `|| [[ -n $line ]]`: read returns false on a final line with no trailing
#     newline, which would otherwise be dropped
#   - tee writes to the log and to stdout (which Shortcuts captures).
#   - --notification-events emits stable, flushed event lines before logins.
#   - The while loop runs in a subshell, so variables set inside it are lost
#     after `done`. That's why the last line is recovered from the log below
#     instead of being tracked here.
python3 -u "$SCRIPT" --remote "$HOST" --user "$RUSER" --notification-events </dev/null 2>&1 |
  while IFS= read -r line || [[ -n $line ]]; do
    printf '%s\n' "$line" | tee -a "$LOG"
    case $line in
    LLM_REFRESH_EVENT:aws_sso_login) notify "llm refresh: AWS SSO" "Finish login in your browser…" ;;
    LLM_REFRESH_EVENT:codex_login) notify "llm refresh: Codex" "Finish login in your browser…" ;;
    esac
  done

# Python's exit status. $? is the while loop's (almost always 0) which is
# unhelpful.
rc=${PIPESTATUS[0]}

# Last non-empty line of this run's output, for the failure notification.
last=$(tail -n +"$((start + 1))" "$LOG" | grep -v '^[[:space:]]*$' | tail -n 1)
echo "exit: $rc" >>"$LOG"

if ((rc == 0)); then
  notify "llm refresh --remote" "Credentials pushed to $HOST"
elif ((rc == 75)); then
  # refresh.py's EXIT_PUSH_FAILED: logins worked, only the rsync failed.
  # Somewhat common (e.g., if not on VPN) so don't show the Console window with
  # the log in this case.
  notify "llm refresh: not pushed" "Refreshed locally; couldn't reach $HOST"
else
  notify "llm refresh ✗ exit $rc" "${last:-no output}"
  open -a Console "$LOG" # show the full log on failure
fi
exit 0 # Shortcuts stops on a non-zero exit, so finish cleanly
