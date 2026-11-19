#!/usr/bin/env python3
"""QA-suite coverage from the ACME/claims-qa Behave suite, read only: nothing is written there.

Writes QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.yaml (and .md): which scenarios test each business object,
screen and table, which have none, the step library, the query and TestData catalogue, and the gaps. A scenario
tests a table only when one of its steps reaches a query key whose SQL reads it, and a screen only when one of its
steps uses the Page element that links to the route (kbgen/behave_links.py). Nothing is matched by name.

    python3 sdlc/framework/tools/kbgen/gen_qa_suite.py            # rebuild
    python3 sdlc/framework/tools/kbgen/gen_qa_suite.py --check    # exit 1 when stale

Prints one `[SDLC] qa` line for Argus Trace. When claims-qa is not on this machine the committed files are
kept and the line says `not run`.
"""
import argparse
import datetime
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import behave_links  # noqa: E402
import gen_ontology  # noqa: E402

REPO = gen_ontology.REPO
KB = gen_ontology.KB
OUT = KB + "/QA-AUTOMATION-DERIVED/03_QA_SUITE_COVERAGE.yaml"
GENERATOR = "sdlc/framework/tools/kbgen/gen_qa_suite.py"
WHY = "new scenarios reuse the suite's steps, and a story's change picks the existing scenarios that test it"


def object_tables(o):
    tables = [o.get("table")] + [(o.get("status") or {}).get("table")] + list(o.get("related_tables") or [])
    return [t for t in dict.fromkeys(tables) if t]


def build(suite, objects, matrix):
    scen = suite["scenarios"]
    by_table, by_route = {}, {}
    for sc in scen:
        for t in sc["tables"]:
            by_table.setdefault(t, []).append(sc["id"])
        for r in sc["screens"]:
            by_route.setdefault(r, []).append(sc["id"])
    obj_rows = []
    for o in objects:
        tables = object_tables(o)
        ids = sorted({i for t in tables for i in by_table.get(t, [])})
        obj_rows.append({"id": o["id"], "label": o["label"], "tables": tables, "scenarios": len(ids),
                         "by_table": {t: len(by_table[t]) for t in tables if t in by_table}, "scenario_ids": ids})
    screens = matrix.get("screens") or {}
    screen_rows = [{"route": r, "scenarios": len(by_route.get(r, [])), "scenario_ids": sorted(by_route.get(r, []))}
                   for r in sorted(screens)]
    query_of = {}
    for k, q in suite["queries"].items():
        for t in q["tables"]:
            query_of.setdefault(t.split(".")[-1].upper(), []).append(k)
    table_rows = [{"table": t, "scenarios": len(ids), "query_keys": sorted(query_of.get(t, [])), "scenario_ids": sorted(ids)}
                  for t, ids in sorted(by_table.items())]
    app_tables = sorted(t for t, v in (matrix.get("tables") or {}).items() if v.get("api"))
    unmatched = {}
    for sc in scen:
        for u in sc["unmatched"]:
            unmatched.setdefault(u["text"], []).append("%s:%d" % (sc["feature"], u["line"]))
    steps = sorted(suite["steps"], key=lambda s: (s["file"], s["line"]))
    return {
        "metadata": {
            "name": "QA-suite coverage",
            "generated": datetime.date.today().isoformat(),
            "generator": GENERATOR,
            "source": {"repo": suite["repo"], "branch": suite["branch"], "commit": suite["commit"]},
            "rule": "Read only from the QA repository at this commit. A scenario tests a table only through a query key its "
                    "steps reach, and a screen only through the Page element its steps use. Coverage is per scenario, "
                    "not end to end; a table or screen with no scenario here may still be tested by hand or in qTest.",
            "counts": {"feature_files": suite["features"], "scenarios": len(scen), "step_definitions": len(steps),
                       "query_keys": len(suite["queries"]), "test_data_sets": len(suite["data_sets"]),
                       "field_mappings": len(suite["field_mappings"]),
                       "unmatched_steps": sum(len(v) for v in unmatched.values())},
        },
        "objects": obj_rows,
        "screens": screen_rows,
        "tables": table_rows,
        "untested": {
            "objects": [o["id"] for o in obj_rows if not o["scenarios"]],
            "screens": [s["route"] for s in screen_rows if not s["scenarios"]],
            "app_tables": [t for t in app_tables if t not in by_table],
        },
        "scenarios": [{"id": sc["id"], "at": "%s:%d" % (sc["feature"], sc["line"]), "name": sc["name"], "tags": sc["tags"],
                       "stories": sc["stories"], "steps": sc["steps"], "tables": sorted(sc["tables"]),
                       "screens": sorted(sc["screens"]), "data_sets": sc["data_sets"], "unmatched_steps": len(sc["unmatched"])}
                      for sc in scen],
        "step_library": [{"keyword": s["keyword"], "pattern": s["pattern"], "at": "%s:%d" % (s["file"], s["line"]),
                          "function": s["function"], "used_by_steps": s["used"]} for s in steps],
        "queries": [{"key": k, "file": q["file"], "tables": q["tables"], "named_at": suite["key_at"].get(k)}
                    for k, q in sorted(suite["queries"].items())],
        "test_data": {"sets": [{"set": k, "file": f} for k, f in sorted(suite["data_sets"].items())],
                      "field_mappings": sorted(suite["field_mappings"])},
        "gaps": {
            "unmatched_steps": [{"text": t, "at": at} for t, at in sorted(unmatched.items())],
            "queries_not_named_in_code": sorted(k for k in suite["queries"] if k not in suite["key_at"]),
            "step_definitions_unused": ["%s:%d" % (s["file"], s["line"]) for s in steps if not s["used"]],
            "scenarios_without_story_tag": sum(1 for sc in scen if not sc["stories"]),
            "not_followed": "query keys built at run time, and Page methods more than two calls below a step",
        },
    }


def md(cov):
    m, c = cov["metadata"], cov["metadata"]["counts"]
    src = m["source"]
    out = ["# QA-suite coverage — `%s`" % src["repo"], "",
           "Generated by `%s` from branch `%s`, commit `%s`. Do not edit by hand; re-run the generator." % (
               m["generator"], src["branch"], (src["commit"] or "?")[:8]), "",
           m["rule"], "",
           "%d feature files, %d scenarios, %d step definitions, %d query keys, %d TestData sets, %d field mappings, "
           "%d steps that match no step definition." % (c["feature_files"], c["scenarios"], c["step_definitions"],
                                                        c["query_keys"], c["test_data_sets"], c["field_mappings"],
                                                        c["unmatched_steps"]), "",
           "## Business objects", "", "| Object | Scenarios | Tables they check |", "|---|---|---|"]
    for o in cov["objects"]:
        out.append("| %s | %d | %s |" % (o["label"], o["scenarios"],
                                          ", ".join("`%s` (%d)" % kv for kv in o["by_table"].items()) or "—"))
    out += ["", "## Screens", "", "| Route | Scenarios |", "|---|---|"]
    out += ["| `%s` | %d |" % (s["route"], s["scenarios"]) for s in cov["screens"]]
    out += ["", "## Tables the scenarios check", "", "| Table | Scenarios | Query keys |", "|---|---|---|"]
    out += ["| `%s` | %d | %s |" % (t["table"], t["scenarios"], ", ".join("`%s`" % k for k in t["query_keys"])) for t in cov["tables"]]
    u = cov["untested"]
    out += ["", "## Not tested by any scenario", "",
            "- Objects: %s" % (", ".join(u["objects"]) or "none"),
            "- Screens: %s" % (", ".join("`%s`" % r for r in u["screens"]) or "none"),
            "- Tables the API reads or writes: %d — %s" % (len(u["app_tables"]), ", ".join("`%s`" % t for t in u["app_tables"]) or "none"),
            "", "## Step library", "", "| Keyword | Step | Defined at | Used by steps |", "|---|---|---|---|"]
    out += ["| %s | %s | `%s` | %d |" % (s["keyword"], s["pattern"].replace("|", "\\|"), s["at"], s["used_by_steps"])
            for s in cov["step_library"]]
    out += ["", "## Query keys", "", "| Key | File | Tables | Named in code at |", "|---|---|---|---|"]
    out += ["| `%s` | `%s` | %s | %s |" % (q["key"], q["file"], ", ".join("`%s`" % t for t in q["tables"]),
                                         "`%s`" % q["named_at"] if q["named_at"] else "not named (built at run time?)")
            for q in cov["queries"]]
    td = cov["test_data"]
    files = {}
    for s in td["sets"]:
        files.setdefault(s["file"], []).append(s["set"])
    out += ["", "## TestData", "", "| File | Sets |", "|---|---|"]
    out += ["| `%s` | %d |" % (f, len(v)) for f, v in sorted(files.items())]
    out += ["", "Field mappings: " + ", ".join("`%s`" % f for f in td["field_mappings"])]
    g = cov["gaps"]
    out += ["", "## Gaps", "",
            "- %d scenarios carry no `@ACME-1234` story tag, so they link to no Jira story." % g["scenarios_without_story_tag"],
            "- Not followed: %s." % g["not_followed"],
            "- Step definitions no scenario uses: %d." % len(g["step_definitions_unused"]),
            "", "Steps that match no step definition:", "", "| Step | Where |", "|---|---|"]
    out += ["| %s | %s |" % (x["text"].replace("|", "\\|"), ", ".join("`%s`" % a for a in x["at"][:3]) +
                             (" and %d more" % (len(x["at"]) - 3) if len(x["at"]) > 3 else "")) for x in g["unmatched_steps"]]
    return "\n".join(out) + "\n"


def inputs():
    objects = gen_ontology.build_objects(gen_ontology.load("entities"), gen_ontology.load("semantic"))
    return objects, gen_ontology.load("app_matrix")


def write(cov, yml):
    with open(yml, "w", encoding="utf-8") as fh:
        fh.write("# QA-suite coverage — generated by %s. Do not edit by hand; re-run it.\n" % GENERATOR)
        yaml.safe_dump(cov, fh, sort_keys=False, allow_unicode=True, width=120)
    with open(yml[:-5] + ".md", "w", encoding="utf-8") as fh:
        fh.write(md(cov))


def body(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [ln for ln in fh.read().splitlines() if not ln.startswith("  generated:")]
    except OSError:
        return None


def run(check=False, repo=None, out=None):
    """Returns (result, detail): result is current, updated, stale or not run."""
    out = out or os.path.join(REPO, OUT)
    suite = behave_links.scan(repo)
    if suite is None:
        return "not run", "%s is not on this machine; the committed coverage is kept" % behave_links.QA_NAME
    cov = build(suite, *inputs())
    c = cov["metadata"]["counts"]
    read = "read %s %s@%s: %d feature files, %d scenarios, %d step definitions, %d query keys, %d TestData sets" % (
        suite["repo"], suite["branch"], (suite["commit"] or "?")[:8], c["feature_files"], c["scenarios"],
        c["step_definitions"], c["query_keys"], c["test_data_sets"])
    tmp = out + ".check.tmp"
    try:
        write(cov, tmp)
        same = body(tmp) == body(out) and body(tmp[:-5] + ".md") == body(out[:-5] + ".md")
        if same:
            return "current", read
        if check:
            return "stale", read + "; run python3 " + GENERATOR
        os.replace(tmp, out)
        os.replace(tmp[:-5] + ".md", out[:-5] + ".md")
        return "updated", read
    finally:
        for p in (tmp, tmp[:-5] + ".md"):
            if os.path.exists(p):
                os.remove(p)


def trace_line(result, detail):
    return "[SDLC] qa %s — %s; why: %s; result: %s" % (os.path.basename(OUT), detail, WHY, result)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when stale")
    ap.add_argument("--qa-repo", help="the claims-qa checkout (default $CLAIMS_QA_REPO or ~/repos/claims-qa)")
    a = ap.parse_args(argv)
    result, detail = run(a.check, a.qa_repo)
    print(trace_line(result, detail))
    return 1 if result == "stale" else 0


if __name__ == "__main__":
    sys.exit(main())
