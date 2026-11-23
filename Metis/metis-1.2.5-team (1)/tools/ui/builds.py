#!/usr/bin/env python3
"""Build the KB from the UI: one run, a list of stages, model stages for Devin and scripted stages the UI runs itself.

    python3 builds.py plan   <kb>                      what a build would do, and what is missing
    python3 builds.py start  <kb> --by NAME            start a run: lint, then queue the model stages
    python3 builds.py status <kb> [RUN]
    python3 builds.py finish <kb> RUN --by NAME        run the scripted stages once every model stage is done

A run is <kb>/_REGEN/<date>-<name>/ (build_plan.py) and its state is <kb>/.metis/builds/<run>.yaml. The model stages follow
`kb-build`: context, one per app module, one per ETL module, db, cross-layer. They write into the run's staging folder. The scripted
stages are the same commands `kb-build` names: verify_kb.py on the staging folder, then either a move into the KB (first build)
or kb_gate.py propose (KB already locked), then build_outputs.py and build_plan.py record. Nothing here writes a KB page itself.
"""
import argparse
import os
import shutil
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import ui_common as C  # noqa: E402
import build_plan  # noqa: E402
import kb_gate  # noqa: E402
import setup_ops  # noqa: E402
import tasks  # noqa: E402

DIR = os.path.join(".metis", "builds")
LOCK = threading.Lock()
SKIP_TOP = ("BUILD.md", "VERIFY.json", "CHECKPOINT.yaml", "_new_questions.yaml", "session")
SCRIPT_STAGES = ("verify", "bring in", "outputs", "record")


def state_path(kb, run):
    return os.path.join(kb, DIR, run + ".yaml")


def runs(kb):
    d = os.path.join(kb, DIR)
    out = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            if n.endswith(".yaml"):
                r = C.load_yaml(os.path.join(d, n))
                if r.get("run"):
                    out.append(r)
    return sorted(out, key=lambda r: (r.get("started") or "", r.get("run") or ""))


def get(kb, run):
    r = C.load_yaml(state_path(kb, run))
    if not r:
        raise C.UiError("no build run %s" % run)
    return r


def save(kb, r):
    C.dump_yaml(state_path(kb, r["run"]), r)


def latest(kb):
    rs = runs(kb)
    return rs[-1] if rs else None


# ---- the plan ------------------------------------------------------------------------------------
def missing(kb):
    """What stops a build, as plain sentences."""
    p = C.profile(kb)
    bad = []
    if not (C.real(C.get(p, "product.name")) and C.real(C.get(p, "owners.kb_owner")) and (C.get(p, "sources.repos") or {})):
        bad.append("The project profile is not complete (Setup: product, KB owner, repos).")
    if not setup_ops.approved(kb):
        bad.append("The tech stack is not approved yet (Setup: detect it, then approve it).")
    if not ((C.get(p, "app.modules") or []) + (C.get(p, "etl.modules") or [])):
        bad.append("No module is named (Setup: app and ETL modules). The build needs at least one.")
    ws = C.workspace_root(kb, p)
    for name, folder in (C.get(p, "sources.repos") or {}).items():
        base = folder if os.path.isabs(str(folder)) else os.path.join(ws, str(folder))
        if not os.path.isdir(base):
            bad.append("Repo %s is not cloned at %s." % (name, base))
    live = [r for r in runs(kb) if r.get("status") == "running"]
    if live:
        bad.append("Run %s is still open; finish or cancel it first." % live[-1]["run"])
    return bad


def model_stages(kb):
    p = C.profile(kb)
    st = [{"name": "context", "label": "Context (Confluence pages and supplied files)"}]
    for m in C.get(p, "app.modules") or []:
        st.append({"name": "app:%s" % m["name"], "label": "Application module %s" % m["name"], "source": m.get("source")})
    for m in C.get(p, "etl.modules") or []:
        st.append({"name": "etl:%s" % m["name"], "label": "ETL module %s" % m["name"], "source": m.get("source")})
    if C.load_yaml(os.path.join(kb, ".metis", "db-environments.yaml")).get("environments"):
        st.append({"name": "db", "label": "Databases and schemas, every environment"})
    st.append({"name": "cross-layer", "label": "Cross-layer: how the layers connect"})
    return st


def instructions(kb, run_dir, stage):
    kbp, name = os.path.abspath(kb), stage["name"]
    head = ("Build one stage of the Metis knowledge base with the `kb-build` skill.\nKB folder: %s\nStaging folder: %s\n"
            "Read only from the sources. Pass --stage %s --rebuild to the stage skill. Every statement cites its source as "
            "[E: ...]; what no source shows becomes a question in %s (python3 <metis>/tools/questions.py add). Never write into the KB "
            "folder itself.\n\n" % (kbp, run_dir, run_dir, os.path.join(run_dir, "_new_questions.yaml")))
    if name == "context":
        body = "Stage: context. Run `kb-context-build --stage %s --rebuild`." % run_dir
    elif name.startswith("app:"):
        body = "Stage: application module %s. Run `app-run-pipeline %s %s --stage %s --rebuild`." % (name[4:], name[4:], stage.get("source"), run_dir)
    elif name.startswith("etl:"):
        body = "Stage: ETL module %s. Run `etl-run-pipeline %s --stage %s --rebuild`." % (name[4:], name[4:], run_dir)
    elif name == "db":
        body = ("Stage: databases. Run `python3 <metis>/tools/db_catalog.py plan %s`, run each catalogue query read only and save the rows, then "
                "`db-run-pipeline --env <reference env> --db <label> --stage %s --rebuild` for each database in the reference environment." % (kbp, run_dir))
    else:
        body = "Stage: cross-layer. Run `db-cross-module --stage %s --rebuild`, then `app-cross-pipeline %s`." % (run_dir, run_dir)
    tail = ("\n\nWhen the stage is written, mark it done and finish the task:\n"
            "  python3 <metis>/tools/build_plan.py done %s \"%s\"\n"
            "  python3 <metis>/tools/ui/tasks.py complete %s <task id> --by \"<your name>\" --note \"<what was built, what was skipped>\"\n"
            % (run_dir, name, kbp))
    return head + body + tail


def start(kb, by):
    if not C.clean(by):
        raise C.UiError("say who is starting the build (top right, 'You are')")
    bad = missing(kb)
    if bad:
        raise C.UiError("The build cannot start yet:\n- " + "\n- ".join(bad))
    code, out = setup_ops.lint(kb)
    if code:
        raise C.UiError("The settings fail the prompt check; fix them in Setup:\n%s" % out[-1500:])
    first = not kb_gate.is_locked(kb)
    run_dir = build_plan.new_run(kb, "kb")
    run = os.path.basename(run_dir)
    stages = []
    for s in model_stages(kb):
        t = tasks.create(kb, "build-stage", "Build %s: %s" % (run, s["label"]), instructions(kb, run_dir, s), by, ref=run, stage=s["name"])
        stages.append({"name": s["name"], "label": s["label"], "kind": "model", "task": t["id"], "status": "queued"})
    for n in SCRIPT_STAGES:
        stages.append({"name": n, "label": {"verify": "Check every line against its source", "bring in": "Bring the pages into the KB" if first
                       else "Propose the pages to a lead", "outputs": "Build graph, matrix, coverage and pages",
                                            "record": "Record the commits this build read"}[n], "kind": "script", "status": "waiting"})
    stale, notes = build_plan.stale(kb)
    r = {"run": run, "stage_dir": run_dir, "started": C.now(), "started_by": C.clean(by), "status": "running", "first_build": first,
         "stages": stages, "stale_pages": len(stale), "notes": notes, "log": []}
    C.write_text(os.path.join(run_dir, "BUILD.md"), "# Build %s\n\n## Change log\n\nStarted %s by %s. %s build.\n" % (
        run, r["started"], C.clean(by), "First" if first else "Incremental"))
    save(kb, r)
    return r


def refresh(kb, r):
    """Bring each model stage's status up to date from its task."""
    for s in r["stages"]:
        if s["kind"] == "model" and s["status"] in ("queued", "running"):
            t = tasks.get(kb, s["task"])
            s["status"] = {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}[t["status"]]
            s["note"] = t.get("note")
    return r


def ready_to_finish(r):
    return all(s["status"] == "done" for s in r["stages"] if s["kind"] == "model")


def cancel(kb, run, by):
    r = get(kb, run)
    for s in r["stages"]:
        if s["kind"] == "model" and s["status"] in ("queued", "running"):
            tasks.cancel(kb, s["task"], by)
            s["status"] = "cancelled"
    r.update(status="cancelled", finished=C.now())
    save(kb, r)
    return r


# ---- scripted stages -------------------------------------------------------------------------------
def staged_files(stage_dir):
    out = []
    for d, dirs, fs in os.walk(stage_dir):
        rel_d = os.path.relpath(d, stage_dir)
        if rel_d == ".":
            dirs[:] = [x for x in dirs if x not in SKIP_TOP and not x.startswith("_")]
        for f in fs:
            rel = os.path.relpath(os.path.join(d, f), stage_dir).replace(os.sep, "/")
            if rel.split("/")[0] in SKIP_TOP:
                continue
            out.append(rel)
    return sorted(out)


def keep_patterns(kb):
    path = os.path.join(kb, ".metis", "kb-keep.yaml")
    if not os.path.isfile(path):
        return []
    import kb_compare
    return kb_compare.load_keep(path)


def do_verify(kb, r):
    code, out = C.run_tool("verify_kb.py", [r["stage_dir"], "--settings", C.profile_path(kb), "--root", C.workspace_root(kb),
                                            "--report", os.path.join(r["stage_dir"], "VERIFY.json")], kb=kb)
    return code == 0, out


def do_bring_in(kb, r):
    files = staged_files(r["stage_dir"])
    if not files:
        return False, "the staging folder has no pages; the model stages wrote nothing"
    if r["first_build"]:
        import kb_compare
        keep, moved, kept = keep_patterns(kb), 0, []
        for rel in files:
            dst = os.path.join(kb, rel)
            if kb_compare.kept_by(rel, keep) and os.path.exists(dst):
                dst = os.path.splitext(dst)[0] + ".NEW" + os.path.splitext(dst)[1]
                kept.append(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(r["stage_dir"], rel), dst)
            moved += 1
        return True, "%d pages moved into the KB%s" % (moved, "; %d kept as .NEW beside the kept file" % len(kept) if kept else "")
    batch = "build-%s" % r["run"]
    try:
        n = kb_gate.propose(kb, batch, r["stage_dir"])
        path, rows = kb_gate.digest(kb, batch)
    except kb_gate.GateError as err:
        return False, str(err)
    r["batch"] = batch
    return True, "%d files proposed as batch %s; a lead certifies them under Approve" % (n, batch)


def do_outputs(kb, r):
    code, out = C.run_tool("build_outputs.py", [kb], kb=kb, timeout=1800)
    return code == 0, out


def do_record(kb, r):
    repos = build_plan.record(kb)
    return True, "recorded %d repo commits" % len(repos)


STEPS = {"verify": do_verify, "bring in": do_bring_in, "outputs": do_outputs, "record": do_record}


def finish(kb, run, by):
    """Run the scripted stages in order. Stops at the first one that does not pass, and says which. Safe to call again."""
    if not C.clean(by):
        raise C.UiError("say who is finishing the build (top right, 'You are')")
    with LOCK:
        r = refresh(kb, get(kb, run))
        if r["status"] != "running":
            raise C.UiError("run %s is %s" % (run, r["status"]))
        if not ready_to_finish(r):
            left = [s["label"] for s in r["stages"] if s["kind"] == "model" and s["status"] != "done"]
            save(kb, r)
            raise C.UiError("These model stages are not finished (a Devin session does them):\n- " + "\n- ".join(left))
        for s in r["stages"]:
            if s["kind"] != "script" or s["status"] == "done":
                continue
            if s["name"] == "outputs" and not r["first_build"] and not kb_gate.is_locked(kb):
                s["status"] = "done"
                continue
            s["status"] = "running"
            save(kb, r)
            ok, out = STEPS[s["name"]](kb, r)
            s.update(status="done" if ok else "failed", output=out[-4000:], at=C.now())
            if s["name"] == "bring in" and ok and not r["first_build"]:
                s["status"] = "done"
            save(kb, r)
            if not ok:
                return r
            if s["name"] == "bring in" and not r["first_build"]:
                # the pages wait for a lead; outputs and record follow the certification, not this call
                for later in r["stages"]:
                    if later["kind"] == "script" and later["status"] == "waiting":
                        later["status"] = "after certification"
                r.update(status="waiting for lead", finished=C.now())
                save(kb, r)
                return r
        r.update(status="done", finished=C.now())
        save(kb, r)
        return r


def finish_later(kb, run, by):
    """Start finish() in the background so a page does not wait for a long output build."""
    t = threading.Thread(target=lambda: _quiet(finish, kb, run, by), daemon=True)
    t.start()
    return t


def _quiet(fn, *a):
    try:
        fn(*a)
    except C.UiError:
        pass


def after_certification(kb, run):
    """Outputs and record, once a lead has certified the proposed batch."""
    r = get(kb, run)
    for s in r["stages"]:
        if s["status"] == "after certification":
            ok, out = STEPS[s["name"]](kb, r)
            s.update(status="done" if ok else "failed", output=out[-4000:], at=C.now())
            save(kb, r)
            if not ok:
                return r
    r.update(status="done")
    save(kb, r)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan"); a.add_argument("kb")
    a = sub.add_parser("start"); a.add_argument("kb"); a.add_argument("--by", required=True)
    a = sub.add_parser("status"); a.add_argument("kb"); a.add_argument("run", nargs="?")
    a = sub.add_parser("finish"); a.add_argument("kb"); a.add_argument("run"); a.add_argument("--by", required=True)
    args = ap.parse_args(argv)
    kb = os.path.abspath(args.kb)
    try:
        if args.cmd == "plan":
            for m in missing(kb):
                print("missing: " + m)
            for s in model_stages(kb):
                print("stage: %s" % s["label"])
        elif args.cmd == "start":
            r = start(kb, args.by)
            print("run %s started; %d stages queued" % (r["run"], sum(1 for s in r["stages"] if s["kind"] == "model")))
        elif args.cmd == "status":
            r = refresh(kb, get(kb, args.run) if args.run else (latest(kb) or {}))
            for s in r.get("stages") or []:
                print("%-14s %-10s %s" % (s["status"], s["kind"], s["label"]))
        else:
            r = finish(kb, args.run, args.by)
            print("run %s: %s" % (r["run"], r["status"]))
    except C.UiError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
