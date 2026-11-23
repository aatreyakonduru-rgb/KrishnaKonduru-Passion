"""Shared CSS and the compact IDE-style frame used by every mock screen."""

ENVS = ["DEV", "SIT", "UAT1", "UAT2", "PREPROD", "IR", "PROD"]

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#d9dde3;font:12px/1.4 -apple-system,"Segoe UI",system-ui,sans-serif;color:#1f2328}
.nav{position:sticky;top:0;z-index:9;background:#111827;padding:6px 14px;display:flex;gap:4px;flex-wrap:wrap;align-items:center}
.nav b{color:#fff;margin-right:8px;font-size:12px}
.nav a{color:#cbd5e1;text-decoration:none;font-size:11px;padding:2px 8px;border-radius:10px;background:#1f2937}
.nav a:hover{background:#2563eb;color:#fff}
.wrap{max-width:1240px;margin:0 auto;padding:14px}
.note{background:#fff7e0;border:1px solid #f0d58a;border-radius:6px;padding:7px 11px;margin-bottom:16px;font-size:12px}
.sc{margin-bottom:30px}
.sc h2{margin:0;font-size:15px}
.sc p.why{margin:1px 0 6px;color:#57606a;font-size:12px}
.fr{display:flex;flex-direction:column;height:580px;background:#fff;border:1px solid #b8c0cc;border-radius:6px;overflow:hidden}
.tb{height:30px;flex:none;display:flex;align-items:center;gap:8px;padding:0 8px;background:#f3f4f6;border-bottom:1px solid #d5d9e0}
.mid{flex:1;display:flex;min-height:0}
.rail{width:46px;flex:none;background:#1b2130;display:flex;flex-direction:column;align-items:center;padding-top:4px;gap:1px}
.rail div{width:46px;text-align:center;color:#8b95a7;font-size:9px;padding:6px 0 5px;border-left:2px solid transparent}
.rail div i{display:block;font-style:normal;font-size:14px;line-height:15px;color:#aab3c5}
.rail div.on{color:#fff;background:#262e42;border-left-color:#3b82f6}
.rail div.on i{color:#fff}
.rail .gap{flex:1}
.lp{width:236px;flex:none;border-right:1px solid #d5d9e0;display:flex;flex-direction:column;background:#fafbfc;min-height:0}
.lp .hd{padding:6px 8px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#57606a;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between}
.lp .sr{margin:6px 8px;border:1px solid #cfd6df;border-radius:4px;padding:3px 7px;color:#8a929c;background:#fff}
.lp .ls{overflow:hidden;flex:1}
.it{padding:4px 8px;border-bottom:1px solid #eef0f3;display:flex;gap:6px;align-items:flex-start}
.it.on{background:#e7f0ff;border-left:2px solid #2563eb;padding-left:6px}
.it .t{flex:1;min-width:0}
.it .s{color:#6b7280;font-size:11px}
.mn{flex:1;min-width:0;display:flex;flex-direction:column}
.mn .hd{padding:6px 10px;border-bottom:1px solid #e5e7eb;display:flex;gap:8px;align-items:center;background:#fff}
.mn .bd{padding:8px 10px;overflow:hidden;flex:1}
.rp{width:252px;flex:none;border-left:1px solid #d5d9e0;background:#fafbfc;padding:8px;overflow:hidden}
.rp h4,.mn h4{margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#57606a}
.sb{height:20px;flex:none;background:#2563eb;color:#e8f0ff;display:flex;gap:14px;align-items:center;padding:0 10px;font-size:11px}
.sb .sp{flex:1}
.sp{flex:1}
.apm{border:1px solid #cfd6df;border-radius:4px;padding:1px 8px;font-weight:700;background:#fff}
.env{border:1px solid #cfd6df;border-radius:4px;padding:1px 8px;background:#fff;font-weight:600}
.env:after{content:" \\25BE";color:#6b7280}
.asof{color:#57606a}
.av{width:20px;height:20px;border-radius:50%;background:#7c5cd8;color:#fff;font-size:9px;font-weight:700;display:flex;align-items:center;justify-content:center}
.chip{display:inline-block;border-radius:8px;padding:0 6px;font-size:10px;font-weight:600;border:1px solid transparent;white-space:nowrap}
.src{background:#e0edff;color:#1d4ed8}.evi{background:#efe7ff;color:#6d28d9}
.ok{background:#dcfce7;color:#166534}.wn{background:#fef3c7;color:#92400e}.er{background:#fee2e2;color:#991b1b}
.gr{background:#f1f3f5;color:#4b5563}.ol{background:#fff;border-color:#cfd6df;color:#374151}
.btn{display:inline-block;border-radius:4px;padding:2px 9px;font-size:11px;font-weight:600;border:1px solid #cfd6df;background:#fff}
.btn.p{background:#2563eb;color:#fff;border-color:#2563eb}
.btn.g{background:#15803d;color:#fff;border-color:#15803d}
.btn.r{color:#b91c1c;border-color:#fca5a5}
.btn.d{background:#f3f4f6;color:#9ca3af}
.mu{color:#6b7280}
.g1{color:#15803d}.w1{color:#b45309}.b1{color:#b91c1c}
.cite{font-family:Consolas,monospace;font-size:10px;background:#f1f3f5;border-radius:3px;padding:0 4px;color:#374151}
table{border-collapse:collapse;width:100%;font-size:11px}
th{text-align:left;font-size:10px;text-transform:uppercase;color:#57606a;border-bottom:1px solid #d5d9e0;padding:3px 6px;background:#fafbfc}
td{border-bottom:1px solid #eef0f3;padding:3px 6px;vertical-align:top}
tr.on td{background:#e7f0ff}
.kp{display:flex;gap:6px;margin-bottom:8px}
.kp div{flex:1;border:1px solid #e1e5ea;border-radius:5px;padding:5px 8px}
.kp b{display:block;font-size:17px}
.tabs{display:flex;gap:2px;border-bottom:1px solid #e5e7eb;padding:0 8px;background:#fafbfc}
.tabs span{padding:4px 9px;color:#57606a;font-size:11px}
.tabs span.on{color:#2563eb;border-bottom:2px solid #2563eb;font-weight:600;background:#fff}
.bar{height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden;width:90px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:#3b82f6}.bar i.w{background:#f59e0b}.bar i.b{background:#ef4444}
.co{border:1px solid #fcd34d;background:#fffbeb;border-radius:5px;padding:4px 8px;margin:5px 0;font-size:11px}
.cf{display:inline-block;border-radius:4px;padding:0 6px;font-weight:700;font-size:10px}
.cf.h{background:#dcfce7;color:#166534}.cf.m{background:#fef3c7;color:#92400e}.cf.l{background:#fee2e2;color:#991b1b}
.sw{display:inline-block;width:26px;height:14px;border-radius:7px;background:#2563eb;position:relative;vertical-align:middle}
.sw:after{content:"";position:absolute;right:2px;top:2px;width:10px;height:10px;background:#fff;border-radius:50%}
.sw.off{background:#d1d5db}.sw.off:after{right:auto;left:2px}
.inp{border:1px solid #cfd6df;border-radius:4px;padding:2px 7px;background:#fff;color:#6b7280;display:inline-block}
.dl{background:#fee2e2;border-left:3px solid #ef4444;padding:3px 7px;margin:3px 0;border-radius:3px}
.ad{background:#dcfce7;border-left:3px solid #22c55e;padding:3px 7px;margin:3px 0;border-radius:3px}
.bub{border-radius:8px;padding:6px 9px;margin:5px 0;max-width:88%}
.me{background:#2563eb;color:#fff;margin-left:auto}.bot{background:#f3f4f6}
.tree div{padding:2px 0}
.foot{text-align:center;color:#6b7280;font-size:11px;border-top:1px solid #c5ccd6;padding:10px}
"""

RAIL = [("home", "&#8962;", "Home"), ("kb", "&#9776;", "KB files"), ("map", "&#9678;", "KB map"),
        ("impact", "&#8644;", "Impact"), ("ask", "&#9993;", "Ask"), ("appr", "&#10003;", "Approve"),
        ("run", "&#9654;", "Refresh"), ("q", "?", "Questions"), ("prom", "&#8679;", "Promote"),
        ("fb", "&#9733;", "Feedback"), ("log", "&#9776;", "Audit"), ("gap", "", ""),
        ("team", "&#9823;", "Teams"), ("set", "&#9881;", "Settings")]


def rail(active):
    out = []
    for key, ico, lab in RAIL:
        if key == "gap":
            out.append('<div class="gap" style="border:0"></div>')
            continue
        out.append('<div class="%s"><i>%s</i>%s</div>' % ("on" if key == active else "", ico, lab))
    return '<div class="rail">%s</div>' % "".join(out)


def topbar(env="SIT", extra=""):
    return ('<div class="tb"><span class="apm">FIN</span><span class="env">%s</span>'
            '<span class="asof">KB as of 12 Nov 2026, 06:02</span>%s<span class="sp"></span>'
            '<span class="inp" style="min-width:150px">Search (Ctrl+K)</span><span class="av">KK</span></div>'
            % (env, extra))


def statusbar(env="SIT", extra=""):
    return ('<div class="sb"><span>FIN</span><span>%s</span><span>Role: Tech lead</span>'
            '<span class="sp"></span>%s<span>Devin session: none running</span></div>' % (env, extra))


def frame(active, main, left="", right="", env="SIT", extra_top="", extra_status="", tabs=""):
    lp = '<div class="lp">%s</div>' % left if left else ""
    rp = '<div class="rp">%s</div>' % right if right else ""
    return ('<div class="fr">%s<div class="mid">%s%s<div class="mn">%s%s</div>%s</div>%s</div>'
            % (topbar(env, extra_top), rail(active), lp, tabs, main, rp, statusbar(env, extra_status)))


def screen(sid, title, why, body):
    return '<div class="sc" id="%s"><h2>%s</h2><p class="why">%s</p>%s</div>' % (sid, title, why, body)
