#!/bin/bash

# Read in stdin all in one shot so we can re-use it below
input=$(cat)

# Uncomment the following to write a JSON file in Claude's working directory 
# that can be used to inspect the JSON payload for further customization.

# echo "$input" >  "$(dirname $(readlink -f "$0"))/status.log"

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
GRAY='\033[38;5;252m'
RESET='\033[0m'

MODEL=$(echo "$input" | jq -r '.model.display_name')
DIR=$(echo "$input" | jq -r '.workspace.current_dir')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
COST_FMT=$(printf '$%.2f' "$COST")
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
DURATION_MS=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
MINS=$((DURATION_MS / 60000)); SECS=$(((DURATION_MS % 60000) / 1000))
INPUT=$(echo "$input" | jq -r '.context_window.current_usage.input_tokens')
OUTPUT=$(echo "$input" | jq -r '.context_window.current_usage.output_tokens')
CACHE_READ=$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens')
CACHE_WRITE=$(echo "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens')
TRANSCRIPT_PATH=$(echo "$input" | jq -r '.transcript_path')

echo -e "[$MODEL] ${CYAN}${DIR}${RESET} | P:${PCT}% | I:${INPUT} | O:${OUTPUT} | R:${CACHE_READ} | W:${CACHE_WRITE} | ${YELLOW}${COST_FMT}${RESET} | ${MINS}m ${SECS}s"
echo -e "${GRAY}${TRANSCRIPT_PATH}${RESET}"
