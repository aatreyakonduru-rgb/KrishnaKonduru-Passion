#!/usr/bin/env python3
"""Run every Metis output step on a KB folder, in order, then check every source.

    python3 build_outputs.py <kb>

table registry (if the catalogue queries are saved) -> SQL links read by the parser (needs sqlglot; skipped with a message
if it is not installed) -> ontology and link graph -> impact matrix and QA
coverage -> ERD and semantic model -> KB coverage report -> VALIDATE_KB page -> VISUALIZATION pages -> manifest -> verify_kb.
Exits 1 if verify_kb reports a problem, or, once the KB is locked, if a file is not certified or a golden question
relies on a file that is gone.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_coverage  # noqa: E402
import gen_db_assets  # noqa: E402
import gen_graph  # noqa: E402
import gen_matrix  # noqa: E402
import gen_registry  # noqa: E402
import gen_visuals  # noqa: E402
import golden  # noqa: E402
import sql_links  # noqa: E402
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402


def optional(name, fn, *args):
    """Run an optional step. A failure is printed and never stops the build or changes its exit code."""
    try:
        return fn(*args)
    except SystemExit as err:
        print("%s: skipped (%s)" % (name, err.code))
    except Exception as err:  # noqa: BLE001
        print("%s: skipped (%s: %s)" % (name, type(err).__name__, err))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    kb = argv[0]
    gen_registry.main([kb])
    sql_links.main([kb])  # exit 2 (sqlglot missing) is printed, not fatal: the other steps still run
    import code_links, column_lineage  # noqa: E402,E401
    optional("code_links", code_links.main, [kb])
    optional("column_lineage", column_lineage.main, ["build", kb])
    gen_graph.main([kb])
    gen_matrix.main([kb])
    gen_db_assets.main([kb])
    kb_coverage.main([kb])
    if os.path.isfile(os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml")):
        questions.main(["html", kb])
    gen_visuals.main([kb])
    import kb_contradict, kb_dupes, kb_links, kb_trend  # noqa: E402,E401
    optional("contradictions", lambda: kb_contradict.write_report(kb, kb_contradict.build(kb)))
    optional("duplicates", lambda: kb_dupes.write_report(kb, kb_dupes.build(kb)))
    optional("link check", lambda: kb_links.write_report(kb, kb_links.check(kb)))
    kb_manifest.main(["generate", kb])
    rep = verify_kb.Checker(kb).run()
    optional("trend", kb_trend.record, kb, rep)
    for p in rep["problems"]:
        print("%s:%s %s" % (p["file"], p["line"], p["problem"]))
    print("verify: %d files, %d tags, %d problems" % (rep["files"], rep["tags"], len(rep["problems"])))
    gate_problems, locked = kb_gate.check(kb)
    if locked:
        gate_problems = gate_problems + golden.static(kb)
        for g in gate_problems:
            print("gate: %s" % g)
        print("gate: %d problems (certification and golden questions)" % len(gate_problems))
    return 1 if rep["problems"] or gate_problems else 0


if __name__ == "__main__":
    sys.exit(main())
