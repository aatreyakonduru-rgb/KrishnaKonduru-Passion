"""Put the current Acme Claims look on pages that were already built with the kit.

A page built by `render_page` carries its own copy of acme.css. When acme.css changes, pages whose
generator needs Jira (roadmap, hygiene rulebook) or was a one-off conversion (decks, status reports)
keep the old copy until they are rebuilt. This swaps that copy for the current file and leaves the
rest of the page as it is.

    python3 tools/artifact_kit/restyle.py PAGE.html [PAGE.html ...] [--check]

`--check` lists the pages that are out of date and exits 1 when there are any.
"""
import argparse
import html
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSS = os.path.join(HERE, "acme.css")
START = "/* Acme Claims theme on top of the artifact kit"
END = "/* end acme.css */"
MARKER = 'content="Acme Claims artifact kit"'


def _history():
    """Every committed version of acme.css, newest first, for pages built before the end marker."""
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, capture_output=True,
                              text=True, check=True).stdout.strip()
        rel = os.path.relpath(CSS, root)
        shas = subprocess.run(["git", "log", "--format=%H", "--", rel], cwd=root, capture_output=True,
                              text=True, check=True).stdout.split()
        return [subprocess.run(["git", "show", "%s:%s" % (sha, rel)], cwd=root, capture_output=True,
                               text=True, check=True).stdout for sha in shas]
    except (OSError, subprocess.CalledProcessError):
        return []


SUBTITLE = re.compile(r'<p class="a-header__subtitle">(.*?)</p>', re.S)


def _tooltip(page):
    """Give a details line without one the tooltip render_page adds, so a line cut short can be read."""
    def add(m):
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        return '<p class="a-header__subtitle" title="%s">%s</p>' % (html.escape(" ".join(text.split())), m.group(1))
    return SUBTITLE.sub(add, page, count=1)


def restyle(page, current, history):
    """(new page text, status) where status is "current", "updated" or why it was skipped."""
    if MARKER not in page:
        return page, "not a kit page"
    at = page.find(START)
    if at < 0:
        return page, "no Acme Claims styles found"
    end = page.find(END, at)
    if end >= 0:
        old = page[at:end + len(END)]
    else:
        old = next((v.rstrip("\n") for v in history if page.startswith(v.rstrip("\n"), at)), None)
        if old is None:
            return page, "styles do not match any saved version of acme.css"
    out = _tooltip(page[:at] + current.rstrip("\n") + page[at + len(old):])
    if out == page:
        return page, "current"
    return out, "updated"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pages", nargs="+")
    parser.add_argument("--check", action="store_true", help="only list the pages that are out of date")
    args = parser.parse_args(argv)
    with open(CSS, encoding="utf-8") as fh:
        current = fh.read()
    history, stale = None, 0
    for path in args.pages:
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        if history is None and END not in page:
            history = _history()
        new, status = restyle(page, current, history or [])
        if status == "updated":
            stale += 1
            if not args.check:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
        print("%-10s %s" % ("out of date" if args.check and status == "updated" else status, path))
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
