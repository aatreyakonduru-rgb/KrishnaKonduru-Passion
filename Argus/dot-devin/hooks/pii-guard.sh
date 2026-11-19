#!/usr/bin/env bash
# PreToolUse (file tools): block content with PII patterns. Enforces .devin/rules/pii-handling.md.
HOOK_NAME=pii-guard
. "$(dirname "${BASH_SOURCE[0]}")/lib/content.sh"
read_tool_content

if printf '%s' "$content" | grep -Eq '\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b' ||
   printf '%s' "$content" | grep -Eq '\b(DOB|date_of_birth|dateOfBirth)[[:space:]]*[:=]' ||
   printf '%s' "$content" | grep -Eq '\bMBR_ID[[:space:]]*=[[:space:]]*[0-9]{6,}'; then
  hook_block 'HOOK-BLOCK: Potential PII detected in file write. Review content before proceeding. Follow .devin/rules/pii-handling.md.'
fi

exit 0
