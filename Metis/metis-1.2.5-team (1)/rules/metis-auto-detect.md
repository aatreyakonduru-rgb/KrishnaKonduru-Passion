---
trigger: always_on
---
# Mētis: detect the team, then run without prompting
- When the user's message is only "metis", "refresh", "dashboard", or asks to build or refresh the KB or dashboard (in any APM org), run the `team-kb-refresh` skill end to end. Its first step detects the APM, repos, tokens, Jira team and Confluence space; never assume CVBC Scorecard.
- Only when detection says `pipeline: cvbc` (APM1081911) run `cvbc-kb-refresh` instead.
- Do not ask setup questions or confirmations; put anything unresolved in VALIDATE_KB, and send the KB zip and the dashboard when done.
- Once the KB is locked (`kb_gate.py`), a refresh still runs to the end but its result is staged in `_PENDING` and waits for a named lead to certify it; say so plainly when you report.
