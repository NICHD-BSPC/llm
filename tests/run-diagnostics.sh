#!/bin/bash
# run-diagnostics.sh - Run container diagnostics in various modes
#
# This script demonstrates different ways to test the container environment:
# 1. Shell mode (direct execution)
# 2. Codex mode (ask AI to run and report)
# 3. Claude mode (ask AI to run and report)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_PY="$REPO_DIR/launch.py"
DIAGNOSTICS_SCRIPT="$SCRIPT_DIR/container-diagnostics.sh"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

print_info() {
    echo -e "${GREEN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

usage() {
    cat <<EOF
Usage: $0 [options] <mode> [backend]

Modes:
  shell   - Run diagnostics directly in shell
  codex   - Ask Codex to run diagnostics and summarize
  claude  - Ask Claude to run diagnostics and summarize
  all     - Run all modes sequentially

Options:
  -e KEY=VALUE   Add custom environment variable (repeatable)
  -m PATH        Add custom mount (repeatable)
  --image-name NAME
                 Override podman image name passed to launch.py
  --sif-path PATH
                 Override singularity image path passed to launch.py
  --non-interactive
                 Skip confirmation prompts
  --help         Show this help

Arguments:
  backend        podman (default) or singularity

Examples:
  # Run shell diagnostics with podman
  $0 shell

  # Run Claude diagnostics with Bedrock enabled explicitly
  $0 -e CLAUDE_CODE_USE_BEDROCK=1 -e AWS_PROFILE=my-aws-profile claude podman

  # Run all diagnostics with singularity
  $0 -e CLAUDE_CODE_USE_BEDROCK=1 -e AWS_PROFILE=my-aws-profile all singularity
EOF
    exit 0
}

# Parse options
EXTRA_ARGS=()
LAUNCH_ARGS=()
NON_INTERACTIVE=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            usage
            ;;
        -e)
            EXTRA_ARGS+=(--env "$2")
            shift 2
            ;;
        -m)
            EXTRA_ARGS+=(--mount "$2")
            shift 2
            ;;
        --image-name)
            LAUNCH_ARGS+=(--image-name "$2")
            shift 2
            ;;
        --sif-path)
            LAUNCH_ARGS+=(--sif-path "$2")
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=1
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [[ $# -lt 1 ]]; then
    echo "Error: mode required"
    usage
fi

MODE="$1"
BACKEND="${2:-podman}"

wait_for_continue() {
    if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
        return
    fi
    read -r
}

run_shell_diagnostics() {
    print_header "Shell Mode: Direct Diagnostics"
    print_info "Running container-diagnostics.sh directly in shell..."
    echo ""

    python "$LAUNCH_PY" \
        --backend "$BACKEND" \
        ${LAUNCH_ARGS[@]+"${LAUNCH_ARGS[@]}"} \
        ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
        shell \
        "$DIAGNOSTICS_SCRIPT"
}

run_codex_diagnostics() {
    print_header "Codex Mode: AI-Assisted Diagnostics"
    print_warning "This will launch Codex and ask it to run diagnostics."
    print_warning "Press Ctrl-C to cancel, or Enter to continue..."
    wait_for_continue
    echo ""

    local prompt="Please run the script located at tests/container-diagnostics.sh and provide a summary of the results. Specifically report:
1. Is the container environment set up correctly?
2. Are credentials mounted properly?
3. Is the workspace writable?
4. Are there any issues or warnings?

For Codex, we expect ~/.aws and ~/.claude* to be missing, and AWS_REGION, AWS_PROFILE, and env vars starting with CLAUDE should be unset.

Please run: bash tests/container-diagnostics.sh"

    python "$LAUNCH_PY" \
        --backend "$BACKEND" \
        ${LAUNCH_ARGS[@]+"${LAUNCH_ARGS[@]}"} \
        ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
        codex \
        exec --sandbox danger-full-access "$prompt"
}

run_claude_diagnostics() {
    print_header "Claude Mode: AI-Assisted Diagnostics"

    print_warning "This will launch Claude and ask it to run diagnostics."
    print_warning "Press Ctrl-C to cancel, or Enter to continue..."
    wait_for_continue
    echo ""

    local prompt="Please run the script located at tests/container-diagnostics.sh and provide a summary of the results. Specifically report:
1. Is the container environment set up correctly?
2. Are credentials mounted properly?
3. Is the workspace writable?
4. Are there any issues or warnings?

For Claude, we expect ~/.codex to be missing.

Please run: bash tests/container-diagnostics.sh"

    python "$LAUNCH_PY" \
        --backend "$BACKEND" \
        ${LAUNCH_ARGS[@]+"${LAUNCH_ARGS[@]}"} \
        ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
        claude --allowedTools 'Bash()' \
        -p "$prompt"
}

case "$MODE" in
    shell)
        run_shell_diagnostics
        ;;
    codex)
        run_codex_diagnostics
        ;;
    claude)
        run_claude_diagnostics
        ;;
    all)
        run_shell_diagnostics
        echo ""
        print_info "Shell diagnostics complete. Press Enter to continue to Codex..."
        wait_for_continue
        run_codex_diagnostics
        echo ""
        print_info "Codex diagnostics complete. Press Enter to continue to Claude..."
        wait_for_continue
        run_claude_diagnostics
        ;;
    *)
        echo "Error: Unknown mode '$MODE'"
        usage
        ;;
esac

print_header "Diagnostics Complete"
