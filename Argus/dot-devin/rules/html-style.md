# Acme Claims HTML style

Every HTML page a skill, playbook or tool generates for Acme Claims (dashboards, LOE reports, roadmap
grids, validation forms, presentations) and Argus (`/argus`) use one look: the artifact kit the `!loe` reports are
built with. Same colours, type, spacing, tabs, tables and light/dark behaviour, so a reader
moving from one page to the next sees the same product.

The kit lives in `sdlc/framework/tools/artifact_kit/`:

| File | What it is |
|---|---|
| `kit.css` | The compiled interactive-artifact kit: tokens (`--bg-page`, `--text-accent`, `--text-red` …) whose light values are the Acme Claims/Acme palette (`#5009b5` accent, `#231e33` text, `#f5f5f5` page, Open Sans stack), light and dark themes, `.a-shell`, `.a-header`, `.a-section`, `.a-panel`, `.a-tabs`, `.a-table`, `.a-btn`, `.a-callout`, `.a-empty`, focus, reduced-motion and print rules |
| `kit.js` | Theme toggle (`?theme=dark`, `#theme=dark`, host messages, `prefers-color-scheme`), keyboard-accessible `[data-a-tabs]`, error region |
| `acme.css` | The Acme Claims theme on top: the Acme Claims application look taken from the Figma Acme Claims file (`0LlbLSi97a750W7pYtSstr`) and `web/src/styles/_colors.scss` — Acme purple gradient header strip — one slim line like Argus bar, title and details line left, chips and theme switch right — with a sky rule (`--brand-purple*`, `--brand-sky`), purple section-title bars, pale-purple table headers and purple selected tab, teal callouts, status colours `--brand-success/warning/error`, all as tokens with a dark variant (`--brand-navy*`/`--brand-gold` remain as aliases) — plus `data-attention="hot|watch|info|action|clear"` (red / amber / blue / violet / green, mapped to the kit's `--text-*` tokens), `.a-chip`, `.a-dot`, `.a-badge`, `.a-field`, `.a-fieldset`, `.a-pre` |
| `__init__.py` | `render_page(title, body, ...)` — wraps a body fragment in the shell and inlines the CSS and JS so the file works offline |

## Rules

- Python generators `import artifact_kit` and call `artifact_kit.render_page(...)`. Do not paste
  a new `<style>` block with its own palette into a generator; add page-specific rules through
  `extra_css` and keep them to layout.
- Pages built directly with the `interactive-artifacts` skill (the LOE report) already use the
  same kit. Use its `[data-a-tabs]`, `.a-table`, `.a-timeline` and `.a-callout--risk` /
  `--decision` rather than hand-written equivalents.
- Colour is a supporting signal, never the only one: a red tab also says what needs doing, a
  flagged table row also says why.
- Tokens only. `rgb(var(--text-red))`, not `#c62828`. If a page needs a colour the kit does not
  have, add it to `acme.css` once so every page gets it.
- One file, no network. Everything inline; the only URLs allowed are links to Jira, Bitbucket
  and Confluence. No fonts, scripts or images fetched at open time, no credentials in the page.
- Check before delivering: light and dark, desktop and ~375px wide, tabs by keyboard, print, no
  console errors.

To refresh `kit.css` / `kit.js` from a newer interactive-artifacts kit, copy the compiled files
over and re-run the dashboard against `tools/fixtures/dashboard-demo.json` to make sure nothing
in `acme.css` broke.

When `acme.css` changes, saved pages that cannot be rebuilt without Jira (or were one-off conversions) get the new look with `python3 sdlc/framework/tools/artifact_kit/restyle.py PAGE.html ...`; it swaps only the page's copy of `acme.css` (`--check` lists the pages that are out of date).
