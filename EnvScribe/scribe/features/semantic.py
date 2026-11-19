"""Feature 8 - Hybrid search for Ask: BM25 (exact terms) fused with a vector ranking.

Default vector model: local sparse TF-IDF over word stems and character trigrams. It tolerates spelling variants, plurals, camelCase/snake_case and
partial words, but it is NOT a language-model embedding and does not understand synonyms. For true semantic matching pass `embedder`
(a callable list[str] -> list[vector], for example a watsonx or Ollama embeddings call; UNVERIFIED here). Either way the grounding rule stays:
a result must pass a relevance threshold or the answer is "not found".
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable

from ..facts import fact_text
from ..knowledge import Index, tokens

COS_MIN = 0.35        # below this cosine a vector-only hit is ignored
RRF_K = 60


def _feats(text: str) -> Counter:
    c: Counter = Counter()
    for t in tokens(text):
        stem = t[:-1] if len(t) > 3 and t.endswith("s") else t
        c["w:" + stem] += 1
        p = f"^{stem}$"
        for i in range(len(p) - 2):
            c["g:" + p[i:i + 3]] += 1
    return c


class HybridIndex(Index):
    def __init__(self, facts: list[dict], embedder: Callable[[list[str]], list[list[float]]] | None = None):
        super().__init__(facts)
        self.embedder = embedder
        self._vec: dict[str, dict[str, float]] = {}
        self._norm: dict[str, float] = {}
        self._finv: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._dense: dict[str, list[float]] = {}
        df: Counter = Counter()
        raw = {}
        for fid, f in self.facts.items():
            c = _feats(fact_text(f))
            raw[fid] = c
            df.update(c.keys())
        n = max(len(raw), 1)
        self._idf = {k: math.log(1 + n / (v + 0.5)) for k, v in df.items()}
        for fid, c in raw.items():
            vec = {k: (1 + math.log(v)) * self._idf[k] for k, v in c.items()}
            nm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
            self._vec[fid], self._norm[fid] = vec, nm
            for k, w in vec.items():
                self._finv[k].append((fid, w / nm))
        if embedder and self.facts:
            ids = list(self.facts)
            for i in range(0, len(ids), 64):
                batch = ids[i:i + 64]
                for fid, v in zip(batch, embedder([fact_text(self.facts[x]) for x in batch])):
                    self._dense[fid] = _unit(v)

    @classmethod
    def from_journal(cls, journal_dir, embedder=None) -> "HybridIndex":
        from ..util import read_jsonl
        from pathlib import Path
        return cls(read_jsonl(Path(journal_dir) / "facts" / "all-facts.jsonl"), embedder)

    def _cosine(self, query: str) -> dict[str, float]:
        if self.embedder and self._dense:
            q = _unit(self.embedder([query])[0])
            return {fid: sum(a * b for a, b in zip(q, v)) for fid, v in self._dense.items()}
        qc = _feats(query)
        qv = {k: (1 + math.log(v)) * self._idf[k] for k, v in qc.items() if k in self._idf}
        qn = math.sqrt(sum(x * x for x in qv.values())) or 1.0
        acc: dict[str, float] = defaultdict(float)
        for k, w in qv.items():
            for fid, dw in self._finv.get(k, ()):
                acc[fid] += (w / qn) * dw
        return acc

    def search(self, query: str, k: int = 12, kinds: set[str] | None = None) -> list[tuple[float, dict]]:
        bm = {f["id"]: s for s, f in super().search(query, 200, kinds)}
        cos = {fid: c for fid, c in self._cosine(query).items() if c >= COS_MIN and (not kinds or self.facts[fid]["kind"] in kinds)}
        ranks: dict[str, float] = defaultdict(float)
        for r, (fid, _) in enumerate(sorted(bm.items(), key=lambda x: (-x[1], x[0]))):
            ranks[fid] += 1 / (RRF_K + r)
        for r, (fid, _) in enumerate(sorted(cos.items(), key=lambda x: (-x[1], x[0]))):
            ranks[fid] += 1 / (RRF_K + r)
        out = []
        for fid, _ in sorted(ranks.items(), key=lambda x: (-x[1], x[0]))[:k]:
            # report on the BM25 scale so the existing "not found" gate (score >= 1.0) keeps its meaning
            out.append((max(bm.get(fid, 0.0), 4 * cos.get(fid, 0.0)), self.facts[fid]))
        return out


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
