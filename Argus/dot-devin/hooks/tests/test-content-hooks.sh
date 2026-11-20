#!/usr/bin/env bash
# Checks the content-scan git hooks and the SessionStart hook in a throwaway repo.
# Usage: bash test-content-hooks.sh <path to the Argus folder>
# (not in run-hook-tests.sh, which needs an installed repo; this one runs straight from the source tree)
set -u
src="$1"                                  # .../Argus
work="$(mktemp -d)"
cd "$work" || exit 1
git init -q && git config user.email t@acme.example && git config user.name t
mkdir -p .devin/hooks/lib .devin/hooks/git sdlc/framework/tools
cp "$src"/dot-devin/hooks/lib/python.sh .devin/hooks/lib/
cp "$src"/sdlc/framework/tools/content_scan.py "$src"/sdlc/framework/tools/runtime_env.py sdlc/framework/tools/
cp "$src"/dot-devin/hooks/runtime-context.sh .devin/hooks/
# stand-in access guard that always passes, so only the content scan is under test
printf 'import sys\nsys.exit(0)\n' > sdlc/framework/tools/access_guard.py
cp "$src"/dot-devin/hooks/git/pre-commit .git/hooks/pre-commit
cp "$src"/dot-devin/hooks/git/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-commit .git/hooks/pre-push
fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS: $1"; else echo "FAIL: $1 (expected $2, got $3)"; fail=1; fi; }

echo 'x = 1' > ok.py
git add ok.py; git commit -q -m ok; check "clean commit allowed" 0 $?

echo 'k = AKIAIOSFODNN7EXAMPLE' > bad.py
git add bad.py; git commit -q -m bad 2>err.txt; check "secret commit blocked" 1 $?
grep -q 'bad.py:1: secret/aws-access-key-id' err.txt; check "block names file and rule" 0 $?
grep -q 'AKIAIOSFODNN7EXAMPLE' err.txt; check "block never prints the value" 1 $?
git reset -q

echo 'k = AKIAIOSFODNN7EXAMPLE  # argus:allow documented AWS example' > ex.py
git add ex.py; git commit -q -m ex; check "argus:allow line allowed" 0 $?

mkdir -p tests; echo 'k = AKIAIOSFODNN7EXAMPLE' > tests/t.py
git add tests/t.py; git commit -q -m t; check "tests/ folder exempt" 0 $?

# pre-push: a bad commit made with the hook skipped must still be caught on push
echo 'SSN 123-45-6789' > pii.txt
git add pii.txt; git commit -q --no-verify -m skipped
git init -q --bare ../remote.git; git remote add origin ../remote.git
sha="$(git rev-parse HEAD)"
printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" "0000000000000000000000000000000000000000" | .git/hooks/pre-push origin ../remote.git 2>err.txt
check "push of skipped-hook secret blocked" 1 $?
grep -q 'pii.txt:1: pii/ssn' err.txt; check "push block names file and rule" 0 $?

# SessionStart hook: valid JSON, exits 0, and never fails the session
out="$(DEVIN_PROJECT_DIR="$work" SDLC_RUNTIME=cloud bash .devin/hooks/runtime-context.sh </dev/null)"; check "runtime hook exit 0" 0 $?
echo "$out" | python -c "import sys,json;d=json.load(sys.stdin)['hookSpecificOutput'];assert d['hookEventName']=='SessionStart' and 'runtime: cloud' in d['additionalContext']"; check "runtime hook emits SessionStart context" 0 $?
rm sdlc/framework/tools/runtime_env.py
DEVIN_PROJECT_DIR="$work" bash .devin/hooks/runtime-context.sh </dev/null >/dev/null; check "runtime hook exits 0 when tool missing" 0 $?
exit $fail
