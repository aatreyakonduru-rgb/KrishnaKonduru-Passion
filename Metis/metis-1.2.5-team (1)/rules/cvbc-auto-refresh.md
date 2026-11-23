# CVBC Scorecard KB: run without prompting
- Only after `team-kb-refresh` step 0 (team/tools/detect_team.py) reports APM1081911 / `pipeline: cvbc`, or the session was started by a CVBC KB refresh automation, run the `cvbc-kb-refresh` skill end to end. In every other APM org, "metis" means `team-kb-refresh`.
- Do not ask setup questions or confirmations for it; put anything unresolved, including the team roster, in VALIDATE_KB and send the dashboard when done.
