#!/usr/bin/env bash
# PreToolUse (exec, Bash): refuse a shell command that skips or switches off the git hooks
# (--no-verify, git commit -n, core.hooksPath) or writes the hook files or the access guard's own
# records by hand (tools/access_guard.py shell-check). Unlike the file guards it fails open: a broken
# check would stop every shell command, and the git hooks still run at commit time.
set -u -o pipefail
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
. "$lib/python.sh"
event=""
[ -t 0 ] || event="$(cat)"
cmd="$(printf '%s' "$event" | sdlc_python "$lib/hook_input.py" command 2>/dev/null)" || exit 0
[ -n "$cmd" ] || exit 0
root="${DEVIN_PROJECT_DIR:-}"
if [ -z "$root" ] || [ ! -d "$root" ]; then
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
fi
guard="$root/sdlc/framework/tools/access_guard.py"
[ -f "$guard" ] || exit 0
output="$(printf '%s' "$cmd" | sdlc_python "$guard" shell-check 2>&1)" && status=0 || status=$?
if [ "$status" -eq 2 ]; then
  printf '%s\n' "$output" >&2
  exit 2
fi
exit 0
