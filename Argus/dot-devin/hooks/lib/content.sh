# Shared by the hook scripts. Source it, then call read_tool_content, read_tool_paths or
# read_prompt.
#
# Devin passes the event as JSON on stdin (lib/hook_input.py reads it; DEVIN_TOOL_CONTENT,
# DEVIN_TOOL_FILE_PATH and DEVIN_USER_PROMPT are the fallback when stdin is empty). A hook
# blocks with exit 2 and the reason on stderr; Devin treats any other non-zero exit as a hook
# error and lets the action through, so every failure path here exits 2 (fail closed),
# including any unexpected error, via the ERR trap.

set -u -o pipefail
trap 'printf "HOOK-BLOCK: %s hit an unexpected error (line %s); action blocked (hooks fail closed).\n" "${HOOK_NAME:-hook}" "$LINENO" >&2; exit 2' ERR

HOOK_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HOOK_LIB/python.sh"
hook_event=""
if [ ! -t 0 ]; then
  hook_event="$(cat)"
fi

hook_block() {
  printf '%s\n' "$1" >&2
  exit 2
}

# hook_field <paths|content|prompt>: prints the field; returns 3 when the event lacks it.
hook_field() {
  local out status
  out="$(printf '%s' "$hook_event" | sdlc_python "$HOOK_LIB/hook_input.py" "$1")" && status=0 || status=$?
  case "$status" in
    0) printf '%s' "$out"; return 0 ;;
    3) return 3 ;;
    *) hook_block "HOOK-BLOCK: ${HOOK_NAME:-hook} could not read the hook event (exit $status). Action blocked — hooks fail closed." ;;
  esac
}

hook_root() {
  if [ -n "${DEVIN_PROJECT_DIR:-}" ] && [ -d "$DEVIN_PROJECT_DIR" ]; then
    printf '%s' "$DEVIN_PROJECT_DIR"
    return 0
  fi
  git rev-parse --show-toplevel 2>/dev/null
}

# Sets $content to the text about to be written. With no text in the event, reads the file
# at the event's path; with neither, blocks.
read_tool_content() {
  local status first
  content="$(hook_field content)" && status=0 || status=$?
  [ "$status" -eq 0 ] && return 0
  [ "$status" -eq 3 ] || exit 2
  first="$(hook_field paths | head -n 1)" || first=""
  if [ -n "$first" ] && [ -r "$first" ]; then
    content="$(cat -- "$first")"
    return 0
  fi
  hook_block "HOOK-BLOCK: ${HOOK_NAME:-hook} received no content to inspect (no text in the tool call, no readable file path). Action blocked — hooks fail closed."
}

# Sets the array $paths to the files the tool call will change; blocks when there are none.
read_tool_paths() {
  local list line status
  list="$(hook_field paths)" && status=0 || status=$?
  [ "$status" -eq 0 ] || [ "$status" -eq 3 ] || exit 2
  if [ "$status" -ne 0 ] || [ -z "$list" ]; then
    hook_block "ACCESS-BLOCK: ${HOOK_NAME:-hook} received no file path to check. Action blocked — hooks fail closed."
  fi
  paths=()
  while IFS= read -r line; do
    [ -n "$line" ] && paths+=("$line")
  done <<< "$list"
}

# Sets $prompt to the user's message ("" when the event carries none).
read_prompt() {
  local status
  prompt="$(hook_field prompt)" && status=0 || status=$?
  case "$status" in
    0) ;;
    3) prompt="" ;;
    *) exit 2 ;;
  esac
}
