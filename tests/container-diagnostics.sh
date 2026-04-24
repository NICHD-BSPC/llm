#!/bin/bash
# container-diagnostics.sh - Diagnostic script to run inside container
#
# This script checks various aspects of the container environment
# and reports back with structured output.

set -euo pipefail

echo "========================================="
echo "Container Diagnostics Report"
echo "========================================="
echo ""

# 1. User Information
echo "--- User Information ---"
echo "USER: $USER"
echo "HOME: $HOME"
echo "UID: $(id -u)"
echo "GID: $(id -g)"
echo "Groups: $(id -Gn)"
echo ""

# 2. Working Directory
echo "--- Working Directory ---"
echo "PWD: $PWD"
echo "HOST_MOUNT_DIR: ${HOST_MOUNT_DIR:-NOT_SET}"
echo ""

# 3. Environment Variables
echo "--- Environment Variables ---"
echo "TOOL: ${TOOL:-NOT_SET}"
echo "AWS_REGION: ${AWS_REGION:-NOT_SET}"
echo "AWS_PROFILE: ${AWS_PROFILE:-NOT_SET}"
echo "CLAUDE_CODE_USE_BEDROCK: ${CLAUDE_CODE_USE_BEDROCK:-NOT_SET}"
echo "PATH: $PATH"
echo ""

# 4. Credential Paths
echo "--- Credential Paths ---"
if [ -d ~/.codex ]; then
    echo "✓ ~/.codex exists"
    [ -f ~/.codex/auth.json ] && echo "  ✓ auth.json found" || echo "  ✗ auth.json NOT found"
else
    echo "✗ ~/.codex does not exist"
fi

if [ -d ~/.claude ]; then
    echo "✓ ~/.claude exists"
    [ -f ~/.claude/settings.json ] && echo "  ✓ settings.json found" || echo "  ✗ settings.json NOT found"
else
    echo "✗ ~/.claude does not exist"
fi

if [ -f ~/.claude.json ]; then
    echo "✓ ~/.claude.json exists"
else
    echo "✗ ~/.claude.json does not exist"
fi

if [ -d ~/.aws ]; then
    echo "✓ ~/.aws exists"
    [ -f ~/.aws/config ] && echo "  ✓ config found" || echo "  ✗ config NOT found"
    [ -d ~/.aws/sso/cache ] && echo "  ✓ sso/cache found" || echo "  ✗ sso/cache NOT found"
else
    echo "✗ ~/.aws does not exist"
fi
echo ""

# 5. Workspace Access
echo "--- Workspace Access ---"
if [ -w "$PWD" ]; then
    echo "✓ Current directory is writable"
    # Try creating a test file
    test_file=".container-test-$$"
    if echo "test" > "$test_file" 2>/dev/null; then
        echo "✓ Successfully created test file: $test_file"
        rm -f "$test_file"
    else
        echo "✗ Failed to create test file"
    fi
else
    echo "✗ Current directory is NOT writable"
fi
echo ""

# 6. PATH Components
echo "--- PATH Components ---"
IFS=':' read -ra PATH_PARTS <<< "$PATH"
for path in "${PATH_PARTS[@]}"; do
    if [ -d "$path" ]; then
        echo "✓ $path (exists)"
    else
        echo "✗ $path (missing)"
    fi
done
echo ""

# 7. Custom Environment Variables (any TEST_* vars)
echo "--- Custom Test Variables ---"
env | grep "^TEST_" || echo "(none set)"
echo ""

# 8. Container Info
echo "--- Container Info ---"
if [ -f /etc/os-release ]; then
    echo "OS: $(grep PRETTY_NAME /etc/os-release | cut -d'"' -f2)"
fi
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo ""

# 9. Available Commands
echo "--- Available Commands ---"
for cmd in python python3 git bash node npm pi; do
    if command -v $cmd &> /dev/null; then
        version=$($cmd --version 2>&1 | head -1 || echo "unknown")
        echo "✓ $cmd: $version"
    else
        echo "✗ $cmd: not found"
    fi
done
echo ""

# 10. File Listing (current directory sample)
echo "--- Current Directory Sample (first 10 files) ---"
ls -la | head -11
echo ""

echo "========================================="
echo "End of Diagnostics"
echo "========================================="
