#!/usr/bin/env bash
set -uo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$root" ]; then
  printf '%s\n' 'FAIL: could not determine repository root'
  exit 1
fi

hook_dir="$root/.devin/hooks"
fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT

failures=0
real_py="$(command -v python3)"

run_case() {
  name="$1"
  expected_status="$2"
  expected_text="$3"
  shift 3

  output="$("$@" 2>&1 </dev/null)"
  status=$?
  check_case "$name" "$expected_status" "$expected_text"
}

# run_event <name> <expected exit> <expected text> <event JSON> <command...>: the event goes on stdin,
# as Devin sends it.
run_event() {
  name="$1"
  expected_status="$2"
  expected_text="$3"
  event="$4"
  shift 4
  output="$(printf '%s' "$event" | "$@" 2>&1)"
  status=$?
  check_case "$name" "$expected_status" "$expected_text"
}

check_case() {
  name="$1"
  expected_status="$2"
  expected_text="$3"
  if [ "$status" -ne "$expected_status" ]; then
    printf 'FAIL: %s (expected exit %s, got %s)\n' "$name" "$expected_status" "$status"
    failures=$((failures + 1))
    return
  fi
  if [ -n "$expected_text" ] && ! printf '%s' "$output" | grep -Fq -- "$expected_text"; then
    printf 'FAIL: %s (expected output missing)\n' "$name"
    failures=$((failures + 1))
    return
  fi
  printf 'PASS: %s\n' "$name"
}

run_case 'pii SSN' 2 'HOOK-BLOCK: Potential PII detected' \
  env DEVIN_TOOL_CONTENT='SSN 123-45-6789' bash "$hook_dir/pii-guard.sh"
run_case 'pii DOB' 2 'HOOK-BLOCK: Potential PII detected' \
  env DEVIN_TOOL_CONTENT='DOB: 1970-01-01' bash "$hook_dir/pii-guard.sh"
run_case 'pii member ID' 2 'HOOK-BLOCK: Potential PII detected' \
  env DEVIN_TOOL_CONTENT='MBR_ID = 123456789' bash "$hook_dir/pii-guard.sh"
run_case 'pii lowercase dob is allowed' 0 '' \
  env DEVIN_TOOL_CONTENT='dob: 1970-01-01' bash "$hook_dir/pii-guard.sh"
run_case 'pii benign prose' 0 '' \
  env DEVIN_TOOL_CONTENT='This is ordinary documentation.' bash "$hook_dir/pii-guard.sh"
run_case 'pii unset content fails closed' 2 'hooks fail closed' \
  env -u DEVIN_TOOL_CONTENT -u DEVIN_TOOL_FILE_PATH bash "$hook_dir/pii-guard.sh"
printf 'SSN 123-45-6789\n' > "$fixture_root/pii.txt"
run_case 'pii falls back to file path' 2 'HOOK-BLOCK: Potential PII detected' \
  env -u DEVIN_TOOL_CONTENT DEVIN_TOOL_FILE_PATH="$fixture_root/pii.txt" bash "$hook_dir/pii-guard.sh"
run_case 'pii unreadable file path fails closed' 2 'hooks fail closed' \
  env -u DEVIN_TOOL_CONTENT DEVIN_TOOL_FILE_PATH="$fixture_root/does-not-exist.txt" bash "$hook_dir/pii-guard.sh"

run_case 'secret AWS key' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  env DEVIN_TOOL_CONTENT='AKIAIOSFODNN7EXAMPLE' bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret password' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  env DEVIN_TOOL_CONTENT='password = hunter2xyz' bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret uppercase password' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  env DEVIN_TOOL_CONTENT='PASSWORD: hunter2xyz' bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret API key' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  env DEVIN_TOOL_CONTENT='api_key: abcdefghijklmnop1234' bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret benign prose' 0 '' \
  env DEVIN_TOOL_CONTENT='This is ordinary documentation.' bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret unset content fails closed' 2 'hooks fail closed' \
  env -u DEVIN_TOOL_CONTENT -u DEVIN_TOOL_FILE_PATH bash "$hook_dir/no-hardcoded-secrets.sh"
run_case 'secret empty content is allowed' 0 '' \
  env DEVIN_TOOL_CONTENT='' bash "$hook_dir/no-hardcoded-secrets.sh"

mkdir -p "$fixture_root/guardbin"
cat > "$fixture_root/guardbin/python3" <<STUB
#!/usr/bin/env bash
case "\$*" in
  *hook_input.py*) exec "$real_py" "\$@" ;;
  *"check allowed.md blocked.md") echo 'ACCESS-BLOCK: Resource 1 (developer) may not change blocked.md'; exit 2 ;;
  *"check allowed.md") exit 0 ;;
  *"check blocked.md") echo 'ACCESS-BLOCK: Resource 1 (developer) may not change blocked.md'; exit 2 ;;
  *) echo boom >&2; exit 9 ;;
esac
STUB
chmod +x "$fixture_root/guardbin/python3"
run_case 'access guard allows' 0 '' \
  env PATH="$fixture_root/guardbin:$PATH" DEVIN_TOOL_FILE_PATH='allowed.md' bash "$hook_dir/write-access-guard.sh"
run_case 'access guard blocks' 2 'ACCESS-BLOCK: Resource 1 (developer) may not change blocked.md' \
  env PATH="$fixture_root/guardbin:$PATH" DEVIN_TOOL_FILE_PATH='blocked.md' bash "$hook_dir/write-access-guard.sh"
run_case 'access guard fails closed when the checker crashes' 2 'ACCESS-BLOCK: access check failed to run' \
  env PATH="$fixture_root/guardbin:$PATH" DEVIN_TOOL_FILE_PATH='other.md' bash "$hook_dir/write-access-guard.sh"
run_case 'access guard fails closed without a path' 2 'received no file path' \
  env -u DEVIN_TOOL_FILE_PATH bash "$hook_dir/write-access-guard.sh"

# Windows: python3 is often only the Microsoft Store alias (in WindowsApps), which fails; the hooks use python.
mkdir -p "$fixture_root/WindowsApps" "$fixture_root/winbin"
printf '#!/usr/bin/env bash\necho "Python was not found" >&2\nexit 49\n' > "$fixture_root/WindowsApps/python3"
chmod +x "$fixture_root/WindowsApps/python3"
ln -sf "$real_py" "$fixture_root/winbin/python"
run_event 'windows: Store python3 alias is skipped' 2 'HOOK-BLOCK: Potential PII detected' \
  '{"tool_name":"write","tool_input":{"file_path":"notes.md","content":"SSN 123-45-6789"}}' \
  env PATH="$fixture_root/WindowsApps:$fixture_root/winbin:$PATH" bash "$hook_dir/pii-guard.sh"

# Events on stdin, in the shape Devin (and Claude Code) send them.
run_event 'event: write with PII' 2 'HOOK-BLOCK: Potential PII detected' \
  '{"tool_name":"write","tool_input":{"file_path":"notes.md","content":"SSN 123-45-6789"}}' bash "$hook_dir/pii-guard.sh"
run_event 'event: edit with a password' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  '{"tool_name":"edit","tool_input":{"file_path":"app.py","old_string":"x","new_string":"password = hunter2xyz"}}' bash "$hook_dir/no-hardcoded-secrets.sh"
run_event 'event: benign edit is allowed' 0 '' \
  '{"tool_name":"edit","tool_input":{"file_path":"app.py","old_string":"x","new_string":"y = 1"}}' bash "$hook_dir/no-hardcoded-secrets.sh"
run_event 'event: edit that deletes text is allowed' 0 '' \
  '{"tool_name":"edit","tool_input":{"file_path":"app.py","old_string":"x","new_string":""}}' bash "$hook_dir/pii-guard.sh"
run_event 'event: Claude Code MultiEdit with an AWS key' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  '{"tool_name":"MultiEdit","tool_input":{"file_path":"a.py","edits":[{"old_string":"a","new_string":"k = AKIAIOSFODNN7EXAMPLE"}]}}' bash "$hook_dir/no-hardcoded-secrets.sh"
run_event 'event: apply_patch adding a password' 2 'HOOK-BLOCK: Potential hardcoded secret detected' \
  '{"tool_name":"apply_patch","tool_input":{"patch":"*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+password = hunter2xyz\n*** End Patch"}}' bash "$hook_dir/no-hardcoded-secrets.sh"
run_event 'event: apply_patch removing a password is allowed' 0 '' \
  '{"tool_name":"apply_patch","tool_input":{"patch":"*** Begin Patch\n*** Update File: app.py\n@@\n-password = hunter2xyz\n+x = 1\n*** End Patch"}}' bash "$hook_dir/no-hardcoded-secrets.sh"
run_event 'event: unreadable event fails closed' 2 'could not read the hook event' \
  'not json' bash "$hook_dir/pii-guard.sh"
run_event 'event: edit allowed by the access guard' 0 '' \
  '{"tool_name":"edit","tool_input":{"file_path":"allowed.md","old_string":"a","new_string":"b"}}' \
  env PATH="$fixture_root/guardbin:$PATH" bash "$hook_dir/write-access-guard.sh"
run_event 'event: edit blocked by the access guard' 2 'ACCESS-BLOCK: Resource 1 (developer) may not change blocked.md' \
  '{"tool_name":"edit","tool_input":{"file_path":"blocked.md","old_string":"a","new_string":"b"}}' \
  env PATH="$fixture_root/guardbin:$PATH" bash "$hook_dir/write-access-guard.sh"
run_event 'event: apply_patch checks every file it touches' 2 'may not change blocked.md' \
  '{"tool_name":"apply_patch","tool_input":{"patch":"*** Begin Patch\n*** Update File: allowed.md\n+a\n*** Add File: blocked.md\n+b\n*** End Patch"}}' \
  env PATH="$fixture_root/guardbin:$PATH" bash "$hook_dir/write-access-guard.sh"
run_event 'event: file tool without a path fails closed' 2 'received no file path' \
  '{"tool_name":"edit","tool_input":{"new_string":"b"}}' bash "$hook_dir/write-access-guard.sh"
run_event 'event: unreadable event blocks the access guard' 2 'could not read the hook event' \
  '{' bash "$hook_dir/write-access-guard.sh"

run_event 'shell guard refuses git commit --no-verify' 2 'ACCESS-BLOCK: the command skips or redirects the git hooks' \
  '{"tool_name":"exec","tool_input":{"command":"git commit --no-verify -m x"}}' bash "$hook_dir/shell-bypass-guard.sh"
run_event 'shell guard refuses a hand-written requester' 2 'ACCESS-BLOCK: the command changes the git hooks' \
  '{"tool_name":"exec","tool_input":{"command":"echo {} > ~/.sdlc/requester.json"}}' bash "$hook_dir/shell-bypass-guard.sh"
run_event 'shell guard allows an ordinary commit' 0 '' \
  '{"tool_name":"exec","tool_input":{"command":"git commit -m x"}}' bash "$hook_dir/shell-bypass-guard.sh"
run_case 'shell guard reads DEVIN_TOOL_COMMAND' 2 'git commit -n skips the git hooks' \
  env DEVIN_TOOL_COMMAND='git commit -n -m x' bash "$hook_dir/shell-bypass-guard.sh"
run_case 'shell guard fails open without a command' 0 '' \
  env -u DEVIN_TOOL_COMMAND bash "$hook_dir/shell-bypass-guard.sh"

session_root="$fixture_root/session"
owner='test-owner'
mkdir -p "$session_root"
run_case 'gate owner directory absent' 0 '' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='please start research' \
  bash "$hook_dir/gate-phase-advance-check.sh"

mkdir -p "$session_root/$owner/REQ-999"
cat > "$session_root/$owner/REQ-999/approvals.yaml" <<'YAML'
requirement_id: "REQ-999"
mode: "bottom_up"
created: "2026-01-01T00:00:00Z"
owner: "test-owner"
owner_email: "test-owner@acme.example"
devin_session_url: "~"
created_on_branch: "test"

phases:
  intake:
    status: pending
    gate: SDLC_01_INTAKE_CLARIFICATION
    artifacts:
      - "REQ-999-SPEC.md"
    signed_by: ~
    signed_at: ~
    notes: ~
    gate_id: SDLC_01_INTAKE_CLARIFICATION
    requirement_id: "REQ-999"
    story_id: ~
    approver_name: ~
    approver_role: ~
    decision: ~
    timestamp: ~
    rationale: ~
    artifacts_reviewed: []
    next_gate: SDLC_02_GAP_ANALYSIS_REVIEW
    role_mismatch: false
YAML
run_case 'gate pending intake blocks research' 2 'GATE-BLOCK: research needs SDLC_01_INTAKE_CLARIFICATION approved for REQ-999' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='please start research' \
  bash "$hook_dir/gate-phase-advance-check.sh"
run_case 'gate unrelated prompt passes' 0 '' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='hello there' \
  bash "$hook_dir/gate-phase-advance-check.sh"
sed -i 's/status: pending/status: approved/' "$session_root/$owner/REQ-999/approvals.yaml"
run_case 'gate hand-edited approval still blocks research' 2 'GATE-BLOCK: research needs SDLC_01_INTAKE_CLARIFICATION approved for REQ-999' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='please start research' \
  bash "$hook_dir/gate-phase-advance-check.sh"
python3 - "$session_root/$owner/REQ-999/approvals.yaml" "$root/sdlc/framework/tools" <<'PY'
import sys, yaml
path = sys.argv[1]
sys.path.insert(0, sys.argv[2])
import gates
gate = gates.gate_defs()["SDLC_01_INTAKE_CLARIFICATION"]
by = next(p["name"] for p in gates.people() if gates.holds_role(p, gate))
with open(path) as fh:
    data = yaml.safe_load(fh)
data["phases"]["intake"].update({"status": "approved", "signed_by": by, "signed_at": "2026-01-01T00:00:00Z",
                                 "decision_items": [{"n": 1, "text": "The artifacts as written", "state": "approved",
                                                     "by": by}]})
with open(path, "w") as fh:
    yaml.safe_dump(data, fh, sort_keys=False)
PY
run_case 'gate approved intake passes research' 0 '' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='please start research' \
  bash "$hook_dir/gate-phase-advance-check.sh"
rm -rf "$session_root/$owner"
mkdir -p "$session_root/other-owner/REQ-998"
cat > "$session_root/other-owner/REQ-998/approvals.yaml" <<'YAML'
requirement_id: "REQ-998"
mode: "bottom_up"
created: "2026-01-01T00:00:00Z"
owner: "other-owner"
owner_email: "other-owner@acme.example"
devin_session_url: "~"
created_on_branch: "test"

phases:
  intake:
    status: pending
    gate: SDLC_01_INTAKE_CLARIFICATION
    artifacts:
      - "REQ-998-SPEC.md"
    signed_by: ~
    signed_at: ~
    notes: ~
    gate_id: SDLC_01_INTAKE_CLARIFICATION
    requirement_id: "REQ-998"
    story_id: ~
    approver_name: ~
    approver_role: ~
    decision: ~
    timestamp: ~
    rationale: ~
    artifacts_reviewed: []
    next_gate: SDLC_02_GAP_ANALYSIS_REVIEW
    role_mismatch: false
YAML
run_case 'gate ignores another owner' 0 '' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='please start research' \
  bash "$hook_dir/gate-phase-advance-check.sh"
run_case 'gate blocks another owner REQ named explicitly' 2 'GATE-BLOCK: REQ-998 is not a session of owner test-owner' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='/research REQ-998' \
  bash "$hook_dir/gate-phase-advance-check.sh"
run_event 'event: prompt on stdin starts a gated stage' 2 'GATE-BLOCK: REQ-998 is not a session of owner test-owner' \
  '{"hook_event_name":"UserPromptSubmit","prompt":"/research REQ-998"}' \
  env -u DEVIN_USER_PROMPT SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" bash "$hook_dir/gate-phase-advance-check.sh"
run_event 'event: unrelated prompt on stdin passes' 0 '' \
  '{"hook_event_name":"UserPromptSubmit","prompt":"hello"}' \
  env -u DEVIN_USER_PROMPT SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" bash "$hook_dir/gate-phase-advance-check.sh"
run_case 'gate later stage blocked until its opening gate' 2 'GATE-BLOCK: plan needs SDLC_03_BACKLOG_APPROVAL approved for REQ-998' \
  env SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="other-owner" DEVIN_USER_PROMPT='/plan REQ-998 STORY-1' \
  bash "$hook_dir/gate-phase-advance-check.sh"
mkdir -p "$fixture_root/stubbin"
printf '#!/usr/bin/env bash\ncase "$*" in *hook_input.py*) exec "%s" "$@" ;; esac\necho boom >&2\nexit 9\n' "$real_py" > "$fixture_root/stubbin/python3"
chmod +x "$fixture_root/stubbin/python3"
run_case 'gate check fails closed when the checker crashes' 2 'GATE-BLOCK: gate check failed to run' \
  env PATH="$fixture_root/stubbin:$PATH" SDLC_SESSION_ROOT="$session_root" SDLC_OWNER="$owner" DEVIN_USER_PROMPT='/research REQ-998' \
  bash "$hook_dir/gate-phase-advance-check.sh"

mkdir -p "$fixture_root/no-requester-home"
stamp='printf "Subject\n\nBody.\n" > "$2"; bash "$1" "$2" && bash "$1" "$2" && cat "$2" && printf "count=%s\n" "$(grep -c "^Requested-by:" "$2")"'
run_case 'commit-msg stamps the requester once' 0 'Requested-by: Resource 3 <resource3@acme.example>' \
  env SDLC_OWNER=resource3 bash -c "$stamp" _ "$hook_dir/git/commit-msg" "$fixture_root/msg-stamp"
run_case 'commit-msg does not repeat the trailer' 0 'count=1' \
  env SDLC_OWNER=resource3 bash -c "$stamp" _ "$hook_dir/git/commit-msg" "$fixture_root/msg-repeat"
run_case 'commit-msg blocks when the requester is unknown' 1 'COMMIT-BLOCK: cannot tell who asked for this commit' \
  env HOME="$fixture_root/no-requester-home" SDLC_OWNER=nobody-here bash -c "$stamp" _ "$hook_dir/git/commit-msg" "$fixture_root/msg-block"

run_case 'commit-msg blocks a PO commit that was not approved' 1 'has not approved these files' \
  env HOME="$fixture_root/no-requester-home" SDLC_OWNER=resource17@acme.example bash -c "$stamp" _ "$hook_dir/git/commit-msg" "$fixture_root/msg-po"

zeros=0000000000000000000000000000000000000000
run_event 'pre-push skips a branch deletion' 0 '' \
  "(delete) $zeros refs/heads/gone $zeros" \
  env SDLC_OWNER=resource17@acme.example bash "$hook_dir/git/pre-push"
run_event 'pre-push lets a tech lead through' 0 '' \
  "refs/heads/x $(git rev-parse HEAD) refs/heads/x $zeros" \
  env SDLC_OWNER=resource3 bash "$hook_dir/git/pre-push"
run_event 'pre-push fails closed when the checker crashes' 1 'ACCESS-BLOCK: pull request check failed to run' \
  "refs/heads/x $(git rev-parse HEAD) refs/heads/x $zeros" \
  env PATH="$fixture_root/stubbin:$PATH" SDLC_OWNER=resource17@acme.example bash "$hook_dir/git/pre-push"

if [ "$failures" -gt 0 ]; then
  printf 'FAIL: %s case(s)\n' "$failures"
  exit 1
fi

printf '%s\n' 'All hook tests passed.'
exit 0
