"""Knowledge access over the journal facts: keyword/BM25-style retrieval, cited Q&A, and Advise (grounded context + labeled PROPOSAL).

Deterministic by default. An optional `llm` callable may draft the PROPOSAL text; its output is verified in code and always labeled.
If retrieval finds nothing, the answer is "not found in the journal" - never a guess from general knowledge.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from .facts import fact_text
from .util import read_jsonl

_TOK = re.compile(r"[A-Za-z0-9_]+")
_STOP = {"the", "a", "an", "of", "to", "in", "and", "or", "is", "are", "for", "on", "with", "what", "which", "how", "does", "do", "we", "it", "this",
         "that", "be", "by", "as", "at", "from", "add", "new", "should", "need", "needs", "want"}


def tokens(text: str) -> list[str]:
    out = []
    for w in _TOK.findall(text):
        for part in re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", w).replace("_", " ").split():
            p = part.lower()
            if len(p) > 1 and p not in _STOP:
                out.append(p)
    return out


class Index:
    def __init__(self, facts: list[dict]):
        self.facts = {f["id"]: f for f in facts}
        self.tf: dict[str, Counter] = {}
        self.df: Counter = Counter()
        self.len: dict[str, int] = {}
        self.inv: dict[str, set[str]] = defaultdict(set)
        for f in facts:
            toks = tokens(fact_text(f))
            self.tf[f["id"]] = Counter(toks)
            self.len[f["id"]] = len(toks) or 1
            for t in set(toks):
                self.df[t] += 1
                self.inv[t].add(f["id"])
        self.avg = (sum(self.len.values()) / len(self.len)) if self.len else 1

    @classmethod
    def from_journal(cls, journal_dir: str | Path) -> "Index":
        return cls(read_jsonl(Path(journal_dir) / "facts" / "all-facts.jsonl"))

    def search(self, query: str, k: int = 12, kinds: set[str] | None = None) -> list[tuple[float, dict]]:
        q = tokens(query)
        n = len(self.facts) or 1
        scores: dict[str, float] = defaultdict(float)
        for t in q:
            for fid in self.inv.get(t, ()):
                f = self.facts[fid]
                if kinds and f["kind"] not in kinds:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                tf = self.tf[fid][t]
                scores[fid] += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * self.len[fid] / self.avg))
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:k]
        return [(s, self.facts[fid]) for fid, s in ranked]


def cite(f: dict) -> str:
    e = f["evidence"][0]
    return f"{e['source']} {e['location']}"


def verify_citations(text: str, idx: Index) -> list[str]:
    """Deterministic check: every `source location` citation in `text` must exist in the facts store."""
    valid = {cite(f) for f in idx.facts.values()}
    bad = []
    for m in re.finditer(r"\[\[(.+?)\]\]", text):
        if m.group(1) not in valid:
            bad.append(m.group(1))
    return bad


def ask(idx: Index, question: str, k: int = 8) -> dict:
    hits = idx.search(question, k)
    if not hits or hits[0][0] < 1.0:
        return {"answer": "Not found in the journal. No fact matched this question, and I will not answer from general knowledge.",
                "found": False, "citations": [], "classes": []}
    lines, cites = [], []
    for score, f in hits:
        a = f["attrs"]
        summary = a.get("text") or a.get("path") or a.get("key") or f["subject"]
        lines.append(f"- [{f['class']}] {f['kind']}: {str(f['subject'])[:120]} - {str(summary)[:160]} [[{cite(f)}]]")
        cites.append(cite(f))
    return {"answer": "Matching facts from the journal (ranked by relevance; as-of times are in each fact):\n" + "\n".join(lines),
            "found": True, "citations": cites, "classes": sorted({f['class'] for _, f in hits}),
            "note": "DOCUMENTED/DISCUSSED items are claims from documents or meetings, not verified against code."}


def advise(idx: Index, requirement: str, llm: Callable[[str], str] | None = None) -> dict:
    """Grounded context (cited, from facts) + PROPOSAL (labeled, suggest-only). Nothing is executed or written."""
    if not requirement.strip():
        return {"error": "empty requirement"}
    hits = idx.search(requirement, 40)
    if not hits:
        return {"grounded_context": [], "proposal": None, "insufficient_information": True,
                "message": "Nothing in the journal relates to this requirement. Rephrase it, name the service/endpoint/table involved, or run a crawl that covers it."}
    ctx: dict[str, list] = defaultdict(list)
    seen = set()
    for _, f in hits:
        key = (f["kind"], f["subject"])
        if key in seen:
            continue
        seen.add(key)
        ctx[f["kind"]].append({"subject": f["subject"], "class": f["class"], "citation": cite(f)})
    affected_files = sorted({f"{f['attrs'].get('repo')}/{f['attrs'].get('path') or f['attrs'].get('file')}" for _, f in hits
                             if f["attrs"].get("repo") and (f["attrs"].get("path") or f["attrs"].get("file"))})
    envs = sorted({f["attrs"].get("environment") for _, f in hits if f["attrs"].get("environment")})
    open_q = []
    if not any(k in ctx for k in ("endpoint", "api_operation")):
        open_q.append("No API endpoint matched; which interface does this change touch?")
    if not envs:
        open_q.append("Which environments (DEV/SIT/UAT) need configuration changes?")
    if not any(k in ctx for k in ("table_reference", "db_table", "db_column")):
        open_q.append("Does this require a data model change? No table reference matched.")
    proposal = {
        "label": "PROPOSAL - unverified. Not compiled, not tested, not executed. Review before use.",
        "files_to_review": affected_files[:40],
        "checklist": ["Confirm each cited file still matches the journal (facts are as of the crawl time).",
                      "Update API contract(s) first if an operation changes; check consumers listed under cross-links.",
                      "Add or change configuration per environment where listed; the environment matrix shows today's differences.",
                      "Add tests alongside each changed file.", "Check pipelines that deploy the affected service."],
        "assumptions": ["The journal reflects the repositories as of its collation time.", "Only static analysis was used; runtime behavior is unknown."],
        "open_questions": open_q,
        "draft_pr_description": f"Title: {requirement.strip()[:80]}\n\nContext: see cited facts. Affected files (from journal): {', '.join(affected_files[:10]) or 'none identified'}.\n"
                                "Status: DRAFT proposal text only.",
        "diff": None,
    }
    if llm:
        prompt = ("Using ONLY the facts below, draft code change suggestions for the requirement. Cite facts as [[source location]]. "
                  "If facts are insufficient, say so. Do not invent files, endpoints or tables.\n\nREQUIREMENT: " + requirement + "\n\nFACTS:\n" +
                  "\n".join(f"- {f['kind']} {f['subject']} [[{cite(f)}]]" for _, f in hits[:30]))
        draft = llm(prompt)
        bad = verify_citations(draft, idx)
        proposal["diff"] = ("[REJECTED by verifier: draft cited sources that do not exist: " + ", ".join(bad[:5]) + "]") if bad else draft
        proposal["llm_draft_verified"] = not bad
    return {"grounded_context": {k: v[:25] for k, v in ctx.items()}, "environments_involved": envs, "proposal": proposal, "insufficient_information": False}
