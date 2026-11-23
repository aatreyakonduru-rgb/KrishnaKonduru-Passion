"""Business glossary for Metis: terms, synonyms, meanings, and where they appear in the knowledge base.

Stored as plain YAML in <KB>/.metis/glossary.yaml.
Product owners and BSAs onboard business definitions; Ask uses synonyms to expand queries.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kb_gate  # noqa: E402
import sensitive  # noqa: E402
import ui_common as C  # noqa: E402

GLOSSARY_FILE = os.path.join(".metis", "glossary.yaml")


def path(kb):
    return os.path.join(kb, GLOSSARY_FILE)


def load(kb):
    """Load the glossary YAML from <KB>/.metis/glossary.yaml. Returns dict with 'entries' list."""
    p = path(kb)
    data = C.load_yaml(p)
    if not isinstance(data, dict):
        return {"entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    # Normalize entry structures
    norm = []
    for e in entries:
        if isinstance(e, dict) and e.get("term"):
            norm.append({
                "term": str(e.get("term", "")),
                "synonyms": [str(s) for s in (e.get("synonyms") or []) if str(s).strip()],
                "meaning": str(e.get("meaning", "") or ""),
                "where_in_kb": [str(w) for w in (e.get("where_in_kb") or []) if str(w).strip()],
                "added_by": str(e.get("added_by", "") or ""),
                "added_on": str(e.get("added_on", "") or ""),
            })
    return {"entries": norm}


def save(kb, data):
    """Save glossary entries to <KB>/.metis/glossary.yaml."""
    p = path(kb)
    entries = data.get("entries", [])
    head = "# Business glossary for Metis. Keep this file under version control.\n"
    C.dump_yaml(p, {"entries": entries}, head=head)


def check_permission(kb, by):
    """Rule: before lock anyone with a name may change entries; after lock only a named lead from kb_gate."""
    user = C.clean(by)
    if not user:
        raise C.UiError("Say who you are first (top right, 'You are'). Your name goes on every approval, rating and answer.")
    if kb_gate.is_locked(kb):
        leads = kb_gate.certifiers(kb)
        if user.lower() not in leads:
            names = ", ".join(v[0] for v in leads.values()) or "no leads named in Setup"
            raise C.UiError("After the KB is locked, only a named lead may change the glossary (leads: %s)." % names)
    return user


def check_secrets(term, synonyms, meaning):
    """Never store secrets: scan all text with sensitive.py."""
    combined = "%s\n%s\n%s" % (term, "\n".join(synonyms), meaning)
    findings = sensitive.scan(combined)
    blocks = sensitive.blocking(findings)
    if blocks:
        raise C.UiError("Cannot store secrets in glossary: %s detected (starting %s)." % (blocks[0]["kind"], blocks[0]["sample"]))


def parse_list(val):
    if isinstance(val, (list, tuple)):
        return [C.clean(s) for s in val if C.clean(s)]
    parts = re.split(r"[\n,]+", str(val or ""))
    return [C.clean(s) for s in parts if C.clean(s)]


def add(kb, term, synonyms, meaning, where_in_kb, by):
    """Add a new glossary entry."""
    user = check_permission(kb, by)
    term_clean = C.clean(term)
    if not term_clean:
        raise C.UiError("Enter a glossary term.")
    syns = parse_list(synonyms)
    pages = parse_list(where_in_kb)
    meaning_clean = str(meaning or "").strip()
    check_secrets(term_clean, syns, meaning_clean)

    data = load(kb)
    entries = data.get("entries", [])
    if any(e["term"].lower() == term_clean.lower() for e in entries):
        raise C.UiError("Term '%s' already exists in the glossary." % term_clean)

    entry = {
        "term": term_clean,
        "synonyms": syns,
        "meaning": meaning_clean,
        "where_in_kb": pages,
        "added_by": user,
        "added_on": C.today(),
    }
    entries.append(entry)
    save(kb, {"entries": entries})
    return entry


add_entry = add


def update(kb, term, synonyms, meaning, where_in_kb, by, old_term=None):
    """Update an existing glossary entry."""
    user = check_permission(kb, by)
    target = C.clean(old_term or term)
    term_clean = C.clean(term)
    if not term_clean:
        raise C.UiError("Enter a glossary term.")
    syns = parse_list(synonyms)
    pages = parse_list(where_in_kb)
    meaning_clean = str(meaning or "").strip()
    check_secrets(term_clean, syns, meaning_clean)

    data = load(kb)
    entries = data.get("entries", [])
    found = None
    for e in entries:
        if e["term"].lower() == target.lower():
            found = e
            break
    if not found:
        raise C.UiError("Term '%s' not found in the glossary." % target)

    # Check for name collision if renaming
    if term_clean.lower() != target.lower() and any(e["term"].lower() == term_clean.lower() for e in entries):
        raise C.UiError("Term '%s' already exists in the glossary." % term_clean)

    found["term"] = term_clean
    found["synonyms"] = syns
    found["meaning"] = meaning_clean
    found["where_in_kb"] = pages
    found["added_by"] = user
    found["added_on"] = C.today()

    save(kb, {"entries": entries})
    return found


update_entry = update


def remove(kb, term, by):
    """Remove a glossary entry by term."""
    check_permission(kb, by)
    target = C.clean(term)
    if not target:
        raise C.UiError("Specify a term to remove.")
    data = load(kb)
    entries = data.get("entries", [])
    keep = [e for e in entries if e["term"].lower() != target.lower()]
    if len(keep) == len(entries):
        raise C.UiError("Term '%s' not found in the glossary." % target)
    save(kb, {"entries": keep})
    return target


remove_entry = remove


def problems(kb):
    """Check for problems: a synonym used by two terms, a page that does not exist, an empty meaning."""
    data = load(kb)
    entries = data.get("entries", [])
    probs = []

    syn_to_terms = {}
    for e in entries:
        t = e["term"]
        # Empty meaning
        if not (e.get("meaning") or "").strip():
            probs.append("%s: meaning is empty" % t)

        # Pages that do not exist
        for page in e.get("where_in_kb", []):
            rel = page.strip().lstrip("/\\")
            full = os.path.join(kb, rel)
            if not os.path.isfile(full):
                probs.append("%s: page does not exist in KB (%s)" % (t, page))

        # Check synonyms
        for s in e.get("synonyms", []):
            s_low = s.strip().lower()
            if not s_low:
                continue
            syn_to_terms.setdefault(s_low, []).append((s, t))

    # Duplicate synonyms across terms
    for s_low, occurrences in sorted(syn_to_terms.items()):
        terms_using = sorted({t for _, t in occurrences})
        if len(terms_using) > 1:
            display_syn = occurrences[0][0]
            probs.append("Synonym '%s' is used by multiple terms: %s" % (display_syn, ", ".join(terms_using)))

    return probs


def expand(kb_or_question, question=None):
    """expand(question) -> {"terms": [...], "extra_words": [...]}

    Returns glossary terms and synonyms found in a question and the other words that mean the same,
    so the Ask page can search with them.
    Can be called as expand(kb, question) or expand(question).
    """
    if question is None:
        q_text = str(kb_or_question or "")
        kb_path = os.environ.get("METIS_KB", ".")
    else:
        kb_path = kb_or_question
        q_text = str(question or "")

    data = load(kb_path)
    entries = data.get("entries", [])
    matched_terms = []
    extra_words = []

    q_lower = q_text.lower()

    for e in entries:
        term = e.get("term", "")
        synonyms = e.get("synonyms", [])
        all_concept_words = [term] + synonyms

        # Check if term or any synonym appears in question as whole word/phrase
        hit = False
        for cand in all_concept_words:
            cand_clean = cand.strip()
            if not cand_clean:
                continue
            pattern = r"(?<!\w)%s(?:s|es)?(?!\w)" % re.escape(cand_clean.lower())  # "client" also finds "clients"
            if re.search(pattern, q_lower):
                hit = True
                break

        if hit:
            if term not in matched_terms:
                matched_terms.append(term)
            for w in all_concept_words:
                w_clean = w.strip()
                if w_clean and w_clean not in extra_words:
                    extra_words.append(w_clean)

    return {
        "terms": matched_terms,
        "extra_words": extra_words,
    }
