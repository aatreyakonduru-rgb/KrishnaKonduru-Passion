#!/usr/bin/env python3
"""Make a sandbox: a made-up company (Acme Claims) with its Jira, Confluence, database, KB and repo.

    python3 make_sandbox.py --folder ~/Documents/sdlc-sandbox [--force]

Writes into the folder:
  jira.yaml          the sample Jira: people, sprints, epics, stories, sub-tasks, defects, comments
  confluence/        the sample Confluence space (index.yaml, pages/<id>.html, index.html)
  sample.db          a SQLite database with claims-style sample data (members, providers, contracts,
                     claims, claim lines, payments)
  sample-kb/         the hand-kept part of the sample app's knowledge base, copied into the repo by the
                     install, which then builds the rest from the code (sample_app.build_kb)
  acme-claims/       the sample app repo on branch main, with origin.git next to it as its "Bitbucket"
  claims-etl/        the sample app's ETL repo (nightly loads), beside it
Everything is made up and the same on every run. Standard library plus PyYAML.
"""
import argparse
import json
import datetime
import os
import random
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sample_app  # noqa: E402
import sandbox_server as server  # noqa: E402

PRODUCT, PROJECT, SPACE, IT_TEAM = "Acme Claims", "ACME", "ACMEWIKI", "Acme-Claims-Web"
DOMAIN = "acme.example"
FIELDS = {"Story Points": "customfield_10001", "Sprint": "customfield_10002",
          "Acceptance Criteria": "customfield_10003", "IT Team": "customfield_10004"}
STATUSES = [("To Do", "new"), ("In Progress", "indeterminate"), ("On Hold", "indeterminate"),
            ("In Review", "indeterminate"), ("Ready for QA", "indeterminate"), ("In QA", "indeterminate"),
            ("Resolved", "indeterminate"), ("Business Review", "indeterminate"),
            ("Awaiting Approval", "indeterminate"), ("Ready for Release", "indeterminate"),
            ("Live Check", "indeterminate"), ("Done", "done")]
ROLES = [  # (primary role, gate roles, allocation, delivery) for Resource 1..22, as in the example roster
    ("manager", ["manager"], 100, False), ("solution_lead", ["tech_lead"], 50, True),
    ("solution_lead", ["tech_lead"], 100, True), ("solution_lead", ["tech_lead"], 100, True),
    ("solution_lead", ["tech_lead", "developer", "dev_team"], 100, True)] + [
    ("developer", ["developer", "dev_team"], 50 if i == 9 else 100, True) for i in range(6, 12)] + [
    ("etl_developer", ["developer", "dev_team"], 100, True)] * 3 + [
    ("ux_designer", ["developer"], 100, True),
    ("product_owner", ["product_owner", "bsa", "ops_release_manager"], 100, True),
    ("product_owner", ["product_owner"], 100, True), ("qa_lead", ["test_lead", "qa_engineer"], 100, True),
    ("qa_staff", ["test_lead", "qa_engineer"], 100, True)] + [("qa_staff", ["tester"], 100, True)] * 3
EPICS = [
    ("Claims intake portal", "Members and providers submit claims online with attachments and see the status.",
     ["Upload claim documents", "Validate member eligibility on submit", "Show claim status timeline",
      "Save a draft claim", "Email a receipt after submit"]),
    ("Provider contracts", "Contract managers set up provider rates and see which claims each contract pays.",
     ["List contracts by provider", "Edit a contract rate table", "Expire a contract",
      "Export contracts to Excel", "Audit trail for rate changes"]),
    ("Payment reporting", "Finance sees what was paid, when and to whom, by month and by line of business.",
     ["Monthly payments report", "Drill from a payment to its claim lines", "Filter by line of business",
      "Schedule the report by email", "Reconcile payments with the bank file"]),
]
DEFECTS = [("Status timeline shows the wrong date - SIT", "In Progress"),
           ("Upload fails for files over 5 MB - SIT", "Ready for QA"),
           ("Rate table loses the last row on save - UAT", "In Review"),
           ("Report total differs from the bank file - UAT", "To Do"),
           ("Draft claim not restored after sign-in - SIT", "Resolved"),
           ("Expired contract still pays claims - PROD", "Done")]


def people():
    out = []
    for i, (primary, gates, alloc, delivery) in enumerate(ROLES, start=1):
        out.append({"name": "resource%d" % i, "key": "resource%d" % i, "displayName": "Resource %d" % i,
                    "emailAddress": "resource%d@%s" % (i, DOMAIN), "active": True,
                    "primary_role": primary, "gate_roles": gates, "allocation": alloc, "delivery": delivery})
    return out


def roster_csv(users, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "email", "jira_user", "primary_role", "roles", "allocation", "delegate", "delivery"])
        for u in users:
            w.writerow([u["displayName"], u["emailAddress"], u["name"], u["primary_role"], ", ".join(u["gate_roles"]),
                        u["allocation"], "", "yes" if u["delivery"] else "no"])


def jira_data(today):
    rnd = random.Random(7)
    users = people()
    devs = [u["name"] for u in users if u["primary_role"] in ("developer", "etl_developer", "solution_lead")]
    qas = [u["name"] for u in users if u["primary_role"] in ("qa_lead", "qa_staff")]
    po, bsa = "resource17", "resource16"

    def ts(days, hour=10):
        return (datetime.datetime.combine(today, datetime.time(hour)) + datetime.timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000+0000")
    start = today - datetime.timedelta(days=5)
    sprints = []
    for n, (offset, state) in enumerate(((-14, "closed"), (0, "active"), (14, "future")), start=1):
        s = start + datetime.timedelta(days=offset)
        sprints.append({"id": n, "name": "%s.%d.%d" % (today.strftime("%y"), (today.month - 1) // 3 + 1, n),
                        "state": state, "startDate": s.isoformat() + "T09:00:00.000Z",
                        "endDate": (s + datetime.timedelta(days=13)).isoformat() + "T17:00:00.000Z",
                        "goal": "Sprint %d of the sample team" % n})
    issues, n = {}, 0

    def add(**rec):
        nonlocal n
        n += 1
        key = "%s-%d" % (PROJECT, n)
        rec.setdefault("id", str(10000 + n))
        rec.setdefault("labels", [])
        rec.setdefault("fields", {})[FIELDS["IT Team"]] = IT_TEAM
        issues[key] = rec
        return key
    story_status = ["Done", "Done", "Ready for Release", "In QA", "Ready for QA", "In Review", "In Progress",
                    "In Progress", "To Do", "To Do", "On Hold", "Business Review", "Awaiting Approval", "To Do", "Done"]
    k = 0
    for e, (title, desc, stories) in enumerate(EPICS):
        epic = add(issuetype="Epic", summary=title, description=desc, status="In Progress", assignee=po, reporter=po,
                   created=ts(-60 + e), updated=ts(-2), priority="High")
        for s_title in stories:
            status = story_status[k % len(story_status)]
            sprint = [1] if status in ("Done",) and k % 2 == 0 else [2] if status not in ("To Do", "On Hold") else (
                [3] if k % 3 == 0 else [])
            dev = devs[k % len(devs)]
            done = status == "Done"
            labels = ["AI-Used"] if k % 3 == 0 else ["AI-NA"] if done else []
            story = add(issuetype="Story", summary=s_title, status=status, assignee=dev, reporter=bsa, parent=epic,
                        description="As a user I want to %s, so that the work is quicker and has fewer errors."
                        % s_title.lower(), created=ts(-40 + k), updated=ts(-rnd.randint(0, 6)), priority="Medium",
                        labels=labels, sprints=sprint, estimate_seconds=8 * 3600 * rnd.choice([1, 2, 3]),
                        resolution="Done" if done else None, resolutiondate=ts(-3) if done else None,
                        comments=[{"id": str(500 + k), "author": bsa, "created": ts(-10 + k % 5),
                                   "body": "Acceptance criteria agreed with the product owner."}],
                        worklogs=[{"id": str(700 + k), "author": dev, "seconds": 3600 * rnd.randint(2, 9),
                                   "started": ts(-4), "comment": "work"}] if status != "To Do" else [])
            issues[story]["fields"][FIELDS["Story Points"]] = rnd.choice([1, 2, 3, 5, 8])
            issues[story]["fields"][FIELDS["Acceptance Criteria"]] = (
                "AC1: %s works for a signed-in user.\nAC2: errors are shown in plain words." % s_title)
            for phase, who in (("DEV", dev), ("QA", qas[k % len(qas)])):
                st = "Done" if done or (phase == "DEV" and status not in ("To Do", "In Progress", "On Hold")) else (
                    "In Progress" if phase == "DEV" and status == "In Progress" else "To Do")
                add(issuetype="Sub-task", summary="%s - %s" % (phase, s_title), status=st, assignee=who, reporter=dev,
                    parent=story, created=ts(-30 + k), updated=ts(-1), sprints=sprint, labels=labels,
                    resolution="Done" if st == "Done" else None, resolutiondate=ts(-2) if st == "Done" else None)
            k += 1
    for i, (title, status) in enumerate(DEFECTS):
        done = status == "Done"
        bug = add(issuetype="Bug", summary=title, status=status, assignee=devs[i % len(devs)], reporter=qas[i % len(qas)],
                  created=ts(-12 + i), updated=ts(-1), priority=["High", "Medium", "Highest", "Medium", "Low", "High"][i],
                  sprints=[2] if status != "To Do" else [], labels=["incident-INC1000%d" % i] if "PROD" in title else [],
                  description="Steps: open the page, do the step, see the wrong result.",
                  resolution="Done" if done else None, resolutiondate=ts(-1) if done else None)
        if i < 3:
            issues[bug]["parent"] = None
    return {"project": {"key": PROJECT, "name": PRODUCT, "id": "10000"}, "me": "resource2",
            "fields": FIELDS, "statuses": [{"name": n_, "category": c} for n_, c in STATUSES],
            "users": [{k_: v for k_, v in u.items() if k_ in ("name", "key", "displayName", "emailAddress", "active")}
                      for u in users],
            "sprints": sprints, "issues": {k_: {x: y for x, y in v.items() if y is not None} for k_, v in issues.items()},
            "links": [{"id": "900", "type": "Blocks", "inward": "%s-1" % PROJECT, "outward": "%s-14" % PROJECT}],
            "next": {"issue": n + 1, "id": 5000}}


def confluence_data(folder, today):
    wiki = os.path.join(folder, "confluence")
    os.makedirs(os.path.join(wiki, "pages"), exist_ok=True)
    stamp = today.strftime("%Y-%m-%dT10:00:00.000+0000")
    pages = {"100000": {"type": "page", "title": PRODUCT, "space": SPACE, "version": 1, "created": stamp,
                        "updated": stamp, "by": "resource2"}}
    server.save_yaml(os.path.join(wiki, "index.yaml"), {"space": SPACE, "space_name": PRODUCT, "next_id": 100100,
                                                        "pages": pages})
    with open(os.path.join(wiki, "pages", "100000.html"), "w", encoding="utf-8") as fh:
        fh.write("<p>Home of the %s team (sandbox). The install puts the team's pages under this one.</p>" % PRODUCT)
    server.Confluence(folder).write_index_html()


TABLES = sample_app.TABLES


def database(path, today):
    rnd = random.Random(11)
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    for name, cols in TABLES.items():
        db.execute("CREATE TABLE %s (%s)" % (name, cols))
    firsts = ["Ana", "Ben", "Cara", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivan", "Jo"]
    lasts = ["Smith", "Lee", "Garcia", "Patel", "Nguyen", "Brown", "Khan", "Lopez", "Wong", "Diaz"]
    states, plans, lobs = ["CA", "NY", "TX", "OH", "VA"], ["Bronze", "Silver", "Gold"], ["Commercial", "Medicare", "Medicaid"]
    for i in range(1, 121):
        db.execute("INSERT INTO SDLC_MEMBER VALUES (?,?,?,?,?,?)", (i, rnd.choice(firsts), rnd.choice(lasts),
                                                                rnd.randint(1940, 2015), rnd.choice(plans), rnd.choice(states)))
    specs = ["Cardiology", "Orthopedics", "Primary Care", "Maternity", "Oncology"]
    for i in range(1, 31):
        db.execute("INSERT INTO SDLC_PROVIDER VALUES (?,?,?,?)", (i, "Provider %d Clinic" % i, rnd.choice(specs), rnd.choice(states)))
    for i in range(1, 41):
        start = today - datetime.timedelta(days=rnd.randint(200, 900))
        end = start + datetime.timedelta(days=730)
        db.execute("INSERT INTO SDLC_CONTRACT VALUES (?,?,?,?,?,?)", (i, rnd.randint(1, 30), start.isoformat(),
                                                                  end.isoformat(), round(rnd.uniform(60, 95), 1),
                                                                  "active" if end > today else "expired"))
    line = pay = 0
    for i in range(1, 301):
        sd = today - datetime.timedelta(days=rnd.randint(1, 365))
        status = rnd.choice(["paid", "paid", "paid", "pending", "denied"])
        db.execute("INSERT INTO SDLC_CLAIM VALUES (?,?,?,?,?,?,?)", (i, rnd.randint(1, 120), rnd.randint(1, 30),
                                                                 rnd.randint(1, 40), sd.isoformat(), status, rnd.choice(lobs)))
        total = 0.0
        for _ in range(rnd.randint(1, 4)):
            line += 1
            billed = round(rnd.uniform(50, 2500), 2)
            allowed = round(billed * rnd.uniform(0.5, 0.95), 2)
            total += allowed
            db.execute("INSERT INTO SDLC_CLAIM_LINE VALUES (?,?,?,?,?)", (line, i, "CPT%05d" % rnd.randint(10000, 99999),
                                                                      billed, allowed))
        if status == "paid":
            pay += 1
            db.execute("INSERT INTO SDLC_PAYMENT VALUES (?,?,?,?)", (pay, i, (sd + datetime.timedelta(days=rnd.randint(5, 40))
                                                                          ).isoformat(), round(total, 2)))
    db.commit()
    counts = {t: db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES}
    db.close()
    return counts


def sample_kb(folder, counts):
    kb = os.path.join(folder, "sample-kb")
    files = {
        "MODULES/claims-intake/00_DISCOVERY_REPORT.md":
            "# Claims intake: discovery (sample)\n\nThe claims intake module of the sandbox's sample app: members "
            "and providers submit a claim with its lines, the app checks the member has an active plan and shows "
            "each status change.\n\n## Screens\n- `/claims/submit`: submit a claim\n- `/claims`: my claims and "
            "their status timeline\n\n## Code\n- `api/apps/claims/` (`/api/claims/list`, `/submit`, `/timeline`)\n"
            "- `web/src/app/claims/`, `web/src/Services/ClaimsService.ts`\n\n## Tables\n- reads `SDLC_MEMBER`, "
            "`SDLC_PROVIDER`\n- writes `SDLC_CLAIM`, `SDLC_CLAIM_LINE`\n",
        "MODULES/claims-intake/02_BRD.md":
            "# Claims intake: business requirements (sample)\n\n- BR-1: a signed-in member can submit a claim.\n"
            "- BR-2: a claim for a member without an active plan is refused with a plain message.\n"
            "- BR-3: the member sees each status change with its date.\n",
        "DB-DOCS/DB_SCHEMA_SUMMARY.md":
            "# Sample database schema\n\nSQLite file `sample.db` in the sandbox folder. Rows per table:\n\n"
            + "".join("- `%s`: %d rows. Columns: %s\n" % (t, counts[t], TABLES[t]) for t in TABLES),
        "ETL/claims-nightly-load/00_ETL_DISCOVERY_REPORT.md":
            "# Claims nightly load: discovery (sample)\n\nThe `claims-etl` repo loads the day's claims "
            "(`claims_nightly_load.sql`) and payments (`payments_load.sql`) from their stage tables, marks "
            "expired contracts (`contract_expiry.sql`) and writes the monthly bank file (`bank_file.py`).\n",
    }
    files.update(sample_app.kb_files(counts))
    sample_app.write_files(kb, files)
    return kb


APP_FILES = sample_app.APP_FILES


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="Resource 2", GIT_AUTHOR_EMAIL="resource2@" + DOMAIN,
               GIT_COMMITTER_NAME="Resource 2", GIT_COMMITTER_EMAIL="resource2@" + DOMAIN)
    subprocess.run(["git"] + list(args), cwd=cwd, env=env, check=True, capture_output=True)


def repo(folder):
    origin = os.path.join(folder, "origin.git")
    app = os.path.join(folder, "acme-claims")
    git(folder, "init", "-q", "--bare", "-b", "main", origin)
    os.makedirs(app)
    sample_app.write_files(app, APP_FILES)
    git(app, "init", "-q", "-b", "main")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "Acme Claims sample app")
    git(app, "remote", "add", "origin", origin)
    git(app, "push", "-q", "origin", "main")
    etl = os.path.join(folder, "claims-etl")
    sample_app.write_files(etl, sample_app.ETL_FILES)
    git(etl, "init", "-q", "-b", "main")
    git(etl, "add", "-A")
    git(etl, "commit", "-q", "-m", "Acme Claims nightly loads")
    return app, origin


def like(repo):
    """Take the sample's names from an installed SDLC, so its Jira matches that profile."""
    global PRODUCT, PROJECT, IT_TEAM, DOMAIN
    rules = os.path.join(os.path.abspath(os.path.expanduser(repo)), ".devin", "rules")
    with open(os.path.join(rules, "sdlc-profile.json"), encoding="utf-8") as fh:
        jira = json.load(fh).get("jira", {})
    PROJECT, IT_TEAM = jira.get("project") or PROJECT, jira.get("it_team") or IT_TEAM
    values = os.path.join(rules, "sdlc-install.yaml")
    if os.path.exists(values):
        v = server.load_yaml(values, {}) or {}
        PRODUCT = v.get("product_name") or PRODUCT
        DOMAIN = (v.get("email_domain") or DOMAIN).lstrip("@")


def make(folder, force=False, today=None):
    folder = os.path.abspath(os.path.expanduser(folder))
    today = today or datetime.date.today()
    if os.path.exists(folder) and os.listdir(folder):
        if not force:
            raise SystemExit("%s is not empty; pick another folder or pass --force to replace it" % folder)
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)
    server.save_yaml(os.path.join(folder, "jira.yaml"), jira_data(today))
    confluence_data(folder, today)
    counts = database(os.path.join(folder, "sample.db"), today)
    sample_kb(folder, counts)
    roster_csv(people(), os.path.join(folder, "roster.csv"))
    app, origin = repo(folder)
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# SDLC sandbox: %s\n\nA made-up company to try the SDLC framework on. Nothing here is real.\n\n"
                 "- `jira.yaml`: the sample Jira\n- `confluence/index.html`: the sample Confluence pages\n"
                 "- `sample.db`: the sample database (SQLite)\n- `sample-kb/`: the sample knowledge base\n"
                 "- `roster.csv`: the sample team, for the install window's Roster step\n"
                 "- `acme-claims/`: the app repo, with `origin.git` as its remote; `python3 run.py setup`, "
                 "then `python3 run.py` runs it (see its README)\n"
                 "- `claims-etl/`: the app's ETL repo\n\n"
                 "Start the sandbox server with `python3 <framework>/tools/sandbox/sandbox_server.py --folder %s`.\n"
                 % (PRODUCT, folder))
    return {"folder": folder, "repo": app, "origin": origin, "tables": counts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", default="~/Documents/sdlc-sandbox")
    ap.add_argument("--force", action="store_true", help="replace a folder that already has files in it")
    ap.add_argument("--like", metavar="REPO", help="a repo where the SDLC is installed: use its Jira project, "
                    "IT team, product and email domain instead of the Acme ones")
    args = ap.parse_args(argv)
    if args.like:
        like(args.like)
    out = make(args.folder, args.force)
    print("sandbox made in %s (repo %s)" % (out["folder"], out["repo"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
