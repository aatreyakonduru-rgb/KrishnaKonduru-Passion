#!/usr/bin/env python3
"""Search the text of the KB pages: BM25 ranking, facets, and snippets that keep the source tag.

    python3 kb_search.py index  <kb> [--rebuild]        build or refresh <kb>/.metis/search.sqlite (it refreshes itself on every query)
    python3 kb_search.py query  <kb> "words" [--folder F] [--type T] [--owner O] [--open-question yes|no] [--stale yes|no]
                                             [--limit N] [--engine python|fts5] [--hybrid|--no-hybrid] [--json]
    python3 kb_search.py facets <kb>                     the facet values of the whole KB
    python3 kb_search.py status <kb>                     what is indexed, what was left out and why

What it searches: the hand-written Markdown pages (the same set the Ask answerer reads: kb_coverage.page_files). It leaves out
_PENDING, _FEEDBACK, _EVIDENCE, _QUESTIONS, .metis, generated pages, and any page sensitive.py blocks (a secret or an id number),
so a search never shows what the gate would refuse to certify.

Ranking: BM25 over chunks (one chunk per heading section). Words in the page title and the heading path count three times.
Words and synonyms from the business glossary (ui/glossary.py) are added at a lower weight. The index is a rebuildable cache
(keep it out of git). It uses SQLite FTS5 when this Python has it, otherwise a pure-Python BM25 over a postings table; both are
kept up to date and `--engine` picks one. The two give close but not identical orders (FTS5 cannot weight glossary synonyms).

A result is a page with its best line, shown as written: the line number and the [E: ...] tag are never cut. Facets:
  folder          the top folder of the page
  type            `type:` (or `page_type:`, `kind:`) in the page's front matter, when it has one
  owner           `owner` in <kb>/.metis/page_meta.yaml, when that file exists
  open question   the page carries a [?: Q-nnnn] tag, or an open question in the register names it in `blocks`
  stale           `review_due` (page_meta.yaml or front matter) is before today, or the front matter says `stale: true`

No query text is stored anywhere. Hybrid (vector) search is optional and lives in kb_embed.py; it is off unless the profile
says `search.hybrid: true`.

Optional re-ranking, off unless asked for, and small on purpose (it can move a page up or down a few places, never hide it):
  team=NAME | "auto"   pages owned by that team (gate.teams) score 15% higher. "auto" uses the team the `who` person is an approver of.
  feedback=True        (or profile `search.feedback_rank: true`) a page cited by rated answers gets a bounded nudge from the likes and
                       dislikes in _FEEDBACK: 3% per net like or dislike, at most +-10%, and only once it has at least
                       MIN_RATINGS (3) ratings, because one or two ratings are noise. A dislike a lead declined is not counted.
A dislike names an answer, not a page, so this is a hint, not a verdict; ratings come from a few people and can drift toward
what they already read. Look at `adjusted` on a result (what was applied and by how much) before trusting the order.
Nothing is stored about the search; the score shown stays the one used to sort, and `base_score` is the one before the nudge.

Labels (claim_labels.py): `search(..., who=NAME_OR_ROLE)` (CLI `--role`) hides what that person may not see when the KB uses
`{env: ...; sensitivity: ...}` labels (none given = the lowest clearance). A page above their clearance is not a result and not counted;
on a page with some withheld lines the title, heading and snippet are taken from the lines they may see, and a page that matches only
through withheld lines is not a result. The index itself is not filtered, so a score can still reflect withheld words; the text never
leaves. A KB with no labels is searched exactly as before.
"""
import argparse
import collections
import datetime
import json
import math
import os
import re
import sqlite3
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import claim_labels  # noqa: E402
import kb_coverage  # noqa: E402
import kb_gate  # noqa: E402
import questions  # noqa: E402
import sensitive  # noqa: E402
import verify_kb  # noqa: E402

DB = os.path.join(".metis", "search.sqlite")
INDEX_VERSION = "1"
HEAD_BOOST = 3.0          # a word in the title or heading path counts this many times
K1, B = 1.2, 0.75
SYN_WEIGHT = 0.6          # a glossary synonym counts this much of a word the person typed
MAX_CHUNK_LINES = 40
SNIPPET_CHARS = 240
STOP = set("a an the of to in on for is are was were what which who how does do did and or by with from this that it as at be me my we "
           "our can i you show list tell about when where why there their its into than then also any all should would could "
           "please give find get use used uses using".split())
WORD = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
TAG = verify_kb.TAG
QTAG = re.compile(r"\[\?:\s*Q-\d+\s*\]")
FACETS = ("folder", "type", "owner", "open_question", "stale")


# ---- words ------------------------------------------------------------------------------------------
def stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text):
    """Stemmed words. OWNER_ID gives owner_id, owner, id; OrderItem gives orderitem, order, item; APP.ORDERS gives app, orders."""
    out = []
    for raw in WORD.findall(str(text)):
        parts = [p for p in raw.split("_") if p]
        forms = []
        if len(parts) > 1:
            forms.append(raw.lower().strip("_"))
        for p in parts:
            sub = CAMEL.findall(p) if (p != p.lower() and p != p.upper()) else [p]
            if len(sub) > 1:
                forms.append(p.lower())
            forms += [s.lower() for s in sub]
        for f in forms:
            if f in STOP or (len(f) < 2 and not f.isdigit()):
                continue
            out.append(stem(f))
    return out


def plain(line):
    return TAG.sub(" ", line)


# ---- the index file ---------------------------------------------------------------------------------
def db_path(kb):
    return os.path.join(kb, DB)


def has_fts5():
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("create virtual table t using fts5(a)")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False


SCHEMA = """
create table meta (k text primary key, v text);
create table files (path text primary key, mtime_ns integer, size integer, title text, ptype text, folder text,
                    q_tags integer, review_due text, stale_flag integer, skip text);
create table chunks (id integer primary key, path text, ord integer, hpath text, first_line integer, last_line integer,
                     text text, len real);
create index chunks_path on chunks(path);
create table post (term text, chunk integer, tf real);
create index post_term on post(term);
create index post_chunk on post(chunk);
"""
FTS = "create virtual table chunks_fts using fts5(hpath, body, tokenize=\"unicode61 tokenchars '_'\")"


def reset(con):
    for (name,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
        if name.startswith("chunks_fts"):
            continue
        con.execute("drop table if exists %s" % name)
    con.execute("drop table if exists chunks_fts")
    con.executescript(SCHEMA)
    if has_fts5():
        con.execute(FTS)
    con.execute("insert into meta values ('version', ?)", (INDEX_VERSION,))
    con.commit()


def tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type in ('table','view')")}


def open_index(kb, rebuild=False):
    p = db_path(kb)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    for _ in range(2):
        con = None
        try:
            con = sqlite3.connect(p, timeout=30)
            have = tables(con)
            ver = con.execute("select v from meta where k='version'").fetchone() if "meta" in have else None
            if rebuild or not ver or ver[0] != INDEX_VERSION:
                reset(con)
            return con
        except sqlite3.DatabaseError:
            if con is not None:
                con.close()
            if os.path.exists(p):
                os.remove(p)  # not a database (or damaged): it is only a cache
    raise RuntimeError("cannot create %s" % p)


def page_paths(kb):
    out = []
    for dirpath, dirnames, filenames in os.walk(kb):
        dirnames[:] = sorted(d for d in dirnames if d not in kb_coverage.SKIP)
        for name in sorted(filenames):
            if name.endswith(".md"):
                out.append(os.path.relpath(os.path.join(dirpath, name), kb).replace(os.sep, "/"))
    return out


def read(kb, rel):
    with open(os.path.join(kb, rel), encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


# ---- chunks -----------------------------------------------------------------------------------------
def chunk_page(title, body, line0):
    """[(heading path, first line, last line, [raw lines])]: one chunk per heading section, long sections cut in pieces.
    Line numbers are file line numbers (line0 is the number of front-matter lines before the body)."""
    out, stack, cur, start, in_code = [], [], [], None, False

    def path():
        names = [title] + [t for _, t in stack]
        if len(names) > 1 and names[1] == title:
            del names[1]
        return " > ".join(names)

    def flush():
        nonlocal cur, start
        if cur and any(l.strip() for l in cur):
            hp = path()
            for i in range(0, len(cur), MAX_CHUNK_LINES):
                piece = cur[i:i + MAX_CHUNK_LINES]
                if any(l.strip() for l in piece):
                    out.append((hp, start + i, start + i + len(piece) - 1, piece))
        cur, start = [], None

    for n, line in enumerate(body.split("\n"), line0 + 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        h = None if in_code else verify_kb.HEADING.match(line.strip())
        if h:
            flush()
            level, text = len(h.group(1)), " ".join(TAG.sub("", h.group(2)).split())
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
        if start is None:
            start = n
        cur.append(line)
    flush()
    return out


def page_title(meta, body, rel):
    if meta.get("title"):
        return " ".join(str(meta["title"]).split())
    for line in body.split("\n"):
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return " ".join(TAG.sub("", m.group(1)).split()) or rel
    return os.path.splitext(os.path.basename(rel))[0]


def drop_path(con, rel):
    ids = [r[0] for r in con.execute("select id from chunks where path=?", (rel,))]
    have = tables(con)
    for i in range(0, len(ids), 500):
        mark = ",".join("?" * len(ids[i:i + 500]))
        con.execute("delete from post where chunk in (%s)" % mark, ids[i:i + 500])
        if "chunks_fts" in have:
            con.execute("delete from chunks_fts where rowid in (%s)" % mark, ids[i:i + 500])
        for extra in ("vec",):  # written by kb_embed.py
            if extra in have:
                con.execute("delete from %s where chunk in (%s)" % (extra, mark), ids[i:i + 500])
    con.execute("delete from chunks where path=?", (rel,))
    con.execute("delete from files where path=?", (rel,))


def index_file(con, kb, rel, mtime_ns, size):
    text = read(kb, rel)
    skip = None
    if "Generated by" in text[:300]:
        skip = "generated"
    elif sensitive.blocking(sensitive.scan(text)):
        skip = "sensitive"
    meta, body = kb_gate.front(text)
    title = page_title(meta, body, rel)
    ptype = str(meta.get("type") or meta.get("page_type") or meta.get("kind") or "").strip()
    due = meta.get("review_due")
    con.execute("insert into files values (?,?,?,?,?,?,?,?,?,?)",
                (rel, mtime_ns, size, title, ptype, rel.split("/")[0] if "/" in rel else "(top)", len(QTAG.findall(text)),
                 str(due) if due else "", 1 if meta.get("stale") is True else 0, skip))
    if skip:
        return 0
    line0 = text.count("\n") - body.count("\n")
    fts = "chunks_fts" in tables(con)
    n = 0
    for order, (hp, first, last, lines) in enumerate(chunk_page(title, body, line0)):
        head = collections.Counter(tokens(hp))
        words = collections.Counter(tokens(plain("\n".join(lines))))
        weighted = collections.Counter()
        for t, c in words.items():
            weighted[t] += c
        for t, c in head.items():
            weighted[t] += HEAD_BOOST * c
        cur = con.execute("insert into chunks (path, ord, hpath, first_line, last_line, text, len) values (?,?,?,?,?,?,?)",
                          (rel, order, hp, first, last, "\n".join(lines), float(sum(weighted.values()))))
        cid = cur.lastrowid
        con.executemany("insert into post values (?,?,?)", [(t, cid, float(c)) for t, c in weighted.items()])
        if fts:
            con.execute("insert into chunks_fts (rowid, hpath, body) values (?,?,?)",
                        (cid, " ".join(tokens(hp)), " ".join(tokens(plain("\n".join(lines))))))
        n += 1
    return n


def sync(kb, rebuild=False):
    """Bring the index in line with the files on disk. Returns {indexed, removed, unchanged}."""
    kb = os.path.abspath(kb)
    con = open_index(kb, rebuild)
    try:
        have = {r[0]: (r[1], r[2]) for r in con.execute("select path, mtime_ns, size from files")}
        now = {}
        for rel in page_paths(kb):
            st = os.stat(os.path.join(kb, rel))
            now[rel] = (st.st_mtime_ns, st.st_size)
        gone = [p for p in have if p not in now]
        todo = [p for p in now if have.get(p) != now[p]]
        for p in gone + [p for p in todo if p in have]:
            drop_path(con, p)
        for rel in todo:
            index_file(con, kb, rel, *now[rel])
        con.commit()
        return {"indexed": len(todo), "removed": len(gone), "unchanged": len(now) - len(todo)}
    finally:
        con.close()


# ---- page facts: owner, stale, open question --------------------------------------------------------
def page_meta(kb):
    """{page: {owner, review_due, ...}} from <kb>/.metis/page_meta.yaml. Accepts `pages: {path: {...}}`, a bare {path: {...}},
    or a list of {path: ..., owner: ...}. {} when the file is missing or unreadable."""
    p = os.path.join(kb, ".metis", "page_meta.yaml")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("pages"), (dict, list)):
        data = data["pages"]
    if isinstance(data, list):
        data = {str(e.get("path")): e for e in data if isinstance(e, dict) and e.get("path")}
    return {str(k).replace("\\", "/"): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def as_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def blocked_pages(kb):
    out = set()
    try:
        for q in questions.load(questions.reg_path(kb)).get("questions") or []:
            if q.get("status") == "open":
                b = q.get("blocks") or []
                out |= set(b if isinstance(b, list) else [b])
    except Exception:
        pass
    return out


def page_facts(kb, rows):
    """{page: {title, folder, type, owner, stale, stale_why, open_question}} for the file rows [(path, title, ptype, folder, q_tags, due, flag)]."""
    pm, blocked, today = page_meta(kb), blocked_pages(kb), datetime.date.today()
    out = {}
    for rel, title, ptype, folder, q_tags, due, flag in rows:
        m = pm.get(rel) or {}
        why = ""
        for src, val in (("page_meta.yaml", m.get("review_due")), ("front matter", due)):
            d = as_date(val) if val else None
            if d and d < today:
                why = "review was due %s (%s)" % (d.isoformat(), src)
                break
        if not why and flag:
            why = "front matter says stale"
        out[rel] = {"title": title, "folder": folder, "type": ptype or "", "owner": str(m.get("owner") or m.get("page_owner") or ""),
                    "stale": bool(why), "stale_why": why, "open_question": bool(q_tags) or rel in blocked}
    return out


# ---- query ------------------------------------------------------------------------------------------
def profile(kb):
    p = os.path.join(kb, ".metis", "kb-profile.yaml")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError):
        return {}


def glossary_words(kb, query):
    """Terms and synonyms the glossary ties to words in the query. A missing or broken glossary never stops a search."""
    try:
        ui = os.path.join(HERE, "ui")
        if ui not in sys.path:
            sys.path.insert(0, ui)
        import glossary
        return list(glossary.expand(kb, query).get("extra_words") or [])
    except Exception:
        return []


def query_terms(kb, query):
    """{stemmed word: weight}: what was typed at 1.0, glossary words at SYN_WEIGHT."""
    terms = {}
    for t in tokens(query):
        terms[t] = 1.0
    for t in tokens(" ".join(glossary_words(kb, query))):
        terms.setdefault(t, SYN_WEIGHT)
    return terms


def rank_python(con, terms):
    n, total = con.execute("select count(*), coalesce(sum(len), 0) from chunks").fetchone()
    if not n:
        return []
    avg = total / n or 1.0
    scores = collections.defaultdict(float)
    for t, w in terms.items():
        rows = con.execute("select p.chunk, p.tf, c.len from post p join chunks c on c.id = p.chunk where p.term=?", (t,)).fetchall()
        df = len(rows)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for chunk, tf, dl in rows:
            scores[chunk] += w * idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avg))
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def rank_fts5(con, terms, limit):
    q = " OR ".join('"%s"' % t for t in terms)
    rows = con.execute("select rowid, bm25(chunks_fts, %r, 1.0) from chunks_fts where chunks_fts match ? order by 2 limit ?"
                       % HEAD_BOOST, (q, limit)).fetchall()
    return sorted(((r, -s) for r, s in rows), key=lambda kv: (-kv[1], kv[0]))


def rank_chunks(con, terms, engine=None, limit=1000):
    """[(chunk id, score)], best first. engine: 'fts5', 'python' or None (fts5 when the index has it)."""
    if not terms:
        return [], "python"
    use = engine or ("fts5" if "chunks_fts" in tables(con) else "python")
    if use == "fts5" and "chunks_fts" not in tables(con):
        raise ValueError("this Python's SQLite has no FTS5; use engine python")
    return (rank_fts5(con, terms, limit) if use == "fts5" else rank_python(con, terms)[:limit]), use


def reciprocal_rank_fusion(rankings, k=60):
    """Combine ranked lists of ids. Each list adds 1/(k + rank) to an id; no scores need to be comparable."""
    fused = collections.defaultdict(float)
    for ranked in rankings:
        for i, (cid, _) in enumerate(ranked, 1):
            fused[cid] += 1.0 / (k + i)
    return sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))


def snippet_text(line, limit=SNIPPET_CHARS):
    """The line as written. A long line is cut in its prose, never in its [E: ...] tags, which are kept whole at the end."""
    s = line.strip()
    if len(s) <= limit:
        return s
    tags = [m.group(0) for m in TAG.finditer(s)]
    prose = " ".join(TAG.sub("", s).split())
    keep = max(40, limit - sum(len(t) + 1 for t in tags))
    if len(prose) > keep:
        prose = prose[:keep].rstrip() + "..."
    return (prose + " " + " ".join(tags)).strip()


def best_line(text, first_line, terms):
    """(line number, raw line) of the line that holds most of the query words; a heading counts only when nothing else matches."""
    best, best_head = None, None
    for i, line in enumerate(text.split("\n")):
        if not line.strip():
            continue
        toks = set(tokens(plain(line)))
        hit = sum(w for t, w in terms.items() if t in toks)
        is_head = bool(verify_kb.HEADING.match(line.strip()))
        cand = (hit, -i, first_line + i, line)
        if is_head:
            if best_head is None or cand > best_head:
                best_head = cand
        elif best is None or cand > best:
            best = cand
    pick = best if best and best[0] > 0 else (best_head if best_head and best_head[0] > 0 else (best or best_head))
    return (pick[2], pick[3]) if pick else (first_line, "")


def chunk_rows(con, ids):
    out = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in con.execute("select id, path, hpath, first_line, text from chunks where id in (%s)" % ",".join("?" * len(part)), part):
            out[r[0]] = r
    return out


def yes_no(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return True if s in ("1", "yes", "true", "y", "on") else False if s in ("0", "no", "false", "n", "off") else None


def under(folder, rel):
    f = folder.strip().strip("/")
    return not f or rel == f or rel.startswith(f + "/")


def visible_view(kb, viewer, rel, terms):
    """What `viewer` (claim_labels.Viewer) may see of page `rel`, as a dict, or None when the page is not a result for them.
    {"masked": False} when nothing on the page is withheld (the index row is used as it is). Otherwise {"masked": True, title,
    heading, line, text, frac}, all taken from the visible lines only; `frac` is the share of the query weight found in them."""
    text = read(kb, rel)
    nums = viewer.numbers(rel, text)
    if nums is None:
        return {"masked": False}
    lines = claim_labels.lines_of(text)
    if not any(l.strip() and (i + 1) in nums for i, l in enumerate(lines)):
        return None
    if all((i + 1) in nums or not l.strip() for i, l in enumerate(lines)):
        return {"masked": False}
    masked = "\n".join(l if (i + 1) in nums else "" for i, l in enumerate(lines))
    meta, body = kb_gate.front(masked)
    title = page_title(meta, body, rel)
    line0 = masked.count("\n") - body.count("\n")
    best = None
    for hp, first, _, piece in chunk_page(title, body, line0):
        n, line = best_line("\n".join(piece), first, terms)
        hit = sum(w for t, w in terms.items() if t in set(tokens(plain(line)))) + sum(w for t, w in terms.items() if t in set(tokens(hp)))
        if best is None or hit > best[0]:
            best = (hit, hp, n, line)
    if best is None:
        return None
    seen = set(tokens(plain(body))) | set(tokens(title))
    total = sum(terms.values())
    frac = sum(w for t, w in terms.items() if t in seen) / total if total else 1.0
    if terms and best[0] <= 0:
        return None
    return {"masked": True, "title": title, "heading": best[1], "line": best[2], "text": best[3], "frac": frac}


TEAM_BOOST = 0.15
FEEDBACK_STEP, FEEDBACK_CAP, MIN_RATINGS = 0.03, 0.10, 3


def team_for(kb, who):
    """The team `who` is an approver of (the first one), or None."""
    key = " ".join(str(who or "").split()).lower()
    for t in kb_gate.teams(kb):
        if key and key in (a.lower() for a in t["approvers"]):
            return t["name"]
    return None


def nudges(kb, rels, team=None, feedback=False):
    """{path: (factor, [reasons])} for the pages the optional re-ranking would move. Empty when neither is asked for."""
    out = {}
    marks = {}
    if feedback:
        import telemetry
        marks = telemetry.rated(kb)
    for rel in rels:
        factor, why = 1.0, []
        if team:
            t = kb_gate.team_of(kb, rel)
            if t and t["name"].lower() == team.lower():
                factor *= 1 + TEAM_BOOST
                why.append("team %s +%d%%" % (t["name"], round(TEAM_BOOST * 100)))
        m = marks.get(rel)
        if m and m["up"] + m["down"] >= MIN_RATINGS:
            step = max(-FEEDBACK_CAP, min(FEEDBACK_CAP, FEEDBACK_STEP * (m["up"] - m["down"])))
            if step:
                factor *= 1 + step
                why.append("ratings %+d%% (%d up, %d down)" % (round(step * 100), m["up"], m["down"]))
        if why:
            out[rel] = (factor, why)
    return out


def search(kb, query, folder=None, ptype=None, owner=None, open_question=None, stale=None, limit=20, engine=None, hybrid=None,
           embedder=None, who=None, team=None, feedback=None):
    """Search the KB pages.

    Returns {query, terms, synonyms, engine, hybrid, notes, total, results, facets, index}. `results` are pages, best first:
    {path, title, heading, line, snippet, score, folder, type, owner, stale, stale_why, open_question}. `facets` count the pages
    that match the words, before the facet filters are applied: {facet: {value: pages}}.
    hybrid: True or False to force, None to follow the profile key search.hybrid (default false). embedder: a kb_embed.Embedder
    to use instead of the one the profile names (the evaluation uses this)."""
    kb = os.path.abspath(kb)
    info = sync(kb)
    con = open_index(kb)
    notes = []
    try:
        terms = query_terms(kb, query or "")
        typed = {t for t in tokens(query or "")}
        ranked, used = rank_chunks(con, terms, engine)
        if hybrid is None:
            hybrid = bool((profile(kb).get("search") or {}).get("hybrid"))
        used_hybrid = False
        if hybrid and (query or "").strip():
            try:
                import kb_embed
                vec, why = kb_embed.vector_rank(kb, query, embedder)
                if vec:
                    ranked = reciprocal_rank_fusion([ranked, vec])
                    used_hybrid = True
                else:
                    notes.append("hybrid search skipped: %s" % why)
            except Exception as err:  # a broken embedder must not stop the keyword search
                notes.append("hybrid search skipped: %s" % err)
        files = {r[0]: r for r in con.execute("select path, title, ptype, folder, q_tags, review_due, stale_flag from files where skip is null")}
        facts = page_facts(kb, list(files.values()))
        rows = chunk_rows(con, [c for c, _ in ranked])
        per_page = collections.defaultdict(list)
        for cid, score in ranked:
            r = rows.get(cid)
            if r:
                per_page[r[1]].append((score, cid))
        scored = []
        for rel, lst in per_page.items():
            lst.sort(key=lambda x: (-x[0], x[1]))
            scored.append((lst[0][0] + 0.1 * sum(s for s, _ in lst[1:4]), rel, lst[0][1]))
        if not (query or "").strip() or not terms:
            scored = [(0.0, rel, None) for rel in sorted(files)]
        if team == "auto":
            team = team_for(kb, who)
            if not team:
                notes.append("team ranking skipped: %s is not an approver of any team" % (who or "nobody named"))
        if feedback is None:
            feedback = bool((profile(kb).get("search") or {}).get("feedback_rank"))
        moved = nudges(kb, [rel for _, rel, _ in scored], team, feedback) if (team or feedback) and (query or "").strip() and terms else {}
        base = {rel: score for score, rel, _ in scored}
        scored = [(score * moved[rel][0] if rel in moved else score, rel, cid) for score, rel, cid in scored]
        views = {}
        viewer = claim_labels.Viewer(kb, who)
        if viewer.active:
            shown = []
            for score, rel, cid in scored:
                v = visible_view(kb, viewer, rel, terms)
                if v is None:
                    continue
                views[rel] = v
                shown.append((score * v["frac"] if v["masked"] else score, rel, cid))
            scored = shown
        scored.sort(key=lambda x: (-x[0], x[1]))
        facets = {f: collections.Counter() for f in FACETS}
        for _, rel, _ in scored:
            f = facts[rel]
            facets["folder"][f["folder"]] += 1
            if f["type"]:
                facets["type"][f["type"]] += 1
            if f["owner"]:
                facets["owner"][f["owner"]] += 1
            facets["open_question"]["yes" if f["open_question"] else "no"] += 1
            facets["stale"]["yes" if f["stale"] else "no"] += 1
        oq, st = yes_no(open_question), yes_no(stale)
        keep = []
        for score, rel, cid in scored:
            f = facts[rel]
            if folder and not under(folder, rel):
                continue
            if ptype and f["type"].lower() != str(ptype).strip().lower():
                continue
            if owner and f["owner"].lower() != str(owner).strip().lower():
                continue
            if oq is not None and f["open_question"] != oq:
                continue
            if st is not None and f["stale"] != st:
                continue
            keep.append((score, rel, cid))
        results = []
        for score, rel, cid in keep[:max(0, int(limit))]:
            f = facts[rel]
            v = views.get(rel) or {}
            if v.get("masked"):
                hp, line_no, line = v["heading"], v["line"], v["text"]
            elif cid is not None and cid in rows:
                _, _, hp, first, text = rows[cid]
                line_no, line = best_line(text, first, terms)
            else:
                hp, line_no, line = f["title"], 1, ""
                text = read(kb, rel)
                _, body = kb_gate.front(text)
                for i, l in enumerate(body.split("\n")):
                    if l.strip() and not verify_kb.HEADING.match(l.strip()):
                        line_no, line = text.count("\n") - body.count("\n") + i + 1, l
                        break
            results.append({"path": rel, "title": v["title"] if v.get("masked") else f["title"], "heading": hp, "line": line_no,
                            "snippet": snippet_text(line),
                            "score": round(score, 4), "folder": f["folder"], "type": f["type"], "owner": f["owner"],
                            "stale": f["stale"], "stale_why": f["stale_why"], "open_question": f["open_question"]})
            if rel in moved:
                results[-1]["base_score"] = round(base[rel], 4)
                results[-1]["adjusted"] = moved[rel][1]
        return {"query": query or "", "terms": sorted(typed), "synonyms": sorted(t for t in terms if t not in typed),
                "engine": used, "hybrid": used_hybrid, "notes": notes, "total": len(keep), "results": results,
                "facets": {k: dict(sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))) for k, v in facets.items()}, "index": info}
    finally:
        con.close()


def status(kb):
    kb = os.path.abspath(kb)
    info = sync(kb)
    con = open_index(kb)
    try:
        skipped = collections.Counter(r[0] for r in con.execute("select skip from files where skip is not null"))
        return {"pages": con.execute("select count(*) from files where skip is null").fetchone()[0],
                "chunks": con.execute("select count(*) from chunks").fetchone()[0], "skipped": dict(skipped),
                "fts5": "chunks_fts" in tables(con), "vectors": con.execute("select count(*) from vec").fetchone()[0]
                if "vec" in tables(con) else 0, "index": info, "file": DB.replace("\\", "/")}
    finally:
        con.close()


def all_facets(kb):
    return search(kb, "", limit=0)["facets"]


# ---- command line -----------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("index")
    a.add_argument("kb")
    a.add_argument("--rebuild", action="store_true")
    a = sub.add_parser("query")
    a.add_argument("kb")
    a.add_argument("words")
    a.add_argument("--folder")
    a.add_argument("--type", dest="ptype")
    a.add_argument("--owner")
    a.add_argument("--open-question", choices=("yes", "no"))
    a.add_argument("--stale", choices=("yes", "no"))
    a.add_argument("--limit", type=int, default=10)
    a.add_argument("--engine", choices=("python", "fts5"))
    a.add_argument("--role", help="name or role whose clearance applies when the KB uses claim labels (default: the lowest)")
    a.add_argument("--team", help="boost pages owned by this team (gate.teams), or `auto` for the team --role is an approver of")
    a.add_argument("--feedback", dest="feedback", action="store_true", default=None, help="nudge by likes and dislikes (bounded; needs 3 ratings)")
    a.add_argument("--hybrid", dest="hybrid", action="store_true", default=None)
    a.add_argument("--no-hybrid", dest="hybrid", action="store_false")
    a.add_argument("--json", action="store_true")
    a = sub.add_parser("facets")
    a.add_argument("kb")
    a = sub.add_parser("status")
    a.add_argument("kb")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kb = os.path.abspath(args.kb)
    if not os.path.isdir(kb):
        print("error: no KB folder %s" % kb, file=sys.stderr)
        return 2
    if args.cmd == "index":
        r = sync(kb, args.rebuild)
        print("indexed %(indexed)d, removed %(removed)d, unchanged %(unchanged)d" % r)
        return 0
    if args.cmd == "status":
        print(json.dumps(status(kb), indent=2))
        return 0
    if args.cmd == "facets":
        print(json.dumps(all_facets(kb), indent=2))
        return 0
    try:
        rep = search(kb, args.words, args.folder, args.ptype, args.owner, args.open_question, args.stale, args.limit, args.engine, args.hybrid,
                     who=args.role, team=args.team, feedback=args.feedback)
    except ValueError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    for n in rep["notes"]:
        print("note: %s" % n)
    print("%d page%s match (%s%s)" % (rep["total"], "" if rep["total"] == 1 else "s", rep["engine"], " + vectors" if rep["hybrid"] else ""))
    for i, r in enumerate(rep["results"], 1):
        flags = "".join(" [%s]" % x for x, on in (("stale", r["stale"]), ("open question", r["open_question"])) if on)
        print("%2d. %s  (%.2f)%s%s" % (i, r["path"], r["score"], " owner %s" % r["owner"] if r["owner"] else "", flags))
        print("    %s" % r["heading"])
        print("    L%d: %s" % (r["line"], r["snippet"]))
        if r.get("adjusted"):
            print("    adjusted from %.2f: %s" % (r["base_score"], "; ".join(r["adjusted"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
