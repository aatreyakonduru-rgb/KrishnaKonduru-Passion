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

CAVEAT = ("Note: a pass shows each tag resolves and each quote is in its source, not that the statement is right.")
ANSWER_SUPPORT_MIN = 0.2   # an answer line must share at least this part of its words with the quotes behind it
STOPWORDS = frozenset("a an the of to in on for is are was were be been being and or but if then than that this these those it its as at by "
                      "with from into out up down over under not no yes do does did has have had can could will would should may might "
                      "each every any all some one two per via also only more most other such what which who whom how when where why "
                      "their there them they we our you your he she his her i me my".split())
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
SYNONYMS = {  # code words and the plain words that mean them: a claim in prose about a quote in code
    "ignorecase": {"case", "insensitive"}, "materialized": {"built", "table", "view", "materialize"},
    "varchar": {"text", "string", "character"}, "int": {"integer", "number"}, "integer": {"number", "int"},
    "pk": {"primary", "key"}, "fk": {"foreign", "key"}, "ref": {"reference", "references", "depends"},
    "src": {"source"}, "stg": {"staging", "stage"}, "dim": {"dimension"}, "fct": {"fact"}, "tbl": {"table"},
}


def stem_word(w):
    w = w.lower()
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def content_words(text):
    """Stemmed content words of a text: the nouns, names and verbs a statement is about (no stop words, no short tokens).
    Code names are split (VARCHAR_IGNORECASE, ownerId, last_name) and a few code words add the plain words that mean them."""
    out = set()
    for tok in WORD.findall(text):
        parts = [p for p in re.split(r"_+", tok) if p]
        pieces = list(parts)
        for p in parts:
            pieces += CAMEL.findall(p)
        for w in pieces:
            lw = w.lower()
            if len(lw) < 3 or lw in STOPWORDS:
                continue
            out.add(stem_word(lw))
            for extra in SYNONYMS.get(lw, ()):
                out.add(stem_word(extra))
    return out


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
        sm = get_key(self.settings, "verify.support_min")
        self.support_min = float(sm) if isinstance(sm, (int, float)) and not isinstance(sm, bool) else 0.0

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
        if not quote and self.strict:
            return "line tag needs a quote in strict mode: %s:%d-%d \"quoted text\"" % (ref, a, b)
        return None

    def cited_text(self, kind, value):
        """The source words a tag stands behind: its quote when it has one, else None. Used to ask whether the statement
        is about them (check_support); a tag without a quote gives no words to compare, so it is left to strict mode."""
        for part in value.split(";"):
            m = re.search(r'"(.+)"\s*$', part.strip())
            if m:
                yield m.group(1)

    def check_support(self, rel, n, line, tags, problems):
        """Does the statement talk about what it cites? A fact line whose content words share none (or almost none) with the
        quotes behind it is a real citation put under an unrelated claim. This is a lexical screen, not a judge: it cannot say a
        sentence is right, only that it is not about its source. Off unless verify.support_min is set (0 to 1, e.g. 0.2);
        answers are checked with a low default."""
        if not self.support_min or not tags:
            return
        if re.match(r"^\s*(?:[-*]|\d+[.)])?\s*Inferred:", line):  # a stated inference combines lines; it is shown as one, not screened
            return
        quotes = [q for kind, value in tags if kind == "E" for q in self.cited_text(kind, value)]
        if not quotes:
            return
        claim = content_words(TAG.sub(" ", line))
        if len(claim) < 4:  # too short to judge
            return
        cited = content_words(" ".join(quotes))
        if not cited:
            return
        share = len(claim & cited) / float(min(len(claim), len(cited)))
        if share < self.support_min:
            problems.append((rel, n, "statement shares %d%% of its words with the text it cites (needs %d%%): %s"
                             % (round(share * 100), round(self.support_min * 100), " ".join(line.split())[:80])))

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
            self.check_support(rel, n, line, tags, problems)
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
        self.support_min = self.support_min or ANSWER_SUPPORT_MIN
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
