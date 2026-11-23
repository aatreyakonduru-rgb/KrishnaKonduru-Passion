#!/usr/bin/env python3
"""Check that every line of a Metis knowledge base can be traced to a source.

    python3 verify_kb.py <kb folder> [--settings <kb-profile.yaml>] [--root <workspace>] [--report out.json]
    python3 verify_kb.py <kb folder> --answer <file.md>    check one answer file (kept outside the KB) instead

A fact carries an evidence tag. The tag forms, and what each one must point at:

    [E: <repo>/<path>:<line>[-<line>] ["quoted text"]]   a line range in a source repo; the quote, when
                                                           given, must appear in those lines
    [E: query:<id>]          <kb>/_EVIDENCE/queries/<id>.sql and <id>.json (the query and its result)
    [E: confluence:<page>@v<n>]  <kb>/_EVIDENCE/confluence/<page>-v<n>.txt (page text saved at read time)
    [E: jira:<KEY-1>]        <kb>/_EVIDENCE/jira/<KEY-1>.json
    [E: file:<name>]         <kb>/_EVIDENCE/files/<name> (a document the team supplied)
    [E: file:<name> "quote"] the quote must appear in that file (required when verify.strict_tags is true in the settings)
    [E: doc:<id>#<place> "quote"]  an uploaded document kept out of the repo; the quote must be listed as
                             checked for that place in <kb>/_EVIDENCE/documents/DOC_SOURCES.yaml
    [E: answer:Q-0001]       an answered question in <kb>/_QUESTIONS/VALIDATE_KB.yaml
    [E: kb:<path>]           another file in this knowledge base
    [E: kb:<path> "quote"]   the quote must appear in that KB file (kb:<path>:<line>[-<line>] "quote" for lines)
    [E: settings:<key>]      a key in the Metis settings file
    [?: Q-0001]              not known; the question must be in the register

`[A]` (an assumption) is not allowed: an unsupported statement becomes a question.
A bullet, numbered item, table row or paragraph needs a tag on the line itself or on the nearest
heading above it. Lines under a heading named Open questions, Don't know, Sources, Evidence,
Contents, Change log or Not in the KB are exempt, as are code blocks and front matter.
Exit code 0 when everything resolves, 1 otherwise.

What a pass means: every tag points at something that exists, and a quoted text appears in it.
It does not mean the statement is correct. A quote can be present and still be read wrongly.
Use llm_judge.py (citation support) and a lead's review for that; the judge's agreement with
people has not been measured.
"""
CAVEAT = ("Note: a pass shows each tag resolves and each quote is in its source, not that the statement is right.")
import argparse
import json
import os
import re
import sys

import yaml

TAG = re.compile(r"\[(E|\?):\s*([^\]]+)\]")
BARE = re.compile(r"\[(A|\?|E)\]")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
EXEMPT = re.compile(r"open questions|don.t know|not in the kb|sources|evidence|contents|change log|question register",
                    re.I)
LINE_REF = re.compile(r'^([^:\s]+):(\d+)(?:-(\d+))?(?:\s+"(.*)")?$')
QID = re.compile(r"^Q-\d{4,}$")


def load_yaml(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_key(data, dotted):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


class Checker:
    def __init__(self, kb, settings_path=None, root=None):
        self.kb = os.path.abspath(kb)
        self.settings_path = settings_path or os.path.join(self.kb, ".metis", "kb-profile.yaml")
        self.settings = load_yaml(self.settings_path)
        self.root = os.path.abspath(root or get_key(self.settings, "sources.workspace_root") or
                                    os.path.dirname(os.path.dirname(self.kb)))
        self.repos = get_key(self.settings, "sources.repos") or {}
        stack = os.path.join(kb, ".metis", "stack.yaml")
        if os.path.isfile(stack):
            with open(stack, encoding="utf-8") as fh:
                for k, v in ((yaml.safe_load(fh) or {}).get("repos") or {}).items():
                    self.repos.setdefault(k, v)
        reg = load_yaml(os.path.join(self.kb, "_QUESTIONS", "VALIDATE_KB.yaml"))
        self.questions = {q.get("id"): q for q in (reg.get("questions") or []) if isinstance(q, dict)}
        self.documents = load_yaml(os.path.join(self.kb, "_EVIDENCE", "documents", "DOC_SOURCES.yaml")).get("documents") or {}
        self._files = {}
        self.strict = bool(get_key(self.settings, "verify.strict_tags"))

    def repo_path(self, ref):
        repo, _, rest = ref.partition("/")
        base = self.repos.get(repo)
        if base is None:
            return None, "repo '%s' is not listed under sources.repos" % repo
        base = base if os.path.isabs(base) else os.path.join(self.root, base)
        return os.path.join(base, rest), None

    def lines(self, path):
        if path not in self._files:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self._files[path] = fh.read().splitlines()
        return self._files[path]

    def resolve(self, kind, value):
        """Return None when the tag resolves, else the reason it does not."""
        value = value.strip()
        if kind == "?":
            if not QID.match(value):
                return "not-known tag needs a question id, e.g. [?: Q-0001]"
            return None if value in self.questions else "question %s is not in the register" % value
        scheme, sep, rest = value.partition(":")
        if sep and scheme in ("query", "confluence", "jira", "file", "doc", "answer", "kb", "settings"):
            rest = rest.strip()
            ev = os.path.join(self.kb, "_EVIDENCE")
            if scheme == "query":
                miss = [p for p in (rest + ".sql", rest + ".json")
                        if not os.path.isfile(os.path.join(ev, "queries", p))]
                return "saved query missing: %s" % ", ".join(miss) if miss else None
            if scheme == "confluence":
                m = re.match(r"^(\d+)@v(\d+)$", rest)
                if not m:
                    return "confluence tag must be confluence:<page id>@v<version>"
                p = os.path.join(ev, "confluence", "%s-v%s.txt" % m.groups())
                return None if os.path.isfile(p) else "page snapshot missing: %s" % os.path.relpath(p, self.kb)
            if scheme == "jira":
                p = os.path.join(ev, "jira", rest + ".json")
                return None if os.path.isfile(p) else "issue snapshot missing: %s" % os.path.relpath(p, self.kb)
            if scheme == "file":
                m = re.match(r'^([^"\s]+)(?:\s+"(.+)")?$', rest)
                if not m:
                    return 'file tag must be file:<name> or file:<name> "quote"'
                name, quote = m.groups()
                p = os.path.join(ev, "files", name)
                if not os.path.isfile(p):
                    return "supplied file missing: _EVIDENCE/files/%s" % name
                if quote:
                    if " ".join(quote.split()).lower() not in " ".join(" ".join(self.lines(p)).split()).lower():
                        return "quoted text not found in _EVIDENCE/files/%s" % name
                elif self.strict:
                    return "file tag needs a quote in strict mode: file:%s \"quoted text\"" % name
                return None
            if scheme == "doc":
                m = re.match(r'^([\w.-]+)#(\S+)\s+"(.+)"$', rest)
                if not m:
                    return 'doc tag must be doc:<id>#<place> "quoted text"'
                did, place, quote = m.groups()
                d = self.documents.get(did)
                if not d:
                    return "document %s is not in _EVIDENCE/documents/DOC_SOURCES.yaml" % did
                want = (place, " ".join(quote.split()).lower())
                if want not in {(c.get("place"), " ".join(str(c.get("quote", "")).split()).lower())
                                for c in d.get("checked") or []}:
                    return "quote at %s#%s was not checked against the document" % (did, place)
                return None
            if scheme == "answer":
                q = self.questions.get(rest)
                if not q:
                    return "question %s is not in the register" % rest
                if q.get("status") not in ("answered", "closed") or not q.get("answer") or not q.get("answered_by"):
                    return "question %s has no recorded answer and answerer" % rest
                return None
            if scheme == "kb":
                m = re.match(r'^([^:"\s]+)(?::(\d+)(?:-(\d+))?)?(?:\s+"(.+)")?$', rest)
                if not m:
                    return 'kb tag must be kb:<path>, kb:<path> "quote" or kb:<path>:<line> "quote"'
                rel, a, b, quote = m.groups()
                p = os.path.join(self.kb, rel)
                if not os.path.exists(p):
                    return "KB file missing: %s" % rel
                if not (a or quote):
                    return None if not self.strict else "kb tag needs a quote or lines in strict mode: kb:%s \"quoted text\"" % rel
                if not os.path.isfile(p):
                    return "KB path %s is a folder; a quote needs a file" % rel
                text = self.lines(p)
                if a:
                    a, b = int(a), int(b or a)
                    if a < 1 or b < a or b > len(text):
                        return "lines %d-%d outside KB file %s (%d lines)" % (a, b, rel, len(text))
                    text = text[a - 1:b]
                if quote and " ".join(quote.split()).lower() not in " ".join(" ".join(text).split()).lower():
                    return "quoted text not found in KB file %s" % rel
                return None
            if scheme == "settings":
                return None if get_key(self.settings, rest) is not None else "settings key missing: %s" % rest
        m = LINE_REF.match(value)
        if not m:
            return "unrecognised source '%s'" % value
        ref, a, b, quote = m.groups()
        path, err = self.repo_path(ref)
        if err:
            return err
        if not os.path.isfile(path):
            return "file not found: %s" % ref
        text = self.lines(path)
        a, b = int(a), int(b or a)
        if a < 1 or b < a or b > len(text):
            return "lines %d-%d outside %s (%d lines)" % (a, b, ref, len(text))
        if quote and quote not in "\n".join(text[a - 1:b]):
            return "quoted text not found in %s:%d-%d" % (ref, a, b)
        return None

    def check_text(self, rel, text, problems, counts):
        heading_tagged, exempt, in_code, in_front = False, False, False, False
        for n, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if n == 1 and s == "---":
                in_front = True
                continue
            if in_front:
                in_front = s != "---"
                continue
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for bare in BARE.finditer(line):
                problems.append((rel, n, "bare [%s] tag; use a source or a question id" % bare.group(1)))
            tags = TAG.findall(line)
            for kind, value in tags:
                counts["tags"] += 1
                for part in value.split(";"):
                    reason = self.resolve(kind, part)
                    if reason:
                        problems.append((rel, n, reason))
            h = HEADING.match(s)
            if h:
                exempt = bool(EXEMPT.search(h.group(2)))
                heading_tagged = bool(tags)
                continue
            if not s or exempt or heading_tagged or s.startswith(("<!--", "|---", "| ---", ">")):
                continue
            if re.match(r"^\|?\s*:?-{3,}", s):
                continue
            counts["fact_lines"] += 1
            if not tags:
                if s.startswith("|") and counts.get("_table_header") != (rel, n - 1):
                    nxt = text.splitlines()[n] if n < len(text.splitlines()) else ""
                    if re.match(r"^\s*\|?\s*:?-{3,}", nxt):
                        counts["_table_header"] = (rel, n)
                        counts["fact_lines"] -= 1
                        continue
                problems.append((rel, n, "no source tag: %s" % s[:90]))

    def check_yaml(self, rel, text, problems, counts):
        for n, line in enumerate(text.splitlines(), 1):
            line = line.replace("''", "'").replace('\\"', '"')
            for kind, value in TAG.findall(line):
                counts["tags"] += 1
                for part in value.split(";"):
                    reason = self.resolve(kind, part)
                    if reason:
                        problems.append((rel, n, reason))
            for bare in BARE.finditer(line):
                problems.append((rel, n, "bare [%s] tag; use a source or a question id" % bare.group(1)))

    def check_answer(self, path):
        self.strict = True  # an answer is always checked to the words it relies on
        problems, counts = [], {"tags": 0, "fact_lines": 0}
        with open(path, encoding="utf-8") as fh:
            self.check_text(os.path.basename(path), fh.read(), problems, counts)
        counts.pop("_table_header", None)
        return {"kb": self.kb, "files": 1, "problems": [
            {"file": f, "line": n, "problem": p} for f, n, p in problems], **counts}

    def run(self):
        problems, counts, files = [], {"tags": 0, "fact_lines": 0}, 0
        for dirpath, dirnames, filenames in os.walk(self.kb):
            dirnames[:] = [d for d in dirnames if d not in ("_EVIDENCE", ".metis", "Archive", ".git", "_PENDING", "_FEEDBACK", "_REGEN")]
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, self.kb)
                if rel.startswith("_QUESTIONS"):
                    continue
                if name.endswith(".md"):
                    files += 1
                    with open(path, encoding="utf-8") as fh:
                        self.check_text(rel, fh.read(), problems, counts)
                elif name.endswith((".yaml", ".yml")):
                    files += 1
                    with open(path, encoding="utf-8") as fh:
                        self.check_yaml(rel, fh.read(), problems, counts)
        counts.pop("_table_header", None)
        return {"kb": self.kb, "files": files, "problems": [
            {"file": f, "line": n, "problem": p} for f, n, p in problems], **counts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kb")
    ap.add_argument("--settings")
    ap.add_argument("--root", help="folder that holds the source repos (default: sources.workspace_root)")
    ap.add_argument("--report", help="write the result as JSON to this file")
    ap.add_argument("--answer", help="check this one answer file against the KB instead of the whole KB")
    args = ap.parse_args(argv)
    checker = Checker(args.kb, args.settings, args.root)
    result = checker.check_answer(args.answer) if args.answer else checker.run()
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    for p in result["problems"][:200]:
        print("%s:%d: %s" % (p["file"], p["line"], p["problem"]))
    print("Checked %d files, %d tags, %d fact lines: %d problems." % (
        result["files"], result["tags"], result["fact_lines"], len(result["problems"])))
    print(CAVEAT)
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
