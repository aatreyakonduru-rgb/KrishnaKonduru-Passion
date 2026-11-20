#!/usr/bin/env bash
# SessionStart: tell the agent where it is running (Devin Cloud or Devin Local) and what that changes.
# Informational only: any failure exits 0 so a session is never refused because detection broke.
# Local (CLI and Desktop) waits for this hook; Cloud runs it in the background and the agent has the
# text from its next turn.
set -u -o pipefail
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
. "$lib/python.sh"
root="${DEVIN_PROJECT_DIR:-}"
if [ -z "$root" ] || [ ! -d "$root" ]; then
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
fi
tool="$root/sdlc/framework/tools/runtime_env.py"
[ -f "$tool" ] || exit 0
sdlc_python "$tool" hook 2>/dev/null </dev/null || exit 0
exit 0
