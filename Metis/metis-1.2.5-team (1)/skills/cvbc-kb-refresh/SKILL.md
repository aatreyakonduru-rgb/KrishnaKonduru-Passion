---
name: cvbc-kb-refresh
description: Rebuild the CVBC Scorecard (APM1081911 / PRFPHM) Mētis knowledge base and its dashboard in one go from every source Devin can read (repos, Snowflake, Confluence, Jira, Devin wiki, playbooks, knowledge notes, skills, automations), read-only and local to the session, and send the dashboard HTML. Use when someone types `cvbc-kb-refresh`, "metis", or asks to build or refresh the CVBC Scorecard KB or dashboard.
triggers:
- model
---

# CVBC Scorecard KB refresh (local, read-only)

Runs the whole build without asking the user anything: no setup questions, no confirmations. Anything a source cannot settle becomes a VALIDATE_KB question, never a chat question.
If a source fails (401/403, no connection), skip it, record it in the delivery note, and carry on. Settings, scripts and assets live in `$C=<this plugin>/cvbc`
(find it with `ls /opt/.devin/plugins/cache/*/*/cvbc 2>/dev/null` or the plugin folder). Mētis tools are `$M=<this plugin>/tools`.

## Hard limits (never break)
- Read only. Never write to the repo (no commit, push, branch, PR), Jira or Confluence. No Snowflake DDL/DML/COMMENT.
- Everything stays in `~/metis-work` and `/tmp/metis-dashboard/run1` on this VM. Do not commit the KB anywhere.
- Every KB line carries `[E: ...]` or `[?: Q-nnnn]`. Do not invent roles; roster roles stay blank unless the user gives them.
- Leave the CRCA-UI team's UI-KB out (user decision).

## Steps
1. **Setup.** `mkdir -p ~/metis-work/{kb/.metis,kb/_EVIDENCE/{queries,confluence,jira,wiki,files},build,argus/repos} /tmp/metis-dashboard/run1`;
   `cp $C/settings/*.yaml ~/metis-work/kb/.metis/`. Make read-only worktrees of `ncr_dna1_crcaprf_files`:
   `~/repos/crcaprf-develop` (develop), `~/repos/crcaprf-master` (master), `~/repos/crcaprf-dec` (feature/CRCA_PRF_DEC_REL), with `git worktree add` from the pre-cloned repo
   (or clone through the git proxy). `ln -sfn ~/repos/crcaprf-develop ~/metis-work/argus/repos/ncr_dna1_crcaprf_files`.
   Record the commit of each branch; update `repo_branches` in kb-profile.yaml.
2. **Snowflake (MCP `snowflakenonprodmcp-*`, read only).** Run each `$C/queries/CATALOG-*-{DEV,SIT}-CRCA.sql`, `DISCOVERY-SCHEMAS-DEV-CRCA.sql`, `IDENTITY-NONPROD.sql`.
   Also run the extra metadata queries (`CATALOG-TABLESTATS-*-PRFPHM`, `CATALOG-STAGES-DEV-CRCA`, `CATALOG-OBJECTCOUNTS-DEV-CRCA`, `CATALOG-VIEWDEF-ACCESS-DEV-PRF`,
   `DISCOVERY-DATABASES-NONPROD`, `DISCOVERY-SCHEMAS-DEV-ACV`). View definitions are hidden from this role; report it, do not work around it.
   Page column queries with `LIMIT 1500 OFFSET n` until a page is short; convert the `result_set` (`rowType` + `data`) to row dicts; save pages as
   `<ID>.pageN.json` and the merged list as `<ID>.json` in `kb/_EVIDENCE/queries/` (empty `[]` when no rows). UAT/PROD have no connection: keep their .sql only.
3. **Confluence.** Bind `CONF` to `secret:org:srcAPM1081911UEPConf` in exec `env` (it is not in the shell by default). Run `python3 $C/tools/conf_export.py` (whole CVBN space),
   then `python3 $C/tools/conf_att.py` (lists attachments on the ~144 CVBC Scorecard team pages) and `python3 $C/tools/conf_att_get.py` (downloads them to `~/metis-work/conf_att_raw`,
   extracts text with stdlib zip/XML: data dictionaries, mapping, design and config workbooks in full; test results and job trackers headers only; emails and images title only).
   Bearer token, GET only; on 401/403 stop, do not retry, tell the user.
4. **Jira (read only).** JQL `project = CVBC AND "IT Team" = EDA-CVBC-Scorecard` (not-done plus done in the last 14 days). Use `$M/dash_jira.py` as the metis-dashboard skill says
   (TLS verify off per dashboard.yaml) into `/tmp/metis-dashboard/run1/jira.json`, and save per-issue snapshots in `kb/_EVIDENCE/jira/` plus `kb/_EVIDENCE/files/jira-snapshot.json`.
   Rebuild TEAM_ROSTER.yaml / dashboard.yaml `team:` from assignees and reporters only if people changed.
5. **Devin wiki and knowledge.** Ask `devin_ask_wiki_question` (repo `bitbucket.elevancehealth.com/AEDLNC/ncr_dna1_crcaprf_files`) the 24 questions listed in
   `$C/settings/wiki_questions.json`; save each answer as `kb/_EVIDENCE/wiki/WIKI-<key>.md` with header lines `repo:`, `question:`, `captured:` then a blank line and the answer.
   Copy the org knowledge notes (cvbc-scorecard-knowledge, APM1081911 context, leader/Jira mapping, service access) as `kb/_EVIDENCE/files/devin-knowledge-<name>.md`.
5b. **Devin org resources.** With `scripted_tools`, paste this inline (do not load it from a file):
   ```python
   import re,os
   E=os.path.expanduser('~/metis-work/kb/_EVIDENCE/files')
   lst=await tools.devin_playbook_manage(action='list',first=200); open(E+'/devin-playbooks.txt','w').write(lst)
   ids=re.findall(r'- (playbook-[0-9a-f]+)',lst)
   for i,r in zip(ids,await asyncio.gather(*[tools.devin_playbook_manage(action='get',playbook_id=i) for i in ids],return_exceptions=True)):
       if not isinstance(r,Exception): open(f'{E}/devin-playbook-{i}.md','w').write(r)
   open(E+'/devin-automations.txt','w').write(await tools.devin_automation_manage(action='list',first=200))
   open(E+'/devin-schedules.txt','w').write(await tools.devin_schedule_manage(action='list',limit=100))
   ```
   Every repo the org has connected is read: list them with the repo tools / `~/repos`, clone any missing one read-only into `~/repos`, and give each the branch
   worktrees of step 1 (today the org has only `ncr_dna1_crcaprf_files`). Other Devin knowledge (plugin skills, rules and knowledge notes) is read from
   `/opt/.devin/plugins/cache` by `gen_devin_res.py` in step 6.
5c. **Efficiency baseline (skill `kb-efficiency-gain`).** `python3 $C/tools/kb_baseline_fetch.py` (12 months of Jira project CVBC, all IT Teams, with
   status history, about 15K issues, 25 min - start it in the background before step 2) and the Devin session pull from that skill (scripted_tools).
6. **Build.** From `~/metis-work`:
   `python3 $M/build_outputs.py kb` (makes the DB registry) →
   `python3 $C/tools/gen_kb.py kb` → `python3 $C/tools/gen_docs.py kb` → `python3 $C/tools/add_wiki.py` → `python3 $C/tools/gen_conf_snow.py` → `python3 $C/tools/gen_devin_res.py` → `python3 $M/questions.py add kb build/_roster_questions.yaml` (one VALIDATE_KB question per roster person: on the team? role?) → `python3 $C/tools/kb_gain.py` → `python3 $M/questions.py add kb build/_gain_questions.yaml` → `python3 $C/tools/kb_gain.py ids` →
   `python3 $M/build_outputs.py kb` again. It must end `verify: ... 0 problems`; fix and rerun if not.
7. **Gallery.** `python3 $C/tools/make_graph.py`; `METIS_KB=~/metis-work/kb METIS_REPOS=~/metis-work/argus/repos METIS_WORK=~/metis-work python3 $C/tools/build_data_cvbc.py`;
   `python3 $C/tools/supp.py`; `python3 $C/tools/splice_cvbc.py`. Check all 30 views draw: inject a script that runs every `VIEWS[i].f()` and dump the DOM with
   headless Chrome (`/opt/.devin/chrome/chrome/*/chrome-linux64/chrome --headless=new --no-sandbox --virtual-time-budget=30000 --dump-dom file://...`). No `ERR` allowed.
8. **Dashboard.** Run the metis-dashboard skill's Jira/usage steps into `/tmp/metis-dashboard/run1/dashboard.html` (developer lens unless the user has a role; Devin
   member list needs `org.membership.view` - if refused, say so, do not guess people). Then `python3 $C/tools/hub2.py` →
   `/tmp/metis-dashboard/run1/CVBC_Scorecard_KB_Dashboard.html` (13 tabs: Overview, KB matrix, Module & DB docs, Visualization gallery, ERD, Ontology,
   Tech stack, KB health, KB manifest, DB drift, Open questions, Efficiency gain from KB, Team dashboard). Screenshot tab `#t3` headless to check it renders.
9. **Deliver.** Zip `~/metis-work/kb` without `VISUALIZATION/ONTOLOGY.html` (too big). Send the dashboard HTML and zip with a short note: verify result, what changed
   since the last counts in the overview, open P1 questions, and anything that could not be read.
