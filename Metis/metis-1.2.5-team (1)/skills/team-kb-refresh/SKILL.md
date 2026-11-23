---
name: team-kb-refresh
description: Detect the team of this Devin session (APM number, repos, Jira/Confluence tokens, Snowflake schemas), then build that team's Mētis KB and dashboard end to end, local and read only, from every source Devin can read, with the 12-month efficiency baseline; send the KB zip and dashboard. Use when someone types "metis", "`team-kb-refresh`" or "refresh", or asks to build or refresh the KB or dashboard for their team.
triggers:
- model
---
# Team KB refresh (any APM)

Paths: `$T` = this plugin's `team/`, `$C` = `cvbc/`, `$M` = `tools/`. Work folder `~/metis-work`, dashboard `/tmp/metis-dashboard/run1`.
Read only: never write to a repo (no commit/push/branch/PR), Jira, Confluence or Snowflake (SELECT / SHOW / INFORMATION_SCHEMA only). Do not ask setup questions; put anything unresolved into VALIDATE_KB and keep going.

## Steps
0. **Detect first.** `mkdir -p ~/metis-work/{kb/.metis,kb/_EVIDENCE/{queries,confluence,confluence_att,jira,wiki,files},build,stage} /tmp/metis-dashboard/run1`;
   `cd ~/metis-work && python3 $T/tools/detect_team.py`. It writes `kb/.metis/team.yaml` and prints APM, repos, Jira project/IT Team, Confluence space and the
   working tokens (tries every `srcAPM<apm>*` env var, `_PAT` first, GET only; 401/403 on one token is noted, not retried). Tell the user in one short message what
   was detected (APM, application, repos, Jira team, Confluence space, tokens) and that the build is starting. Also run `git_list_repos` and `devin_list_wiki_repos`;
   clone any listed repo missing from `~/repos` read-only through the git proxy and rerun detection.
   - If `pipeline: cvbc` (APM1081911), stop here and run the `cvbc-kb-refresh` skill instead.
   - If `open:` lists an IT Team or space it could not decide, take the best candidate it printed, and add it as a P1 question.
   - New APM with no preset: copy `$T/settings/teams/APM1081910.yaml` as a pattern and fill it from team.yaml in `~/metis-work/kb/.metis/` (local only).
1. **Settings.** `cp $C/settings/kb-impact.yaml $C/settings/kb-keep.yaml $C/settings/dashboard.yaml kb/.metis/`; set `team_value` (= team.yaml `jira.team_value`),
   `project`, and add `team_name:` in `kb/.metis/kb-impact.yaml`. Write `kb/.metis/kb-profile.yaml` with `sources.jira.secret` = team.yaml `jira.secret`.
2. **Background pulls (start now).** `nohup python3 $C/tools/kb_baseline_fetch.py > stage/baseline.log &` (12 months of the Jira project, ~15K issues, ~25 min).
   Confluence: bind `CONF` to the env var named by team.yaml `confluence.secret` and run `python3 $C/tools/conf_export.py` (whole space), then
   `python3 $C/tools/conf_att.py && python3 $C/tools/conf_att_get.py` (attachments of the team pages under `confluence.team_root_title`).
3. **Snowflake (MCP `snowflakenonprodmcp-*`, `sql_exec_tool`).** With `scripted_tools` (so results go to files, not chat), page each query by `LIMIT 1500 OFFSET n`, convert
   `result_set` (`rowType` + `data`) to row dicts and save `kb/_EVIDENCE/queries/<ID>.json` (+ `.pageN.json`):
   `IDENTITY-NONPROD` (CURRENT_ROLE/WAREHOUSE/USER), `DISCOVERY-SCHEMAS-DEV-CRCA` (TABLES grouped by schema/type), `CATALOG-TABLES-DEV-CRCA_ALL`
   (all non-PHI-view tables of the dev db), `CATALOG-TABLES-SIT-CRCA_FIN` (SIT db, first team schema), `CATALOG-STAGES-DEV-CRCA`, and columns
   `CATALOG-COLUMNS-DEV-CRCA_FIN` (first team schema), `CATALOG-COLUMNS-DEV-CRCA_STG_FNC` and `CATALOG-COLUMNS-DEV-CRCA_UI_RUN` (other team schemas filtered by
   team.yaml `snowflake.table_prefixes`). Never read table rows that may hold member data.
4. **Devin wiki, knowledge, resources.** `devin_read_wiki_structure` + `devin_read_wiki_contents` for every wiki repo; save the full text as
   `kb/_EVIDENCE/wiki/devin_wiki_crcafin_full.md` (team_kb.py splits it per page). Copy every org/account knowledge note
   (`/opt/.devin/plugins/cache/*knowledge*/*/skills/*/SKILL.md`) to `kb/_EVIDENCE/files/devin-knowledge-<name>.md` - these hold any KB the team built already.
   With `scripted_tools` save playbooks (list + get each), automations and schedules to `kb/_EVIDENCE/files/devin-*.txt|md`, and the Devin session pull of the
   `kb-efficiency-gain` skill (step 3 there) to `stage/devin_sessions_raw.txt`.
5. **Build** (after the background pulls end): `python3 $T/tools/team_kb.py ~/metis-work` → `python3 $C/tools/kb_gain.py` →
   `python3 $M/questions.py add kb build/_gain_questions.yaml` → `python3 $C/tools/kb_gain.py ids` → `python3 $T/tools/team_viz.py ~/metis-work` (link graph, ontology, impact matrix,
   stack and the VISUALIZATION/*.html pages) → `python3 $T/tools/team_gallery.py ~/metis-work` (→ `argus/gallery.html`) →
   `python3 $M/verify_kb.py kb --report build/verify.json`.
   It must end `0 problems`; fix the generator and rerun if not.
6. **Dashboard.** `python3 $T/tools/team_hub.py ~/metis-work` → `/tmp/metis-dashboard/run1/<SHORT>_KB_Dashboard.html` (Overview, Team & sources, Modules,
   Database, Visualization gallery, ERD, Ontology & link graph, Tech stack, KB health, Lineage, DB drift, Confluence, Jira work, Devin wiki & existing KB, Open questions, Efficiency baseline, KB manifest). Screenshot the Overview, Visualization gallery and
   Efficiency baseline tabs with headless Chrome (`/opt/.devin/chrome/chrome/*/chrome-linux64/chrome --headless=new --screenshot=... file://...#t0`) and look at them.
7. **Deliver.** `cd ~/metis-work && zip -qr /tmp/metis-dashboard/run1/<SHORT>_KB.zip kb`. Send the dashboard HTML and the zip with a short note: detected team,
   verify result, counts, open P1 questions, and anything that could not be read (e.g. tokens that answered 401).
