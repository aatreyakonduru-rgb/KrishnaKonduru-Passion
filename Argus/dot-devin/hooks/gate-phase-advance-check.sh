#!/usr/bin/env bash
# UserPromptSubmit: refuse to start a stage whose opening gate is not approved.
# Fails closed: if the prompt starts a stage and the check itself cannot run, the prompt is blocked.
HOOK_NAME=gate-phase-advance-check
. "$(dirname "${BASH_SOURCE[0]}")/lib/content.sh"
read_prompt

stage_re='(research|/plan|/implement|/pr-readiness|/eval|/release|/kb-refresh|gap analysis|generate stories|routing map|insertion points?)'
if ! printf '%s' "$prompt" | grep -Eiq "$stage_re"; then
  exit 0
fi

root="$(hook_root)" || root=""
[ -n "$root" ] || hook_block 'GATE-BLOCK: cannot locate the repository root, so the gate check cannot run.'

# Older callers/tests export SDLC_SESSION_ROOT; session_store.py reads SDLC_SESSION_HOME.
if [ -n "${SDLC_SESSION_ROOT:-}" ] && [ -z "${SDLC_SESSION_HOME:-}" ]; then
  export SDLC_SESSION_HOME="$SDLC_SESSION_ROOT"
fi

output="$(sdlc_python "$root/sdlc/framework/tools/gates.py" precheck "$prompt" 2>&1)" && status=0 || status=$?
case "$status" in
  0) exit 0 ;;
  2) hook_block "$output" ;;
  *) hook_block "GATE-BLOCK: gate check failed to run (exit $status). $output" ;;
esac
