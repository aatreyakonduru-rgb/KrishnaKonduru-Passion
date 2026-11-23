import os as _o
import sys as _s;_s.path.insert(0,_o.path.dirname(_o.path.abspath(__file__)));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo
import pickle,json,re,collections,os
R=REPOSROOT
P={}
def load(f):
    d=json.load(open(f))
    def w(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if isinstance(v,(dict,list)): w(v)
                elif isinstance(v,str): P.setdefault(k.upper(),v.upper())
        elif isinstance(x,list):
            for v in x: w(v)
    w(d)
# Everything below comes from `viz.lineage` in the profile; without it there are no layers and nothing is drawn.
#   param_files: JSON files (under the repos folder) whose ${NAME} values name schemas
#   zones: [{label, schemas: [exact names], prefixes: [name starts], table_prefix: "LZ_"}], in flow order, upstream first
#   source_repo_pattern: regex on a link file path that selects the ETL code; skip_pattern: names to leave out
#   database_prefix: regex a 3-part name's first part must match (e.g. "(D01|T01|\\$)"); empty = any
LIN=S.viz.get("lineage") or {}
for _f in LIN.get("param_files") or []:
    try: load(R+"/"+str(_f))
    except (OSError,ValueError): pass
ZN=[z for z in LIN.get("zones") or [] if isinstance(z,dict) and z.get("label")]
ZONES=[z["label"] for z in ZN]
SRC=re.compile(LIN.get("source_repo_pattern") or r"(?!x)x")
DBP=re.compile(LIN["database_prefix"]) if LIN.get("database_prefix") else None
def res(x):
    m=re.fullmatch(r"\$\{?([A-Z0-9_]+)\}?",x)
    if m: return P.get(m.group(1),x)
    return x
def zone(sch,tb):
    if not tb or "LOAD_LOG" in tb or "BKP" in tb or tb.startswith("TMP_") or tb.startswith("TEMP_"): return None
    for i,z in enumerate(ZN):
        if z.get("table_prefix") and tb.startswith(z["table_prefix"]): return i
    for i,z in enumerate(ZN):
        if sch in (z.get("schemas") or []): return i
    for i,z in enumerate(ZN):
        if any(sch.startswith(p) for p in (z.get("prefixes") or [])): return i
    return None
def norm(t):
    p=[res(x.strip('"')) for x in t.upper().split(".")]
    p=[q.split(".")[-1] for q in p]
    if len(p)==3: db,s,tb=p
    elif len(p)==2: db,(s,tb)=None,p
    else: return None
    if db and DBP and not DBP.match(db) and not db.startswith("$"): return None
    z=zone(s,tb)
    return (z,s,tb) if z is not None else None
g=pickle.load(open(_o.path.join(WORK,"graph.pkl"),"rb"))
io=collections.defaultdict(lambda:[set(),set()])
SKIP=re.compile(r"archiv|adhoc|backup|_bkp|/test",re.I)
for e in g["edges"]:
    d=e.get("defined_in","")
    if not SRC.search(d): continue
    if e["rel"] not in("reads","writes") or not e["to"].startswith("table:"): continue
    if SKIP.search(e["from"]): continue
    n=norm(e["to"][6:])
    if n: io[e["from"]][0 if e["rel"]=="reads" else 1].add(n)
T={};S=[];E=collections.Counter()
def tid(n):
    k=n[1]+"."+n[2]
    if k not in T: T[k]=[len(T),n[0],n[1],n[2]]
    return T[k][0]
for sc,(r,w) in io.items():
    if not w: continue
    si=len(S); S.append(sc.split(":",2)[-1] if sc.count(":")>=2 else sc)
    for a in r:
        for b in w:
            if a!=b and a[0]<=b[0]: E[(tid(a),tid(b),si)]+=1
tabs=sorted(T.values()); 
flow={"zones":ZONES,"t":[[x[1],x[2],x[3]] for x in tabs],"s":S,"e":[list(k) for k in E]}
D=json.load(open("mag_data.json")); D["flow"]=flow; json.dump(D,open("mag_data.json","w"),separators=(",",":"))
zc=collections.Counter(x[1] for x in tabs); print({ZONES[k]:v for k,v in sorted(zc.items())}); print(len(S),"scripts",len(E),"edges")
zz=collections.Counter((T2[0],T3[0]) for T2,T3 in [((tabs[a][1],),(tabs[b][1],)) for a,b,_ in E]); print(sorted(zz.items()))
