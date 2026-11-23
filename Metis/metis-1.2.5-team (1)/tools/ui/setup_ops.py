#!/usr/bin/env python3
"""Project setup for the Metis UI: the profile, the detected stack, databases and environments, and the checks.

Every write goes to <KB>/.metis/. Detection, approval and the prompt lint are the existing tools (detect_stack.py, prompts.py);
this module only collects the person's answers, writes them in the shape those tools read, and reports what is still missing.
It never guesses a value: what nobody gave stays empty.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402

ROLES = ("dev lead", "etl lead", "data lead", "architect", "manager", "product owner", "business analyst", "security lead", "operations")
ENGINES = ("snowflake", "postgresql", "mysql", "sqlserver", "oracle", "h2", "schema-files")
TEMPLATES = os.path.join(C.METIS, "templates")


def lines(text):
    return [l.strip() for l in str(text or "").splitlines() if l.strip() and not l.strip().startswith("#")]


def split_pipe(line, n):
    parts = [p.strip() for p in line.split("|")]
    return (parts + [""] * n)[:n]


# ---- the profile ----------------------------------------------------------------------------------
def starter(kb):
    return {"product": {"name": "", "short_name": ""},
            "repo": {"url": "", "base_branch": ""},
            "paths": {"kb_root": ".", "db_docs": "db", "module_docs": "modules", "etl_docs": "etl", "context_dir": "context"},
            "sources": {"workspace_root": "", "repos": {}, "repo_urls": {}},
            "app": {"source_dirs": [], "modules": []}, "etl": {"modules": []},
            "db": {"environments_file": "db-environments.yaml"},
            "owners": {"kb_owner": "", "roles": {r: "" for r in ROLES}},
            "gate": {"certifiers": [], "allow_self_certify": False, "teams": []},
            "verify": {"strict_tags": True},
            "questions": {"role_for_type": {"business": "product owner", "application": "dev lead", "data": "data lead",
                                            "etl-batch": "etl lead", "access": "manager", "security": "security lead"}}}


def form_values(kb):
    """The profile as the setup form shows it."""
    p = C.profile(kb) or starter(kb)
    src = p.get("sources") or {}
    owners = p.get("owners") or {}
    roles = owners.get("roles") or {}
    repos = src.get("repos") or {}
    urls = src.get("repo_urls") or {}

    def mod(m):
        return "|".join(str(m.get(k) or "") for k in ("name", "source", "kind"))
    return {
        "name": C.get(p, "product.name") or "", "short": C.get(p, "product.short_name") or "",
        "team_repo": C.get(p, "repo.url") or "", "branch": C.get(p, "repo.base_branch") or "",
        "workspace": src.get("workspace_root") or "",
        "repos": "\n".join("%s|%s|%s" % (k, v, urls.get(k, "")) for k, v in repos.items() if C.real(k)),
        "kb_owner": owners.get("kb_owner") or "",
        "roles": {r: roles.get(r, "") or "" for r in list(ROLES) + [x for x in roles if x not in ROLES]},
        "certifiers": ", ".join((p.get("gate") or {}).get("certifiers") or []),
        "app_modules": "\n".join(mod(m) for m in C.get(p, "app.modules") or [] if isinstance(m, dict)),
        "etl_modules": "\n".join(mod(m) for m in C.get(p, "etl.modules") or [] if isinstance(m, dict)),
        "jira_url": C.get(p, "sources.jira.base_url") or "", "jira_projects": ", ".join(C.get(p, "sources.jira.projects") or []),
        "jira_secret": C.get(p, "sources.jira.secret") or "",
        "conf_url": C.get(p, "sources.confluence.base_url") or "", "conf_spaces": ", ".join(C.get(p, "sources.confluence.spaces") or []),
        "conf_secret": C.get(p, "sources.confluence.secret") or "",
    }


def problems_in(values):
    bad = []
    if not C.clean(values.get("name")):
        bad.append("Give the product name.")
    if not C.clean(values.get("kb_owner")):
        bad.append("Name the KB owner: they approve the KB and are the first lead who can certify changes.")
    if not C.clean(values.get("workspace")):
        bad.append("Give the folder the source repos are cloned into.")
    if not lines(values.get("repos")):
        bad.append("List at least one source repo, one per line: name|folder|clone URL.")
    seen = set()
    for l in lines(values.get("repos")):
        name, folder, _ = split_pipe(l, 3)
        if not re.match(r"^[\w.-]+$", name or ""):
            bad.append("Repo name '%s' must be letters, digits, dots, dashes or underscores (it is used in source tags)." % name)
        if not folder:
            bad.append("Repo '%s' needs its folder." % name)
        if name in seen:
            bad.append("Repo '%s' is listed twice." % name)
        seen.add(name)
    for key, label in (("app_modules", "App module"), ("etl_modules", "ETL module")):
        for l in lines(values.get(key)):
            name, source, _ = split_pipe(l, 3)
            if not name or not source:
                bad.append("%s line needs name|source|kind: %s" % (label, l))
            elif source.split("/")[0] not in seen:
                bad.append("%s '%s' reads from '%s', which is not a listed repo." % (label, name, source.split("/")[0]))
    return bad


def save_profile(kb, values):
    bad = problems_in(values)
    if bad:
        raise C.UiError("\n".join(bad))
    p = C.profile(kb) or starter(kb)
    base = starter(kb)
    for k, v in base.items():
        p.setdefault(k, v)
    p["product"].update(name=C.clean(values["name"]), short_name=C.clean(values.get("short")) or C.clean(values["name"]).split()[0])
    p["repo"] = {"url": C.clean(values.get("team_repo")), "base_branch": C.clean(values.get("branch"))}
    src = p["sources"]
    src["workspace_root"] = C.clean(values["workspace"])
    src["repos"], src["repo_urls"] = {}, {}
    for l in lines(values["repos"]):
        name, folder, url = split_pipe(l, 3)
        src["repos"][name] = folder
        if url:
            src["repo_urls"][name] = url
    owners = p["owners"]
    owners["kb_owner"] = C.clean(values["kb_owner"])
    roles = values.get("roles") or {}
    owners["roles"] = {r: C.clean(roles.get(r)) for r in ROLES}
    for r, n in roles.items():
        if r not in ROLES and C.clean(r) and C.clean(n):
            owners["roles"][C.clean(r)] = C.clean(n)
    p["gate"]["certifiers"] = [C.clean(x) for x in re.split(r"[,\n]", values.get("certifiers") or "") if C.clean(x)]
    for key, sect in (("app_modules", p["app"]), ("etl_modules", p["etl"])):
        sect["modules"] = [dict(zip(("name", "source", "kind"), split_pipe(l, 3))) for l in lines(values.get(key))]
    p["app"]["source_dirs"] = sorted({m["source"] for m in p["app"]["modules"]})
    if C.clean(values.get("jira_url")):
        src["jira"] = {"enabled": True, "base_url": C.clean(values["jira_url"]), "projects": csv(values.get("jira_projects")),
                       "boards": (src.get("jira") or {}).get("boards") or [], "jql": "", "secret": C.clean(values.get("jira_secret"))}
    else:
        src.pop("jira", None)
    if C.clean(values.get("conf_url")):
        src["confluence"] = {"enabled": True, "base_url": C.clean(values["conf_url"]), "spaces": csv(values.get("conf_spaces")),
                             "root_pages": (src.get("confluence") or {}).get("root_pages") or [], "secret": C.clean(values.get("conf_secret")),
                             "auth": "bearer", "verify_tls": True}
    else:
        src.pop("confluence", None)
    C.dump_yaml(C.profile_path(kb), p, "# Mētis settings. Written by the Mētis UI (Setup). Every value is the team's own.\n")
    for d in ("_EVIDENCE/queries", "_EVIDENCE/confluence", "_EVIDENCE/jira", "_EVIDENCE/files", "_EVIDENCE/documents", "_QUESTIONS"):
        g = os.path.join(kb, d, ".gitkeep")
        if not os.path.exists(g):
            C.write_text(g, "")
    for name in ("kb-keep.yaml",):
        dst = os.path.join(kb, ".metis", name)
        if not os.path.exists(dst) and os.path.isfile(os.path.join(TEMPLATES, name)):
            shutil.copy(os.path.join(TEMPLATES, name), dst)
    return p


def csv(text):
    return [C.clean(x) for x in re.split(r"[,\n]", text or "") if C.clean(x)]


# ---- stack ----------------------------------------------------------------------------------------
def detect(kb):
    code, out = C.run_tool("detect_stack.py", ["detect", kb, "--all"], kb=kb, timeout=600)
    return code, out


def detected(kb):
    return C.load_yaml(os.path.join(kb, ".metis", "DETECTED_STACK.yaml"))


def approved(kb):
    return C.load_yaml(os.path.join(kb, ".metis", "stack.yaml"))


def stack_ident(it):
    return "|".join(str(it.get(k) or "") for k in ("category", "name", "repo", "engine", "env", "key", "value"))


def stack_changes(kb, removes, adds, by):
    """Approve the detected stack with the person's changes. removes: ids from stack_ident; adds: dicts with category and name."""
    if not C.clean(by):
        raise C.UiError("say who is approving (top right, 'You are')")
    det = detected(kb)
    if not det:
        raise C.UiError("run detection first")
    by_id = {stack_ident(i): i for i in det.get("items") or []}
    ch = {"remove": [], "add": []}
    for rid in removes:
        it = by_id.get(rid)
        if it:
            ch["remove"].append({k: it[k] for k in ("category", "name", "repo") if it.get(k)})
    for a in adds:
        if C.clean(a.get("category")) and C.clean(a.get("name")):
            ch["add"].append({k: C.clean(v) for k, v in a.items() if C.clean(v)})
    args = ["approve", kb, "--by", C.clean(by)]
    if ch["add"] or ch["remove"]:
        path = os.path.join(kb, ".metis", "stack-changes.yaml")
        C.dump_yaml(path, ch)
        args += ["--changes", path]
    code, out = C.run_tool("detect_stack.py", args, kb=kb)
    if code:
        raise C.UiError(out or "approval failed")
    return out


# ---- databases --------------------------------------------------------------------------------------
def db_text(kb):
    d = C.load_yaml(os.path.join(kb, ".metis", "db-environments.yaml"))
    rows = []
    for env, body in (d.get("environments") or {}).items():
        for db in (body or {}).get("databases") or []:
            rows.append("|".join([str(env), str(db.get("label") or ""), str(db.get("engine") or ""), str(db.get("database") or ""),
                                  ",".join(db.get("schemas") or []), str(db.get("warehouse") or ""),
                                  str(db.get("connection") or db.get("repo") or ""), ",".join(db.get("paths") or [])]))
    return d.get("reference_environment") or "", "\n".join(rows)


def save_databases(kb, reference, text):
    envs = {}
    for l in lines(text):
        env, label, engine, database, schemas, warehouse, conn, paths = split_pipe(l, 8)
        if not re.match(r"^[A-Za-z0-9_]+$", env or ""):
            raise C.UiError("Environment '%s' must be letters, digits and _ only." % env)
        if not label or engine not in ENGINES:
            raise C.UiError("Line '%s': give a label and an engine from: %s" % (l, ", ".join(ENGINES)))
        d = {"label": label, "engine": engine, "database": database, "schemas": csv(schemas)}
        if warehouse:
            d["warehouse"] = warehouse
        if engine == "schema-files":
            if not conn or not paths:
                raise C.UiError("Line '%s': a schema-files database needs the repo and its paths (comma separated)." % l)
            d.update(repo=conn, paths=csv(paths))
        else:
            d["connection"] = conn
        envs.setdefault(env, {"docs_dir": "", "databases": []})["databases"].append(d)
    if envs and C.clean(reference) not in envs:
        raise C.UiError("The reference environment must be one of: %s" % ", ".join(envs))
    C.dump_yaml(os.path.join(kb, ".metis", "db-environments.yaml"),
                {"reference_environment": C.clean(reference), "environments": envs},
                "# Databases per environment. Written by the Mētis UI (Setup). Nothing here is guessed.\n")
    return len(envs)


# ---- checks -----------------------------------------------------------------------------------------
def check_connections(kb):
    """[(source, ok, what it says, what to do)]. Read only: git log, folder existence. A database needs a live connection."""
    p = C.profile(kb)
    rows = []
    ws = C.workspace_root(kb, p)
    for name, folder in (C.get(p, "sources.repos") or {}).items():
        base = folder if os.path.isabs(str(folder)) else os.path.join(ws, str(folder))
        if not os.path.isdir(base):
            rows.append((name, False, "folder not found: %s" % base, "clone the repo there, or correct the folder in Setup"))
            continue
        import subprocess
        r = subprocess.run(["git", "-C", base, "log", "-1", "--format=%h"], capture_output=True, text=True, timeout=30)
        if r.returncode:
            rows.append((name, False, "folder is not a git clone", "clone it with git, so every source line has a commit"))
        else:
            rows.append((name, True, "commit %s" % r.stdout.strip(), ""))
    d = C.load_yaml(os.path.join(kb, ".metis", "db-environments.yaml"))
    for env, body in (d.get("environments") or {}).items():
        for db in (body or {}).get("databases") or []:
            who = "%s (%s)" % (db.get("label"), env)
            if db.get("engine") == "schema-files":
                missing = [x for x in db.get("paths") or [] if not os.path.exists(os.path.join(ws, str((C.get(p, "sources.repos") or {}).get(db.get("repo"), db.get("repo"))), x.split("*")[0].rstrip("/")))]
                rows.append((who, not missing, "schema files found" if not missing else "not found: %s" % ", ".join(missing),
                             "" if not missing else "correct the paths in Setup"))
            elif not db.get("connection"):
                rows.append((who, False, "no connection named", "name the read-only Devin connection, or use schema-files"))
            else:
                rows.append((who, None, "connection %s is checked from a Devin session" % db["connection"],
                             "the build's database stage runs the read-only identity check"))
    for kind in ("jira", "confluence"):
        s = C.get(p, "sources.%s" % kind)
        if s:
            rows.append((kind, None, "token secret %s is read from a Devin session" % (s.get("secret") or "(none named)"),
                         "" if s.get("secret") else "name the Devin secret that holds the service-account token"))
    return rows


def lint(kb):
    import prompts
    return C.run_tool("prompts.py", ["lint"] + prompts.live_files(), kb=kb, timeout=300)


# ---- readiness (drives Home and the Build screen) --------------------------------------------------
def readiness(kb):
    """[(key, done, label, detail, link)] in the order a person does them."""
    p = C.profile(kb)
    have_profile = bool(C.real(C.get(p, "product.name")) and C.real(C.get(p, "owners.kb_owner")) and (C.get(p, "sources.repos") or {}))
    det = detected(kb)
    app = approved(kb)
    mods = (C.get(p, "app.modules") or []) + (C.get(p, "etl.modules") or [])
    dbs = C.load_yaml(os.path.join(kb, ".metis", "db-environments.yaml")).get("environments") or {}
    import kb_gate
    locked = kb_gate.is_locked(kb)
    pages = built_pages(kb)
    return [
        ("profile", have_profile, "Project profile", "product, KB owner and repos" if not have_profile else C.get(p, "product.name"), "/setup"),
        ("stack", bool(app), "Tech stack approved", ("approved by %s on %s" % (app.get("approved_by"), app.get("approved_on"))) if app
         else ("detected, waiting for approval" if det else "not detected yet"), "/setup#stack"),
        ("modules", bool(mods), "Modules named", "%d modules" % len(mods) if mods else "none yet; the build needs at least one", "/setup#modules"),
        ("databases", bool(dbs), "Databases (optional)", "%d environments" % len(dbs) if dbs else "none; the build skips the database stage", "/setup#databases"),
        ("built", bool(pages), "KB built", "%d pages" % pages if pages else "not built yet", "/build"),
        ("locked", locked, "KB locked by a lead", "changes now need a lead's certification" if locked else "after the first build is accepted", "/approve"),
    ]


def built_pages(kb):
    import kb_coverage
    try:
        return len(kb_coverage.page_files(kb))
    except Exception:
        return 0
