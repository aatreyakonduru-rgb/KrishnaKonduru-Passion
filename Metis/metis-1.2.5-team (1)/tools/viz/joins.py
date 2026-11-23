import os as _o
import os,re,json,collections,sys
sys.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."))
import site_paths
S=site_paths.load()
R=S.repos;OUT=_o.path.join(S.work,"erd","joins.json");_o.makedirs(_o.path.dirname(OUT),exist_ok=True)
P={}
def load(f):
    try: d=json.load(open(f))
    except Exception: return
    def w(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if isinstance(v,(dict,list)): w(v)
                elif isinstance(v,str): P.setdefault(k.upper(),v.upper())
        elif isinstance(x,list):
            for v in x: w(v)
    w(d)
# viz.param_files in the profile: JSON files (relative to the repos folder) whose ${NAME} values name schemas; none = none
for _f in S.list_of("param_files"): load(R+"/"+str(_f))
def res(x):
    m=re.fullmatch(r"\$\{?([A-Z0-9_]+)\}?",x)
    return P.get(m.group(1),x).split(".")[-1] if m else x
KW={"SELECT","WHERE","ON","LEFT","RIGHT","INNER","OUTER","FULL","CROSS","JOIN","GROUP","ORDER","UNION","SET","AND","OR","USING","AS","WITH","LATERAL","QUALIFY","HAVING","LIMIT","WHEN","THEN","ELSE","END","NATURAL"}
TAB=re.compile(r"\b(?:FROM|JOIN)\s+([A-Z0-9_$\{\}\"]+(?:\.[A-Z0-9_$\{\}\"]+){0,2})(?:\s+(?:AS\s+)?([A-Z_][A-Z0-9_]*))?",re.I)
COND=re.compile(r"\b([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)",re.I)
SKIPT=re.compile(r"LOAD_LOG|_BKP|^TEMP_|^TMP_|_TEMP$|_TMP$|^DUAL$",re.I)
pairs=collections.defaultdict(lambda:{"cols":collections.Counter(),"ev":[]})
tabs={}
nf=0
for repo in sorted(os.listdir(R)):
    root=os.path.join(R,repo)
    if not os.path.isdir(root): continue
    for d,ds,fs in os.walk(root):
        ds[:]=[x for x in ds if x not in(".git","node_modules","target","dist","build") and "archiv" not in x.lower()]
        for f in fs:
            if not f.lower().endswith((".sql",".java",".xml",".py",".bteq",".hql",".txt")): continue
            p=os.path.join(d,f)
            try:
                if os.path.getsize(p)>3_000_000: continue
                t=open(p,encoding="utf-8",errors="replace").read()
            except Exception: continue
            if not re.search(r"\bJOIN\b",t,re.I): continue
            nf+=1;rel=os.path.relpath(p,R)
            t2=re.sub(r"--[^\n]*","",t);t2=re.sub(r"/\*.*?\*/",lambda m:"\n"*m.group(0).count("\n"),t2,flags=re.S)
            pos=0
            for stmt in re.split(r";",t2):
                line0=t2.count("\n",0,pos)+1;pos+=len(stmt)+1
                al={}
                for m in TAB.finditer(stmt):
                    full=[res(x.strip('"').upper()) for x in m.group(1).split(".")]
                    tb=full[-1];sc=full[-2] if len(full)>1 else ""
                    if tb in KW or tb.startswith("(") or not re.match(r"[A-Z_]",tb): continue
                    a=(m.group(2) or "").upper()
                    if a in KW or not a: a=tb
                    al[a]=(sc,tb);al[tb]=(sc,tb)
                for m in COND.finditer(stmt):
                    a,c1,b,c2=[x.upper() for x in m.groups()]
                    if a not in al or b not in al: continue
                    (s1,t1),(s2,t2_)=al[a],al[b]
                    if t1==t2_ or SKIPT.search(t1) or SKIPT.search(t2_): continue
                    ln=line0+stmt.count("\n",0,m.start())
                    k=tuple(sorted([(s1,t1,c1),(s2,t2_,c2)]))
                    key=(k[0][0]+"."+k[0][1],k[1][0]+"."+k[1][1])
                    e=pairs[key];e["cols"][k[0][2]+"="+k[1][2]]+=1
                    if len(e["ev"])<5: e["ev"].append(f"{rel}:{ln}")
                    for s,tb in ((s1,t1),(s2,t2_)): tabs.setdefault(s+"."+tb,0);tabs[s+"."+tb]+=1
out={"tables":tabs,"pairs":[{"a":a,"b":b,"cols":dict(v["cols"].most_common(6)),"n":sum(v["cols"].values()),"ev":v["ev"]} for (a,b),v in pairs.items()]}
json.dump(out,open(OUT,"w"))
print("files with JOIN",nf,"tables",len(tabs),"pairs",len(out["pairs"]),"MB",round(os.path.getsize(OUT)/1e6,1))
print(sorted(out["pairs"],key=lambda x:-x["n"])[:3])
