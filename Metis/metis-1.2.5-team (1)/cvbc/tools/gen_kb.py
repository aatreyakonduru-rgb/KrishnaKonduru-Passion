#!/usr/bin/env python3
"""Local Mētis generator for APM1081911: sourced ETL/app/DB docs + links from the repo and saved catalogue."""
import ast, json, os, re, sys, collections, yaml, datetime
W='/home/ubuntu/metis-work'; KB=W+'/kb'; ST=sys.argv[1]
REPO='ncr_dna1_crcaprf_files'; ROOT='/home/ubuntu/repos/crcaprf-develop'
TODAY=datetime.date.today().isoformat()
def tag(path,a,b=None,q=None):
    r=f'{REPO}/{path}:{a}'+(f'-{b}' if b and b!=a else '')
    if q and '"' not in q and ']' not in q: r+=f' "{q}"'
    return f'[E: {r}]'
def wr(p,s):
    p=os.path.join(ST,p); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(s)
def wy(p,d): wr(p,yaml.safe_dump(d,sort_keys=False,allow_unicode=True,width=200))
# ---------- params (dev) with line numbers
PF='scripts/sql/param/cvbc_prf_params_dev.json'
PARAM={}; PLINE={}
for i,l in enumerate(open(f'{ROOT}/{PF}'),1):
    m=re.match(r'\s*"([^"]+)"\s*:\s*"([^"]*)"',l)
    if m: PARAM.setdefault(m.group(1).lower(),m.group(2)); PLINE.setdefault(m.group(1).lower(),i)
# ---------- catalogue
REG=yaml.safe_load(open(f'{KB}/db/DB_TABLE_REGISTRY.yaml'))
CAT={t['key'].upper():t for t in REG['tables']}
BYNAME=collections.defaultdict(list)
for k,t in CAT.items(): BYNAME[t['name'].upper()].append(k)
DB0='D01_CRCA'
# ---------- SQL parsing
TOK=r'((?:\$\{?\w+\}?|"?\w+"?)(?:\.(?:\$\{?\w+\}?|"?\w+"?)){0,2})'
TGT=[('INSERT',re.compile(r'\bINSERT\s+(?:OVERWRITE\s+)?INTO\s+'+TOK,re.I)),('MERGE',re.compile(r'\bMERGE\s+INTO\s+'+TOK,re.I)),
     ('UPDATE',re.compile(r'^\s*UPDATE\s+'+TOK,re.I)),('DELETE',re.compile(r'\bDELETE\s+FROM\s+'+TOK,re.I)),
     ('TRUNCATE',re.compile(r'\bTRUNCATE\s+(?:TABLE\s+)?(?:IF\s+EXISTS\s+)?'+TOK,re.I)),
     ('CREATE',re.compile(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:LOCAL\s+|GLOBAL\s+)?TEMP(?:ORARY)?\s+|TRANSIENT\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?'+TOK,re.I))]
SRC=re.compile(r'\b(?:FROM|JOIN|USING)\s+'+TOK+r'(?:\s+(?:AS\s+)?(?!ON\b|WHERE\b|INNER\b|LEFT\b|RIGHT\b|FULL\b|JOIN\b|GROUP\b|ORDER\b|QUALIFY\b|UNION\b|WHEN\b|SET\b|CROSS\b|LIMIT\b|HAVING\b|AND\b|OR\b|USING\b|SELECT\b|WITH\b|LATERAL\b)([A-Za-z_]\w*))?',re.I)
JOINEQ=re.compile(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b')
USE=re.compile(r'\bUSE\s+SCHEMA\s+'+TOK,re.I)
KW={'SELECT','DUAL','TABLE','LATERAL','VALUES','IDENTIFIER','INFORMATION_SCHEMA'}
def strip_comments(t):
    out=[];i=0;n=len(t);q=None
    while i<n:
        c=t[i]
        if q:
            out.append(c)
            if c==q: q=None
            i+=1;continue
        if c=="'": q=c; out.append(c); i+=1; continue
        if t.startswith('--',i) or t.startswith('//',i):
            j=t.find('\n',i); j=n if j<0 else j; out.append(' '*(j-i)); i=j; continue
        if t.startswith('/*',i):
            j=t.find('*/',i+2); j=n if j<0 else j+2; out.append(re.sub(r'[^\n]',' ',t[i:j])); i=j; continue
        out.append(c); i+=1
    return ''.join(out)
def resolve(raw,cur_schema):
    s=raw.replace('"','')
    def rv(m):
        v=PARAM.get(m.group(1).lower()); return v if v is not None else m.group(0)
    s=re.sub(r'\$\{?(\w+)\}?',rv,s).upper()
    parts=s.split('.')
    if '$' in s: return s,False
    if len(parts)==1: parts=[cur_schema or '?']+parts
    if len(parts)==2:
        if parts[0].startswith('CRCA_'): parts=[DB0]+parts
    return '.'.join(parts), True
def is_temp(name,temps):
    t=name.split('.')[-1]
    if name.upper() not in CAT and (t in CTES or not re.match(r'(VB_|CRCA_|CVBC_|WORK_|LZ_|UDL_|CQDM_|ACV_|EDL_|CLM|MBR|PROV|SCRCRD)',t)): return True
    return name in temps or t.startswith(('TEMP_','TMP_')) or '$' in name or t in KW or name.endswith('.?')
def parse_sql(path):
    raw=open(f'{ROOT}/{path}',encoding='utf-8',errors='replace').read()
    lines=raw.splitlines(); t=strip_comments(raw)
    hdr={}
    for i,l in enumerate(lines[:40],1):
        m=re.match(r'\s*--#?\s*(TITLE|Filename|TARGET Tables?|Developer|Created ON|Parameters)\s*:(.*)',l,re.I)
        if m and m.group(2).strip(): hdr[m.group(1).strip().upper()]=(m.group(2).strip(),i)
    stmts=[];start=0;q=False
    for i,c in enumerate(t):
        if c=="'": q=not q
        if c==';' and not q:
            stmts.append((start,i)); start=i+1
    if t[start:].strip(): stmts.append((start,len(t)))
    cur=None; temps=set(); out=[]
    CTES.update(m.group(1).upper() for m in re.finditer(r'(?:\bWITH|,)\s+(\w+)\s+AS\s*\(',t,re.I))
    for a,b in stmts:
        body=t[a:b]
        if not body.strip(): continue
        lead=len(body)-len(body.lstrip())
        la=t.count('\n',0,a+lead)+1; lb=t.count('\n',0,b)+1
        m=USE.search(body)
        if m and body.strip().upper().startswith('USE'):
            cur,_=resolve(m.group(1),None); cur=cur.split('.')[-1]; continue
        if body.strip().upper().startswith('USE'): continue
        kind='SELECT';target=None
        for k,rx in TGT:
            m=rx.search(body)
            if m: kind=k; target,_=resolve(m.group(1),cur); tl=t.count('\n',0,a+m.start(1))+1; break
        if kind=='CREATE' and re.search(r'\bTEMP(ORARY)?\b',body[:200],re.I): temps.add(target); kind='CREATE TEMP'
        alias={}; srcs=[]
        for m in SRC.finditer(body):
            if body[m.start(1)-1:m.start(1)]=='(': continue
            nm,ok=resolve(m.group(1),cur)
            if nm.split('.')[-1] in KW or re.fullmatch(r'\d+',nm.split('.')[-1]): continue
            ln=t.count('\n',0,a+m.start(1))+1
            if kind=='DELETE' and nm==target and not srcs: continue
            srcs.append((nm,ln,m.group(1)))
            if m.group(2): alias[m.group(2).upper()]=nm
            alias[nm.split('.')[-1]]=nm
        if target: alias.setdefault(target.split('.')[-1],target)
        joins=[]
        for m in JOINEQ.finditer(body):
            x,cx,y,cy=[g.upper() for g in m.groups()]
            if x in alias and y in alias and alias[x]!=alias[y]:
                joins.append((alias[x],cx,alias[y],cy,t.count('\n',0,a+m.start())+1,m.group(0)))
        out.append({'kind':kind,'target':target,'tline':tl if target else la,'traw':m.group(1) if False else None,'a':la,'b':lb,'srcs':srcs,'joins':joins})
    return {'path':path,'n':len(lines),'hdr':hdr,'stmts':out,'temps':temps,'lines':lines}
def short(n): return n.replace(DB0+'.','')
def catalogued(n): return n.upper() in CAT
LINKS=collections.defaultdict(list)
CTES=set()
def link(area,ft,fn,rel,tt,tn,src):
    LINKS[area].append({'from':{'type':ft,'name':fn},'rel':rel,'to':{'type':tt,'name':tn},'source':src})
IO=collections.defaultdict(lambda:{'written_by':[],'read_by':[]})
def quote_for(lines,ln,raw):
    l=lines[ln-1]
    tok=raw.split('.')[-1].strip('"${}')
    return tok if tok and tok in l else None
def etl_doc(mod,p,area):
    P=parse_sql(p); L=P['lines']; job=os.path.basename(p)
    jobname=f'{mod}/{job}'
    md=[f'# {job}',f'',f'Module: {mod}. File: `{p}` ({P["n"]} lines, branch develop). {tag(p,1,P["n"])}','']
    md+=['## Header',f'']
    if P['hdr']:
        for k,(v,i) in P['hdr'].items(): md.append(f'- {k.title()}: {v} {tag(p,i)}')
    else: md.append(f'- The file has no comment header. {tag(p,1)}')
    writes=collections.OrderedDict(); reads=collections.OrderedDict(); pars=collections.OrderedDict()
    for i,l in enumerate(L,1):
        for m in re.finditer(r'\$\{?(\w+)\}?',l):
            pars.setdefault(m.group(1),i)
    md+=['','## Steps','',f'Each SQL statement in file order (temporary tables are working steps inside this file). {tag(p,1,P["n"])}','',
         '| # | Lines | Statement | Target | Reads (resolved) | Source |','|---|---|---|---|---|---|']
    k=0
    for s in P['stmts']:
        if s['kind']=='SELECT' and not s['srcs']: continue
        k+=1
        rd=sorted({short(n) for n,_,_ in s['srcs']})
        md.append(f"| {k} | {s['a']}-{s['b']} | {s['kind']} | {short(s['target']) if s['target'] else '-'} | {', '.join(rd[:8])}{' …' if len(rd)>8 else ''} | {tag(p,s['a'],s['b'])} |")
        if s['target'] and s['kind']!='CREATE TEMP' and not is_temp(s['target'],P['temps']):
            writes.setdefault(s['target'],(s['tline'],s['kind']))
        for n,ln,raw in s['srcs']:
            if not is_temp(n,P['temps']): reads.setdefault(n,(ln,raw))
    md+=['','## Tables written','']
    if not writes: md.append(f'- No permanent table is written by this file; it only reads or builds temporary tables. {tag(p,1,P["n"])}')
    for n,(ln,kd) in writes.items():
        q=quote_for(L,ln,n); c='in the dev catalogue' if catalogued(n) else 'not found in the dev catalogue'
        md.append(f'- `{n}` ({kd}, {c}) {tag(p,ln,None,q)}')
        link(area,'job',jobname,'writes','table',n,tag(p,ln,None,q)); IO[n]['written_by'].append((jobname,p,ln))
    md+=['','## Tables read','']
    if not reads: md.append(f'- No permanent table is read. {tag(p,1,P["n"])}')
    for n,(ln,raw) in reads.items():
        q=quote_for(L,ln,raw); c='in the dev catalogue' if catalogued(n) else 'not found in the dev catalogue'
        md.append(f'- `{n}` ({c}) {tag(p,ln,None,q)}')
        link(area,'job',jobname,'reads','table',n,tag(p,ln,None,q)); IO[n]['read_by'].append((jobname,p,ln))
    md+=['','## Parameters used','',f'Values shown are the dev values from the param file. {tag(PF,1,len(open(ROOT+"/"+PF).readlines()))}','']
    for v,i in pars.items():
        pv=PARAM.get(v.lower())
        if pv is not None: md.append(f'- `${{{v}}}` = `{pv}` (dev) {tag(p,i)} {tag(PF,PLINE[v.lower()])}')
        else: md.append(f'- `${v}` is set outside the dev param file (not in `{os.path.basename(PF)}`). {tag(p,i)}')
    jn=[]
    for s in P['stmts']:
        for x,cx,y,cy,ln,txt in s['joins']:
            if catalogued(x) and catalogued(y) and not is_temp(x,P['temps']) and not is_temp(y,P['temps']):
                jn.append((x,cx,y,cy,ln,txt))
    if jn:
        md+=['','## Joins between catalogued tables','']
        seen=set()
        for x,cx,y,cy,ln,txt in jn:
            key=(x,cx,y,cy)
            if key in seen: continue
            seen.add(key)
            q=txt if txt in L[ln-1] else None
            md.append(f'- `{short(x)}.{cx}` = `{short(y)}.{cy}` {tag(p,ln,None,q)}')
            link(area,'column',f'{x}.{cx}','joins','column',f'{y}.{cy}',tag(p,ln,None,q))
    wr(f'etl/{mod}/jobs/{job}.md','\n'.join(md)+'\n')
    return {'job':job,'path':p,'n':P['n'],'title':P['hdr'].get('TITLE',(None,0)),'writes':list(writes),'reads':list(reads),'stmts':len(P['stmts'])}
# ---------- Python parsing
def py_doc(mod,p,area,kind):
    src=open(f'{ROOT}/{p}',encoding='utf-8',errors='replace').read(); L=src.splitlines()
    md=[f'# {os.path.basename(p)}','',f'Module: {mod}. File: `{p}` ({len(L)} lines, branch develop). {tag(p,1,len(L))}','']
    try: tree=ast.parse(src)
    except SyntaxError as e:
        md.append(f'- The file does not parse as Python 3 ({e.msg}). {tag(p,1,len(L))}'); wr(f'{kind}/{mod}/files/{os.path.basename(p)}.md','\n'.join(md)+'\n'); return {}
    ds=ast.get_docstring(tree)
    if ds: md+=['## Purpose (module docstring)','',f'- {ds.strip().splitlines()[0]} {tag(p,1,tree.body[0].end_lineno)}','']
    imps=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): imps+= [(a.name,n.lineno) for a in n.names]
        elif isinstance(n,ast.ImportFrom) and n.module: imps.append((n.module,n.lineno))
    md+=['## Imports','']
    for nm,ln in sorted(set(imps),key=lambda x:x[1]): md.append(f'- `{nm}` {tag(p,ln,None,nm.split(".")[0])}')
    routes=[];funcs=[]
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            doc=(ast.get_docstring(n) or '').strip().splitlines()
            funcs.append((n.name,n.lineno,n.end_lineno,doc[0] if doc else ''))
            for d in n.decorator_list:
                if isinstance(d,ast.Call) and getattr(d.func,'attr','') in ('route','get','post','put','delete') and d.args and isinstance(d.args[0],ast.Constant):
                    meth=getattr(d.func,'attr','route')
                    ms=[k for k in d.keywords if k.arg=='methods']
                    if ms and isinstance(ms[0].value,(ast.List,ast.Tuple)): meth='/'.join(e.value for e in ms[0].value.elts if isinstance(e,ast.Constant))
                    elif meth=='route': meth='GET'
                    routes.append((meth.upper(),d.args[0].value,n.name,d.lineno))
        elif isinstance(n,ast.ClassDef): funcs.append(('class '+n.name,n.lineno,n.end_lineno,(ast.get_docstring(n) or '').strip().split('\n')[0]))
    if routes:
        md+=['','## HTTP endpoints','','| Method | Path | Handler | Source |','|---|---|---|---|']
        for m_,path,h,ln in routes:
            md.append(f'| {m_} | `{path}` | `{h}` | {tag(p,ln,None,path)} |')
            ep=f'{m_} {path}'; link(area,'endpoint',f'{mod}:{ep}','handled by','function',f'{mod}:{os.path.basename(p)}:{h}',tag(p,ln,None,path))
    md+=['','## Functions and classes','','| Name | Lines | First docstring line | Source |','|---|---|---|---|']
    for nm,a,b,d in sorted(funcs,key=lambda x:x[1]):
        md.append(f'| `{nm}` | {a}-{b} | {d.replace("|","/")[:120]} | {tag(p,a,b)} |')
    ext=[]
    for i,l in enumerate(L,1):
        for rx,lab in ((r'snowflake\.connector\.connect','Snowflake connection'),(r'mysql\.connector\.connect','MySQL connection'),(r'boto3\.(client|resource)\(','AWS SDK client'),
                       (r'smtplib\.SMTP','SMTP mail'),(r'requests\.(get|post|put|delete)\(','HTTP call'),(r'subprocess\.','subprocess'),(r'pyodbc\.connect','ODBC (SQL Server) connection'),
                       (r'st\.(title|set_page_config)\(','Streamlit page'),(r'Flask\(__name__','Flask app'),(r'os\.(environ|getenv)','environment variable read')):
            m=re.search(rx,l)
            if m: ext.append((lab,i,m.group(0)))
    if ext:
        md+=['','## External calls and runtime','']
        for lab,i,q in ext[:80]: md.append(f'- {lab} {tag(p,i,None,q)}')
    tabs=collections.OrderedDict()
    for i,l in enumerate(L,1):
        for m in re.finditer(r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+[\{\w\$\}\.]*?\b((?:VB|CRCA|CVBC)_[A-Z0-9_]+)\b',l):
            nm=m.group(1)
            if nm in BYNAME: tabs.setdefault(nm,(i,m.group(0)))
    if tabs:
        md+=['','## Tables named in SQL text','',f'Matched by exact table name against the dev catalogue; the schema comes from a variable at run time. {tag(p,1,len(L))} [E: query:CATALOG-TABLES-DEV-CRCA]','']
        for nm,(i,q) in tabs.items():
            ks=BYNAME[nm]; base=[k for k in ks if CAT[k]['type']=='BASE TABLE']
            md.append(f'- `{nm}` (catalogue: {", ".join(short(k) for k in ks[:4])}) {tag(p,i,None,nm)}')
            if len(base)==1: link(area,'job' if kind=='etl' else 'module',f'{mod}/{os.path.basename(p)}','uses','table',base[0],tag(p,i,None,nm))
    wr(f'{kind}/{mod}/files/{os.path.basename(p)}.md','\n'.join(md)+'\n')
    return {'file':p,'n':len(L),'routes':len(routes),'funcs':len(funcs),'tables':list(tabs),'doc':(ds or '').strip().split('\n')[0]}
def files(pref,ext,exclude=()):
    out=[]
    for dp,dn,fn in os.walk(f'{ROOT}/{pref}'):
        rel=os.path.relpath(dp,ROOT)
        if any(rel.startswith(e) for e in exclude): continue
        for f in sorted(fn):
            if f.endswith(ext): out.append(os.path.join(rel,f) if rel!='.' else f)
        if pref.endswith('*'): break
    return sorted(out)
mods={'scorecard-sql':[f for f in files('scripts/sql','.sql',('scripts/sql/magnolia_scripts',)) ],
      'magnolia':files('scripts/sql/magnolia_scripts','.sql')}
summary={'etl':{},'app':{}}
for mod,fl in mods.items():
    rows=[etl_doc(mod,p,'etl') for p in fl]; summary['etl'][mod]=rows
orch=[f for f in files('scripts/sql/python','.py') if f.count('/')==3]
summary['etl']['orchestration']=[py_doc('orchestration',p,'etl','etl') for p in orch]
for mod,d in (('cvbc-scorecard-copilot','scripts/sql/python/cvbc_scorecard_copilot'),('migration-assist-tool','scripts/sql/python/migration_assist_tool'),('vldtn-table-manager','scripts/sql/python/vldtn_table_manager')):
    summary['app'][mod]=[py_doc(mod,p,'modules','modules') for p in files(d,'.py')]
for area,ls in LINKS.items():
    seen=set();uniq=[]
    for l in ls:
        k=(l['from']['name'],l['rel'],l['to']['name'])
        if k not in seen: seen.add(k); uniq.append(l)
    wy(f'{area}/{area}.links.yaml',{'links':uniq})
json.dump({'summary':summary,'io':{k:v for k,v in IO.items()}},open(f'{W}/build/summary.json','w'),indent=1,default=str)
print({a:len(v) for a,v in LINKS.items()}, {m:len(r) for m,r in summary['etl'].items()}, {m:len(r) for m,r in summary['app'].items()})
