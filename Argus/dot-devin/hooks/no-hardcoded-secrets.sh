#!/usr/bin/env bash
# PreToolUse (file tools): block hardcoded secrets. Enforces .devin/rules/secure-coding.md.
HOOK_NAME=no-hardcoded-secrets
. "$(dirname "${BASH_SOURCE[0]}")/lib/content.sh"
read_tool_content

aws_secret_pattern="(aws_secret|aws_access_key)[[:space:]]*[:=][[:space:]]*[\"']?[A-Za-z0-9/+]{20,}"
password_pattern="(password|passwd|pwd)[[:space:]]*[:=][[:space:]]*[\"']?[^[:space:]\"'{]{6,}"
token_pattern="(api_key|apikey|token|secret)[[:space:]]*[:=][[:space:]]*[\"']?[A-Za-z0-9_-]{16,}"

if printf '%s' "$content" | grep -Eq 'AKIA[0-9A-Z]{16}' ||
   printf '%s' "$content" | grep -Eiq "$aws_secret_pattern" ||
   printf '%s' "$content" | grep -Eiq "$password_pattern" ||
   printf '%s' "$content" | grep -Eiq "$token_pattern"; then
  hook_block 'HOOK-BLOCK: Potential hardcoded secret detected. Never commit credentials. Follow .devin/rules/secure-coding.md.'
fi

exit 0
