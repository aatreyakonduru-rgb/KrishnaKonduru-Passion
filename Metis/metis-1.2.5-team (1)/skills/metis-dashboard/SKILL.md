---
name: metis-dashboard
description: Mētis dashboard - one read-only page with the team's Jira work, Devin usage and learning plans, and KB health (source checks, open questions, drift). The view follows the person's role. Use when someone says "dashboard", "team dashboard", "how is the team doing", "Devin usage" or "learning plan".
triggers:
  - model
---

# Mētis dashboard

`$METIS` is the folder two levels above this SKILL.md; `<KB>` holds `.metis/kb-profile.yaml`.
Rules that apply: `$METIS/rules/metis-evidence.md`, `$METIS/rules/metis-writes.md`.
Read only: nothing is written to Jira, Confluence or the repo. Jira data is never committed.

## 1. Who and which view
- The person is the one asking, unless they name someone ("dashboard for <name>").
- Views: `manager`, `tech_lead`, `product_owner`, `developer`. The view comes from the person's role in
  `<KB>/.metis/dashboard.yaml` (`team`, `role_lens`) or `owners.roles` in kb-profile.yaml. If neither names them,
  use `default_lens` and say so. They can ask for another view ("show the manager view").
- If `<KB>/.metis/dashboard.yaml` is missing, use `$METIS/templates/dashboard.yaml` and offer to add it through
  `metis-setup`.

## 2. Devin org members
- List the members of this Devin org with the org user list tool, both `direct` and `idp` memberships, every page.
  Write `/tmp/metis-dashboard/<run>/members.json` as `[{"name": "...", "email": "..."}]`.
- If the tool isn't available or returns nobody, use `team` in dashboard.yaml and say the org list couldn't be read.
- Never give anyone a role the settings don't name.

## 3. Jira (read only)
- `python3 $METIS/tools/dash_jira.py <KB> -o /tmp/metis-dashboard/<run>/jira.json`
- It uses `sources.jira` in kb-profile.yaml and the token in the secret it names. On 401/403 it stops: tell the
  person the service-account token needs to be rotated, and build the page without Jira. Don't retry.

## 4. Teams Devin Usage (read only)
Who is on the team comes from `usage.team_from` in dashboard.yaml. The default, `jira`, means the people on the
team's Jira stories: assignees and reporters in the Jira snapshot, over every board in `sources.jira.boards` (each
board's own filter) and every project in `sources.jira.projects`. The Jira service account and anyone in
`usage.not_people` are left out. A person is matched to a Devin user only by the same email; nobody else in the org
is counted, and a person with no matching Devin user is shown as "no Devin user found".

1. Sessions. In one script (not in the conversation), for the last `usage.days` days (default 30), work out the first
   and last second as unix times and page through, saving each page's text exactly as returned:
   - `devin_session_search` with `created_after` and `created_before`, `first` 100, following `end_cursor`:
     `<run>/usage-raw/sessions-001.txt`, `-002`, ...
   - `devin_session_insights` action `list` with the same times: `<run>/usage-raw/insights-001.txt`, ...
   - `devin_user_list`, `direct` and `idp`, every page: `<run>/usage-raw/members-direct-001.txt`, `members-idp-001.txt`
2. `python3 $METIS/tools/dash_usage.py parse <run>/usage-raw --start <first> --end <last>
   --session-url https://<this Devin web address>/sessions -o <run>/usage.json`
3. Findings (only if the person asks for prompt patterns, skill gaps or learning plans, or the view is manager or
   tech lead): for each team member's larger sessions (by ACUs) and every session with high-impact issues, call
   `devin_session_insights` `generate`, then `get`. Write `<run>/findings.json` from what the analyses say:
   - `prompt_patterns`: `{pattern, sessions, before, better}`; `gaps`: `{gap, sessions, lesson}`;
     `repeated`: `{task, sessions, suggestion}`; `wins`: `{user_id, what, sessions}`
   - `people`: keyed by Devin user id, `{sessions, gaps, tips, questions, prompt_before, prompt_after}`
   - A pattern, gap or repeat needs two or more sessions; a win or a person's plan cites only that person's sessions.
     If the analysis doesn't support a point, leave it out. Prompt examples are short and cleaned: no names,
     secrets, member data or personal details.
   - `python3 $METIS/tools/dash_usage.py check <run>/usage.json <run>/findings.json`. The page also leaves out and
     lists any finding that fails the check.
4. Cost: dollars only when `usage.usd_per_acu` is set in dashboard.yaml (with `usd_per_acu_source`). Otherwise only
   ACUs are shown. Never work out a price.
5. `usage.json` and `findings.json` hold per-person usage. They stay in `/tmp/metis-dashboard/<run>/` and are
   never committed or posted to Jira or Confluence. Managers and tech leads (`usage.per_person_lenses`) see every
   person; everyone else sees the team totals and their own row and plan.
6. If the settings miss something (no Jira, no boards), the tab says what is missing. Point the person to
   `metis-setup`, which finds the boards.

## 5. Build and show
- `python3 $METIS/tools/gen_dashboard.py <KB> --user "<name or email>" --members <run>/members.json
  --jira <run>/jira.json --usage <run>/usage.json [--findings <run>/findings.json] [--lens <view>] -o /tmp/metis-dashboard/<run>/dashboard.html`
- Send `dashboard.html` as an attachment. In chat give only the overview numbers, each with where it came from.
- The page counts and lists only what Jira, the Devin session tools, the org list and the KB hold. Don't add judgements ("overloaded",
  "at risk") in the page or in chat. Without capacity, workload is counts only.
- Run it again any time; each run reads Jira fresh.

## 1.1.0 additions
- Layout (default): thin header (product logo + product name left, "Mētis - Knowledgebase Dashboard" centre, build date without time right), one menu row, no inner page banners, + / − / Reset bottom-left, scrollbars only when needed. One shared hub file for the people in `usage.per_person_lenses` unless they ask for separate copies. Build it with `tools/viz/hub.py`.
- Every tab and every gallery view carries a collapsible "What am I seeing?" panel: what you see, relationships, how to use it, what you can infer, purpose.
- Visualization gallery (tab, not a separate file): `tools/viz/build_data.py` → `cat.py` → `ep_fix.py` → `etl_layer_lineage.py` → `splice.py` (+ `banner.py`, `patch.js`) on `assets/gallery/gallery_template.html`. Views live in a left sidebar grouped Ontology / KB link graph / Lineage & impact; every view must be clickable/drillable; no "+N more" dead ends; no unlabeled dot clouds.
- These scripts need `METIS_KB` set to the KB folder and take every team-specific value (name, title, logo, colours, areas, databases, patterns) from the `viz:` section of `<KB>/.metis/kb-profile.yaml`. If a value is missing the matching part is left out; fill it in the profile, never in the script. They read the scratch folder (`METIS_WORK`, default `~/metis-work`) that the graph step fills.
- Session paging: `devin_session_search` / `devin_session_insights list` return "Pass after=<cursor> to fetch the next page"; follow that text until it is absent.
- `devin_session_insights generate` returns 403 for other people's sessions; say how many sessions have full analyses and leave findings out rather than inventing them.
- `dash_jira.py` warns when open issues hit the 2,000 cap or a whole-project JQL is present; tell the person instead of showing capped counts as real.
