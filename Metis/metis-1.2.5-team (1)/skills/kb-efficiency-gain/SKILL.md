---
name: kb-efficiency-gain
description: Measure the efficiency gain from using the CVBC Scorecard (APM1081911) Mētis KB - a 12-month Jira and Devin baseline before the KB start date, the same measures for every month after it, sister teams for comparison, the Efficiency gain from KB dashboard tab, and VALIDATE_KB questions for what no source holds (onboarding, hours, support time). Use when someone asks how useful the KB is, its impact, ROI, efficiency gain or baseline; also run as part of `cvbc-kb-refresh`.
triggers:
- model
---
# KB usage efficiency gain (APM1081911)

Read-only and local, like the rest of the CVBC KB (rule `cvbc-local-only`). Never asks the user anything: unknowns go to VALIDATE_KB.
`C` = this plugin's `cvbc` folder, `M` = its `tools` folder, work dir `~/metis-work`.

1. **Settings.** `kb/.metis/kb-impact.yaml` (copy from `$C/settings/kb-impact.yaml` if missing): `kb_start_date` (default 2026-11-09, the day the
   KB was first built), 12-month baseline, project CVBC, IT Team field `customfield_12479` = EDA-CVBC-Scorecard, ai labels (`ai-used`...),
   points/sprint/defect fields. `usd_per_acu` stays null until someone gives a price; show ACUs only.
2. **Jira.** `python3 $C/tools/kb_baseline_fetch.py` → `stage/jira12m/issues.jsonl`: every CVBC issue (all IT Teams, so sister teams are included)
   created or resolved since baseline start, open and closed, with status/label/sprint history. Token env `srcAPM1081911UEPJira`; on 401/403 stop.
3. **Devin sessions.** With `scripted_tools`, paste inline:
   ```python
   import re,time,os
   out=[];after=None;start=int(time.mktime((2025,11,9,0,0,0,0,0,0)))   # baseline start from kb-impact.yaml
   for _ in range(300):
       r=await tools.devin_session_search(created_after=start,first=100,after=after);out.append(r)
       m=re.search(r'Pass after=(\S+?) to fetch',r)
       if not m: break
       after=m.group(1)
   open(os.path.expanduser('~/metis-work/stage/devin_sessions_raw.txt'),'w').write('\n=====PAGE=====\n'.join(out))
   ```
4. **Compute.** `python3 $C/tools/kb_gain.py` → `kb/_EVIDENCE/files/kb-gain-jira.json`, `kb-gain-devin.json` (aggregates, no names),
   `kb/context/KB_EFFICIENCY_GAIN.md`, `kb/VISUALIZATION/KB_EFFICIENCY_GAIN.html`, `build/_gain_questions.yaml`. Then
   `python3 $M/questions.py add kb build/_gain_questions.yaml` and `python3 $C/tools/kb_gain.py ids` (puts the register ids into the doc).
   The whole monthly series is recomputed from Jira every run, so nothing has to be kept between sessions; months after `kb_start_date` appear on
   the charts as they pass (red dashed line = KB start).
5. **Measures** (team and sister teams, by month, baseline vs after): tickets and points resolved, median/p75 lead time (created → resolved),
   median/p75 cycle time (first move to a not-done status → resolved), defects created and resolved, reopened, carried over sprints, ai-used share;
   Devin sessions/ACUs for the org and for sessions whose title names a team Jira key.
6. **Gain.** Per measure: team change from baseline to after, minus the sister teams' change over the same months; and, after the start date,
   ai-used tickets (taken as using the KB; the user said tickets without the label probably did not) against the rest. Dollars = ACUs x usd_per_acu.
7. **Dashboard.** `hub2.py` adds the "Efficiency gain from KB" tab. When answers arrive (onboarding days, hours per point, price per ACU, start
   date, sister team), apply them with `questions.py answer` and put settings into `kb-impact.yaml`, then rerun steps 4 and 7.
