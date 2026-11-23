#!/usr/bin/env python3
"""Ask a judge whether a cited source text supports a claim, and set that beside the lexical golden score. Never replaces it.

    python3 llm_judge.py citations    <kb> <file.md> [--judge file|http]   judge each cited line of a KB page or an answer file
    python3 llm_judge.py golden_judge <kb> <answers dir> [--judge file|http]
                                       the lexical result of golden.py and the judged result, side by side, per golden question
    python3 llm_judge.py status       <kb>                                requests waiting, verdicts read
    python3 llm_judge.py collect      <kb>                                list the verdicts found

A judge reads a request and answers `supported`, `partial` or `unsupported` with a reason. What it is asked is narrow: does the
quoted source text support the claim as written. A `supported` verdict means "supported by the quoted source text". It does not
mean the claim is correct, the source is current, or the KB is right. The judge is a model; it can be wrong.

Two judges ship, behind one interface (`Judge.judge(request)` returns a verdict, or None while it is still pending):

  FileJudge  writes <kb>/.metis/judge/requests/J-xxxx.json (claim, quote, source window, expected pages). A Devin/Bob session
             reads them and writes <kb>/.metis/judge/verdicts/J-xxxx.json: {"id", "verdict", "reason", "judged_by"}.
             Run the command again and the verdicts are read. Needs a session; nothing here calls a model.
  HttpJudge  an OpenAI-compatible chat endpoint (stdlib urllib). Profile keys under `judge`: endpoint (the full chat completions
             URL), model, api_key_env (the NAME of an environment variable that holds the key; the key is never stored or
             logged), timeout (seconds, default 60). https is required unless the host is this machine. The request text, which
             contains KB lines and source text, goes to that endpoint: use one your organisation approves.
             Needs your environment to verify: it is tested only against a fake.

The judge folder is local (a .gitignore of `*`). Request ids hash the claim, quote and source window, so a changed line gets a new
request and an old verdict is never reused for it.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feedback  # noqa: E402
import golden  # noqa: E402
import verify_kb  # noqa: E402

DIR = os.path.join(".metis", "judge")
VERDICTS = ("supported", "partial", "unsupported")
SAYS = {"supported": "supported by the quoted source text", "partial": "partly supported by the quoted source text",
        "unsupported": "not supported by the quoted source text"}
NOTE = ("A judged verdict reads the quoted source text only. It does not say the claim is correct, the source is current, "
        "or the KB is right.")
INSTRUCTIONS = ("Decide whether the source text supports the claim as written. Use only the source text given. Answer with a verdict "
                "(supported = every part of the claim is stated or directly implied by the source text; partial = some parts are, some "
                "are not; unsupported = the source text does not state it or says otherwise) and a one-sentence reason. "
                "Do not say whether the claim is true in the world. Do not use outside knowledge.")
WINDOW_CHARS = 1500
GOLDEN_CHARS = 3000
HEAD = re.compile(r"^#{1,6}\s")


class JudgeError(ValueError):
    pass


def judge_dir(kb, *parts):
    return os.path.join(kb, DIR, *parts)


def guard(kb):
    folder = judge_dir(kb)
    os.makedirs(folder, exist_ok=True)
    g = os.path.join(folder, ".gitignore")
    if not os.path.isfile(g):
        with open(g, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("*\n")


def request_id(req):
    key = json.dumps([req.get("kind"), req.get("claim"), req.get("quote"), req.get("source_window"), req.get("expected_pages"),
                      req.get("question")], sort_keys=True)
    return "J-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def check_verdict(v, want_id=None):
    """The verdict dict, cleaned, or JudgeError."""
    if not isinstance(v, dict):
        raise JudgeError("a verdict is an object with id, verdict and reason")
    if want_id and v.get("id") != want_id:
        raise JudgeError("verdict id %s does not match the request %s" % (v.get("id"), want_id))
    if v.get("verdict") not in VERDICTS:
        raise JudgeError("verdict must be one of %s, not %r" % (", ".join(VERDICTS), v.get("verdict")))
    if not str(v.get("reason") or "").strip():
        raise JudgeError("a verdict needs a reason")
    return {"id": v.get("id"), "verdict": v["verdict"], "reason": " ".join(str(v["reason"]).split())[:400],
            "judged_by": str(v.get("judged_by") or "unnamed judge")}


# ---- the judges -------------------------------------------------------------------------------
class Judge(object):
    """judge(request) -> verdict dict {id, verdict, reason, judged_by}, or None while the verdict is pending."""
    name = "judge"

    def judge(self, request):
        raise NotImplementedError


class FileJudge(Judge):
    name = "file"

    def __init__(self, kb):
        self.kb = kb

    def request_path(self, rid):
        return judge_dir(self.kb, "requests", rid + ".json")

    def verdict_path(self, rid):
        return judge_dir(self.kb, "verdicts", rid + ".json")

    def judge(self, request):
        rid = request["id"]
        vp = self.verdict_path(rid)
        if os.path.isfile(vp):
            try:
                with open(vp, encoding="utf-8") as fh:
                    return check_verdict(json.load(fh), rid)
            except (ValueError, OSError) as err:
                raise JudgeError("%s: %s" % (os.path.relpath(vp, self.kb).replace(os.sep, "/"), err))
        rp = self.request_path(rid)
        if not os.path.isfile(rp) and len(request) > 1:
            guard(self.kb)
            os.makedirs(os.path.dirname(rp), exist_ok=True)
            os.makedirs(os.path.dirname(vp), exist_ok=True)
            with open(rp, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(dict(request, instructions=INSTRUCTIONS, write_verdict_to=os.path.relpath(vp, self.kb).replace(os.sep, "/"),
                               verdict_format={"id": rid, "verdict": "supported|partial|unsupported", "reason": "one sentence",
                                               "judged_by": "your name or session"}), fh, indent=2, ensure_ascii=False)
        return None


class HttpJudge(Judge):
    name = "http"

    def __init__(self, endpoint, model, api_key_env, timeout=60, opener=None, environ=None):
        u = urllib.parse.urlparse(endpoint or "")
        if u.scheme not in ("http", "https") or not u.netloc:
            raise JudgeError("judge.endpoint must be an http(s) URL")
        if u.scheme == "http" and (u.hostname or "") not in ("127.0.0.1", "localhost", "::1"):
            raise JudgeError("judge.endpoint must be https unless it is on this machine")
        if not model:
            raise JudgeError("judge.model is not set")
        self.endpoint, self.model, self.api_key_env, self.timeout = endpoint, model, api_key_env, timeout
        self.opener = opener or urllib.request.urlopen
        self.environ = os.environ if environ is None else environ

    def prompt(self, request):
        parts = [INSTRUCTIONS, 'Reply with only a JSON object: {"verdict": "supported|partial|unsupported", "reason": "one sentence"}.']
        if request.get("question"):
            parts.append("Question: %s" % request["question"])
        parts.append("Claim:\n%s" % request["claim"])
        if request.get("quote"):
            parts.append("Quoted text:\n%s" % request["quote"])
        parts.append("Source text:\n%s" % request["source_window"])
        return "\n\n".join(parts)

    def judge(self, request):
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            key = self.environ.get(self.api_key_env)
            if not key:
                raise JudgeError("the environment variable %s is not set (judge.api_key_env)" % self.api_key_env)
            headers["Authorization"] = "Bearer " + key
        body = json.dumps({"model": self.model, "temperature": 0,
                           "messages": [{"role": "user", "content": self.prompt(request)}]}).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            text = data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as err:
            raise JudgeError("the judge endpoint answered HTTP %s" % err.code)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as err:
            raise JudgeError("the judge endpoint could not be used: %s" % type(err).__name__)
        m = re.search(r"\{.*\}", str(text), re.S)
        try:
            got = json.loads(m.group(0)) if m else None
        except ValueError:
            got = None
        if not isinstance(got, dict):
            raise JudgeError("the judge did not answer with a JSON verdict")
        got = dict(got, id=request["id"], judged_by="http:" + self.model)
        got["verdict"] = str(got.get("verdict", "")).strip().lower()
        return check_verdict(got, request["id"])


def judge_from_profile(kb, kind=None, opener=None, environ=None):
    """The judge to use: `kind` file or http; by default http when judge.endpoint is in the profile, else file."""
    prof = verify_kb.load_yaml(os.path.join(kb, ".metis", "kb-profile.yaml"))
    cfg = prof.get("judge") if isinstance(prof.get("judge"), dict) else {}
    endpoint = str(cfg.get("endpoint") or "").strip()
    if endpoint.startswith("<"):
        endpoint = ""
    kind = kind or ("http" if endpoint else "file")
    if kind == "file":
        return FileJudge(kb)
    if kind != "http":
        raise JudgeError("judge must be file or http")
    if not endpoint:
        raise JudgeError("judge.endpoint is not set in .metis/kb-profile.yaml")
    return HttpJudge(endpoint, cfg.get("model"), cfg.get("api_key_env"), int(cfg.get("timeout") or 60), opener, environ)


# ---- requests: the claim, the quote, the source window ---------------------------------------
def squash(s):
    return " ".join(str(s).split())


def clip(text, n=WINDOW_CHARS):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


def window_around(lines, a, b, pad=2):
    lo, hi = max(1, a - pad), min(len(lines), b + pad)
    return "\n".join("%d: %s" % (i, lines[i - 1]) for i in range(lo, hi + 1))


def quote_window(lines, quote, pad=3):
    first = squash(quote.split("\n")[0]).lower()
    for i, l in enumerate(lines, 1):
        if first and first in squash(l).lower():
            return window_around(lines, i, i, pad)
    if first and first in squash(" ".join(lines)).lower():  # the quote crosses a line break: show the text from the top
        return "\n".join(lines)
    return None


def evidence_file(kb, scheme, rest):
    ev = os.path.join(kb, "_EVIDENCE")
    if scheme == "file":
        return os.path.join(ev, "files", rest)
    if scheme == "jira":
        return os.path.join(ev, "jira", rest + ".json")
    if scheme == "confluence":
        m = re.match(r"^(\d+)@v(\d+)$", rest)
        return os.path.join(ev, "confluence", "%s-v%s.txt" % m.groups()) if m else None
    if scheme == "query":
        return os.path.join(ev, "queries", rest + ".json")
    return None


def resolve_source(chk, part):
    """(label, quote, window) for one tag part, or (None, None, reason) when no source text can be shown to a judge."""
    part = part.strip()
    scheme, sep, rest = part.partition(":")
    rest = rest.strip()
    if sep and scheme in ("kb", "file", "jira", "confluence", "query", "doc", "answer", "settings"):
        m = re.match(r'^(.*?)(?:\s+"(.+)")?$', rest, re.S)
        ref, quote = m.group(1).strip(), m.group(2)
        if scheme == "kb":
            mm = re.match(r"^([^:\s]+)(?::(\d+)(?:-(\d+))?)?$", ref)
            if not mm:
                return None, None, "unreadable kb reference"
            rel, a, b = mm.groups()
            path = os.path.join(chk.kb, rel)
            if not os.path.isfile(path):
                return None, None, "KB file not found: %s" % rel
            lines = chk.lines(path)
            label = "kb:%s" % rel + (":%s%s" % (a, "-" + b if b else "") if a else "")
            if a:
                if int(a) < 1 or int(b or a) > len(lines):
                    return None, None, "lines outside %s" % rel
                win = window_around(lines, int(a), int(b or a))
            else:
                win = quote_window(lines, quote, 3) if quote else "\n".join(lines[:25])
        elif scheme in ("file", "jira", "confluence", "query"):
            path = evidence_file(chk.kb, scheme, ref)
            if not path or not os.path.isfile(path):
                return None, None, "source snapshot not found: %s:%s" % (scheme, ref)
            lines = chk.lines(path)
            label = "%s:%s" % (scheme, ref)
            win = (quote_window(lines, quote, 3) if quote else None) or "\n".join(lines[:25])
        else:
            return None, None, "a %s source is not shown to a judge" % scheme
    else:
        mm = verify_kb.LINE_REF.match(part)
        if not mm:
            return None, None, "unrecognised source"
        ref, a, b, quote = mm.groups()
        path, err = chk.repo_path(ref)
        if err or not os.path.isfile(path):
            return None, None, err or "file not found: %s" % ref
        lines = chk.lines(path)
        a, b = int(a), int(b or a)
        if a < 1 or b > len(lines) or b < a:
            return None, None, "lines outside %s" % ref
        label, win = "%s:%d-%d" % (ref, a, b), window_around(lines, a, b)
    return label, quote, clip(win or "")


def claim_text(line):
    t = verify_kb.TAG.sub("", line)
    t = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", t.strip())
    t = t.strip().strip("|").replace("|", " | ")
    return squash(t)


def citation_requests(kb, text, label="", checker=None):
    """[(request, lexical)] for every tagged fact line in a page or answer. lexical is None when verify_kb's check passes, else why not."""
    chk = checker or verify_kb.Checker(kb)
    out, in_code, in_front = [], False, False
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
        if in_code or HEAD.match(s):
            continue
        claim = claim_text(line)
        for kind, value in verify_kb.TAG.findall(line):
            if kind != "E" or not claim:
                continue
            for part in value.split(";"):
                lab, quote, win = resolve_source(chk, part)
                if lab is None:
                    out.append(({"id": None, "kind": "citation", "claim": claim, "where": "%s:%d" % (label, n), "source": part.strip(),
                                 "unavailable": win}, win))
                    continue
                req = {"kind": "citation", "claim": claim, "quote": quote or "", "source": lab, "source_window": win, "expected_pages": [],
                       "where": "%s:%d" % (label, n)}
                req["id"] = request_id(req)
                out.append((req, chk.resolve("E", part)))
    return out


def run_judge(judge, request):
    """{status: judged|pending|error|unavailable, verdict, reason, says}: one request through a judge."""
    if request.get("unavailable"):
        return {"status": "unavailable", "reason": request["unavailable"]}
    try:
        v = judge.judge(request)
    except JudgeError as err:
        return {"status": "error", "reason": str(err)}
    if v is None:
        return {"status": "pending", "reason": "waiting for a verdict in %s" % (DIR + "/verdicts/" + request["id"] + ".json").replace(os.sep, "/")}
    return {"status": "judged", "verdict": v["verdict"], "reason": v["reason"], "says": SAYS[v["verdict"]], "judged_by": v["judged_by"]}


def judge_citations(kb, text, judge, label=""):
    """One row per citation: the lexical result from verify_kb beside the judged result."""
    rows = []
    for req, lexical in citation_requests(kb, text, label):
        r = run_judge(judge, req)
        rows.append({"id": req.get("id"), "where": req["where"], "claim": req["claim"], "source": req.get("source"),
                     "lexical": "quote and lines check out" if lexical is None else lexical, "judged": r})
    return rows


# ---- golden: lexical and judged side by side --------------------------------------------------
def answer_claims(text):
    """The fact lines of an answer (no headings, no tags) joined, and the quotes it cites."""
    lines = [claim_text(l) for l in text.splitlines() if verify_kb.TAG.search(l) and not HEAD.match(l.strip())]
    _, quotes = feedback.cited(text)
    return "\n".join(l for l in lines if l), quotes


def expected_window(kb, pages):
    out, each = [], max(400, GOLDEN_CHARS // max(1, len(pages)))
    for rel in pages:
        p = os.path.join(kb, rel)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                out.append("== %s ==\n%s" % (rel, clip(fh.read(), each)))
    return "\n\n".join(out)


def golden_request(kb, g, answer_text):
    claim, quotes = answer_claims(answer_text)
    req = {"kind": "golden", "question": g["question"], "claim": clip(claim or squash(answer_text), GOLDEN_CHARS),
           "quote": " | ".join(quotes)[:600], "source": "expected pages", "source_window": expected_window(kb, g["cite"]),
           "expected_pages": list(g["cite"]), "must_include": list(g.get("include") or []), "where": g["id"]}
    req["id"] = request_id(req)
    return req


def golden_judge(kb, answers, judge):
    """Per golden question: the lexical result of golden.score untouched, and the judged result beside it.

    `flag` is set when the two disagree (lexical pass but judged unsupported, or lexical fail but judged supported); it is a
    reason to read the answer, not a ruling."""
    lex = {r["id"]: r for r in golden.score(kb, answers)}
    rows = []
    for g in golden.load(kb).get("golden") or []:
        lexical = lex[g["id"]]
        row = {"id": g["id"], "question": g["question"], "lexical": {"result": lexical["result"], "why": lexical["why"]}}
        p = os.path.join(answers, g["id"] + ".md")
        if not os.path.isfile(p):
            row["judged"] = {"status": "no answer", "reason": "no answer file"}
        else:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            row["judged"] = run_judge(judge, golden_request(kb, g, text))
            row["citations"] = judge_citations(kb, text, judge, g["id"] + ".md")
        v = row["judged"].get("verdict")
        row["flag"] = ("lexical pass, judged unsupported" if lexical["result"] == "pass" and v == "unsupported" else
                       "lexical fail, judged supported" if lexical["result"] == "fail" and v == "supported" else "")
        rows.append(row)
    return rows


def summary(rows):
    c = {"supported": 0, "partial": 0, "unsupported": 0, "pending": 0, "error": 0, "other": 0}
    for r in rows:
        j = r["judged"] if "judged" in r else r
        k = j.get("verdict") if j.get("status") == "judged" else j.get("status")
        c[k if k in c else "other"] += 1
    return c


# ---- what is on disk --------------------------------------------------------------------------
def list_requests(kb):
    """[{id, where, kind, status, verdict, reason}] for every request file; status is judged, pending or error."""
    out, fj = [], FileJudge(kb)
    folder = judge_dir(kb, "requests")
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                req = json.load(fh)
        except (ValueError, OSError):
            continue
        row = {"id": req.get("id", name[:-5]), "kind": req.get("kind"), "where": req.get("where"), "claim": req.get("claim", ""),
               "source": req.get("source")}
        try:
            v = fj.judge({"id": row["id"]})
        except JudgeError as err:
            row.update(status="error", reason=str(err))
        else:
            if v is None:
                row.update(status="pending", reason="")
            else:
                row.update(status="judged", verdict=v["verdict"], reason=v["reason"], judged_by=v["judged_by"], says=SAYS[v["verdict"]])
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("citations"); c.add_argument("kb"); c.add_argument("file"); c.add_argument("--judge", choices=("file", "http"))
    g = sub.add_parser("golden_judge"); g.add_argument("kb"); g.add_argument("answers"); g.add_argument("--judge", choices=("file", "http"))
    s = sub.add_parser("status"); s.add_argument("kb")
    s = sub.add_parser("collect"); s.add_argument("kb")
    a = ap.parse_args(argv)
    kb = os.path.abspath(a.kb)
    try:
        if a.cmd in ("status", "collect"):
            rows = list_requests(kb)
            for r in rows:
                print("%s %-8s %-11s %s" % (r["id"], r["status"], r.get("verdict", ""), (r.get("where") or "")))
            n = {k: sum(1 for r in rows if r["status"] == k) for k in ("judged", "pending", "error")}
            print("judge: %d requests, %d judged, %d waiting, %d with a problem" % (len(rows), n["judged"], n["pending"], n["error"]))
            return 0
        judge = judge_from_profile(kb, a.judge)
        if a.cmd == "citations":
            with open(a.file, encoding="utf-8") as fh:
                rows = judge_citations(kb, fh.read(), judge, os.path.basename(a.file))
            for r in rows:
                j = r["judged"]
                print("%s %s: %s [lexical: %s]" % (r["where"], r["id"] or "-", j.get("says") or "%s (%s)" % (j["status"], j.get("reason", "")), r["lexical"]))
            print("judge: %s" % (", ".join("%d %s" % (v, k) for k, v in summary(rows).items() if v) or "no citations"))
            print(NOTE)
            return 0
        rows = golden_judge(kb, os.path.abspath(a.answers), judge)
        for r in rows:
            j = r["judged"]
            print("%s lexical %-7s | judged %s%s%s" % (r["id"], r["lexical"]["result"], j.get("says") or "%s (%s)" % (j["status"], j.get("reason", "")),
                                                     "; " + j["reason"] if j.get("says") else "", "  <- " + r["flag"] if r["flag"] else ""))
        print("golden_judge: %d questions; %s" % (len(rows), ", ".join("%d %s" % (v, k) for k, v in summary(rows).items() if v) or "none"))
        print(NOTE)
        return 0
    except (JudgeError, golden.GoldenError, OSError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
