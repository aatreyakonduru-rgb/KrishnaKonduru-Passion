#!/usr/bin/env python3
"""Who is asking, and which layer of the KB they should meet first.

    python3 audience.py list                    the audiences and what each one favours
    python3 audience.py layers <kb>             how the KB's pages fall into the four layers (and which pages have no clear layer)
    python3 audience.py who    <kb> <person>    the audience Metis would use for this person

The KB is read as four layers, outermost first, like the skins of an onion:

    meaning   what the words and the business are: glossary, overview, domain context
    rules     what must hold: requirements, processes, security rules, decisions, test expectations
    design    how the parts fit: architecture, modules, the link graph, diagrams, impact
    code      what is implemented: tables, columns, jobs, models, endpoints, with line ranges

An audience is a lens over those layers. It changes which lines come first, how many link lines are shown and how much of a
context pack goes to the impact list. It never changes a fact, a source tag, a certification or a clearance: two people asking the
same question see the same true lines, ordered differently, and the answer says how many lines sit at the other layers.
The lens is a ranking hint, never a source. A person's role does not prove anything about the KB.

A page names its layer in its front matter (`layer: meaning|rules|design|code`). Without it the layer comes from the folder
(see FOLDERS), then from the kinds of source it cites. `audience.py layers` lists the guesses so a lead can correct them.

Choosing the audience, first match wins: the one asked for; the profile's `audience.people` (person or role -> audience);
`audience.default`; none (the order the KB had before). Standard library plus PyYAML.
"""
import argparse
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

LAYERS = ("meaning", "rules", "design", "code")

# audience id -> title, what each layer is worth to them (1.0 = neutral), how many link lines to show,
# the share of a context pack given to the impact list, and the question words they lean on
AUDIENCES = {
    "business": {
        "title": "Business",
        "layers": {"meaning": 1.8, "rules": 1.6, "design": 0.7, "code": 0.4},
        "graph_lines": 3, "impact_share": 0.15,
        "blurb": "what it means and which rules apply, before how it is built",
    },
    "developer": {
        "title": "Developer",
        "layers": {"meaning": 0.6, "rules": 0.9, "design": 1.0, "code": 1.8},
        "graph_lines": 15, "impact_share": 0.40,
        "blurb": "the implementation first: names, types, keys, line references",
    },
    "tech_lead": {
        "title": "Tech lead",
        "layers": {"meaning": 0.6, "rules": 1.2, "design": 1.6, "code": 1.3},
        "graph_lines": 15, "impact_share": 0.50,
        "blurb": "what a change touches, who owns it and what could break",
    },
    "architect": {
        "title": "Architect",
        "layers": {"meaning": 0.8, "rules": 1.3, "design": 1.9, "code": 0.8},
        "graph_lines": 15, "impact_share": 0.50,
        "blurb": "how the parts fit and where the boundaries and dependencies are",
    },
    "support": {
        "title": "Support and operations",
        "layers": {"meaning": 1.0, "rules": 1.4, "design": 0.8, "code": 1.0},
        "graph_lines": 6, "impact_share": 0.30,
        "blurb": "what runs when, what to check when it fails and who to call",
    },
}
ALIASES = {"biz": "business", "ba": "business", "bsa": "business", "product owner": "business", "po": "business",
           "dev": "developer", "engineer": "developer", "tech lead": "tech_lead", "techlead": "tech_lead", "lead": "tech_lead",
           "tl": "tech_lead", "arch": "architect", "ops": "support", "operations": "support", "sre": "support"}

# a folder name on a page's path -> layer; layers are tried in this order, a match on any folder counts
FOLDERS = (
    ("meaning", ("glossary", "overview", "domain", "business", "product")),
    ("rules", ("requirements", "requirement", "processes", "process", "security", "testing", "decisions", "adr", "meetings", "policies")),
    ("design", ("architecture", "design", "cross-layer", "modules", "diagrams", "semantic", "context")),
    ("code", ("db", "etl", "dbt", "app", "src", "documents", "jobs", "models", "api")),
)
FRONT = re.compile(r"\A---\s*\n(.*?)\n---", re.S)
EVIDENCE_LAYER = (("code", re.compile(r"\[E:\s*[^\]:\s]+/[^\]\s]+:\d+")), ("code", re.compile(r"\[E:\s*query:")),
                  ("rules", re.compile(r"\[E:\s*(?:confluence|jira|doc|file|answer):")))


class AudienceError(ValueError):
    pass


def norm(name):
    key = " ".join(str(name or "").lower().replace("_", " ").replace("-", " ").split())
    key = ALIASES.get(key, key)
    return key.replace(" ", "_")


def get(name):
    """The audience definition for a name or alias, or None for no lens. An unknown name is an error, not a silent default."""
    if not name:
        return None
    key = norm(name)
    if key in AUDIENCES:
        return dict(AUDIENCES[key], id=key)
    raise AudienceError("audience must be one of: %s" % ", ".join(sorted(AUDIENCES)))


def profile(kb):
    p = os.path.join(kb, ".metis", "kb-profile.yaml")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve(kb, who=None, asked=None):
    """The audience for this question: asked for, else the profile's mapping for the person, else the default, else None."""
    if asked:
        return get(asked)
    cfg = (profile(kb).get("audience") or {})
    people = {norm(k): v for k, v in (cfg.get("people") or {}).items()}
    if who and norm(who) in people:
        return get(people[norm(who)])
    if who and norm(who) in AUDIENCES:
        return get(who)
    return get(cfg.get("default")) if cfg.get("default") else None


def front_layer(text):
    m = FRONT.match(text or "")
    if not m:
        return None
    try:
        v = (yaml.safe_load(m.group(1)) or {}).get("layer")
    except yaml.YAMLError:
        return None
    v = str(v or "").strip().lower()
    return v if v in LAYERS else None


def layer_of(rel, text=""):
    """(layer, how) for a page: its front matter, else its folder, else the sources it cites, else design."""
    fl = front_layer(text)
    if fl:
        return fl, "front matter"
    parts = [p for p in re.split(r"[\\/]", rel.lower()) if p]
    folders = parts[:-1]
    for layer, names in FOLDERS:
        if any(f in names for f in folders):
            return layer, "folder"
    for layer, rx in EVIDENCE_LAYER:
        if len(rx.findall(text or "")) >= 2:
            return layer, "sources"
    return "design", "default"


class Lens:
    """An audience applied to one KB: page layers are read once and cached."""

    def __init__(self, kb, audience):
        self.kb, self.a = kb, audience
        self._layers = {}

    @property
    def id(self):
        return self.a["id"]

    def layer(self, rel):
        if rel not in self._layers:
            text = ""
            p = os.path.join(self.kb, rel)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            self._layers[rel] = layer_of(rel, text)[0]
        return self._layers[rel]

    def weight(self, rel):
        return self.a["layers"].get(self.layer(rel), 1.0)

    def order(self):
        return sorted(LAYERS, key=lambda l: -self.a["layers"][l])

    def describe(self):
        return "%s: %s (layers first: %s)" % (self.a["title"], self.a["blurb"], ", ".join(self.order()))


def lens_for(kb, who=None, asked=None):
    a = resolve(kb, who, asked)
    return Lens(kb, a) if a else None


def survey(kb):
    import kb_coverage
    rows = []
    for rel, text in sorted(kb_coverage.page_files(kb).items()):
        layer, how = layer_of(rel, text)
        rows.append({"page": rel, "layer": layer, "from": how})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("layers")
    p.add_argument("kb")
    p.add_argument("--strict", action="store_true", help="exit 1 when a page has no layer from front matter, folder or sources")
    p = sub.add_parser("who")
    p.add_argument("kb")
    p.add_argument("person")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for k, v in AUDIENCES.items():
            print("%-10s %s" % (k, v["blurb"]))
        return 0
    if a.cmd == "layers":
        rows = survey(a.kb)
        for layer in LAYERS:
            hit = [r for r in rows if r["layer"] == layer]
            print("%-8s %3d page(s)" % (layer, len(hit)))
            for r in hit:
                print("           %s  (%s)" % (r["page"], r["from"]))
        guess = [r for r in rows if r["from"] == "default"]
        if guess:
            print("\n%d page(s) have no layer from front matter, folder or sources; add `layer:` to their front matter." % len(guess))
        return 1 if guess and a.strict else 0
    try:
        aud = resolve(a.kb, a.person)
    except AudienceError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("%s -> %s" % (a.person, aud["id"] if aud else "no lens (the KB's own order)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
