import html,re,os,glob,datetime
K='/home/ubuntu/metis-work/kb';R='/tmp/metis-dashboard/run1';OUT=R+'/CVBC_Scorecard_Metis_Dashboard.html'
BB='https://bitbucket.elevancehealth.com/projects/AEDLNC/repos/ncr_dna1_crcaprf_files/browse/'
def evtag(m):
    ev=html.unescape(m.group(1));mm=re.match(r'ncr_dna1_crcaprf_files/([^:\s]+?)(?::(\d+))?(?:-\d+)?(?:\s|$)',ev)
    h=(BB+mm.group(1)+'?at=refs%2Fheads%2Fdevelop'+('#'+mm.group(2) if mm.group(2) else '')) if mm else ''
    t=html.escape(ev,quote=True)
    return f"<a class=ev href='{h}' target=_blank title='{t}'>src</a>" if h else f"<span class=ev title='{t}'>src</span>"
def md2html(p):
    out=[];tbl=False
    for l in open(p).read().splitlines():
        e=html.escape(l);e=re.sub(r'`([^`]+)`',r'<code>\1</code>',e);e=re.sub(r'\[E: ([^\]]+)\]',evtag,e);e=re.sub(r'\[\?: (Q-\d+)\]',r"<span class=q>open \1</span>",e)
        if l.startswith('|'):
            if re.match(r'^\|[-| :]+\|$',l): continue
            cells=e.strip('|').split('|');tg='th' if not tbl else 'td'
            if not tbl: out.append('<table>');tbl=True
            out.append('<tr>'+''.join(f'<{tg}>{c.strip()}</{tg}>' for c in cells)+'</tr>');continue
        if tbl: out.append('</table>');tbl=False
        m=re.match(r'^(#+)\s+(.*)',e)
        if m: out.append(f'<h{len(m.group(1))+1}>{m.group(2)}</h{len(m.group(1))+1}>')
        elif l.startswith('- '): out.append(f'<li>{e[2:]}</li>')
        elif e.strip(): out.append(f'<p>{e}</p>')
    if tbl: out.append('</table>')
    return '\n'.join(out)
docs=['context/SYSTEM_OVERVIEW.md','context/DOMAIN_CONTEXT.md','context/DEVIN_WIKI.md','context/DEVIN_RESOURCES.md','context/KB_EFFICIENCY_GAIN.md','context/TEAM.md','context/JIRA_SNAPSHOT.md','etl/README.md','etl/scorecard-sql/README.md','etl/magnolia/README.md','etl/orchestration/README.md','etl/TABLE_IO.md',
      'modules/cvbc-scorecard-copilot/README.md','modules/migration-assist-tool/README.md','modules/vldtn-table-manager/README.md','db/DB_OVERVIEW.md','db/TABLE_USAGE.md','context/CONFLUENCE_TEAM.md','db/DB_TEAM_SCHEMAS.md','context/CONFLUENCE_INDEX.md']
docs+=sorted(glob.glob(K+'/etl/*/jobs/*.md'))+sorted(glob.glob(K+'/etl/orchestration/files/*.md'))+sorted(glob.glob(K+'/modules/*/files/*.md'))
docs=[d if d.startswith('/') else K+'/'+d for d in docs]
grp=lambda p:os.path.relpath(p,K).rsplit('/',1)[0]
nav=[];secs=[];last=None
for i,p in enumerate(docs):
    g=grp(p)
    if g!=last: nav.append(f'<div class=g>{html.escape(g)}</div>');last=g
    nav.append(f"<a href='#' data-i='{i}' onclick=\"sd({i});return false\">{html.escape(os.path.basename(p).replace('.md',''))}</a>")
    secs.append(f"<section id=d{i} style='display:none'><div class=path>{html.escape(os.path.relpath(p,K))}</div>{md2html(p)}</section>")
kbdocs=f"""<!doctype html><html><head><meta charset=utf-8><style>body{{margin:0;font:13px Segoe UI,Arial,sans-serif;color:#231E33;display:flex}}nav{{width:300px;height:100vh;overflow:auto;position:fixed;border-right:1px solid #ddd;background:#fff}}
nav input{{width:90%;margin:8px;padding:5px}}nav a{{display:block;padding:3px 14px;color:#231E33;text-decoration:none;font-size:12px}}nav a:hover{{background:#EBE4FF}}.g{{font-weight:600;padding:8px 10px 2px;color:#5009B5}}
main{{margin-left:310px;padding:14px;flex:1}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:3px 6px;text-align:left;vertical-align:top}}th{{background:#EBE4FF}}
.ev{{background:#E1EDFF;color:#2861BB;border-radius:8px;padding:0 6px;font-size:10px;text-decoration:none}}.q{{background:#FFF3CD;border-radius:8px;padding:0 6px;font-size:10px}}code{{color:#5009B5}}.path{{color:#888;font-size:11px}}</style></head>
<body><nav><input placeholder='Filter documents' oninput="var v=this.value.toLowerCase();document.querySelectorAll('nav a').forEach(a=>a.style.display=a.textContent.toLowerCase().includes(v)?'block':'none')">{''.join(nav)}</nav><main>{''.join(secs)}</main>
<script>function sd(i){{document.querySelectorAll('section').forEach(s=>s.style.display='none');document.getElementById('d'+i).style.display='block';scrollTo(0,0)}}sd(0)</script></body></html>"""
import json,yaml,base64,collections,re as _re
A='/home/ubuntu/metis-work/argus';D=json.load(open(A+'/mag_data.json'));S=json.load(open('/home/ubuntu/metis-work/build/summary.json'));IO=S['io']
OUT=R+'/CVBC_Scorecard_KB_Dashboard.html';E=html.escape;TODAY=datetime.date.today().strftime('%d %b %Y')
CSS="""<style>body{margin:0;padding:14px 18px;font:13px 'Segoe UI',Arial,sans-serif;color:#231E33;background:#F5F5F5}h1{font-size:20px;color:#5009B5;margin:0 0 4px}h2{font-size:15px;color:#5009B5;margin:18px 0 6px}p.s{color:#5B6770;margin:2px 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}.card{background:#fff;border:1px solid #D9D9D9;border-radius:8px;padding:10px 12px}.card b{display:block;font-size:24px;color:#5009B5}.card span{font-weight:600}.card small{display:block;color:#5B6770;font-size:10.5px;margin-top:4px;word-break:break-all}
table{border-collapse:collapse;background:#fff;font-size:12px}td,th{border:1px solid #D9D9D9;padding:3px 7px;text-align:left;vertical-align:top}th{background:#EBE4FF;position:sticky;top:0}td.n{text-align:right}.h0{background:#fff}.box{background:#fff;border:1px solid #D9D9D9;border-radius:8px;padding:10px 12px;margin-bottom:10px}
.lay{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.lay .box h3{margin:0 0 6px;font-size:13px;color:#5009B5}.pill{display:inline-block;background:#EBE4FF;border-radius:10px;padding:1px 8px;margin:2px;font-size:11px}.P1{color:#B00020;font-weight:700}.P2{color:#B86E00;font-weight:700}code{color:#5009B5}</style>"""
def page(title,body): return f"<!doctype html><html><head><meta charset=utf-8><title>{E(title)}</title>{CSS}</head><body>{body}</body></html>"
def cnt(p): return sum(1 for _ in open(p))
reg=yaml.load(open(K+'/db/DB_TABLE_REGISTRY.yaml'),Loader=yaml.CSafeLoader)['tables']
lg=collections.Counter(n.split(':')[0] for n in D['G']['ids'])
Qs=yaml.safe_load(open(K+'/_QUESTIONS/VALIDATE_KB.yaml'))['questions']
mf=yaml.safe_load(open(K+'/KNOWLEDGE-MANIFEST.yaml'))
nodes=sum(D['lgCounts'].get(k,0) for k in D['lgCounts'] if k!='edges')
etl=S['summary']['etl'];app=S['summary']['app']
import glob,subprocess
_vk=sorted(glob.glob('/opt/.devin/plugins/cache/*metis*/*/tools/verify_kb.py'),key=os.path.getmtime)
_vo=subprocess.run(['python3',_vk[-1],K],capture_output=True,text=True).stdout if _vk else ''
_m=re.search(r'([\d,]+) tags.*?(\d+) problems',_vo)
VER=f'{int(_m.group(1).replace(",","")):,} · {_m.group(2)} problems' if _m else 'not run'
cards=[('ETL SQL & Python jobs',sum(len(v) for v in etl.values()),'kb/etl/*/jobs/ (scorecard-sql, magnolia, orchestration)'),
 ('App code files documented',sum(len(v) for v in app.values()),'kb/modules/*/ (copilot, migration-assist-tool, vldtn-table-manager)'),
 ('Tables used by the code',len(IO),'kb/db/TABLE_USAGE.md'),('D01_CRCA tables & views',len(reg),'kb/db/DB_TABLE_REGISTRY.yaml'),
 ('D01_CRCA columns',sum(len(t['columns']) for t in reg),'kb/db/DB_TABLE_REGISTRY.yaml'),('ERD tables / code joins','68 / 888','kb/db/ERD.md'),
 ('D01 vs T01 drift items',481,'kb/db/DB_DRIFT.yaml'),('Link-graph nodes',f"{nodes:,}",'kb/CROSS-LAYER/LINK_GRAPH.yaml'),('Link-graph links',f"{D['lgCounts'].get('edges',0):,}",'kb/CROSS-LAYER/LINK_GRAPH.yaml'),
 ('Impact entries','38,307','kb/CROSS-LAYER/IMPACT_MATRIX.yaml'),('Confluence pages read',len(json.load(open(K+'/_EVIDENCE/confluence/_INDEX.json'))),'kb/_EVIDENCE/confluence/_INDEX.json'),
 ('Team Confluence attachments read',len(json.load(open(K+'/_EVIDENCE/files/conf-att-index.json'))) if os.path.exists(K+'/_EVIDENCE/files/conf-att-index.json') else 0,'kb/context/CONFLUENCE_TEAM.md'),
 ('Jira issues read',len(json.load(open(K+'/_EVIDENCE/jira/_SNAPSHOT.json'))['issue_keys']),'kb/_EVIDENCE/jira/_SNAPSHOT.json'),
 ('Devin playbooks read',len(glob.glob(K+'/_EVIDENCE/files/devin-playbook-*.md')),'kb/context/DEVIN_RESOURCES.md'),
 ('Plugin skills & notes listed',len(json.load(open(K+'/_EVIDENCE/files/devin-skills-inventory.json'))) if os.path.exists(K+'/_EVIDENCE/files/devin-skills-inventory.json') else 0,'kb/context/DEVIN_RESOURCES.md'),
 ('Team roster (from Jira)',len(yaml.safe_load(open(K+'/.metis/TEAM_ROSTER.yaml'))['team']),'kb/.metis/TEAM_ROSTER.yaml'),('Open questions (incl. roster)',len(Qs),'kb/_QUESTIONS/VALIDATE_KB.yaml'),('Source tags checked',VER,'verify_kb.py over kb/')]
ov=page('CVBC Scorecard KB overview',f"<h1>CVBC Scorecard KB overview</h1><p class=s>Counts read from the KB files named on each card. Code: ncr_dna1_crcaprf_files develop @ 5af0e18 · DB: D01_CRCA (dev) vs T01_CRCA (SIT) · built {TODAY}, local and read-only.</p><div class=cards>"+''.join(f"<div class=card><b>{v}</b><span>{E(k)}</span><small>{E(s)}</small></div>" for k,v,s in cards)+"</div>")
# KB matrix: module x schema and job x schema
sch=collections.Counter();mm=collections.defaultdict(collections.Counter);jm=collections.defaultdict(collections.Counter)
for k,v in IO.items():
    p=k.split('.');s=(p[0]+'.'+p[1]) if len(p)==3 else '(schema not resolved)'
    for kind in ('read_by','written_by'):
        for j in v[kind]:
            sch[s]+=1;mm[j[0].split('/')[0]][s]+=1;jm[j[0]][(s,kind)]+=1
cols=[s for s,_ in sch.most_common(14)]
def mat(rows,cell,lab):
    return "<table><tr><th>"+lab+"</th>"+''.join(f"<th>{E(c.replace('D01_CRCA.',''))}</th>" for c in cols)+"</tr>"+''.join(f"<tr><td>{E(r)}</td>"+''.join(f"<td class=n style='background:rgba(80,9,181,{min(.6,cell(r,c)/40):.2f})'>{cell(r,c) or ''}</td>" for c in cols)+"</tr>" for r in rows)+"</table>"
jobs=sorted(jm,key=lambda j:-sum(jm[j].values()))[:60]
kbm=page('KB matrix',"<h1>KB matrix</h1><p class=s>From kb/db/TABLE_USAGE.md (each statement's tables, with file and line). Columns are the most-used schemas; the D01_CRCA prefix is dropped.</p><h2>Module → schema</h2><p class=s>Count of read + write references from each module's code to each schema.</p>"+mat(sorted(mm),lambda r,c:mm[r][c],'Module')+
 "<h2>Job → schema (top 60 jobs, R = reads, W = writes)</h2>"+"<table><tr><th>Job file</th>"+''.join(f"<th>{E(c.replace('D01_CRCA.',''))}</th>" for c in cols)+"</tr>"+''.join(f"<tr><td>{E(j)}</td>"+''.join("<td>"+(f"R{jm[j][(c,'read_by')]} " if jm[j][(c,'read_by')] else '')+(f"<b>W{jm[j][(c,'written_by')]}</b>" if jm[j][(c,'written_by')] else '')+"</td>" for c in cols)+"</tr>" for j in jobs)+"</table>")
# Ontology page
Z=D['flow']['zones'];zt=collections.defaultdict(set)
for z,s,t in D['flow']['t']: zt[z].add(s)
lay=f"""<div class=lay><div class=box><h3>Business layer</h3>{''.join(f"<div class=pill>{E(o['label'])}</div>" for o in D['objects'])}<p class=s>Areas of the CVBC Scorecard work, taken from the code modules (kb/CROSS-LAYER/ONTOLOGY.yaml). Business object names from the KT notes are in context/DOMAIN_CONTEXT.md.</p></div>
<div class=box><h3>Application layer</h3>{''.join(f"<div class=pill>{E(m)} ({len(v)})</div>" for m,v in app.items())}<p class=s>{len(D['endpoints'])} Copilot API endpoints (kb/modules/cvbc-scorecard-copilot).</p></div>
<div class=box><h3>ETL layer</h3>{''.join(f"<div class=pill>{E(m)} ({len(v)})</div>" for m,v in etl.items())}<p class=s>{len(D['jobs'])} jobs with table reads/writes (kb/etl/).</p></div>
<div class=box><h3>Data layer</h3>{''.join(f"<div class=pill>{E(z)}</div>" for z in Z)}<p class=s>{len(reg)} D01_CRCA objects (kb/db/DB_TABLE_REGISTRY.yaml).</p></div></div>"""
sysr=''.join(f"<tr><td>{E(s['dir'])}</td><td>{E(s['sys'])}</td><td>{len(s['tables'])}</td><td>{E(', '.join(s['tables']))}</td></tr>" for s in D['systems'])
chr_=''.join(f"<tr><td>{E(c['id'])}</td><td>{E(c['name'])}</td><td>{E(c['risk'])}</td><td>{E('; '.join(x['item'] for x in c['w']))}</td><td>{E('; '.join(x['item'] for x in c['r']))}</td></tr>" for c in D['chains'])
prr=''.join(f"<div class=box><b>{E(p['name'])}</b><p class=s>{E(p['desc'])}</p>"+' → '.join(f"<span class=pill>{E(s['stage'])}</span>" for s in p['stages'])+"</div>" for p in D['processes'])
stt=''.join(f"<tr><td><code>{E(s['name'])}</code></td><td>{E(', '.join(v[0] for v in s['values']))}</td></tr>" for s in D['states'])
ont=page('CVBC Scorecard ontology',f"<h1>CVBC Scorecard ontology</h1><p class=s>Business, application, ETL and data layers of D01_CRCA, built from the CVBC Scorecard KB on {TODAY}. The interactive pictures are in the Visualization gallery tab.</p>{lay}<h2>Systems in and out</h2><p class=s>Outside schemas the ETL reads, and the Magnolia reporting tables it writes (kb/db/TABLE_USAGE.md).</p><table><tr><th>Dir</th><th>System / schema</th><th>Tables</th><th>Tables (first 12)</th></tr>{sysr}</table><h2>Impact paths (most-used tables)</h2><p class=s>Writers and readers of each table from kb/CROSS-LAYER/IMPACT_MATRIX.yaml; risk is by number of jobs touching the table.</p><table><tr><th>Id</th><th>Table</th><th>Risk</th><th>Written by</th><th>Read by</th></tr>{chr_}</table><h2>Processes (statement order inside the biggest jobs)</h2>{prr}<h2>Value lists from the dev param file</h2><p class=s>scripts/sql/param/cvbc_prf_params_dev.json</p><table><tr><th>Param</th><th>Values</th></tr>{stt}</table>")
oq=page('Open questions',"<h1>Open questions</h1><p class=s>From kb/_QUESTIONS/VALIDATE_KB.yaml. Nothing that depends on an open question is final.</p><table><tr><th>Priority</th><th>Id</th><th>Type</th><th>Question</th><th>Why it is open (evidence)</th><th>Who answers</th><th>Blocks</th><th>Status</th></tr>"+''.join(f"<tr><td class={q['priority']}>{q['priority']}</td><td>{q['id']}</td><td>{E(q['type'])}</td><td>{E(q['question'])}</td><td>{'<br>'.join(E(c) for c in q.get('context') or [])}</td><td>{E(q.get('answer_role') or '')}</td><td>{E(', '.join(q.get('blocks') or []))}</td><td>{q['status']}</td></tr>" for q in sorted(Qs,key=lambda q:q['priority']))+"</table>")
V=lambda f:open(f'{K}/VISUALIZATION/{f}.html').read()
P=[('Overview',ov,'KB counts at a glance, each with the file it is counted from.'),
 ('KB matrix',kbm,'Which modules and jobs read or write which schemas.'),
 ('Module & DB docs',kbdocs,'The ETL, app, DB and context documents of the CVBC Scorecard KB, picked from a list.'),
 ('Visualization gallery',open(A+'/gallery.html').read(),'Ontology, link graph, lineage and impact pictures. Click to drill in; scroll to zoom; drag to pan.'),
 ('ERD',V('ERD'),'Tables joined in the code, on which columns, with file and line.'),
 ('Ontology',ont,'The CVBC Scorecard ontology: layers, systems in and out, impact paths, processes and value lists.'),
 ('Tech stack',V('TECH_STACK'),'Languages, databases and versions read from the repo files, with file and line.'),
 ('KB health',V('KB_HEALTH'),'Source checks, link graph gaps, open questions by priority and by who answers.'),
 ('KB manifest',V('KB_MANIFEST'),'Every KB file with its kind, area and size.'),
 ('DB drift',V('DB_DRIFT'),'Dev (D01) against SIT (T01): tables and columns that differ.'),
 ('Open questions',oq,'The KB open questions with why they are open and who answers.'),
 ('Efficiency gain from KB',V('KB_EFFICIENCY_GAIN'),'12-month Jira and Devin baseline before the KB start date, with months after it added on each refresh, and sister teams.'),
 ('Team dashboard',open(R+'/dashboard.html').read(),'Jira work for EDA-CVBC-Scorecard (sprint, waiting, stale, done) and Devin usage. Read-only.')]
AS=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','assets')
head=open(AS+'/hub_head.html').read().replace('<title>CVBC KB dashboard</title>','<title>CVBC Scorecard (PRFPHM) KB dashboard</title>')
tail=open(AS+'/hub_tail.js').read()
body=f"<body><div class=\"hdr\"><b>CVBC Scorecard KB dashboard</b><span>APM1081911 · PRFPHM · built from the Mētis KB (ncr_dna1_crcaprf_files, CVBN, Jira CVBC, D01/T01_CRCA)</span><span class=\"m\">generated {TODAY} · local, read-only · every item names its source</span><button class=\"fsh\" type=\"button\" onclick=\"hubFs()\">⛶ Full screen</button></div><nav class=\"tabs\">"+''.join(f'<button class="tab" onclick="go({i})">{E(t)}</button>' for i,(t,_,_) in enumerate(P))+"</nav><div id=\"hi\"></div><iframe id=\"f\" title=\"KB dashboard page\" allow=\"fullscreen *\" allowfullscreen></iframe>"
body+=''.join(f'<script type="text/plain" id="p{i}">{base64.b64encode(c.encode()).decode()}</script>' for i,(_,c,_) in enumerate(P))
body+='<script>var HI='+json.dumps([h for _,_,h in P])+';'+tail
open(OUT,'w').write(head+body);print(OUT,round(len(head+body)/1e6,1),'MB')
