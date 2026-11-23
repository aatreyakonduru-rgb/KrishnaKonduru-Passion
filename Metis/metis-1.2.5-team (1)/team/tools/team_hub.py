#!/usr/bin/env python3
"""Team KB dashboard: one self-contained HTML page from the KB built by team_kb.py and kb_gain.py.

    python3 team_hub.py [~/metis-work]  ->  /tmp/metis-dashboard/run1/<SHORT>_KB_Dashboard.html
"""
import glob, html, json, os, re, sys, datetime, collections
import yaml

W = os.path.abspath(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/metis-work')); KB = W + '/kb'
T = yaml.safe_load(open(KB + '/.metis/team.yaml')); TM = T.get('team', {})
SHORT = TM.get('short_name') or T['apm']; NAME = TM.get('name') or T.get('application')
OUT = f'/tmp/metis-dashboard/run1/{SHORT}_KB_Dashboard.html'; os.makedirs(os.path.dirname(OUT), exist_ok=True)


def inline(s):
    s = html.escape(s)
    s = re.sub(r'\[(E|\?): ([^\]]+)\]', lambda m: f'<span class="tag {"q" if m.group(1) == "?" else "e"}" title="{m.group(2)}">{"?" if m.group(1) == "?" else "E"}</span>', s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', s)
    return re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)


def md(p, limit=None):
    if not os.path.exists(p): return '<p>(not built)</p>'
    out = []; tbl = []; n = 0
    def flush():
        if tbl:
            rows = [r for r in tbl if not re.match(r'^\|[\s|:-]+\|$', r)]
            h = ''.join(f'<th>{inline(c.strip())}</th>' for c in rows[0].strip('|').split('|'))
            b = ''.join('<tr>' + ''.join(f'<td>{inline(c.strip())}</td>' for c in r.strip('|').split('|')) + '</tr>' for r in rows[1:limit])
            more = f'<p class="muted">{len(rows) - 1 - limit} more rows in the KB file</p>' if limit and len(rows) - 1 > limit else ''
            out.append(f'<div class="tw"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>{more}'); tbl.clear()
    for l in open(p).read().split('\n'):
        if l.startswith('|'): tbl.append(l); continue
        flush()
        m = re.match(r'^(#{1,4})\s+(.*)', l)
        if m: out.append(f'<h{len(m.group(1)) + 1}>{inline(m.group(2))}</h{len(m.group(1)) + 1}>')
        elif l.startswith('- '): out.append(f'<li>{inline(l[2:])}</li>')
        elif l.strip(): out.append(f'<p>{inline(l)}</p>')
    flush(); return '\n'.join(out)


def card(k, v): return f'<div class="card"><div class="v">{v}</div><div class="k">{k}</div></div>'


reg = yaml.safe_load(open(KB + '/db/DB_TABLE_REGISTRY.yaml'))['tables']
lin = yaml.safe_load(open(KB + '/lineage/SCRIPT_TABLE_LINEAGE.yaml'))['edges']
Q = yaml.safe_load(open(KB + '/_QUESTIONS/VALIDATE_KB.yaml'))['questions']
G = json.load(open(KB + '/_EVIDENCE/files/kb-gain-jira.json')) if os.path.exists(KB + '/_EVIDENCE/files/kb-gain-jira.json') else {}
ver = json.load(open(W + '/build/verify.json')) if os.path.exists(W + '/build/verify.json') else {}
jm = json.load(open(KB + '/_EVIDENCE/files/jira12m-meta.json'))
docs = sorted(os.path.relpath(p, KB) for p in glob.glob(KB + '/**/*.md', recursive=True) if '/_EVIDENCE/' not in p)
ev = collections.Counter(os.path.relpath(p, KB + '/_EVIDENCE').split('/')[0] for p in glob.glob(KB + '/_EVIDENCE/**/*', recursive=True) if os.path.isfile(p))
probs = ver.get('problems', ver.get('errors', []))
nprob = len(probs) if isinstance(probs, list) else probs
tabs = []
mods = sorted(glob.glob(KB + '/etl/*.md'))
over = '<div class="cards">' + ''.join([card('KB documents', len(docs)), card('Table pages', len(glob.glob(KB + '/db/tables/*.md'))), card('Script→table links', len(lin)),
       card('Tables in registry', len(reg)), card('Team Jira issues (12 m)', jm['team_issues']), card('Confluence evidence files', ev.get('confluence', 0)),
       card('Attachments read', ev.get('confluence_att', 0)), card('Open questions', sum(1 for x in Q if x['status'] == 'open')),
       card('Source check', f"{'0 problems' if not nprob else str(nprob) + ' problems'}")]) + '</div>' + md(KB + '/context/SYSTEM_OVERVIEW.md')
tabs.append(('Overview', over))
tabs.append(('Team & sources', md(KB + '/context/TEAM_PROFILE.md')))
tabs.append(('Modules', ''.join(f'<details><summary>{html.escape(os.path.basename(p)[:-3])}</summary>{md(p, 80)}</details>' for p in mods)))
tabs.append(('Database', ''.join(f'<details open><summary>{html.escape(os.path.basename(p)[:-3])}</summary>{md(p, 200)}</details>' for p in sorted(glob.glob(KB + '/db/CRCA_*.md')))))
top = collections.Counter(e['table'] for e in lin if e['op'] != 'READ').most_common(40)
ld = '<h3>Most-written tables</h3><div class="tw"><table><tr><th>Table</th><th>Writes</th><th>Written by (first 4)</th></tr>' + ''.join(
    f"<tr><td><code>{html.escape(t)}</code></td><td>{n}</td><td>{html.escape(', '.join(sorted({e['script'].split('/')[-1] for e in lin if e['table'] == t and e['op'] != 'READ'})[:4]))}</td></tr>" for t, n in top) + '</table></div>'
W_ = os.path.dirname(KB)
def frame(path, h=1400, note=''):
    if not os.path.exists(path):
        return '<p class="muted">(%s not built)</p>' % html.escape(os.path.basename(path))
    return (f'<p class="muted">{note}</p>' if note else '') + f'<iframe class="viz" style="height:{h}px" srcdoc="{html.escape(open(path).read())}"></iframe>'
tabs.append(('Visualization gallery', frame(W_ + '/argus/gallery.html', 1500, '30 pictures of the ontology, link graph, lineage, impact and KB. Click to drill in; scroll to zoom; drag to pan. Data: kb/CROSS-LAYER/LINK_GRAPH.yaml.')))
tabs.append(('ERD', frame(KB + '/VISUALIZATION/ERD.html', 1400, 'Tables joined in the SQL, on which columns, with file and line (kb/db/CODE_JOINS.links.yaml).')))
tabs.append(('Ontology & link graph', frame(KB + '/VISUALIZATION/ONTOLOGY.html', 1500, 'Jobs, modules and tables with every sourced link; impact paths from kb/CROSS-LAYER/IMPACT_MATRIX.yaml.')))
tabs.append(('Tech stack', frame(KB + '/VISUALIZATION/TECH_STACK.html', 1000, 'Read from the repo files (kb/.metis/DETECTED_STACK.yaml); not approved by the team yet.')))
tabs.append(('KB health', frame(KB + '/VISUALIZATION/KB_HEALTH.html', 900)))
tabs.append(('Lineage', ld + '<p class="muted">Full list: lineage/SCRIPT_TABLE_LINEAGE.yaml in the zip.</p>'))
tabs.append(('DB drift', md(KB + '/db/DB_DRIFT.md')))
tabs.append(('Confluence', md(KB + '/context/CONFLUENCE_TEAM_PAGES.md', 150)))
tabs.append(('Jira work', md(KB + '/context/JIRA_TEAM_WORK.md', 120)))
tabs.append(('Devin wiki & existing KB', md(KB + '/context/DEVIN_WIKI.md') + md(KB + '/context/EXISTING_TEAM_KB.md')))
qh = '<div class="tw"><table><tr><th>Id</th><th>Priority</th><th>Who</th><th>Question</th><th>Status</th></tr>' + ''.join(
    f"<tr><td>{x['id']}</td><td>{x['priority']}</td><td>{html.escape(x.get('answer_role') or '')}</td><td>{html.escape(x['question'])}</td><td>{x['status']}</td></tr>" for x in sorted(Q, key=lambda x: (x['priority'], x['id']))) + '</table></div>'
tabs.append(('Open questions', qh))
gh = KB + '/VISUALIZATION/KB_EFFICIENCY_GAIN.html'
gain = (f'<p>12-month baseline before the KB start date ({G.get("kb_start_date", "")}), then every month after it; sister teams in the same Jira project for comparison. Source: kb-gain-jira.json, kb-gain-devin.json.</p>'
        f'<iframe class="gain" srcdoc="{html.escape(open(gh).read())}"></iframe>' if os.path.exists(gh) else '<p>(baseline not built)</p>') + md(KB + '/context/KB_EFFICIENCY_GAIN.md')
tabs.append(('Efficiency baseline', gain))
man = '<div class="tw"><table><tr><th>KB file</th><th>Bytes</th></tr>' + ''.join(f'<tr><td>{html.escape(d)}</td><td>{os.path.getsize(KB + "/" + d)}</td></tr>' for d in docs if '/tables/' not in d) + '</table></div>' + \
      '<h3>Evidence saved</h3><ul>' + ''.join(f'<li>{k}: {v} files</li>' for k, v in ev.most_common()) + '</ul>'
tabs.append(('KB manifest', man))
CSS = """body{font:14px/1.45 system-ui,Segoe UI,Arial;margin:0;background:#f5f7fa;color:#1d2433}.hdr{background:#0b3d91;color:#fff;padding:14px 22px}.hdr span{opacity:.8;margin-left:12px;font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:4px;padding:8px 16px;background:#fff;border-bottom:1px solid #dde3ec;position:sticky;top:0;z-index:2}nav a{padding:6px 11px;border-radius:6px;cursor:pointer;color:#0b3d91;text-decoration:none}nav a.on{background:#0b3d91;color:#fff}
section{display:none;padding:16px 24px}section.on{display:block}.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}.card{background:#fff;border:1px solid #dde3ec;border-radius:8px;padding:10px 14px;min-width:140px}.card .v{font-size:22px;font-weight:600;color:#0b3d91}.card .k{font-size:12px;color:#5a6577}
.tw{overflow:auto;max-height:640px;background:#fff;border:1px solid #dde3ec;border-radius:6px;margin:6px 0}table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{border-bottom:1px solid #eef1f5;padding:4px 8px;text-align:left;vertical-align:top}th{background:#f0f3f8;position:sticky;top:0}
code{background:#eef1f6;padding:0 3px;border-radius:3px;font-size:12px}.tag{display:inline-block;font-size:10px;border-radius:3px;padding:0 4px;margin-left:3px;cursor:help}.tag.e{background:#dff3e4;color:#1b6b34}.tag.q{background:#fde8c8;color:#8a5200}
details{background:#fff;border:1px solid #dde3ec;border-radius:6px;margin:6px 0;padding:6px 10px}summary{cursor:pointer;font-weight:600}.muted{color:#6b7587;font-size:12px}iframe.gain,iframe.viz{width:100%;height:1500px;border:1px solid #dde3ec;border-radius:6px;background:#fff}"""
nav = ''.join(f'<a data-t="t{i}" class="{"on" if i == 0 else ""}">{html.escape(n)}</a>' for i, (n, _) in enumerate(tabs))
sec = ''.join(f'<section id="t{i}" class="{"on" if i == 0 else ""}">{b}</section>' for i, (_, b) in enumerate(tabs))
JS = "document.querySelectorAll('nav a').forEach(a=>a.onclick=()=>{document.querySelectorAll('nav a,section').forEach(e=>e.classList.remove('on'));a.classList.add('on');document.getElementById(a.dataset.t).classList.add('on');history.replaceState(null,'','#'+a.dataset.t)});if(location.hash){const a=document.querySelector('nav a[data-t=\"'+location.hash.slice(1)+'\"]');if(a)a.click()}"
repos = ', '.join(r['name'] for r in T['repos'])
open(OUT, 'w').write(f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(NAME)} KB dashboard</title><style>{CSS}</style></head><body>'
                     f'<div class="hdr"><b>{html.escape(NAME)} KB dashboard</b><span>{T["apm"]} · {html.escape(repos)} · Jira {T["jira"]["project"]} / {T["jira"]["team_value"]} · Confluence {T["confluence"]["space"]} · built {datetime.date.today()} (local, read only)</span></div>'
                     f'<nav>{nav}</nav>{sec}<script>{JS}</script></body></html>')
print(OUT, os.path.getsize(OUT), 'bytes', len(tabs), 'tabs')
