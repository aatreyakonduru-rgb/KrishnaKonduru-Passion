"""Shared helpers for the Metis UI: reading and writing settings, running the existing tools, and the page layout.

The UI is a thin layer over the tools in the folder above. It never reimplements a rule: it calls them (as a program, or as
a library where the tool exposes a function) and shows what they say. Standard library plus PyYAML only.
"""
import datetime
import html
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
METIS = os.path.dirname(TOOLS)
for _p in (TOOLS, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TAG = re.compile(r"\[(E|\?):\s*([^\]]+)\]")
NAV = [("/", "Home"), ("/setup", "Setup"), ("/build", "Build"), ("/files", "KB files"), ("/ask", "Ask"),
       ("/questions", "Questions"), ("/approve", "Approve"), ("/coverage", "Coverage")]
NAV_MORE = []  # second row: filled by server.load_screens() from the screens_*.py modules


class UiError(ValueError):
    """A problem the person can fix; its text is shown on the page."""


class Ctx(object):
    """One request's context. `user` is the name on every record. With sign-in on (auth.mode oidc) it is the verified identity from
    the signed session and `sso` is True, so a cookie cannot change it. `theme` is auto|light|dark and `env` the chosen environment
    ('' = the reference one); both come from cookies the server validates."""
    def __init__(self, kb, token, user="", theme="auto", env="", sso=False, roles=()):
        self.kb = os.path.abspath(kb)
        self.token = token
        self.user = user
        self.theme = theme if theme in ("auto", "light", "dark") else "auto"
        self.env = env
        self.sso = bool(sso)
        self.roles = list(roles)


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def today():
    return datetime.date.today().isoformat()


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def clean(text):
    return " ".join(str(text or "").split())


def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def dump_yaml(path, data, head=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def profile_path(kb):
    return os.path.join(kb, ".metis", "kb-profile.yaml")


def profile(kb):
    return load_yaml(profile_path(kb))


def real(value):
    v = clean(value)
    return bool(v) and not (v.startswith("<") and v.endswith(">"))


def get(data, dotted, default=None):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def workspace_root(kb, prof=None):
    prof = prof if prof is not None else profile(kb)
    ws = get(prof, "sources.workspace_root")
    if real(ws):
        return os.path.abspath(ws)
    return os.path.dirname(os.path.dirname(os.path.abspath(kb)))


def run_tool(script, args=(), kb=None, env=None, timeout=900):
    """Run one of the Metis tools as a program. Returns (exit code, output). Output is never empty of the reason it failed."""
    path = script if os.path.isabs(script) else os.path.join(TOOLS, script)
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if kb:
        e["METIS_KB"] = kb
        e["KB_PROFILE"] = profile_path(kb)
        e["KB_TEAM_ROOT"] = kb
    if env:
        e.update(env)
    try:
        r = subprocess.run([sys.executable, path] + [str(a) for a in args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=e, cwd=kb or TOOLS)
    except subprocess.TimeoutExpired:
        return 124, "%s did not finish within %d seconds" % (os.path.basename(path), timeout)
    out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr and r.stderr.strip() else "")
    return r.returncode, out.strip()


# ---- markdown to html, enough for KB pages and answers --------------------------------------------
def inline(text):
    t = esc(text)
    t = re.sub(r"\[(E|\?):\s*([^\]]+)\]", lambda m: '<span class="tag" title="source">[%s: %s]</span>' % (m.group(1), m.group(2)), t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return t


def render_md(text):
    out, in_code, in_list, rows = [], False, False, []
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if end:
            lines = lines[end + 1:]

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def flush_rows():
        nonlocal rows
        if rows:
            body = [r for r in rows if not re.match(r"^\s*\|?\s*:?-{3,}", r)]
            html_rows = []
            for i, r in enumerate(body):
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                tag = "th" if i == 0 else "td"
                html_rows.append("<tr>%s</tr>" % "".join("<%s>%s</%s>" % (tag, inline(c), tag) for c in cells))
            out.append("<table>%s</table>" % "".join(html_rows))
            rows = []

    for line in lines:
        s = line.rstrip()
        if s.strip().startswith("```"):
            flush_rows()
            close_list()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(esc(s))
            continue
        if s.strip().startswith("|"):
            rows.append(s)
            continue
        flush_rows()
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close_list()
            n = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (n, inline(m.group(2)), n))
        elif re.match(r"^\s*([-*]|\d+[.)])\s+", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(re.sub(r"^\s*([-*]|\d+[.)])\s+", "", s)))
        elif not s.strip():
            close_list()
        else:
            close_list()
            out.append("<p>%s</p>" % inline(s))
    flush_rows()
    close_list()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


# ---- page layout -----------------------------------------------------------------------------------
# Colours are tokens (CSS variables). TOKENS_LIGHT is the default; TOKENS_DARK applies when the cookie `theme` says dark, or when
# it says auto (or is missing) and the browser prefers dark. /theme sets the cookie (dark|light|auto); there is no JavaScript.
TOKENS_LIGHT = {
    "bg": "#ffffff", "fg": "#1f2328", "muted": "#57606a", "sub": "#6b7280", "surface": "#f3f4f6", "panel": "#fafbfc",
    "soft": "#f7f8fa", "border": "#d5d9e0", "border2": "#e5e7eb", "line": "#eef0f3", "field-border": "#cfd6df",
    "card-border": "#e1e5ea", "field-bg": "#ffffff", "hover": "#f1f5fb", "sel-bg": "#e7f0ff", "accent": "#2563eb",
    "on-accent": "#ffffff", "link": "#1d4ed8", "code-bg": "#f1f3f5", "tag": "#6d28d9", "ok": "#15803d", "no": "#b91c1c",
    "warn": "#b45309", "ok-bg": "#dcfce7", "ok-bd": "#a7dbb7", "no-bg": "#fee2e2", "no-bd": "#f0b4ae",
    "pill-ok-fg": "#166534", "pill-ok-bg": "#dcfce7", "pill-ok-bd": "#bbf7d0",
    "pill-no-fg": "#991b1b", "pill-no-bg": "#fee2e2", "pill-no-bd": "#fecaca",
    "pill-warn-fg": "#92400e", "pill-warn-bg": "#fef3c7", "pill-warn-bd": "#fde68a",
    "pill-blue-fg": "#1d4ed8", "pill-blue-bg": "#e0edff", "pill-blue-bd": "#bfdbfe",
    "bad": "#b42318", "avatar": "#7c5cd8", "bar": "#e5e7eb", "bar-fill": "#3b82f6", "bot-bg": "#f3f4f6",
    "rail-bg": "#1b2130", "rail-line": "#2a3348", "rail-fg": "#8b95a7", "rail-ico": "#aab3c5", "rail-hover": "#232b3d",
    "rail-on": "#262e42", "rail-on-fg": "#ffffff", "sb-bg": "#1d4ed8", "sb-fg": "#e8f0ff",
    "diff-add": "#e6ffec", "diff-del": "#ffebe9", "diff-hunk": "#f0f1f3",
}
TOKENS_DARK = {
    "bg": "#0f1420", "fg": "#e6e9ef", "muted": "#a3adbd", "sub": "#9aa5b8", "surface": "#171d2b", "panel": "#131927",
    "soft": "#161c2a", "border": "#2b3447", "border2": "#2b3447", "line": "#232b3b", "field-border": "#3a4559",
    "card-border": "#2b3447", "field-bg": "#0b101a", "hover": "#1b2436", "sel-bg": "#1c2b4a", "accent": "#2b5fd9",
    "on-accent": "#ffffff", "link": "#8ab4ff", "code-bg": "#1f2738", "tag": "#c4a6ff", "ok": "#4ade80", "no": "#f87171",
    "warn": "#fbbf24", "ok-bg": "#12301f", "ok-bd": "#1f5133", "no-bg": "#3a1618", "no-bd": "#6b2a2d",
    "pill-ok-fg": "#86efac", "pill-ok-bg": "#12301f", "pill-ok-bd": "#1f5133",
    "pill-no-fg": "#fca5a5", "pill-no-bg": "#3a1618", "pill-no-bd": "#6b2a2d",
    "pill-warn-fg": "#fcd34d", "pill-warn-bg": "#3a2c0c", "pill-warn-bd": "#6b5217",
    "pill-blue-fg": "#93c5fd", "pill-blue-bg": "#14284d", "pill-blue-bd": "#24427a",
    "bad": "#c6382b", "avatar": "#7c5cd8", "bar": "#2b3447", "bar-fill": "#3b82f6", "bot-bg": "#1f2738",
    "rail-bg": "#0a0e17", "rail-line": "#232b3d", "rail-fg": "#8b95a7", "rail-ico": "#aab3c5", "rail-hover": "#171e2e",
    "rail-on": "#1b2438", "rail-on-fg": "#ffffff", "sb-bg": "#1b3a8a", "sb-fg": "#e8f0ff",
    "diff-add": "#12301f", "diff-del": "#3a1618", "diff-hunk": "#1f2738",
}
THEMES = ("auto", "light", "dark")


def _vars(tokens):
    return ";".join("--%s:%s" % (k, v) for k, v in tokens.items())


CSS = (":root{%s;color-scheme:light}\n"
       "@media(prefers-color-scheme:dark){:root:not([data-theme=light]){%s;color-scheme:dark}}\n"
       ":root[data-theme=dark]{%s;color-scheme:dark}\n") % (_vars(TOKENS_LIGHT), _vars(TOKENS_DARK), _vars(TOKENS_DARK)) + """
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;display:flex;flex-direction:column;font:13px/1.45 -apple-system,"Segoe UI",system-ui,sans-serif;color:var(--fg);background:var(--bg)}
a{color:var(--link)}
.tb{height:34px;flex:none;display:flex;align-items:center;gap:8px;padding:0 10px;background:var(--surface);border-bottom:1px solid var(--border)}
.brand{display:inline-flex;align-items:center;gap:6px;text-decoration:none;color:var(--fg);font-weight:700;font-size:13px;padding:2px 6px;border-radius:4px;white-space:nowrap}
.brand:hover{background:var(--hover)}
.brand svg{display:inline-block;vertical-align:middle;flex:none}
.tb form{margin:0;display:flex;gap:4px;align-items:center}
.tb input[type=text]{width:auto;padding:2px 7px;font-size:12px;border-radius:4px;background:var(--field-bg)}
.tb select{width:auto;padding:1px 4px;font-size:12px}
.tb button{padding:2px 9px;font-size:12px}
.tb .sp,.sb .sp{flex:1}
.apm{border:1px solid var(--field-border);border-radius:4px;padding:1px 8px;font-weight:700;background:var(--field-bg)}
.env{border:1px solid var(--field-border);border-radius:4px;padding:1px 8px;background:var(--field-bg);font-weight:600}
.thm{border:1px solid var(--field-border);border-radius:4px;padding:1px 8px;background:var(--field-bg);font-size:12px;text-decoration:none;color:var(--fg);white-space:nowrap}
.asof{color:var(--muted)}
.av{width:22px;height:22px;border-radius:50%;background:var(--avatar);color:#fff;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center}
.mid{flex:1;display:flex;min-height:0}
.rail{width:58px;flex:none;background:var(--rail-bg);display:flex;flex-direction:column;padding-top:2px}
.rail .top{flex:1;min-height:0;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--rail-line) var(--rail-bg);background:var(--rail-bg)}
.rail .bot{flex:none;background:var(--rail-bg);border-top:1px solid var(--rail-line)}
.rail .top::-webkit-scrollbar{width:4px}.rail .top::-webkit-scrollbar-thumb{background:var(--rail-line)}
.rail a{position:relative;display:block;text-align:center;color:var(--rail-fg);font-size:9px;padding:4px 0 3px;border-left:2px solid transparent;text-decoration:none}
.rail a i{display:block;font-style:normal;font-size:15px;line-height:16px;color:var(--rail-ico)}
.rail a:hover{background:var(--rail-hover)}
.rail a.on{color:var(--rail-on-fg);background:var(--rail-on);border-left-color:#3b82f6}
.rail a.on i{color:var(--rail-on-fg)}
.rail .n{position:absolute;top:2px;right:7px;background:#ef4444;color:#fff;border-radius:8px;font-size:9px;line-height:13px;padding:0 4px}
.lp{width:236px;flex:none;border-right:1px solid var(--border);display:flex;flex-direction:column;background:var(--panel);min-height:0;overflow-y:auto}
.lp .hd{padding:7px 10px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:1px solid var(--border2);display:flex;justify-content:space-between}
.lp .flt{margin:6px 8px}.lp .flt input{padding:3px 7px;font-size:12px}
.it{display:block;padding:6px 10px;border-bottom:1px solid var(--line);color:inherit;text-decoration:none}
.it:hover{background:var(--hover)}
.it.on{background:var(--sel-bg);border-left:2px solid var(--accent);padding-left:8px}
.it .s{display:block;color:var(--sub);font-size:11px}
.it .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:#9ca3af}
.it .dot.r{background:var(--no)}.it .dot.a{background:var(--warn)}.it .dot.g{background:var(--ok)}
.grp{padding:6px 10px;font-weight:700;border-bottom:1px solid var(--line);color:var(--fg)}
.grp .c{color:var(--sub);font-weight:400}
.mn{flex:1;min-width:0;overflow-y:auto}
.rp{width:252px;flex:none;border-left:1px solid var(--border);background:var(--panel);padding:10px;overflow-y:auto}
.rp h4,.lp h4{margin:12px 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.rp h4:first-child{margin-top:0}
.rp table td{padding:3px 4px}
.sb{height:22px;flex:none;background:var(--sb-bg);color:var(--sb-fg);display:flex;gap:14px;align-items:center;padding:0 10px;font-size:11px}
main{padding:14px 18px 40px}
h1{font-size:18px;margin:0 0 4px}h2{font-size:13px;margin:20px 0 6px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}h3{font-size:13px;margin:14px 0 4px}
p.lead{color:var(--muted);margin:0 0 12px}
.card{border:1px solid var(--card-border);border-radius:5px;padding:10px 12px;margin:10px 0;background:var(--bg)}
.card.soft{background:var(--soft)}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:4px 7px;text-align:left;vertical-align:top}
th{background:var(--panel);font-weight:700;font-size:10px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)}
input[type=text],input[type=url],textarea,select{width:100%;padding:4px 7px;border:1px solid var(--field-border);border-radius:4px;font:inherit;background:var(--field-bg);color:var(--fg)}
textarea{min-height:80px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
label{display:block;font-weight:600;margin:8px 0 3px;font-size:12px}label small{font-weight:400;color:var(--muted)}
button,.btn{background:var(--accent);color:var(--on-accent);border:1px solid var(--accent);border-radius:4px;padding:3px 11px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
button.alt,.btn.alt{background:var(--field-bg);color:var(--fg);border:1px solid var(--field-border)}button.bad{background:var(--bad);border-color:var(--bad)}
.ok{color:var(--ok)}.no{color:var(--no)}.muted{color:var(--muted)}.warn{color:var(--warn)}
.flash{background:var(--ok-bg);border:1px solid var(--ok-bd);padding:6px 10px;border-radius:4px;margin-bottom:10px}
.err{background:var(--no-bg);border:1px solid var(--no-bd);padding:6px 10px;border-radius:4px;margin-bottom:10px;white-space:pre-wrap}
pre{background:var(--soft);border:1px solid var(--border2);padding:8px;border-radius:4px;overflow:auto;font-size:12px;white-space:pre-wrap}
code{background:var(--code-bg);padding:0 4px;border-radius:3px;font-size:11.5px;font-family:Consolas,monospace}
.tag{color:var(--tag);font-size:11.5px;font-family:Consolas,monospace}
.pill{display:inline-block;border:1px solid var(--field-border);border-radius:9px;padding:0 7px;font-size:11px;font-weight:600;color:var(--muted);background:var(--field-bg)}
.pill.ok{border-color:var(--pill-ok-bd);background:var(--pill-ok-bg);color:var(--pill-ok-fg)}.pill.no{border-color:var(--pill-no-bd);background:var(--pill-no-bg);color:var(--pill-no-fg)}.pill.warn{border-color:var(--pill-warn-bd);background:var(--pill-warn-bg);color:var(--pill-warn-fg)}
.pill.blue{border-color:var(--pill-blue-bd);background:var(--pill-blue-bg);color:var(--pill-blue-fg)}
.row{display:flex;gap:10px;flex-wrap:wrap}.row>*{flex:1;min-width:220px}.inline{display:inline}
.rate{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.rate .reason{display:none;flex-basis:100%}
.dn-toggle{position:absolute;opacity:0;pointer-events:none}.dn-toggle:checked~.reason{display:block}
.thumb{background:var(--field-bg);color:var(--fg);border:1px solid var(--field-border);border-radius:4px;width:34px;height:28px;padding:0;margin:0;font-size:16px;line-height:26px;text-align:center;cursor:pointer;display:inline-block}
.thumb:hover,.dn-toggle:checked+form+.thumb,.dn-toggle:focus-visible+form+.thumb{background:var(--sel-bg);border-color:var(--accent)}
.stat{font-size:20px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.grid .card{margin:0}
.bar{height:6px;background:var(--bar);border-radius:3px;overflow:hidden;width:110px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:var(--bar-fill)}.bar i.w{background:#f59e0b}.bar i.b{background:#ef4444}
.bub{border-radius:8px;padding:7px 10px;margin:6px 0;max-width:88%}
.me{background:var(--accent);color:var(--on-accent);margin-left:auto}.bot{background:var(--bot-bg)}
.tscroll{overflow-x:auto;max-width:100%}
/* inline colours that other screens write into style="..." follow the theme */
[style*="background:#fff"]{background:var(--bg)!important}
[style*="background:#e6ffec"]{background:var(--diff-add)!important}
[style*="background:#ffebe9"]{background:var(--diff-del)!important}
[style*="background:#f0f1f3"]{background:var(--diff-hunk)!important}
[style*="solid #e5e7eb"]{border-color:var(--border2)!important}
/* narrow screens and touch: the icon rail becomes a strip across the top, panes stack, tables scroll, buttons get bigger */
@media(max-width:800px){
html,body{height:auto;min-height:100%}
.tb{height:auto;flex-wrap:wrap;padding:6px 10px;gap:6px}
.tb .sp{display:none}
.tb input[type=text]{width:100%!important;min-height:38px}
.tb form{flex-wrap:wrap}
.mid{flex:1 0 auto;flex-direction:column;min-height:0}
.rail{width:auto;flex-direction:row;padding-top:0;overflow-x:auto;-webkit-overflow-scrolling:touch}
.rail .top{display:flex;flex:none;overflow:visible}
.rail .bot{display:flex;flex:none;border-top:0;border-left:1px solid var(--rail-line)}
.rail a{min-width:64px;min-height:48px;padding:7px 4px 4px;border-left:0;border-bottom:2px solid transparent;font-size:10px}
.rail a.on{border-bottom-color:#3b82f6}
.rail .n{right:12px}
.lp{width:auto;border-right:0;border-bottom:1px solid var(--border);max-height:40vh;flex:none}
.rp{width:auto;border-left:0;border-top:1px solid var(--border);overflow-y:visible;flex:none}
.mn{flex:none;overflow-y:visible}
main{padding:12px 12px 32px}
.it{padding:11px 12px}
button,.btn,input[type=text],input[type=url],select{min-height:40px}
button,.btn{padding:6px 14px}
.thumb{min-width:44px;min-height:40px}
main table,.rp table{display:block;overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch}
.row>*{min-width:0;flex-basis:100%}
.sb{height:auto;flex-wrap:wrap;gap:4px 12px;padding:4px 10px}
.bub{max-width:100%}
}
"""


def form(ctx, action, body, method="post", cls=""):
    token = "" if method == "get" else '<input type="hidden" name="_t" value="%s">' % esc(ctx.token)
    return '<form method="%s" action="%s" class="%s">%s%s</form>' % (method, esc(action), cls, body, token)


def field(name, label, value="", kind="text", hint="", rows=None, required=False):
    h = " <small>%s</small>" % esc(hint) if hint else ""
    if kind == "textarea":
        return '<label for="%s">%s%s</label><textarea id="%s" name="%s"%s>%s</textarea>' % (
            name, esc(label), h, name, name, ' rows="%d"' % rows if rows else "", esc(value))
    return '<label for="%s">%s%s</label><input type="%s" id="%s" name="%s" value="%s"%s>' % (
        name, esc(label), h, kind, name, name, esc(value), " required" if required else "")


def audience_options(ctx):
    """<option> list for an audience picker: the person's usual audience first (from the profile), then each audience."""
    import audience as aud
    try:
        cur = aud.resolve(ctx.kb, clean(ctx.user))
    except aud.AudienceError:
        cur = None
    opts = ['<option value="" selected>my usual (%s)</option>' % esc(cur["title"] if cur else "the KB's own order")]
    opts += ['<option value="%s">%s: %s</option>' % (k, esc(v["title"]), esc(v["blurb"])) for k, v in aud.AUDIENCES.items()]
    return "".join(opts)


def pill(ok, yes="ok", no="not yet", warn=False):
    if ok:
        return '<span class="pill ok">%s</span>' % esc(yes)
    return '<span class="pill %s">%s</span>' % ("warn" if warn else "no", esc(no))


def counts(kb):
    """Small numbers for the navigation badges. Never raises: a badge must not break a page."""
    out = {}
    try:
        import questions
        reg = questions.load(questions.reg_path(kb)).get("questions") or []
        out["/questions"] = sum(1 for q in reg if q.get("status") == "open")
    except Exception:
        pass
    try:
        import feedback
        import kb_gate
        n = sum(1 for f in feedback.load(kb).get("feedback") or [] if f.get("status") == "open" and f.get("rating") == "down")
        out["/approve"] = n + len(kb_gate.batches(kb))
    except Exception:
        pass
    return out


# ---- the app frame: top bar, icon rail, optional list and side panes, status bar ----------------------
RAIL_ICON = {"/": ("&#8962;", "Home"), "/setup": ("&#9998;", "Setup"), "/build": ("&#9654;", "Build"),
             "/files": ("&#9776;", "KB files"), "/ask": ("&#9993;", "Ask"), "/questions": ("?", "Questions"),
             "/approve": ("&#10003;", "Approve"), "/coverage": ("&#9684;", "Coverage"), "/golden": ("&#9830;", "Golden"),
             "/pack": ("&#9635;", "Pack"), "/glossary": ("Aa", "Glossary"), "/review": ("&#9873;", "Review"),
             "/usage": ("&#9636;", "Usage"), "/compare": ("&#8644;", "Compare"), "/audit": ("&#9776;", "Audit"),
             "/teams": ("&#9823;", "Teams"), "/settings": ("&#9881;", "Settings")}
RAIL_ICON.update({"/owners": ("&#9733;", "Owners"), "/search": ("&#8981;", "Search"), "/chat": ("&#9993;", "Chat"),
                  "/quality": ("&#9878;", "Quality"), "/notify": ("&#9830;", "Notify"), "/federation": ("&#9741;", "Federation"),
                  "/suggest": ("&#9998;", "Suggest"), "/map": ("&#9673;", "Map"), "/visualizations": ("&#9883;", "Visuals")})
RAIL_BOTTOM = ("/audit", "/teams", "/settings")
# The top bar search form. server.py sets this to ("/search", "q") when a /search screen is registered; until then it is the
# KB files filter it always was.
SEARCH_FORM = ("/files", "find", "Search KB files")


# ---- environments: the list from db-environments.yaml, and the one the person chose (cookie `metis_env`) ---------------
def environments(kb):
    """([environment names], reference environment text). The text is what the header always showed (it may be empty)."""
    data = load_yaml(os.path.join(kb, ".metis", "db-environments.yaml"))
    ref = clean(data.get("reference_environment"))
    names = []
    try:
        import db_catalog
        envs, cat_ref = db_catalog.environments(kb)
        names = list(envs)
        ref = ref or clean(cat_ref)
    except Exception:
        names = [str(n) for n in (data.get("environments") or {}) if not str(n).startswith("<")]
    return names, ref


def current_env(ctx):
    """The environment this person looks at: their choice if it is on the list, else the reference environment ('' when none)."""
    names, ref = environments(ctx.kb)
    return ctx.env if ctx.env in names else ref


def rail(ctx, active, badges):
    names = dict(NAV + NAV_MORE)
    try:
        import features
        off = features.hidden_screens(ctx.kb)  # screens of experimental features this KB has not turned on stay reachable by link
    except Exception:
        off = set()
    order = [h for h, _ in NAV] + [h for h, _ in sorted(NAV_MORE, key=lambda x: x[1]) if h not in RAIL_BOTTOM and (h not in off or h == active)]
    bottom = [h for h in RAIL_BOTTOM if h in names]
    def one(href):
        ico, lab = RAIL_ICON.get(href, ("&#9679;", names.get(href, href)[:8]))
        n = '<span class="n">%d</span>' % badges[href] if badges.get(href) else ""
        return '<a href="%s" title="%s"%s><i>%s</i>%s%s</a>' % (
            href, esc(names.get(href, lab)), ' class="on"' if href == active else "", ico, esc(lab), n)
    top = "".join(one(h) for h in order)  # a long list scrolls inside the rail (thin visible scrollbar); on a phone it is a strip
    return '<nav class="rail"><div class="top">%s</div><div class="bot">%s</div></nav>' % (top, "".join(one(h) for h in bottom))


def role_text(ctx):
    if not clean(ctx.user):
        return "Role: not set (enter your name, top right)"
    try:
        import kb_gate
        got = kb_gate.certifiers(ctx.kb).get(clean(ctx.user).lower())
    except Exception:
        got = None
    sso = " [SSO roles: %s]" % ", ".join(ctx.roles) if ctx.roles else ""
    return "Role: %s%s" % ("lead (%s)" % got[1] if got else "member", sso)


def devin_text(kb):
    try:
        import tasks
        s = tasks.summary(kb)
    except Exception:
        return "Devin session: unknown"
    run, wait = s.get("running", 0), s.get("queued", 0)
    if run:
        return "Devin session: %d task(s) running" % run
    return "Devin session: none running" + (", %d task(s) waiting" % wait if wait else "")


def pane_item(href, title, sub="", on=False, dot=""):
    d = '<span class="dot %s"></span>' % dot if dot else ""
    return '<a class="it%s" href="%s">%s%s%s</a>' % (
        " on" if on else "", esc(href), d, title, '<span class="s">%s</span>' % sub if sub else "")


def left_pane(title, items, count="", top=""):
    c = "<span>%s</span>" % esc(count) if count != "" else ""
    return '<aside class="lp"><div class="hd"><span>%s</span>%s</div>%s%s</aside>' % (esc(title), c, top, items)


def right_pane(html_):
    return '<aside class="rp">%s</aside>' % html_


def theme_link(ctx):
    """A plain link that moves the theme on one step: auto -> dark -> light -> auto. /theme sets the cookie; no JavaScript."""
    cur = ctx.theme if ctx.theme in THEMES else "auto"
    nxt = {"auto": "dark", "dark": "light", "light": "auto"}[cur]
    return '<a class="thm" href="/theme?set=%s" title="Colour theme: %s. Click for %s.">Theme: %s</a>' % (nxt, cur, nxt, cur)


def env_box(ctx):
    """The header's environment: a switcher when the KB has more than one environment, else the text it always showed."""
    names, ref = environments(ctx.kb)
    cur = current_env(ctx)
    if len(names) < 2:
        return '<span class="env">%s</span>' % esc(cur or "no environment")
    opts = "".join('<option value="%s"%s>%s</option>' % (esc(n), " selected" if n == cur else "", esc(n + (" (reference)" if n == ref else "")))
                   for n in names)
    return form(ctx, "/env", '<select name="name" aria-label="Environment" class="env">%s</select><button class="alt">Use</button>' % opts)


def page(ctx, title, active, body, flash=None, error=None, left="", right=""):
    prof = profile(ctx.kb)
    product = get(prof, "product.name") or "No project yet"
    env = current_env(ctx) or "no environment"
    built = os.path.join(ctx.kb, "CROSS-LAYER", "COVERAGE.yaml")
    asof = ("Built %s" % datetime.datetime.fromtimestamp(os.path.getmtime(built)).strftime("%d %b %Y, %H:%M")
            if os.path.isfile(built) else "Not built yet")
    initials = "".join(w[0] for w in clean(ctx.user).split()[:2]).upper() or "?"
    s_path, s_name, s_hint = SEARCH_FORM
    find = form(ctx, s_path, '<input type="text" name="%s" placeholder="%s" style="width:160px">' % (esc(s_name), esc(s_hint)), method="get")
    if ctx.sso:  # signed in through the identity provider: the name is the verified one and cannot be typed over
        who = ('<span class="muted">Signed in as</span> <b>%s</b> <a href="/logout">Sign out</a>' % esc(ctx.user))
    else:
        who = form(ctx, "/whoami", '<span class="muted">You are</span><input type="text" name="name" value="%s" '
                   'placeholder="your name" style="width:130px"><button class="alt">Set</button>' % esc(ctx.user))
    note = ""
    if flash:
        note += '<div class="flash">%s</div>' % esc(flash)
    if error:
        note += '<div class="err">%s</div>' % esc(error)
    brand_icon = ('<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMjAgMTIwIj48ZGVmcz48bGluZWFyR3JhZGllbnQgaWQ9ImciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiM1YjIxYjYiLz48c3RvcCBvZmZzZXQ9IjEiIHN0b3AtY29sb3I9IiM3YzNhZWQiLz48L2xpbmVhckdyYWRpZW50PjwvZGVmcz48cmVjdCB4PSI0IiB5PSI0IiB3aWR0aD0iMTEyIiBoZWlnaHQ9IjExMiIgcng9IjI2IiBmaWxsPSJ1cmwoI2cpIi8+PGNpcmNsZSBjeD0iNDgiIGN5PSI0OCIgcj0iMTAiIGZpbGw9IiNmZmYiLz48Y2lyY2xlIGN4PSI3MiIgY3k9IjQ4IiByPSIxMCIgZmlsbD0iI2ZmZiIvPjxjaXJjbGUgY3g9IjQ4IiBjeT0iNDgiIHI9IjQuNSIgZmlsbD0iIzViMjFiNiIvPjxjaXJjbGUgY3g9IjcyIiBjeT0iNDgiIHI9IjQuNSIgZmlsbD0iIzViMjFiNiIvPjxwYXRoIGQ9Ik00OCA2OCBRNjAgODAgNzIgNjgiIHN0cm9rZT0iI2M0YjVmZCIgc3Ryb2tlLXdpZHRoPSI2IiBmaWxsPSJub25lIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48L3N2Zz4=" width="18" height="18" alt="Mētis" style="display:inline-block;vertical-align:middle">')
    brand = '<a href="/" class="brand" title="Mētis Knowledge Base">%s <span>M&#275;tis</span></a>' % brand_icon
    top = ('<div class="tb">%s<span class="apm">%s</span>%s<span class="asof">%s</span><span class="sp"></span>'
           '%s%s%s<span class="av" title="%s">%s</span></div>') % (brand, esc(product), env_box(ctx), esc(asof), find, theme_link(ctx), who,
                                                                    esc(ctx.user), esc(initials))
    status = ('<div class="sb"><span>%s</span><span>%s</span><span>%s</span><span class="sp"></span><span>%s</span></div>'
              % (esc(product), esc(env), esc(role_text(ctx)), esc(devin_text(ctx.kb))))
    return ('<!DOCTYPE html><html lang="en"%s><head><meta charset="utf-8"><title>%s - M&#275;tis</title>'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><style>%s</style></head><body>%s'
            '<div class="mid">%s%s<div class="mn"><main>%s%s</main></div>%s</div>%s</body></html>') % (
        ' data-theme="%s"' % ctx.theme if ctx.theme in ("dark", "light") else "",
        esc(title), CSS, top, rail(ctx, active, counts(ctx.kb)), left, note, body, right, status)
