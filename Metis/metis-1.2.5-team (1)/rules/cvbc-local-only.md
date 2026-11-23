---
trigger: model_decision
description: Applies when building or refreshing the CVBC Scorecard (APM1081911) Mētis knowledge base or dashboard.
---
# CVBC Scorecard KB stays local
- For APM1081911 the Mētis KB and dashboard are built in the session only (`~/metis-work`). Read the repo, Jira, Confluence, Snowflake and the Devin wiki; never write to the repo, Jira or Confluence, and do not open a PR for the KB.
- This replaces the kb-build and metis-setup step that delivers settings or the KB as a pull request, for APM1081911 only.
- Leave the CRCA-UI team's UI-KB out of this KB.
