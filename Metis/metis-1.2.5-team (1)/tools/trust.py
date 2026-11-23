#!/usr/bin/env python3
"""Trust signals: the facts a reviewer or a model needs to judge a link or a page, shown raw. No score, no confidence band.

    python3 trust.py page <kb> REL [REL ...]       signals for KB pages
    python3 trust.py edge <kb> NODE [--limit 40]   signals for every link touching a graph node (e.g. table:APP.ORDERS)

An edge (a link in the graph) shows:
  origin           parsed (a program read it), catalogue (a database catalogue), or ai-proposed (a model wrote it)
  quote            "verified": its source tag resolves and carries a quote that is found in the source;
                   "resolves, no quote": the tag resolves but quotes nothing; "does not resolve: <why>"
  source           "unchanged since build", "changed since build", or "cannot compare" (the repo has no recorded commit or no clone);
                   left out for sources that are not a repo file (query, file, doc, answer tags)
A page shows:
  tags / problems  how many source tags it has and how many source problems verify_kb finds in it
  sources          whether any repo file it cites changed since the build (build_plan.py), with the first reasons
  page changed     the KB commit that last touched it (git; blank without history)
  certified        who certified it and when, and whether it has changed since (only when the gate is locked)
  blocked by       open questions that name the page under `blocks`, with priority

These are facts read from the KB and git, not judgements. A verified quote means the words are in the source, not that the
statement drawn from them is right.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_plan  # noqa: E402
import graph_store  # noqa: E402
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402
import questions  # noqa: E402
import verify_kb  # noqa: E402

REPO_CITE = build_plan.CITE


class Trust:
    def __init__(self, kb):
        self.kb = os.path.abspath(kb)
        self.checker = verify_kb.Checker(self.kb)
        self.notes = []
        try:
            self.changed, more = build_plan.changed_since_build(self.kb)
            self.notes += more
        except Exception as exc:  # no git, no clone: signals about change are unknown, the rest still work
            self.changed = None
            self.notes.append("source change not available: %s" % exc)
        self._commits = None
        self._edge = {}
        self._pages = {}
        reg = questions.load(questions.reg_path(self.kb)).get("questions") or []
        self.open_q = [q for q in reg if q.get("status") == "open"]
        self.gate = kb_gate.load_state(self.kb) if kb_gate.is_locked(self.kb) else None

    # ---- edges ----------------------------------------------------------------------------
    def edge(self, origin, source):
        """{origin, quote, source}: raw signals for one link and its source tag."""
        key = (origin, source)
        if key not in self._edge:
            self._edge[key] = {"origin": origin or "unknown", **self._source(source)}
        return self._edge[key]

    def _source(self, source):
        parts = [p.strip() for k, v in verify_kb.TAG.findall(str(source or "")) if k == "E" for p in v.split(";") if p.strip()]
        if not parts:
            return {"quote": "no source tag", "source": None}
        worst, quotes, states = None, 0, set()
        for part in parts:
            why = self.checker.resolve("E", part)
            if why:
                worst = worst or why
            elif '"' in part:
                quotes += 1
            m = REPO_CITE.match(part)
            if m and self.changed is not None and m.group(1) in self.changed:
                files = self.changed[m.group(1)]
                states.add("cannot compare" if files is None else "changed since build" if m.group(2) in files else "unchanged since build")
        change = next((s for s in ("changed since build", "cannot compare", "unchanged since build") if s in states), None)
        if worst:
            quote = "does not resolve: %s" % worst
        elif quotes == len(parts):
            quote = "verified"
        else:
            quote = "resolves, no quote"
        return {"quote": quote, "source": change}

    @staticmethod
    def edge_text(sig):
        bits = ["quote " + sig["quote"] if sig["quote"] != "verified" else "quote verified"]
        if sig.get("source"):
            bits.append("source " + sig["source"])
        return "; ".join(bits)

    # ---- pages ----------------------------------------------------------------------------
    def commits(self):
        if self._commits is None:
            self._commits = kb_manifest.last_commits(self.kb)
        return self._commits

    def page(self, rel):
        if rel not in self._pages:
            self._pages[rel] = self._page(rel)
        return self._pages[rel]

    def _page(self, rel):
        path = os.path.join(self.kb, rel)
        if not os.path.isfile(path):
            raise ValueError("not a KB file: %s" % rel)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        problems, counts = [], {"tags": 0, "fact_lines": 0}
        if rel.endswith(".md"):
            self.checker.check_text(rel, text, problems, counts)
        elif rel.endswith((".yaml", ".yml")):
            self.checker.check_yaml(rel, text, problems, counts)
        reasons = None
        if self.changed is not None:
            reasons = []
            for repo, paths in sorted(build_plan.cited_files(self.kb).get(rel, {}).items()):
                if repo not in self.changed:
                    continue
                if self.changed[repo] is None:
                    reasons.append("%s: cannot compare" % repo)
                else:
                    reasons += ["%s/%s changed" % (repo, p) for p in sorted(paths) if p in self.changed[repo]]
        cert = None
        if self.gate is not None:
            c = (self.gate.get("files") or {}).get(rel)
            if c:
                cert = {"by": c.get("by"), "on": str(c.get("on")), "unchanged": kb_gate.sha_file(path) == c.get("sha256")}
            else:
                cert = {"by": None, "on": None, "unchanged": False}
        blocked = []
        for q in self.open_q:
            b = q.get("blocks") or []
            if rel in (b if isinstance(b, list) else [b]):
                blocked.append({"id": q.get("id"), "priority": q.get("priority")})
        return {"page": rel, "tags": counts["tags"], "problems": len(problems), "sources_changed": reasons,
                "page_changed": self.commits().get(rel), "certified": cert, "blocked_by": blocked}

    @staticmethod
    def page_text(sig, with_questions=True):
        out = ["%d tags, %d source problems" % (sig["tags"], sig["problems"])]
        if sig["sources_changed"] is None:
            out.append("sources: change not known")
        elif sig["sources_changed"]:
            out.append("sources changed since build (%s)" % "; ".join(sig["sources_changed"][:2]))
        else:
            out.append("cited sources unchanged since build")
        if sig["page_changed"]:
            out.append("page last changed " + sig["page_changed"])
        c = sig["certified"]
        if c is not None:
            out.append("not certified" if not c["by"] else "certified by %s on %s%s" % (c["by"], c["on"], "" if c["unchanged"] else ", changed since"))
        if with_questions and sig["blocked_by"]:
            out.append("blocked by " + ", ".join("%s (%s)" % (b["id"], b["priority"]) for b in sig["blocked_by"]))
        return "; ".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("page"); a.add_argument("kb"); a.add_argument("files", nargs="+")
    a = sub.add_parser("edge"); a.add_argument("kb"); a.add_argument("node"); a.add_argument("--limit", type=int, default=40)
    a.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        t = Trust(args.kb)
        if args.cmd == "page":
            for rel in args.files:
                print("%s: %s" % (rel, t.page_text(t.page(rel))))
        else:
            edges = graph_store.around(os.path.abspath(args.kb), args.node)
            if not edges:
                print("no links touch %s" % args.node)
            for e in edges[:args.limit]:
                s = t.edge(e["origin"], e["source"])
                print("%s -%s-> %s [%s] %s" % (e["from"], e["rel"], e["to"], s["origin"], t.edge_text(s)))
        for n in t.notes:
            print("note: " + n, file=sys.stderr)
    except ValueError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
