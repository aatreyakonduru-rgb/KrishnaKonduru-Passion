import os as _o
import sys as _s;_s.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo
import os,re,base64,html,json,glob,yaml,collections,datetime,sys
K=KBROOT; R=sys.argv[1]; OUT=sys.argv[2]; DASH=sys.argv[3]
V=f"{K}/VISUALIZATION"
# Team colours: viz.primary_color and viz.palette in the profile (site_paths.py). No palette = stock colours.
CSS="""<meta charset=utf-8><style>body>header,body>.hero,body>.banner{display:none!important}html{overflow:auto}header{background:#fff!important;color:#231E33!important;border-bottom:3px solid #5009B5;box-shadow:0px 2px 1px -1px rgba(0,0,0,0.2)}header h1,header b{color:#5009B5!important}header span,header div{color:#5B6770!important;opacity:1!important}
body,button,input,select,table{font-family:"Open Sans","Roboto","Helvetica","Arial",sans-serif!important;font-size:13px}
body{background:#F5F5F5!important;color:#231E33}h1,h2,h3{color:#231E33;font-weight:600}a{color:#2861BB}
th{background:#EBE4FF!important;color:#231E33!important}.card,.panel{box-shadow:0px 2px 1px -1px rgba(0,0,0,0.2),0px 1px 1px 0px rgba(0,0,0,0.14),0px 1px 3px 0px rgba(0,0,0,0.12)}</style>"""
EVJS="""<style>.ev{cursor:pointer}#evp{position:fixed;z-index:99;max-width:560px;background:#fff;border:1px solid #5009B5;border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.18);padding:10px 12px;font-size:12px;display:none;word-break:break-word}#evp a{color:#5009B5;font-weight:600}#evp .x{float:right;cursor:pointer;color:#5B6770;margin-left:8px}</style>
<script>function evp(el,e){e.stopPropagation();var p=document.getElementById('evp');if(!p){p=document.createElement('div');p.id='evp';document.body.appendChild(p);document.addEventListener('click',function(){p.style.display='none'})}
var h=el.getAttribute('data-href'),ev=el.getAttribute('data-ev');p.innerHTML='<span class=x>&#10005;</span><b>Source</b><br><code>'+ev.replace(/</g,'&lt;')+'</code>'+(h?'<br><br><a href="'+h+'" target="_blank" rel="noopener">Open source &#8599;</a>':(ev.indexOf('query:')==0?'<br><br>Saved query result in the KB _EVIDENCE folder.':''));
p.onclick=function(x){x.stopPropagation();if(x.target.className=='x')p.style.display='none'};p.style.display='block';var r=el.getBoundingClientRect();p.style.left=Math.min(r.left,innerWidth-580)+'px';p.style.top=(r.bottom+6+p.offsetHeight>innerHeight?r.top-p.offsetHeight-6:r.bottom+6)+'px'}</script>"""
def theme(t):
    t=S.recolor(t).replace('#5009B5',S.primary)
    X=(CSS+EVJS).replace("#5009B5",S.primary)
    return t.replace("</head>",X+"</head>",1) if "</head>" in t else X+t
PROJ=S.projects()  # repo folder -> project, from viz.source_link.remote_regex; empty = no "Open in ..." links
def evtag(m):
    ev=m.group(1);mm=re.match(r"([^/\s]+)/([^:\s]+?)(?::(\d+))?(?:\s|$)",html.unescape(ev))
    href=""
    if mm: href=S.link(mm.group(1),mm.group(2),mm.group(3),PROJ)
    return "<span class=ev data-ev='%s' data-href='%s' onclick='evp(this,event)' title='Click for the source'>src</span>"%(ev.replace("'","&#39;"),href)
def md2html(p):
    out=[];tbl=False
    for l in open(p).read().splitlines():
        e=html.escape(l);e=re.sub(r"`([^`]+)`",r"<code>\1</code>",e);e=re.sub(r"\[E: ([^\]]+)\]",evtag,e)
        if l.startswith("|"):
            if re.match(r"^\|[-| :]+\|$",l): continue
            cells=e.strip("|").split("|");tag="th" if not tbl else "td"
            if not tbl: out.append("<table>");tbl=True
            out.append("<tr>"+"".join(f"<{tag}>{c.strip()}</{tag}>" for c in cells)+"</tr>");continue
        if tbl: out.append("</table>");tbl=False
        m=re.match(r"^(#+)\s+(.*)",e)
        out.append(f"<h{len(m.group(1))+1}>{m.group(2)}</h{len(m.group(1))+1}>" if m else (f"<p>{e}</p>" if e.strip() else ""))
    if tbl: out.append("</table>")
    return "\n".join(out)
mods=sorted(glob.glob(f"{K}/modules/*/00_MODULE_OVERVIEW.md"))+[f"{K}/db/00_DB_OVERVIEW.md"]
nav="".join(f"<a href='#' onclick=\"show('{i}');return false\">{os.path.basename(os.path.dirname(p))}</a>" for i,p in enumerate(mods))
body="".join(f"<section id='m{i}' style='display:{'block' if i==0 else 'none'}'>{md2html(p)}</section>" for i,p in enumerate(mods))
docs=f"""<html><head><style>body{{margin:0;display:flex}}nav{{width:220px;background:#fff;border-right:1px solid #D9D9D9;height:100vh;overflow:auto;position:fixed}}
nav a{{display:block;padding:8px 16px;color:#231E33;text-decoration:none;border-left:4px solid transparent}}nav a:hover{{background:#EBE4FF;border-left-color:#5009B5}}
main{{margin-left:240px;padding:16px;flex:1}}table{{border-collapse:collapse;background:#fff;width:100%}}td,th{{border:1px solid #D9D9D9;padding:4px 8px;text-align:left;vertical-align:top}}
.ev{{background:#E1EDFF;color:#2861BB;border-radius:8px;padding:0 6px;font-size:11px;cursor:help}}code{{color:#5009B5}}</style></head>
<body><nav>{nav}</nav><main>{body}</main><script>function show(i){{document.querySelectorAll('section').forEach(function(s){{s.style.display='none'}});document.getElementById('m'+i).style.display='block'}}</script></body></html>"""
# KB matrix: API module x table, from the sourced links only
links=[]
for f in glob.glob(f"{K}/modules/*/*.links.yaml"): links+=yaml.safe_load(open(f)).get("links") or []
mt=collections.defaultdict(lambda:collections.defaultdict(set))
for l in links:
    if l["to"]["type"]=="table": mt[l["to"]["name"]][l["from"]["name"].split(":")[0]].add("W" if l["rel"]=="writes" else "R")
ui2api=collections.defaultdict(lambda:collections.defaultdict(int))
for l in links:
    if l["rel"]=="calls" and " " in l["to"]["name"]: ui2api[l["from"]["name"].split(":")[0]][l["to"]["name"].split(" ")[1].split("/")[0]]+=1
apis=sorted({m for t in mt.values() for m in t}); uis=sorted(ui2api); apis2=sorted({a for u in ui2api.values() for a in u})
rows="".join(f"<tr><td><code>{t}</code></td>"+"".join(f"<td class='c {''.join(sorted(mt[t][a]))}'>{'/'.join(sorted(mt[t][a]))}</td>" for a in apis)+"</tr>" for t in sorted(mt,key=lambda t:-len(mt[t])))
urows="".join(f"<tr><td>{u}</td>"+"".join(f"<td class='c {'R' if ui2api[u][a] else ''}'>{ui2api[u][a] or ''}</td>" for a in apis2)+"</tr>" for u in uis)
matrix=f"""<html><head><style>body{{padding:16px}}table{{border-collapse:collapse;background:#fff}}td,th{{border:1px solid #D9D9D9;padding:3px 8px;font-size:12px}}
th{{position:sticky;top:0}}.c{{text-align:center}}.R{{background:#D9F5F5}}.W{{background:#F7D5CF}}.RW{{background:#EEAA9F}}input{{padding:6px;width:300px;border:1px solid #D9D9D9;margin:8px 0}}</style></head><body>
<h2>UI → API matrix</h2><p>Count of UI files whose code calls an endpoint of the API (from <code>modules/*/*.links.yaml</code>, each link source-checked).</p>
<table><tr><th>UI \\ API</th>{''.join(f'<th>{a}</th>' for a in apis2)}</tr>{urows}</table>
<h2>API → table matrix</h2><p>R = read, W = written, from FROM/JOIN/INTO/UPDATE clauses in the API code, matched to the catalogue. {len(mt)} tables.</p>
<input placeholder='filter tables' oninput="var v=this.value.toUpperCase();document.querySelectorAll('#tm tr').forEach(function(r,i){{if(i)r.style.display=r.cells[0].textContent.indexOf(v)>=0?'':'none'}})">
<table id=tm><tr><th>Table</th>{''.join(f'<th>{a}</th>' for a in apis)}</tr>{rows}</table></body></html>"""
pages=[("Team dashboard",open(DASH).read()),("KB matrix",matrix),("Module & DB docs",docs)]
if _o.path.isfile(_o.path.join(WORK,"erd/ERD_JOINS.html")): pages.append(("ERD",open(_o.path.join(WORK,"erd/ERD_JOINS.html")).read()))
for name,f in [("Tech stack","TECH_STACK.html"),("KB health","KB_HEALTH.html"),("KB manifest","KB_MANIFEST.html"),("DB drift","DB_DRIFT.html"),("Visualization index","index.html")]:
    pages.append((name,open(f"{V}/{f}").read()))
GAL=_o.path.join(WORK,"argus/VIZ_GALLERY.html")
if _o.path.isfile(GAL):
    g=open(GAL).read().replace("</head>","<style>.r1{display:none!important}</style></head>",1)
    pages.insert(min(3,len(pages)),("Visualization gallery",g))
pages.append(("Questions (VALIDATE_KB)",open(f"{K}/_QUESTIONS/VALIDATE_KB.html").read()))
logo=base64.b64encode(open(LOGO,"rb").read()).decode() if LOGO else ""
img=f'<img src="data:image/png;base64,{logo}" alt="{html.escape(S.short)}">' if logo else ""
tabs="".join(f"<button class='tab{' on' if i==0 else ''}' onclick='go({i})'>{html.escape(n)}</button>" for i,(n,_) in enumerate(pages))
store="".join("<script type='text/plain' id='p%d'>%s</script>"%(i,base64.b64encode((t if n=='Visualization gallery' else theme(t)).encode()).decode()) for i,(n,t) in enumerate(pages))
HI={
"Team dashboard":["Jira work on the team's boards (sprint, workload, waiting, stale, done) and Devin usage of everyone who ran sessions in the last 30 days.","Use the inner tabs. Stale = in progress with no update for 5+ days.","Who is overloaded, what is blocked, how Devin is used."],
"KB matrix":["Two grids from the code: which UI module calls which API module, and which API module reads or writes which table.","Find a module row; a filled cell means a link with a source file and line in the KB.","Which modules a change to one API or table touches."],
"Module & DB docs":["Every Mētis document for the app modules, ETL modules and databases, rendered from the KB.","Pick a document in the left list.","Read the BRD/FRD/TRD, manuals, security reviews and DB semantic layer."],
"ERD":["Tables joined to the selected table in the code: every JOIN ... ON a.col = b.col found in the SQL scripts, API queries and test queries. Line thickness = how many join conditions.","Pick or search a table on the left, choose 1 or 2 steps, click a table to re-centre, click a line for the join columns and the file:line (opens the code host when viz.source_link is set). Mouse wheel zooms, drag pans, + / - / Reset bottom-left.","Which tables are really joined together and on which keys - what a change to a key column would break."],
"Tech stack":["Languages, frameworks, build tools and databases detected in every repo.","Scan by repo.","Spot outdated or inconsistent versions."],
"KB health":["Source checks on every KB file: tags checked, problems found, open questions.","0 problems = every fact line points to a real source.","How trustworthy the KB is today."],
"KB manifest":["Every KB file with its size, kind and module.","Search or scroll.","What the KB contains and where."],
"DB drift":["Differences between the environments the profile names: tables or columns in one and not the other.","Look for objects missing in SIT before a release.","Release readiness of the schemas."],
"Visualization index":["The list of Mētis visualization pages generated from the KB.","Click a page to open it.","Quick access to every generated view."],
"Questions (VALIDATE_KB)":["Open questions the KB could not answer from code, config or the database, each with its owner.","Answer them in this file; Mētis then rebuilds the lines waiting on each answer.","Where the KB still needs a person."]}
hinfo=json.dumps({n:HI.get(n) for n,_ in pages})
hub=f"""<!doctype html><html><head><meta charset=utf-8><title>{html.escape(S.short)} Mētis</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:"Open Sans","Roboto","Helvetica","Arial",sans-serif;background:#F5F5F5;color:#231E33;font-size:13px}}
.hdr{{height:32px;background:#fff;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 12px;border-bottom:1px solid #D9D9D9}}
.hdr .l{{display:flex;align-items:center;gap:8px}}.hdr img{{height:20px}}.t{{font-size:12px;letter-spacing:2px;color:#5a6275;white-space:nowrap}}
.s{{font-size:14px;font-weight:600;color:#5009B5;letter-spacing:.5px;white-space:nowrap}}.meta{{justify-self:end;color:#5B6770;font-size:11px}}
.tabs{{display:flex;background:#fff;border-bottom:2px solid #5009B5;overflow-x:auto}}.tab{{border:0;background:none;padding:6px 14px;font:inherit;color:#5B6770;cursor:pointer;border-bottom:3px solid transparent;white-space:nowrap}}
.tab:hover{{background:rgba(90,98,117,0.06)}}.tab.on{{color:#5009B5;border-bottom-color:#5009B5;font-weight:600}}
html,body{{height:100%}}body{{display:flex;flex-direction:column;overflow:hidden}}iframe{{border:0;width:100%;flex:1;min-height:0;background:#F5F5F5;display:block}}#hi{{background:#fff;border-bottom:1px solid #D9D9D9;padding:5px 14px;font-size:12px}}#hi:empty{{display:none}}#hi a{{color:#5009B5;margin-left:6px;cursor:pointer;text-decoration:underline}}#hi .g{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:6px 0 2px}}#hi .g div{{background:#F1EBFC;border-radius:6px;padding:6px 8px}}.tabs{{flex-shrink:0}}.hdr{{flex-shrink:0}}
#zbar{{position:fixed;left:12px;bottom:12px;display:flex;gap:4px;z-index:9}}#zbar button{{width:30px;height:30px;border-radius:6px;border:1px solid #D9D9D9;background:#fff;color:#5009B5;font-size:16px;font-weight:700;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.12)}}#zbar button.r{{width:auto;font-size:12px;padding:0 8px}}</style></head><body>
<div class=hdr><div class=l>{img}<span class=t>{html.escape(S.org.upper() or S.name.upper())}</span></div><span class=s>{html.escape(S.title)}</span>
<span class=meta>Built {datetime.date.today():%d %b %Y}</span></div>
<div class=tabs>{tabs}</div><div id=hi></div><iframe id=f></iframe><div id=zbar><button onclick="zm(1.1)" title="Zoom in">+</button><button onclick="zm(1/1.1)" title="Zoom out">&minus;</button><button class=r onclick="zm(0)">Reset</button></div>{store}
<script>var HI={hinfo},HO=false,CUR=0;function hi(){{var n=document.querySelectorAll('.tab')[CUR].textContent,x=HI[n],e=document.getElementById('hi');if(!x){{e.innerHTML='';return}}e.innerHTML='<b style="color:#5009B5">'+n+':</b> '+x[2]+'<a onclick="HO=!HO;hi()">'+(HO?'Hide details &#9652;':'What am I seeing? &#9662;')+'</a>'+(HO?'<div class=g><div><b>What you see</b><br>'+x[0]+'</div><div><b>How to use it</b><br>'+x[1]+'</div><div><b>What it tells you</b><br>'+x[2]+'</div></div>':'')}}var f=document.getElementById('f'),Z=1;function zm(k){{Z=k?Z*k:1;try{{f.contentDocument.body.style.zoom=Z}}catch(e){{}}}}f.onload=function(){{Z=1}};function go(i){{CUR=i;hi();document.querySelectorAll('.tab').forEach(function(b,j){{b.classList.toggle('on',i==j)}});
var u=URL.createObjectURL(new Blob([Uint8Array.from(atob(document.getElementById('p'+i).textContent),function(c){{return c.charCodeAt(0)}})],{{type:'text/html;charset=utf-8'}}));f.src=u;document.getElementById('zbar').style.display=document.querySelectorAll('.tab')[i].textContent=='Visualization gallery'?'none':'flex'}}go(parseInt((location.hash||'#0').slice(1))||0);</script></body></html>"""
hub=hub.replace("#5009B5",S.primary)
open(OUT,"w").write(hub); print(OUT,round(len(hub)/1e6,1),"MB",len(pages),"tabs")
