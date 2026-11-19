#!/usr/bin/env python3
"""Build the reference pages Argus menu opens without starting a Devin session.

Help, Catalogue and the onboarding guides say the same thing to everyone, so they are rendered from
their Markdown sources into ACME-styled HTML under sdlc/framework/reference/. Presentation
is already a finished page (ARCHITECTURE.html). Rebuild after changing a source; --check fails when a
committed page no longer matches its source:

    python3 sdlc/framework/tools/gen_reference_pages.py [--check]
"""
import argparse
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifact_kit  # noqa: E402
from artifact_kit import esc, markdown_html  # noqa: E402
import team_links  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = "sdlc/framework/reference"
KB_DIR = "docs/knowledge-base/REPORTS/onboarding"
ONBOARDING_RE = re.compile(r"^ONBOARDING-(?P<role>[A-Za-z-]+?)-(?P<date>\d{4}-\d{2}-\d{2})\.md$")
ONBOARDING_ROLES = [("access", "Getting access"), ("bsa", "BSA"), ("po", "PO"), ("finance-user", "Finance user"), ("developer", "Developer")]
# Written by hand from the team's access sheet, not by /onboarding-guide.
HAND_WRITTEN_GUIDES = {"access"}
BUILDER = "sdlc/framework/tools/gen_reference_pages.py"

DOCS = {
    "help": ("sdlc/framework/USER-MANUAL.md", "HELP.html",
             "Every command, grouped by what you are trying to do."),
    "catalogue": ("sdlc/framework/CATALOGUE.md", "CATALOGUE.html",
                  "Every skill, agent and playbook in the repository, one line each."),
}
# One chapter of a Markdown source as its own page: (source, chapter heading, file name, title, subtitle).
SECTIONS = {
    "po-bsa-sm-guide": ("sdlc/framework/guides/PO-BSA-SM-GUIDE.md", "## One-hour session",
                        "acme-ui-po-bsa-sm-guide.html", "Acme Claims on Devin Cloud: a guide for Product Owners, BSAs and Scrum Masters",
                        "A one-hour, follow-along introduction: run each step in your own Devin Cloud session."),
}
PAGES = list(DOCS) + list(SECTIONS) + ["onboarding"]
ROSTER = ".devin/rules/people.yaml"
CONFLUENCE_PAGE = team_links.confluence()["host"] + "/pages/viewpage.action?pageId=%s"
# Built when opened rather than committed: the roster is regenerated from Confluence by roster_sync.py.
LIVE_PAGES = ["roster"]
OUT_NAMES = dict({k: v[1] for k, v in DOCS.items()}, onboarding="ONBOARDING.html", **{k: v[2] for k, v in SECTIONS.items()})

CSS = """
.ref-doc { max-width: none; font-size: 14px; line-height: 1.6; color: rgb(var(--text-primary)); }
.ref-doc h2 { font-size: 20px; margin: 28px 0 8px; }
.ref-doc h3 { font-size: 16px; margin: 22px 0 6px; }
.ref-doc h4, .ref-doc h5, .ref-doc h6 { font-size: 14px; margin: 16px 0 4px; }
.ref-doc p, .ref-doc ul, .ref-doc ol { margin: 0 0 10px; }
.ref-doc blockquote { margin: 0 0 12px; padding: 6px 14px; border-left: 3px solid rgb(var(--brand-teal));
  background: rgb(var(--tint-tertiary)); }
.ref-doc blockquote p { margin: 4px 0; }
.ref-doc .a-table-scroll { margin: 0 0 14px; }
.ref-doc code { font-size: 12.5px; }
.ref-doc hr { border: 0; border-top: 1px solid rgb(var(--border-secondary)); margin: 20px 0; }
.ref-code { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; margin: 0 0 12px; }
.ref-tabs { margin-bottom: 16px; }
.ref-empty { padding: 16px; border: 1px dashed rgb(var(--border-primary)); border-radius: var(--radius); }
[data-wb-skill][hidden] { display: none; }
"""


class Checkout:
    """Source files from this working tree."""

    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def read_bytes(self, rel):
        with open(os.path.join(ROOT, rel), "rb") as fh:
            return fh.read()

    def list(self, rel_dir):
        path = os.path.join(ROOT, rel_dir)
        return sorted(os.listdir(path)) if os.path.isdir(path) else []


def split_title(text):
    """(first H1, the rest) so the page header carries the title once."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            m = re.match(r"^#\s+(.*)$", line)
            if m:
                return m.group(1).strip(), "\n".join(lines[i + 1:])
            break
    return "", text


def footnote(sources):
    return ("Built from %s by <code>%s</code>. It opens instantly and changes only when its source does."
            % (", ".join("<code>%s</code>" % esc(s) for s in sources), BUILDER))


def image_reader(src, source):
    """data: URIs for the images a Markdown source names, relative to its folder, so the page stays one file."""
    import base64
    base = os.path.dirname(source)

    def image(rel):
        if "://" in rel or not hasattr(src, "read_bytes"):
            return None
        try:
            data = src.read_bytes(os.path.normpath(os.path.join(base, rel)))
        except (OSError, KeyError, ValueError):
            return None
        kind = "png" if rel.lower().endswith(".png") else "jpeg"
        return "data:image/%s;base64,%s" % (kind, base64.b64encode(data).decode("ascii"))
    return image


HELP_CSS = """
.ref-help { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 24px; align-items: start; }
.ref-toc { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; display: grid; gap: 2px;
  padding: 10px; border: 1px solid rgb(var(--border-primary)); border-radius: var(--radius-lg, 8px); background: rgb(var(--bg-elevated)); }
.ref-toc .a-input { width: 100%; box-sizing: border-box; margin-bottom: 6px; }
.ref-toc a { display: block; padding: 4px 6px; border-radius: 4px; font-size: 13px; text-decoration: none; color: rgb(var(--text-primary)); }
.ref-toc a:hover { background: rgb(var(--tint-secondary)); }
.ref-toc a[hidden] { display: none; }
.ref-none { font-size: 12px; color: rgb(var(--text-secondary)); }
.ref-help img[alt^="Hand sketch"] { max-width: 360px; display: block; }
.ref-doc h3 { scroll-margin-top: 12px; }
.ref-help > * { min-width: 0; }
@media (max-width: 900px) { .ref-help { grid-template-columns: minmax(0, 1fr); } .ref-toc { position: static; max-height: 240px; } }
@media print { .ref-toc { display: none; } .ref-help { display: block; } }
"""


def with_contents(html_text):
    """Chapter ids on the h3 headings, and a contents list beside the article with a box to find a chapter."""
    heads, seen = [], {}

    def tag(m):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "chapter"
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug += "-%d" % seen[slug]
        heads.append((slug, text))
        return '<h3 id="%s">%s</h3>' % (slug, m.group(1))
    html_text = re.sub(r"<h3>(.*?)</h3>", tag, html_text)
    if not heads:
        return '<article class="ref-doc">%s</article>' % html_text
    links = "".join('<a href="#%s">%s</a>' % (slug, text) for slug, text in heads)
    return ('<div class="ref-help"><nav class="ref-toc" aria-label="Chapters"><input type="search" class="a-input" '
            'id="refFind" placeholder="Find a chapter or word" aria-label="Find a chapter or word in this manual">'
            '<div id="refToc">%s</div><p class="ref-none" id="refNone" hidden>No chapter matches.</p></nav>'
            '<article class="ref-doc">%s</article></div>' % (links, html_text))


TOC_JS = """
(function () {
  var box = document.getElementById("refFind"); if (!box) { return; }
  var links = Array.prototype.slice.call(document.querySelectorAll("#refToc a"));
  function text(a) {
    var h = document.getElementById(a.getAttribute("href").slice(1)), t = h ? h.textContent : "", n = h && h.nextElementSibling;
    while (n && n.tagName !== "H3") { t += " " + n.textContent; n = n.nextElementSibling; }
    return t.toLowerCase();
  }
  var texts = links.map(text);
  box.addEventListener("input", function () {
    var q = box.value.trim().toLowerCase(), shown = 0;
    links.forEach(function (a, i) { var hit = !q || texts[i].indexOf(q) >= 0; a.hidden = !hit; if (hit) { shown += 1; } });
    document.getElementById("refNone").hidden = shown > 0;
  });
})();
"""


def doc_page(name, src):
    source, _, subtitle = DOCS[name]
    title, body = split_title(src.read(source))
    article = markdown_html(body, image_reader(src, source))
    if name == "help":
        return artifact_kit.render_page(title or name.capitalize(), with_contents(article), subtitle=esc(subtitle),
                                        footnote=footnote([source]), extra_css=CSS + HELP_CSS, extra_js=TOC_JS)
    return artifact_kit.render_page(title or name.capitalize(), '<article class="ref-doc">%s</article>' % article,
                                    subtitle=esc(subtitle), footnote=footnote([source]), extra_css=CSS)


def section_page(name, src):
    source, heading, _, title, subtitle = SECTIONS[name]
    text = src.read(source)
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    body = text[start:end if end >= 0 else len(text)]
    image = image_reader(src, source)
    parts = re.split(r"^### +(.+)$", body, flags=re.M)
    intro, sections = parts[0], list(zip(parts[1::2], parts[2::2]))
    tabs, panels = [], []
    for i, (head, text_) in enumerate(sections):
        tid = "tab-%d" % i
        tabs.append('<button class="a-btn" role="tab" type="button" aria-controls="%s" aria-selected="%s">%s</button>'
                    % (tid, "true" if i == 0 else "false", esc(head.strip())))
        panels.append('<section id="%s" role="tabpanel"%s><article class="ref-doc"><h2>%s</h2>%s</article></section>'
                      % (tid, "" if i == 0 else " hidden", esc(head.strip()), markdown_html(text_, image)))
    page = ('<article class="ref-doc">%s</article><div class="a-tabs a-tabs--wrap ref-tabs" data-a-tabs role="tablist" '
            'aria-label="Guide sections">%s</div>%s' % (markdown_html(intro, image), "".join(tabs), "".join(panels)))
    return artifact_kit.render_page(title, page, subtitle=esc(subtitle), footnote=footnote([source]), extra_css=CSS)


def latest_guides(src):
    """{role key: (file name, date)} for the newest ONBOARDING-<role>-<date>.md of each role."""
    found = {}
    for fname in src.list(KB_DIR):
        m = ONBOARDING_RE.match(fname)
        if not m:
            continue
        role = m.group("role").lower()
        if role not in found or m.group("date") > found[role][1]:
            found[role] = (fname, m.group("date"))
    return found


def onboarding_page(src):
    guides = latest_guides(src)
    tabs, panels = [], []
    first = next((k for k, _ in ONBOARDING_ROLES if k in guides), ONBOARDING_ROLES[0][0])
    for key, label in ONBOARDING_ROLES:
        guide = guides.get(key)
        tabs.append('<button class="a-btn" type="button" role="tab" aria-controls="tab-%s"%s>%s%s</button>' % (
            key, ' aria-selected="true"' if key == first else "", esc(label), "" if guide else " (not written yet)"))
        role_arg = key if key == "finance-user" else label
        ask = ('<button type="button" class="a-btn a-btn--outline" data-wb-skill="onboarding-guide" '
               'data-wb-text="%s" hidden>%s</button>'
               % (esc(role_arg), "Rewrite this guide" if guide else "Ask Devin to write it"))
        if key in HAND_WRITTEN_GUIDES:
            ask = ""
        if guide:
            _, body = split_title(src.read(KB_DIR + "/" + guide[0]))
            origin = "by hand. Edit %s when a request changes." % esc(guide[0]) if key in HAND_WRITTEN_GUIDES \
                else "from the knowledge base."
            inner = ('<p class="a-section__note">Written %s %s %s</p>'
                     '<article class="ref-doc">%s</article>' % (esc(guide[1]), origin, ask, markdown_html(body)))
        else:
            inner = ('<div class="ref-empty">There is no %s guide yet. Guides are written once by '
                     '<code>/onboarding-guide</code> and rewritten when the knowledge base changes. %s</div>'
                     % (esc(label), ask))
        panels.append('<section id="tab-%s" role="tabpanel">%s</section>' % (key, inner))
    body = ('<div class="a-tabs ref-tabs" data-a-tabs role="tablist" aria-label="Onboarding guides">%s</div>%s'
            % ("".join(tabs), "".join(panels)))
    if not guides:
        body = ('<div class="ref-empty">No onboarding guides are written yet. Run <code>/onboarding-guide</code> '
                'with a role to write the first one; it is saved in <code>%s</code> and shows here.</div>%s'
                % (esc(KB_DIR), body))
    sources = [KB_DIR + "/" + g[0] for g in sorted(guides.values())] or [KB_DIR + "/ONBOARDING-<role>-<date>.md"]
    return artifact_kit.render_page("Acme Claims onboarding guides", body,
                                    subtitle="Start here in your first two weeks. Pick your role.",
                                    footnote=footnote(sources), extra_css=CSS)


ROLE_ROUTING = ".devin/rules/role-routing.yaml"


def role_name(role, labels=None):
    return (labels or {}).get(role) or (role or "").replace("_", " ").capitalize()


def roster_page(src):
    """Everyone on people.yaml, grouped by job role, with the hats they wear and the gates they can sign."""
    data = yaml.safe_load(src.read(ROSTER)) or {}
    people = data.get("people") or []
    source = data.get("source") or {}
    signoff = (data.get("owner") or {}).get("signoff") or {}
    names = {p.get("jira_user"): p.get("name") or p.get("jira_user") for p in people}
    routing = (yaml.safe_load(src.read(ROLE_ROUTING)) or {}).get("roles") or {}
    labels = {k: v.get("label") for k, v in routing.items() if isinstance(v, dict) and v.get("label")}
    groups = {}
    for person in people:
        groups.setdefault(person.get("primary_role") or "unassigned", []).append(person)
    head = ("<th>Name</th><th>Jira user</th><th>Also wears</th><th>Can sign gates as</th>"
            "<th>Sprint time</th><th>Away cover</th><th>Devin linked</th>")
    sections = []
    for role in sorted(groups, key=lambda r: (-len(groups[r]), r)):
        rows = []
        for p in sorted(groups[role], key=lambda x: x.get("name") or ""):
            if p.get("delivery") is False:
                time_note = "no sprint work"
            elif p.get("allocation") is not None:
                time_note = "%s%%" % p["allocation"]
            else:
                time_note = "full"
            email = p.get("email") or ""
            name = esc(p.get("name") or p.get("jira_user") or "")
            rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in [
                '<a href="mailto:%s">%s</a>' % (esc(email), name) if email else name,
                "<code>%s</code>" % esc(p.get("jira_user") or "none yet"),
                esc(", ".join(role_name(r, labels) for r in p.get("secondary_roles") or []) or "—"),
                esc(", ".join(role_name(r) for r in p.get("roles") or []) or "—"),
                esc(time_note),
                esc(names.get(p.get("delegate_to"), p.get("delegate_to")) or "—"),
                "yes" if p.get("devin_user_id") else "not yet",
            ]))
        sections.append('<h2>%s <span class="a-badge">%d</span></h2><div class="a-table-scroll"><table class="a-table">'
                        "<thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
                        % (esc(role_name(role, labels)), len(rows), head, "".join(rows)))
    page_id = source.get("confluence_page_id")
    where = ('<a href="%s">%s</a> (version %s)' % (esc(CONFLUENCE_PAGE % page_id), esc(source.get("confluence_title") or
             "the roster page"), esc(source.get("confluence_version"))) if page_id else "<code>%s</code>" % ROSTER)
    intro = (
        '<div class="ref-doc"><p>%d people are on the Acme Claims roster. The list comes from %s, copied to '
        "<code>%s</code> on %s%s. To add someone or change a role, edit the Confluence page; "
        "<code>/roster-check</code> compares it with Jira and raises a pull request for anything that has drifted.</p>"
        "<p><b>Also wears</b> is the other work a person does, which shapes how Devin talks to them. "
        "<b>Can sign gates as</b> is what the approval gates check. <b>Devin linked</b> says whether "
        "their Devin Cloud user id is on the roster, which is how Devin and Argus know who they are "
        "without asking.</p>%s</div>"
        % (len(people), where, ROSTER, esc(str(source.get("synced_at") or "an unknown date")[:10]),
           ", signed off by %s on %s" % (esc(names.get(signoff.get("signed_by"), signoff.get("signed_by"))),
                                         esc(signoff.get("signed_on"))) if signoff.get("status") == "signed" else "",
           '<button type="button" class="a-btn a-btn--outline" data-wb-skill="roster-check" hidden>'
           "Check the roster against Jira</button>"))
    return artifact_kit.render_page("Acme Claims team roster", intro + "".join(sections),
                                    subtitle="Who is who, and which hats they wear.",
                                    footnote=footnote([ROSTER, ROLE_ROUTING]), extra_css=CSS)


def render(name, src=None):
    src = src or Checkout()
    if name == "roster":
        return roster_page(src)
    if name in DOCS:
        return doc_page(name, src)
    if name in SECTIONS:
        return section_page(name, src)
    if name == "onboarding":
        return onboarding_page(src)
    raise KeyError(name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if a committed page is out of date")
    args = ap.parse_args(argv)
    stale = []
    for name in PAGES:
        path = os.path.join(ROOT, OUT_DIR, OUT_NAMES[name])
        page = render(name)
        current = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                current = fh.read()
        if current == page:
            continue
        if args.check:
            stale.append(os.path.relpath(path, ROOT))
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
        print("wrote", os.path.relpath(path, ROOT))
    if stale:
        print("out of date (run %s): %s" % (BUILDER, ", ".join(stale)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
