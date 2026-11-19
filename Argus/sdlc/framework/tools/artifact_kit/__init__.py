"""The Acme Claims house style for every generated HTML page.

`kit.css` and `kit.js` are the Devin artifact kit as compiled by `interactive_artifact_compile`
(the same shell the `!loe` reports use); `acme.css` adds the few controls the kit does not ship
(form fields, tab badges, attention colours) on top of the kit's own tokens. Generators call
`render_page` with a body fragment written in `a-` classes and get one offline, self-contained
file back: no fonts, scripts or styles are fetched at runtime.
"""
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


def _plain(markup):
    """The text of an HTML fragment, for a tooltip."""
    return html.unescape(re.sub(r"<[^>]+>", "", str(markup)))


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


THEME_TOGGLE = (
    '<button type="button" class="a-btn a-btn--icon a-no-print" data-a-theme-toggle '
    'aria-label="Switch to dark mode" title="Switch to dark mode">'
    '<svg class="a-theme-icon a-theme-icon--moon" aria-hidden="true" viewBox="0 0 24 24">'
    '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" /></svg>'
    '<svg class="a-theme-icon a-theme-icon--sun" aria-hidden="true" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="4" />'
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4'
    'M17.7 6.3l1.4-1.4" /></svg></button>'
)

ERROR_REGION = (
    '<section class="a-section a-error" data-a-error role="alert" aria-live="polite" hidden>'
    '<p class="a-error__title">Something in this page failed to run</p>'
    '<p>The content below is still readable, but an interactive control may not respond. '
    '<span data-a-error-detail></span></p></section>'
)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="generator" content="Acme Claims artifact kit" />
<title>%(title)s</title>
<style>
%(kit_css)s
%(acme_css)s
%(extra_css)s
</style>
</head>
<body class="%(body_class)s">
<main class="a-shell">
<header class="a-header">%(logo)s<div><h1 class="a-header__title">%(title)s</h1>%(subtitle)s%(header_extra)s</div>
<div class="a-header__aside">%(aside)s%(toggle)s</div></header>
%(error)s
%(body)s
%(footer)s
%(before_kit_js)s
</main>
<script>
%(kit_js)s
</script>
<script>
%(extra_js)s
</script>
</body>
</html>
"""


def render_page(title, body, subtitle="", footnote="", extra_css="", extra_js="",
                before_kit_js="", header_extra="", aside="", body_class="", logo=""):
    """Wrap a body fragment in the Acme Claims shell.

    `body`, `header_extra`, `aside` and `footnote` are HTML the caller has already escaped.
    `before_kit_js` runs after the body but before the kit script (for example to pick the
    initial tab from the URL hash); `extra_js` runs after the kit.
    """
    return PAGE % {
        "title": esc(title),
        "subtitle": ('<p class="a-header__subtitle" title="%s">%s</p>' % (esc(_plain(subtitle)), subtitle)
                     if subtitle else ""),
        "header_extra": header_extra,
        "logo": ('<img class="a-header__logo" src="%s" alt="" />' % esc(logo)) if logo else "",
        "aside": aside,
        "toggle": THEME_TOGGLE,
        "error": ERROR_REGION,
        "body": body,
        "footer": '<footer class="a-footnote">%s</footer>' % footnote if footnote else "",
        "kit_css": _read("kit.css"),
        "acme_css": _read("acme.css"),
        "extra_css": extra_css,
        "kit_js": _read("kit.js"),
        "extra_js": extra_js,
        "before_kit_js": '<script>\n%s\n</script>' % before_kit_js if before_kit_js else "",
        "body_class": esc(body_class),
    }


TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _inline(text):
    out = esc(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\s][^*]*)\*(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    return out


def _cells(row):
    row = row.strip()[1:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


IMAGE_LINE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")


def markdown_html(text, image=None):
    """The Markdown the repository writes (headings, paragraphs, lists, tables, quotes, code) as kit HTML.

    Everything is escaped first; links only become anchors for http(s) targets. A line that is only an image,
    ![alt](path), becomes a figure when `image(path)` returns a data URI for it, and its alt text otherwise.
    """
    lines = (text or "").replace("\r", "").split("\n")
    out, para, i = [], [], 0

    def flush():
        if para:
            out.append("<p>%s</p>" % " ".join(_inline(p) for p in para))
            del para[:]

    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append('<pre class="a-pre ref-code">%s</pre>' % esc("\n".join(code)))
            i += 1
            continue
        m = IMAGE_LINE.match(line.strip())
        if m:
            flush()
            src = image(m.group(2)) if image else None
            out.append('<figure class="ref-fig"><img src="%s" alt="%s" style="max-width:100%%"></figure>' % (esc(src), esc(m.group(1)))
                       if src else "<p><em>[Image: %s]</em></p>" % esc(m.group(1)))
            i += 1
            continue
        if TABLE_ROW.match(line):
            flush()
            rows = []
            while i < len(lines) and TABLE_ROW.match(lines[i]):
                if not TABLE_RULE.match(lines[i]):
                    rows.append(_cells(lines[i].replace("\\|", "&#124;")))
                i += 1
            head = "".join("<th>%s</th>" % _inline(c).replace("&amp;#124;", "|") for c in rows[0])
            body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c).replace("&amp;#124;", "|") for c in r)
                           for r in rows[1:])
            out.append('<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead>'
                       '<tbody>%s</tbody></table></div>' % (head, body))
            continue
        m = HEADING.match(line)
        if m:
            flush()
            level = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            i += 1
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            flush()
            out.append("<hr />")
            i += 1
            continue
        if line.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % markdown_html("\n".join(quote)))
            continue
        m = LIST_ITEM.match(line)
        if m:
            flush()
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            items = []
            while i < len(lines):
                m = LIST_ITEM.match(lines[i])
                if m:
                    items.append(m.group(3))
                elif lines[i].startswith("  ") and lines[i].strip() and items:
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % _inline(t) for t in items), tag))
            continue
        if not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)
