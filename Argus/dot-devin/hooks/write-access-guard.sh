#!/usr/bin/env bash
# PreToolUse (write, edit, apply_patch, notebook_edit): refuse a file change the requester's roster
# roles do not allow. The rules are the `access:` section of .devin/rules/people.yaml;
# tools/access_guard.py applies them. Fails closed: no file path, or a checker that cannot run,
# blocks the change.
HOOK_NAME=write-access-guard
. "$(dirname "${BASH_SOURCE[0]}")/lib/content.sh"
read_tool_paths

root="$(hook_root)" || root=""
[ -n "$root" ] || hook_block 'ACCESS-BLOCK: cannot locate the repository root, so the access check cannot run.'

output="$(sdlc_python "$root/sdlc/framework/tools/access_guard.py" check "${paths[@]}" 2>&1)" && status=0 || status=$?
case "$status" in
  0) exit 0 ;;
  2) hook_block "$output" ;;
  *) hook_block "ACCESS-BLOCK: access check failed to run (exit $status). $output" ;;
esac
