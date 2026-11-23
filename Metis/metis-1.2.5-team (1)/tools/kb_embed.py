#!/usr/bin/env python3
"""Optional hybrid search: keyword (BM25) plus vector similarity, fused by reciprocal rank. Off by default.

    python3 kb_embed.py build  <kb> [--embedder SPEC]            embed every chunk into <kb>/.metis/search.sqlite (table vec)
    python3 kb_embed.py query  <kb> "words" [--embedder SPEC]    hybrid results (BM25 + vectors)
    python3 kb_embed.py status <kb>                              which embedder built the vectors, how many chunks
    python3 kb_embed.py eval   <kb> [--k 1,3,5,10] [--embedder SPEC] [--json]
                                                                 score BM25 alone against hybrid on the golden questions

Turn it on in the KB profile (default is off, and nothing here runs unless it is on):

    search:
      hybrid: true                  # false (the default) = keyword search only
      embedder: hashing             # hashing | sentence-transformers[:model] | a mapping, see below

Embedders (all behind the `Embedder` interface: `embed(texts) -> unit vectors`, `name`, optional `fit`):
  hashing                 built in, no packages, deterministic: stemmed words, word pairs and character trigrams hashed into
                          256 buckets, weighted by TF-IDF fitted on this KB. It matches word shape (owner / owners / ownr),
                          not meaning. It is the fallback and the baseline `eval` is judged against.
  sentence-transformers   `pip install sentence-transformers`; runs a local model (default all-MiniLM-L6-v2). Guarded import:
                          without the package it says so and keyword search carries on. Needs your environment to verify.
  http                    an embedding endpoint that takes {"model":..., "input":[...]} and answers {"data":[{"embedding":[...]}]}
                          (the usual shape), or {"embeddings":[[...]]}. Mapping keys: type: http, url, model, api_key_env (the NAME of
                          an environment variable that holds the key; the key is never written to the profile), batch, timeout,
                          allow_page_text: true. Page text is sent to that URL, so the mapping must say allow_page_text: true.
                          Needs your environment to verify; tested here only against a fake transport.

Contextual chunk prefix: each chunk is embedded as "<page title > heading path>: <chunk text>" so a line under "Columns" keeps
the name of its page. Source tags are removed before embedding (they are not meaning) and are kept in the snippet shown.

Vectors live in the SQLite cache (table `vec`), rebuilt for chunks the keyword index re-chunked. No query text is stored.
`eval` asks each golden question (tools/golden.py) of both engines and prints recall@k: the share of the pages the question
says a good answer cites that appear in the top k pages. Use it for the release-record check on retrieval: enable hybrid only
when its recall@k is at least BM25's on your own golden set.
"""
import argparse
import array
import hashlib
import json
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kb_search  # noqa: E402

DEFAULT_ST_MODEL = "all-MiniLM-L6-v2"
DIM = 256


class EmbedderUnavailable(RuntimeError):
    """The embedder cannot run here (package missing, endpoint unreachable, not allowed). Keyword search carries on."""


# ---- the interface ----------------------------------------------------------------------------------
class Embedder(object):
    """Turn texts into unit-length vectors. `name` identifies the embedder and its settings: vectors built by a different name
    are rebuilt. `fitted` embedders learn corpus statistics in `fit` and keep them through `state` / `load_state`."""
    name = "base"
    fitted = False

    def fit(self, texts):
        pass

    def state(self):
        return {}

    def load_state(self, state):
        pass

    def embed(self, texts):
        raise NotImplementedError


def normalise(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


# ---- built in: hashing TF-IDF -----------------------------------------------------------------------
def bucket(feature, dim):
    h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    n = int.from_bytes(h, "big")
    return n % dim, 1.0 if (n >> 63) & 1 else -1.0


class HashingEmbedder(Embedder):
    """Deterministic and dependency-free. Same text and same fitted statistics give the same vector on every machine."""
    fitted = True

    def __init__(self, dim=DIM):
        self.dim = int(dim)
        self.idf = {}
        self.default_idf = 1.0
        self.name = "hashing-%d" % self.dim

    def fit(self, texts):
        df, n = {}, 0
        for t in texts:
            n += 1
            for w in set(kb_search.tokens(t)):
                df[w] = df.get(w, 0) + 1
        self.idf = {w: round(math.log(1 + (n + 1) / (c + 0.5)), 4) for w, c in df.items()}
        self.default_idf = round(math.log(1 + (n + 1) / 0.5), 4) if n else 1.0

    def state(self):
        return {"idf": self.idf, "default": self.default_idf}

    def load_state(self, state):
        self.idf = dict((state or {}).get("idf") or {})
        self.default_idf = float((state or {}).get("default") or 1.0)

    def one(self, text):
        words = kb_search.tokens(text)
        feats = {}

        def add(f, w):
            feats[f] = feats.get(f, 0.0) + w

        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        for w, c in counts.items():
            idf = self.idf.get(w, self.default_idf)
            tf = 1.0 + math.log(c)
            add("w:" + w, tf * idf)
            if len(w) >= 4:
                g = "^" + w + "$"
                for i in range(len(g) - 2):
                    add("c:" + g[i:i + 3], 0.25 * tf * idf)
        for a, b in zip(words, words[1:]):
            add("b:%s %s" % (a, b), 0.5 * min(self.idf.get(a, self.default_idf), self.idf.get(b, self.default_idf)))
        v = [0.0] * self.dim
        for f, w in feats.items():
            i, s = bucket(f, self.dim)
            v[i] += s * w
        return normalise(v)

    def embed(self, texts):
        return [self.one(t) for t in texts]


# ---- optional: sentence-transformers ----------------------------------------------------------------
class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model=DEFAULT_ST_MODEL, loader=None):
        self.model_name = model or DEFAULT_ST_MODEL
        self.name = "sentence-transformers:%s" % self.model_name
        self._loader = loader
        self._model = None

    def load(self):
        if self._model is None:
            if self._loader:
                self._model = self._loader(self.model_name)
            else:
                try:
                    from sentence_transformers import SentenceTransformer  # guarded: optional package
                except ImportError:
                    raise EmbedderUnavailable("sentence-transformers is not installed (pip install sentence-transformers); "
                                              "use embedder: hashing, or leave search.hybrid off")
                try:
                    self._model = SentenceTransformer(self.model_name)
                except Exception as err:
                    raise EmbedderUnavailable("could not load model %s: %s" % (self.model_name, err))
        return self._model

    def embed(self, texts):
        out = self.load().encode(list(texts), normalize_embeddings=True)
        return [normalise([float(x) for x in row]) for row in (out.tolist() if hasattr(out, "tolist") else out)]


# ---- optional: an HTTP embedding endpoint -----------------------------------------------------------
def post_json(url, payload, headers, timeout):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise EmbedderUnavailable("embedding endpoint %s failed: %s" % (url, err))


class HttpEmbedder(Embedder):
    def __init__(self, url, model="", api_key_env="", batch=32, timeout=30, allow_page_text=False, transport=None, env=None):
        if not url:
            raise EmbedderUnavailable("search.embedder of type http needs a url")
        if not allow_page_text:
            raise EmbedderUnavailable("search.embedder of type http sends page text to %s; say allow_page_text: true to allow it" % url)
        self.url, self.model, self.batch, self.timeout = url, model, max(1, int(batch)), timeout
        self.api_key_env = api_key_env
        self.transport = transport or post_json
        self.env = os.environ if env is None else env
        self.name = "http:%s:%s" % (hashlib.sha1(url.encode("utf-8")).hexdigest()[:8], model)

    def embed(self, texts):
        headers = {}
        if self.api_key_env:
            key = self.env.get(self.api_key_env)
            if not key:
                raise EmbedderUnavailable("environment variable %s (api_key_env) is not set" % self.api_key_env)
            headers["Authorization"] = "Bearer " + key
        out = []
        texts = list(texts)
        for i in range(0, len(texts), self.batch):
            part = texts[i:i + self.batch]
            body = {"input": part}
            if self.model:
                body["model"] = self.model
            rep = self.transport(self.url, body, headers, self.timeout)
            if isinstance(rep, dict) and isinstance(rep.get("data"), list):
                rows = [d.get("embedding") for d in rep["data"] if isinstance(d, dict)]
            elif isinstance(rep, dict) and isinstance(rep.get("embeddings"), list):
                rows = rep["embeddings"]
            else:
                raise EmbedderUnavailable("embedding endpoint answered in a shape this client does not know")
            if len(rows) != len(part) or any(not isinstance(r, list) or not r for r in rows):
                raise EmbedderUnavailable("embedding endpoint returned %d vectors for %d texts" % (len(rows), len(part)))
            out += [normalise([float(x) for x in r]) for r in rows]
        return out


def make_embedder(kb, spec=None):
    """The embedder the profile (search.embedder) or `spec` names. A string is hashing, sentence-transformers[:model] or http."""
    if spec is None:
        spec = (kb_search.profile(kb).get("search") or {}).get("embedder")
    if isinstance(spec, Embedder):
        return spec
    if not spec:
        return HashingEmbedder()
    if isinstance(spec, str):
        kind, _, rest = spec.partition(":")
        spec = {"type": kind.strip().lower()}
        if rest:
            spec["model"] = rest.strip()
    if not isinstance(spec, dict):
        raise EmbedderUnavailable("search.embedder must be a name or a mapping")
    kind = str(spec.get("type") or "hashing").lower()
    if kind == "hashing":
        return HashingEmbedder(spec.get("dim") or DIM)
    if kind in ("sentence-transformers", "sentence_transformers", "st"):
        return SentenceTransformerEmbedder(spec.get("model") or DEFAULT_ST_MODEL)
    if kind == "http":
        return HttpEmbedder(spec.get("url"), spec.get("model") or "", spec.get("api_key_env") or "", spec.get("batch") or 32,
                            spec.get("timeout") or 30, bool(spec.get("allow_page_text")))
    raise EmbedderUnavailable("unknown embedder %r (use hashing, sentence-transformers or http)" % kind)


# ---- vectors in the search cache --------------------------------------------------------------------
VEC_SCHEMA = """
create table if not exists vec (chunk integer primary key, dim integer, v blob);
create table if not exists vec_meta (k text primary key, v text);
"""


def contextual_text(hpath, text):
    """What is embedded for a chunk: its page title and heading path in front of its words, without source tags."""
    body = " ".join(kb_search.plain(text).split())
    return "%s: %s" % (hpath, body) if hpath else body


def pack(v):
    return array.array("f", v).tobytes()


def unpack(blob):
    a = array.array("f")
    a.frombytes(blob)
    return a


def stamp(con):
    h = hashlib.sha1()
    for cid, ln in con.execute("select id, len from chunks order by id"):
        h.update(("%d:%s;" % (cid, ln)).encode("ascii"))
    return h.hexdigest()


def meta_get(con, k):
    r = con.execute("select v from vec_meta where k=?", (k,)).fetchone()
    return r[0] if r else None


def meta_set(con, k, v):
    con.execute("insert or replace into vec_meta values (?,?)", (k, v))


def build_vectors(kb, embedder=None):
    """Embed every chunk the cache holds that has no vector yet (all of them for an embedder that learns from the corpus, or
    when the embedder changed). Returns {embedder, chunks, embedded}. Raises EmbedderUnavailable when the embedder cannot run."""
    kb = os.path.abspath(kb)
    embedder = embedder or make_embedder(kb)
    kb_search.sync(kb)
    con = kb_search.open_index(kb)
    try:
        con.executescript(VEC_SCHEMA)
        total = con.execute("select count(*) from chunks").fetchone()[0]
        same = meta_get(con, "embedder") == embedder.name
        if same and embedder.fitted and meta_get(con, "stamp") == stamp(con):
            embedder.load_state(json.loads(meta_get(con, "state") or "{}"))
            return {"embedder": embedder.name, "chunks": total, "embedded": 0}
        if not same or embedder.fitted:
            con.execute("delete from vec")
        rows = con.execute("select c.id, c.hpath, c.text from chunks c left join vec v on v.chunk = c.id where v.chunk is null order by c.id").fetchall()
        everything = con.execute("select hpath, text from chunks").fetchall() if embedder.fitted else []
        if embedder.fitted:
            embedder.fit([contextual_text(h, t) for h, t in everything])
        done = 0
        for i in range(0, len(rows), 64):
            part = rows[i:i + 64]
            vecs = embedder.embed([contextual_text(h, t) for _, h, t in part])
            con.executemany("insert or replace into vec values (?,?,?)", [(cid, len(v), pack(v)) for (cid, _, _), v in zip(part, vecs)])
            done += len(part)
        meta_set(con, "embedder", embedder.name)
        meta_set(con, "stamp", stamp(con))
        meta_set(con, "state", json.dumps(embedder.state(), sort_keys=True))
        con.commit()
        return {"embedder": embedder.name, "chunks": total, "embedded": done}
    finally:
        con.close()


def vector_rank(kb, query, embedder=None, limit=1000):
    """([(chunk id, cosine)], why): the chunks closest to the query, best first. why says what went wrong when the list is empty."""
    kb = os.path.abspath(kb)
    try:
        embedder = embedder or make_embedder(kb)
        build_vectors(kb, embedder)
        con = kb_search.open_index(kb)
        try:
            if embedder.fitted:
                embedder.load_state(json.loads(meta_get(con, "state") or "{}"))
            q = embedder.embed([query])[0]
            scored = []
            for cid, blob in con.execute("select chunk, v from vec"):
                v = unpack(blob)
                if len(v) != len(q):
                    return [], "vectors were built with a different size; run kb_embed.py build"
                scored.append((cid, sum(a * b for a, b in zip(q, v))))
        finally:
            con.close()
    except EmbedderUnavailable as err:
        return [], str(err)
    scored = [s for s in scored if s[1] > 0]
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored[:limit], ("no chunk is close to the query" if not scored else "")


def status(kb):
    kb = os.path.abspath(kb)
    kb_search.sync(kb)
    con = kb_search.open_index(kb)
    try:
        if "vec" not in kb_search.tables(con):
            return {"built": False, "vectors": 0, "chunks": con.execute("select count(*) from chunks").fetchone()[0]}
        return {"built": True, "embedder": meta_get(con, "embedder"), "vectors": con.execute("select count(*) from vec").fetchone()[0],
                "chunks": con.execute("select count(*) from chunks").fetchone()[0],
                "hybrid_on": bool((kb_search.profile(kb).get("search") or {}).get("hybrid"))}
    finally:
        con.close()


# ---- evaluation: BM25 alone against hybrid, on the golden questions ---------------------------------
def evaluate(kb, ks=(1, 3, 5, 10), embedder=None):
    """Recall@k of keyword search and of hybrid search on the golden questions (tools/golden.py).

    For each question the relevant pages are the ones it says a good answer cites (`cite`), limited to pages the search covers.
    recall@k = pages found in the top k pages / relevant pages, averaged over questions. Also reported: the share of questions
    with at least one relevant page in the top k (hit@k). Questions with no searchable relevant page are counted as skipped."""
    import golden
    kb = os.path.abspath(kb)
    ks = sorted({int(k) for k in ks if int(k) > 0})
    embedder = embedder or make_embedder(kb)
    kb_search.sync(kb)
    con = kb_search.open_index(kb)
    try:
        indexed = {r[0] for r in con.execute("select path from files where skip is null")}
    finally:
        con.close()
    note = ""
    try:
        build_vectors(kb, embedder)
    except EmbedderUnavailable as err:
        note = str(err)
    qs = golden.load(kb).get("golden") or []
    per, used = [], 0
    for g in qs:
        rel = [c for c in g.get("cite") or [] if c in indexed]
        if not rel:
            continue
        used += 1
        row = {"id": g.get("id"), "relevant": rel}
        for engine, kw in (("bm25", {"hybrid": False}), ("hybrid", {"hybrid": True, "embedder": embedder})):
            if engine == "hybrid" and note:
                row[engine] = None
                continue
            rep = kb_search.search(kb, g["question"], limit=max(ks), **kw)
            row[engine] = [r["path"] for r in rep["results"]]
        per.append(row)
    out = {"embedder": embedder.name, "questions": len(qs), "scored": used, "skipped": len(qs) - used, "k": ks, "note": note, "per_question": per}
    for engine in ("bm25", "hybrid"):
        rec, hit = {}, {}
        for k in ks:
            r = [len(set(p["relevant"]) & set(p[engine][:k])) / len(p["relevant"]) for p in per if p[engine] is not None]
            h = [1.0 if set(p["relevant"]) & set(p[engine][:k]) else 0.0 for p in per if p[engine] is not None]
            rec[k] = round(sum(r) / len(r), 4) if r else None
            hit[k] = round(sum(h) / len(h), 4) if h else None
        out[engine] = {"recall": rec, "hit": hit}
    better = [k for k in ks if out["hybrid"]["recall"][k] is not None and out["hybrid"]["recall"][k] > out["bm25"]["recall"][k]]
    worse = [k for k in ks if out["hybrid"]["recall"][k] is not None and out["hybrid"]["recall"][k] < out["bm25"]["recall"][k]]
    if not used:
        out["verdict"] = "no golden question cites a searchable page; add golden questions first (golden.py add)"
    elif note:
        out["verdict"] = "hybrid could not run (%s); only keyword results are scored" % note
    elif worse:
        out["verdict"] = "hybrid is worse than keyword search at k=%s: leave search.hybrid off" % ",".join(map(str, worse))
    elif better:
        out["verdict"] = "hybrid is better at k=%s and not worse anywhere: it may be turned on" % ",".join(map(str, better))
    else:
        out["verdict"] = "hybrid is no better than keyword search on this set: leave search.hybrid off"
    return out


def report(rep):
    ks = rep["k"]
    lines = ["Retrieval evaluation: %d golden questions, %d scored, %d skipped (no searchable cited page). Embedder: %s"
             % (rep["questions"], rep["scored"], rep["skipped"], rep["embedder"]),
             "%-13s " % "" + " ".join("%8s" % ("@%d" % k) for k in ks)]
    for engine, label in (("bm25", "BM25"), ("hybrid", "hybrid")):
        for key, what in (("recall", "recall"), ("hit", "hit")):
            vals = rep[engine][key]
            lines.append("%-13s " % ("%s %s" % (label, what)) + " ".join("%8s" % ("-" if vals[k] is None else "%.3f" % vals[k]) for k in ks))
    lines.append("Verdict: " + rep["verdict"])
    return "\n".join(lines)


# ---- command line -----------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "status", "query", "eval"):
        a = sub.add_parser(name)
        a.add_argument("kb")
        if name == "query":
            a.add_argument("words")
            a.add_argument("--limit", type=int, default=10)
        if name == "eval":
            a.add_argument("--k", default="1,3,5,10")
            a.add_argument("--json", action="store_true")
        if name != "status":
            a.add_argument("--embedder", help="hashing, sentence-transformers[:model] (default: the profile's search.embedder)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kb = os.path.abspath(args.kb)
    if not os.path.isdir(kb):
        print("error: no KB folder %s" % kb, file=sys.stderr)
        return 2
    try:
        if args.cmd == "status":
            print(json.dumps(status(kb), indent=2))
            return 0
        emb = make_embedder(kb, getattr(args, "embedder", None))
        if args.cmd == "build":
            r = build_vectors(kb, emb)
            print("%(embedder)s: %(embedded)d of %(chunks)d chunks embedded" % r)
        elif args.cmd == "query":
            rep = kb_search.search(kb, args.words, limit=args.limit, hybrid=True, embedder=emb)
            for n in rep["notes"]:
                print("note: %s" % n)
            for i, r in enumerate(rep["results"], 1):
                print("%2d. %s  (%.4f)\n    %s\n    L%d: %s" % (i, r["path"], r["score"], r["heading"], r["line"], r["snippet"]))
        else:
            rep = evaluate(kb, args.k.split(","), emb)
            print(json.dumps(rep, indent=2) if args.json else report(rep))
            return 0 if rep["scored"] else 2
    except EmbedderUnavailable as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
