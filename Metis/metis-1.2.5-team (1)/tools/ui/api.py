"""A read-only JSON API over the KB, an OpenAPI description of it, and an llms.txt index. Standard library only.

    GET /api/v1/search?q=...&folder=&type=&owner=&limit=      ranked pages with the best line and its source tag (kb_search.py)
    GET /api/v1/page?path=<page.md>                           one page's text, as the caller may see it
    GET /api/v1/impact?node=<type:name>&depth=&direction=     what moves when the node changes (direction=down, default) or what it depends on (up)
    GET /api/v1/questions?status=open|answered|closed         the question register (no context lines)
    GET /api/v1/glossary                                      terms, synonyms, meanings, where in the KB
    GET /api/v1/onboarding?for=<team | approver | role>       a reading path (onboarding.py)
    GET /openapi.json                                         this API as OpenAPI 3.0
    GET /llms.txt                                             an index of the KB for language models: the pages the caller may see, each with its API link

How it is served: server.py calls handle() inside do_GET, after its own password check and SSO gate, so a request is allowed
exactly when the same person could open the web UI. There is no API key and no token of its own: with METIS_UI_PASSWORD set a client
sends HTTP Basic (any user name); with sign-in (OIDC) on, a client needs a browser session. The caller is named by the same
cookie the UI uses, so a script that sends no cookie is the lowest clearance ("public") when the KB uses claim labels. This API can
therefore be used by a script on a trusted network, not as a public endpoint; a public one would need its own authentication,
which does not exist here. Without OIDC the name in that cookie is not proven (the UI has the same limit): anyone who can reach
the API can send a lead's name and get a lead's clearance. Only OIDC sign-in ties a name to a person.

Read-only: every endpoint is GET and nothing is written to the KB (graph_store.py may build its rebuildable index under .metis/
the first time impact is asked). Claim labels (claim_labels.py) apply to pages, search results, impact steps and questions: what a
caller may not see is left out, not masked with a marker. Pages sensitive.py would block (a secret, an id number) are never served.
Errors are {"error": "..."} with 400, 404 or 405. There is no rate limit, no paging beyond `limit`, and no CORS header.
"""
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import claim_labels  # noqa: E402
import glossary  # noqa: E402
import graph_store  # noqa: E402
import kb_gate  # noqa: E402
import kb_search  # noqa: E402
import onboarding  # noqa: E402
import questions  # noqa: E402
import sensitive  # noqa: E402

JSON = "application/json; charset=utf-8"
MAX_LIMIT = 50
VERSION = "1"

# path -> (summary, [(name, in, description, required, schema type)])
ENDPOINTS = {
    "/api/v1/search": ("Search the KB pages", [
        ("q", "query", "Words to search for", True, "string"), ("folder", "query", "Top folder to keep", False, "string"),
        ("type", "query", "Page type to keep", False, "string"), ("owner", "query", "Page owner to keep", False, "string"),
        ("limit", "query", "Results to return, 1 to %d (default 10)" % MAX_LIMIT, False, "integer")]),
    "/api/v1/page": ("One KB page as the caller may see it", [
        ("path", "query", "Path of a page, relative to the KB, from a search result", True, "string")]),
    "/api/v1/impact": ("What moves when a node changes, or what it depends on", [
        ("node", "query", "Node id such as table:orders", True, "string"), ("depth", "query", "Steps to follow (default: all)", False, "integer"),
        ("direction", "query", "down = what moves (default), up = what it depends on", False, "string")]),
    "/api/v1/questions": ("The question register", [
        ("status", "query", "open, answered or closed (default: all)", False, "string")]),
    "/api/v1/glossary": ("Business glossary", []),
    "/api/v1/onboarding": ("A reading path for a team, approver or role", [
        ("for", "query", "A team, a team approver or a role that open questions wait on", True, "string"),
        ("limit", "query", "Pages and objects to list (default 12)", False, "integer")]),
}


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def out(code, obj):
    return code, json.dumps(obj, indent=2, ensure_ascii=False), JSON


def number(q, name, default, low, high):
    raw = q.get(name)
    if raw in (None, ""):
        return default
    try:
        n = int(raw)
    except ValueError:
        raise ApiError(400, "%s must be a whole number" % name)
    return max(low, min(high, n))


def need(q, name):
    v = (q.get(name) or "").strip()
    if not v:
        raise ApiError(400, "%s is required" % name)
    return v


# ---- endpoints ---------------------------------------------------------------------------------------
def ep_search(kb, user, q):
    rep = kb_search.search(kb, need(q, "q"), folder=q.get("folder") or None, ptype=q.get("type") or None,
                           owner=q.get("owner") or None, limit=number(q, "limit", 10, 1, MAX_LIMIT), who=user)
    return {"query": rep["query"], "total": rep["total"], "results": rep["results"], "facets": rep["facets"], "notes": rep["notes"]}


def servable(kb, rel):
    """The page's text when it is a hand-written page that sensitive.py does not block; else None."""
    rel = (rel or "").replace("\\", "/").strip("/")
    if rel not in set(kb_search.page_paths(kb)):
        return None
    text = kb_search.read(kb, rel)
    return None if sensitive.blocking(sensitive.scan(text)) else text


def ep_page(kb, user, q):
    rel = need(q, "path").replace("\\", "/").strip("/")
    text = servable(kb, rel)
    if text is None:
        raise ApiError(404, "no such page: %s" % rel)
    viewer = claim_labels.Viewer(kb, user)
    shown, hidden = viewer.filter(rel, text)
    if hidden and not shown.strip():
        raise ApiError(404, "no such page: %s" % rel)
    return {"path": rel, "title": onboarding.title_of(rel, shown), "text": shown, "withheld_lines": hidden}


def ep_impact(kb, user, q):
    node = need(q, "node")
    direction = (q.get("direction") or "down").lower()
    if direction not in ("down", "up"):
        raise ApiError(400, "direction must be down or up")
    depth = number(q, "depth", None, 1, 50)
    walk = graph_store.impact if direction == "down" else graph_store.upstream
    try:
        rows, cut = walk(kb, node, depth, 2000)
    except SystemExit:
        raise ApiError(404, "this KB has no link graph yet")
    if not rows:
        raise ApiError(404, "nothing reached from %s (no such node, or nothing depends on it)" % node)
    viewer = claim_labels.Viewer(kb, user)
    kept = [r for r in rows if not any(claim_labels.source_hidden(viewer, s.get("source")) for s in r["via"])]
    return {"node": node, "direction": direction, "stopped_at_limit": cut, "left_out": len(rows) - len(kept), "results": kept}


def ep_questions(kb, user, q):
    status = (q.get("status") or "").lower()
    if status and status not in questions.STATUSES:
        raise ApiError(400, "status must be one of %s" % ", ".join(questions.STATUSES))
    viewer = claim_labels.Viewer(kb, user)
    pages = set(kb_search.page_paths(kb))
    res, left_out = [], 0
    for item in questions.load(questions.reg_path(kb)).get("questions") or []:
        if status and item.get("status") != status:
            continue
        blocks = item.get("blocks") if isinstance(item.get("blocks"), list) else [item.get("blocks")]
        blocks = [b for b in blocks if b]
        known = [b for b in blocks if b in pages]
        if viewer.active and known and all(viewer.numbers(b, kb_search.read(kb, b)) == set() for b in known):
            left_out += 1  # every page it blocks is above the caller's clearance
            continue
        row = {k: item.get(k) for k in ("id", "question", "type", "priority", "answer_role", "status", "answer", "answered_by",
                                        "answered_on", "raised_on")}
        row["blocks"] = blocks
        res.append(row)
    return {"total": len(res), "left_out": left_out, "questions": res}


def ep_glossary(kb, user, q):
    return {"entries": glossary.load(kb)["entries"]}


def ep_onboarding(kb, user, q):
    return onboarding.build(kb, need(q, "for"), as_who=user, limit=number(q, "limit", 12, 1, MAX_LIMIT))


HANDLERS = {"/api/v1/search": ep_search, "/api/v1/page": ep_page, "/api/v1/impact": ep_impact, "/api/v1/questions": ep_questions,
            "/api/v1/glossary": ep_glossary, "/api/v1/onboarding": ep_onboarding}


# ---- description and index ---------------------------------------------------------------------------
def openapi(secured=False):
    err = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    paths = {}
    for p, (summary, params) in ENDPOINTS.items():
        paths[p] = {"get": {
            "summary": summary,
            "parameters": [{"name": n, "in": where, "description": d, "required": req, "schema": {"type": t}} for n, where, d, req, t in params],
            "responses": {"200": {"description": "JSON", "content": {"application/json": {"schema": {"type": "object"}}}},
                          "400": dict(err, description="A parameter is missing or wrong"),
                          "404": dict(err, description="No such page, node or link graph")}}}
    paths["/llms.txt"] = {"get": {"summary": "Index of the KB for language models", "responses": {"200": {"description": "text/plain"}}}}
    doc = {"openapi": "3.0.3",
           "info": {"title": "Metis KB read-only API", "version": VERSION,
                    "description": "Read-only. Every answer keeps the [E: ...] source tags of the KB lines it quotes. Claim labels apply: what the caller may not see is left out."},
           "paths": paths,
           "components": {"schemas": {"Error": {"type": "object", "properties": {"error": {"type": "string"}}}}}}
    if secured:
        doc["components"]["securitySchemes"] = {"basic": {"type": "http", "scheme": "basic"}}
        doc["security"] = [{"basic": []}]
    return doc


def llms_txt(kb, user):
    name = ((kb_gate.profile(kb).get("product") or {}).get("name")) or os.path.basename(os.path.abspath(kb))
    viewer = claim_labels.Viewer(kb, user)
    lines = ["# %s knowledge base" % name, "",
             "> A verifiable engineering knowledge base. Every fact line carries a source tag [E: ...]; what is not known is an open question "
             "[?: Q-nnnn], not a guess. Read pages through the API below; each answer keeps those tags.", "",
             "## API", "", "- [OpenAPI description](/openapi.json)"]
    lines += ["- [%s](%s): %s" % (p, p, s) for p, (s, _) in ENDPOINTS.items()]
    lines += ["", "## Pages", ""]
    listed = []
    for rel in kb_search.page_paths(kb):
        text = servable(kb, rel)
        if text is None:
            continue
        shown, hidden = viewer.filter(rel, text)
        if hidden and not shown.strip():
            continue
        listed.append("- [%s](/api/v1/page?path=%s)" % (onboarding.title_of(rel, shown), urllib.parse.quote(rel)))
    return "\n".join(lines + (listed or ["(no pages)"])) + "\n"


# ---- entry point for server.py -----------------------------------------------------------------------
def handle(kb, user, method, path, query, secured=False):
    """None when `path` is not an API path (the server carries on); else (status, body, content type)."""
    if path not in HANDLERS and path not in ("/openapi.json", "/llms.txt"):
        if path.startswith("/api/"):
            return out(404, {"error": "no such endpoint: %s" % path})
        return None
    if method != "GET":
        return out(405, {"error": "this API is read-only (GET only)"})
    try:
        if path == "/openapi.json":
            return out(200, openapi(secured))
        if path == "/llms.txt":
            return 200, llms_txt(kb, user), "text/plain; charset=utf-8"
        return out(200, HANDLERS[path](kb, user, query))
    except ApiError as err:
        return out(err.code, {"error": err.message})
    except (ValueError, claim_labels.LabelError) as err:
        return out(400, {"error": str(err)})
