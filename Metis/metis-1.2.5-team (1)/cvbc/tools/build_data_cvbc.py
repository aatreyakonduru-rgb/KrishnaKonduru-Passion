import os as _o
WORK=_o.environ.get("METIS_WORK",_o.path.expanduser("~/metis-work"));KBROOT=_o.environ.get("METIS_KB",_o.path.expanduser("~/PCMS-MAGNOLIA-KB"));REPOSROOT=_o.environ.get("METIS_REPOS",_o.path.expanduser("~/repos"));LOGO=_o.environ.get("METIS_LOGO",REPOSROOT+"/pcms-admin/admin-ui/src/main/webapp/resources/images/app-logo.png")
import pickle,json,yaml,collections,os,re,subprocess,glob
K=KBROOT; R=REPOSROOT
L=lambda p: yaml.load(open(p),Loader=yaml.CSafeLoader)
g=pickle.load(open(_o.path.join(WORK,"graph.pkl"),"rb"))
E=g["edges"]; N={n["id"]:n for n in g["nodes"]}
def ty(i): return i.split(":")[0]
def tn(i):  # table short name
    return i.split(":",1)[1].split(".")[-1].strip('"').upper()
def mod_of(e):
    f=e["from"].split(":",1)[1] if ":" in e["from"] else e["from"]
    return re.split(r"[/:]",f)[0]
JOBT={"sql_script","job","etl_job","lambda","glue_job","step_function","procedure"}
FILET={"handler","dao","code_file","repo_file","file","service","view"}
def gt(t):
    if t in ("table",): return "table"
    if t in JOBT: return "job"
    if t in FILET: return "file"
    if t=="endpoint": return "endpoint"
    if t=="screen": return "screen"
    if t=="column": return "column"
    return "system"
# ---- endpoints
h2t=collections.defaultdict(lambda:{"r":set(),"w":set()})
for e in E:
    if ty(e["from"]) in ("handler","dao","service") and ty(e["to"])=="table":
        h2t[e["from"]]["r" if e["rel"]=="reads" else "w"].add(tn(e["to"]))
ep={}
for e in E:
    if ty(e["from"])=="endpoint":
        i=e["from"].split(":",1)[1]; d=ep.setdefault(i,{"id":i,"app":i.split(" ",1)[-1].split("/")[0],"r":set(),"w":set()})
        if e["rel"] in("handled_by","calls"): d["r"]|=h2t[e["to"]]["r"]; d["w"]|=h2t[e["to"]]["w"]
for n in g["nodes"]:
    if n["type"]=="endpoint":
        i=n["id"].split(":",1)[1]; ep.setdefault(i,{"id":i,"app":i.split(" ",1)[-1].split("/")[0],"r":set(),"w":set()})
# daos as pseudo endpoints for legacy pcms apps
for h,v in h2t.items():
    if ty(h)=="dao":
        i="DAO "+h.split(":",1)[1]; ep[i]={"id":i,"app":h.split(":")[1],"r":v["r"],"w":v["w"]}
endpoints=[{"id":d["id"],"app":d["app"],"r":sorted(d["r"]),"w":sorted(d["w"])} for d in ep.values()]
EP={x["id"]:x for x in endpoints}
# ---- screens
sc=collections.defaultdict(set)
for e in E:
    if ty(e["from"])=="screen" and ty(e["to"])=="endpoint": sc[e["from"].split(":",1)[1]].add(e["to"].split(":",1)[1])
screens=[]
for s,eps in sorted(sc.items()):
    t=set()
    for x in eps: t|=set(EP.get(x,{}).get("r",[]))|set(EP.get(x,{}).get("w",[]))
    screens.append({"route":s.split(":",1)[0]+":"+s.split("/")[-1],"eps":sorted(eps),"tables":sorted(t)})
# ---- jobs
jb=collections.defaultdict(lambda:{"r":set(),"w":set(),"m":""})
for e in E:
    if ty(e["from"]) in JOBT and ty(e["to"])=="table" and e["rel"] in("reads","writes"):
        d=jb[e["from"]]; d["r" if e["rel"]=="reads" else "w"].add(tn(e["to"])); d["m"]=mod_of(e)
jobs=[{"id":k.split(":",1)[1].split(":")[-1].split("/")[-1],"r":sorted(v["r"]),"w":sorted(v["w"]),"desc":f"{ty(k)} in {v['m']}"} for k,v in sorted(jb.items(),key=lambda kv:-(len(kv[1]['r'])+len(kv[1]['w'])))]
jobs=[j for j in jobs if j["w"]][:400]
# ---- DBs
DBS=[("D01_CRCA","db")]
def ld(p):
    try: return L(f"{K}/{p}")
    except Exception: return {}
# business objects = Magnolia application areas, tables = what their code touches
AREAS=[("scorecard_calc","Scorecard calculation SQL","scorecard-sql"),("magnolia","Magnolia reporting SQL","magnolia"),("orchestration","Orchestration jobs (Python)","orchestration"),
 ("copilot","CVBC Scorecard Copilot","cvbc-scorecard-copilot"),("migration","Migration assist tool","migration-assist-tool"),("vldtn","Validation table manager","vldtn-table-manager")]
area_t=collections.defaultdict(collections.Counter)
for e in E:
    if ty(e["to"])!="table" or e["rel"] not in("reads","writes","uses"): continue
    m=mod_of(e)
    for a,_,p in AREAS:
        if m.startswith(p): area_t[a][tn(e["to"])]+=1; break
objects=[];objTables={}
reg=ld("db/13_DB_ENTITY_REGISTRY.yaml").get("entities",[])
keyof={x["entity"]:x.get("key") for x in reg if isinstance(x,dict)}
sem=ld("db/09_DB_SEMANTIC_LAYER.yaml")
for t in sem.get("tables",[]) or []:
    if t.get("key"): keyof[t["name"]]=t["key"] if isinstance(t["key"],str) else ",".join(t["key"])
for a,lab,p in AREAS:
    c=area_t[a]
    if not c: continue
    top=[t for t,_ in c.most_common(12)]
    objTables[a]=top
    objects.append({"id":a,"label":lab,"table":top[0],"aliases":[p.strip("-"),lab.lower()],"key":keyof.get(top[0]) or "","types":0})
rels=[]
ids=[o["id"] for o in objects]
for i,a in enumerate(ids):
    for b in ids[i+1:]:
        sh=set(area_t[a])&set(area_t[b])
        if sh:
            t=max(sh,key=lambda x:area_t[a][x]+area_t[b][x])
            rels.append({"name":f"{dict((x,y) for x,y,_ in AREAS)[a]} shares {t} with {dict((x,y) for x,y,_ in AREAS)[b]}","fo":a,"to":b,"ft":t,"tt":t,"card":f"{len(sh)} shared tables"})
rels=sorted(rels,key=lambda r:-int(r["card"].split()[0]))[:16]
# ---- systems from lineage files
systems=[];si=0
for db,p in DBS:
    lin=ld(f"{p}/11_DB_DATA_LINEAGE.yaml")
    inc=collections.defaultdict(set); out=collections.defaultdict(set)
    for x in [y for y in (lin.get("inbound") or []) if isinstance(y,dict)]: inc[str(x.get("from",""))[:70]].add(str(x.get("target","")).split(".")[-1])
    for x in [y for y in (lin.get("outbound") or []) if isinstance(y,dict)]:
        for c in x.get("consumers",[]) or []: out[c].add(str(x.get("object","")))
    for k,v in sorted(inc.items(),key=lambda kv:-len(kv[1]))[:3]:
        si+=1; systems.append({"id":f"INB-{si:03d}","dir":"in","name":f"{k} → {db}","sys":db,"tables":sorted(v)[:12]})
    for k,v in sorted(out.items(),key=lambda kv:-len(kv[1]))[:2]:
        si+=1; systems.append({"id":f"OUT-{si:03d}","dir":"out","name":f"{db} → {k}","sys":k,"tables":sorted(v)[:12]})
# ---- states, metrics, rules
states=[];metrics=[];rules=[]
def kind(r):
    r=r.lower()
    if any(w in r for w in("never","read-only","do not","no ","block","mask")): return "forbidden_actions"
    if any(w in r for w in("filter","always include","where")): return "mandatory_filters"
    if any(w in r for w in("cite","answer","return","respond")): return "response_rules"
    return "query_rules"
seenr=set()
for db,p in DBS:
    s=ld(f"{p}/09_DB_SEMANTIC_LAYER.yaml")
    for v in s.get("value_dictionaries",[]) or []:
        if not isinstance(v,dict): continue
        states.append({"name":f"{v.get('column')}","desc":f"{db}.{v.get('table')}","values":[[str(x.get("value")),str(x.get("meaning") or "")] if isinstance(x,dict) else [str(x),""] for x in (v.get("values") or [])][:20]})
    for t in s.get("tables",[]) or []:
        if not isinstance(t,dict): continue
        for c in t.get("columns",[]) or []:
            if isinstance(c,dict) and str(c.get("class","")).lower() in("measure","metric","amount") and len(metrics)<60:
                metrics.append({"label":c["name"],"area":db,"means":f"{t['name']}.{c['name']} ({c.get('type','')})"})
    gr=ld(f"{p}/12_DB_AI_GUARDRAILS.yaml")
    for r in gr.get("rules",[]) or []:
        if not isinstance(r,dict) or not r.get("rule"): continue
        if r.get("rule") in seenr: continue
        seenr.add(r.get("rule")); rules.append({"kind":kind(r["rule"]),"rule":r["rule"]})
if not metrics:
    for db,p in DBS[:3]:
        for t in (ld(f"{p}/09_DB_SEMANTIC_LAYER.yaml").get("tables") or [])[:10]:
            metrics.append({"label":t["name"],"area":db,"means":f"row count {t.get('row_count')}"})
# ---- processes: step functions
sf=collections.defaultdict(list); trig=collections.defaultdict(list)
for e in E:
    if ty(e["from"])=="step_function" and e["rel"] in("invokes","starts"): sf[e["from"].split(":",1)[1]].append(e["to"].split(":",1)[1])
    if ty(e["from"])=="eventbridge_rule" and e["rel"]=="triggers": trig[e["to"].split(":",1)[1]].append(e["from"].split(":",1)[1])
lt={}
for e in E:
    if ty(e["from"])=="lambda" and ty(e["to"])=="table": lt.setdefault(e["from"].split(":",1)[1],set()).add(tn(e["to"]))
processes=[{"name":k,"desc":f"Step Function; triggered by {len(trig.get(k,[]))} EventBridge rules","stages":[{"stage":f"{i+1}_{x.split('-')[-1]}","tables":sorted(lt.get(x,[]))[:6],"trigger":(trig.get(k) or ['manual'])[0] if i==0 else "previous stage"} for i,x in enumerate(v)]} for k,v in sf.items()]
# ---- chains from DB-16
chains=[];cs=None
for db,p in DBS:
    d=ld(f"{p}/16_DB_CROSS_MODULE_DEPENDENCY_MATRIX.yaml")
    if not d: continue
    cs=cs or d.get("change_scenarios")
    for c in sorted([y for y in (d.get("dependency_chains") or []) if isinstance(y,dict) and y.get("table")],key=lambda c:-(len({x.get('layer') for x in c.get('readers',[])})*100+len(c.get('readers',[]))))[:2]:
        nr=len(c.get("readers",[]))+len(c.get("writers",[]))
        risk="CRITICAL" if nr>40 else "HIGH" if nr>15 else "MEDIUM" if nr>5 else "LOW"
        lay=lambda x:{"api":"API","ui":"FE","etl":"ETL","db":"DB"}.get(x.get("layer"),str(x.get("layer")).upper())
        chains.append({"id":c["id"]+"-"+db,"attr":f"{c['table'].split('.')[-1]}.{c.get('column')}","name":f"{c['table'].split('.')[-1]}.{c.get('column')} ({db})","risk":risk,
          "w":[{"layer":lay(x),"item":str(x.get("where"))[:70],"action":"writes"} for x in c.get("writers",[])[:4]],
          "r":[{"layer":lay(x),"item":str(x.get("where"))[:70],"action":"reads"} for x in c.get("readers",[])[:5]],
          "ch":[{"layer":str(x.get("layer")).upper(),"action":str(x.get("step") or x.get("work"))[:90],"effort":"HIGH" if x.get("layer")=="etl" else "MEDIUM" if x.get("layer")=="api" else "LOW"} for x in ((cs or [{}])[0].get("layers") or (cs or [{}])[0].get("layers_touched") or [])]})
# ---- lineage: table->table through jobs
lc=collections.Counter()
for v in jb.values():
    for a in v["r"]:
        for b in v["w"]:
            if a!=b: lc[(a,b)]+=1
lineage=[{"s":a,"t":b,"q":n,"c":n} for (a,b),n in lc.most_common(60)]
# ---- link graph summaries (columns excluded from heavy parts)
deg=collections.Counter(); by=collections.defaultdict(collections.Counter)
trip=collections.Counter()
for e in E:
    a,b=gt(ty(e["from"])),gt(ty(e["to"]))
    trip[(a,e["rel"],b)]+=1
    if a=="column" and b=="table" or e["rel"]=="has column": continue
    deg[e["from"]]+=1; deg[e["to"]]+=1; by[e["to"]][a]+=1; by[e["from"]][b]+=1
lgCounts=collections.Counter(gt(n["type"]) for n in g["nodes"]); lgCounts=dict(lgCounts); lgCounts["edges"]=len(E)
lgTriples=[[a,r,b,n] for (a,r,b),n in trip.most_common(25)]
tabdeg=[(i,d) for i,d in deg.most_common() if ty(i)=="table"]
hubs=[{"name":tn(i),"deg":d,"by":dict(by[i])} for i,d in tabdeg[:25]]
pack={}
for t in ["table","endpoint","file","job","screen","column","system"]:
    items=[(i,d) for i,d in deg.most_common() if gt(ty(i))==t]
    pack[t]={"n":sum(1 for n in g["nodes"] if gt(n["type"])==t),"top":[[i.split(":",1)[1].split(":")[-1][-60:],d] for i,d in items[:40]]}
# sub graph: endpoints + their tables + screens + top jobs
keep=set()
for x in list(EP)[:]: keep.add("endpoint:"+x) if ("endpoint:"+x) in N else None
for i,_ in tabdeg[:120]: keep.add(i)
for i,_ in [(i,d) for i,d in deg.most_common() if ty(i)=="screen"][:60]: keep.add(i)
for i,_ in [(i,d) for i,d in deg.most_common() if ty(i) in JOBT][:80]: keep.add(i)
se=[]
for e in E:
    a,b=e["from"],e["to"]
    if a in keep and b in keep: se.append([a,b,e["rel"]])
    elif ty(a)=="endpoint" and a in keep and ty(b)=="handler":
        for t in h2t[b]["r"]|h2t[b]["w"]:
            for cand in ("table:"+t,):
                pass
# endpoint->table via handler
tid={tn(i):i for i,_ in tabdeg[:120]}
for x in EP.values():
    a="endpoint:"+x["id"]
    if a not in keep: continue
    for t in x["r"]:
        if t in tid: se.append([a,tid[t],"reads"])
    for t in x["w"]:
        if t in tid: se.append([a,tid[t],"writes"])
used={a for a,_,_ in se}|{b for _,b,_ in se}
sub={"nodes":[{"id":gt(ty(i))+":"+i.split(":",1)[1],"t":gt(ty(i)),"l":(tn(i) if ty(i)=="table" else i.split(":",1)[1])[-70:],"d":deg[i],"app":(i.split(" ",1)[-1].split("/")[0] if ty(i)=="endpoint" else i.split(":")[1] if ty(i)=="screen" else "")} for i in used],
     "edges":[[gt(ty(a))+":"+a.split(":",1)[1],gt(ty(b))+":"+b.split(":",1)[1],r] for a,b,r in se]}
# arc: tables co-used by endpoints
co=collections.Counter(); epc=collections.Counter()
for x in endpoints:
    ts=sorted(set(x["r"])|set(x["w"]))
    for t in ts: epc[t]+=1
    for i in range(len(ts)):
        for j in range(i+1,len(ts)): co[(ts[i],ts[j])]+=1
at=[t for t,_ in epc.most_common(40)]
arc={"tables":at,"links":[[a,b,n] for (a,b),n in co.most_common(300) if a in at and b in at][:150],"eps":{t:epc[t] for t in at}}
# G: full navigable graph minus columns
gids=[i for i,_ in deg.most_common() if ty(i)!="column"][:6000]
gi={k:i for i,k in enumerate(gids)}; verbs=sorted({e["rel"] for e in E})
ge=[[gi[e["from"]],gi[e["to"]],verbs.index(e["rel"])] for e in E if e["from"] in gi and e["to"] in gi]
G={"ids":[gt(ty(i))+":"+(tn(i) if ty(i)=="table" else i.split(":",1)[1]) for i in gids],"info":{},"verbs":verbs,"e":ge}
# stories from git history (PCMSP keys) -> files -> tables via evidence tags
file_t=collections.defaultdict(set)
for e in E:
    if ty(e["to"])=="table":
        m=re.match(r"\[E: ([^:\]]+)",e.get("source",""))
        if m: file_t[m.group(1)].add(tn(e["to"]))
st=collections.defaultdict(lambda:collections.defaultdict(set))
for repo in sorted(os.listdir(R)):
    if not os.path.exists(f"{R}/{repo}/.git"): continue
    try: out=subprocess.run(["git","-C",f"{R}/{repo}","log","-n","4000","--name-only","--format=@@%s"],capture_output=True,text=True,timeout=120).stdout
    except Exception: continue
    keys=[]
    for line in out.splitlines():
        if line.startswith("@@"): keys=re.findall(r"\b(CVBC-\d+)\b",line)
        elif line and keys:
            f=f"{repo}/{line}"
            if f in file_t:
                for k in keys: st[k][f]|=file_t[f]
stories=[{"id":k,"files":[{"f":f,"t":sorted(t)[:10]} for f,t in v.items()][:12]} for k,v in sorted(st.items(),key=lambda kv:-sum(len(t) for t in kv[1].values()))[:15]]
# tests: none linked (QA coverage 0)
testScreens=[[s["route"],0] for s in screens[:40]]
tableTest=[[h["name"],0,h["deg"]] for h in hubs]+[[tn(i),0,d] for i,d in tabdeg[25:200]]
# gates from question register by answer role
qs=L(f"{K}/_QUESTIONS/VALIDATE_KB.yaml")["questions"]
gq=collections.defaultdict(list)
for q in qs: gq[(q.get("answer_role") or "unassigned",q.get("type") or "other")].append(q)
gates=[]
for (role,t),v in sorted(gq.items(),key=lambda kv:-len(kv[1]))[:14]:
    bl=collections.Counter(b for q in v for b in (q.get("blocks") or []))
    gates.append({"id":f"KB_{t.upper()}_{role.upper().replace(' ','_')}","name":f"{t} questions for {role}","stage":"knowledge_base_builder","role":role,"blocks":(bl.most_common(1)[0][0] if bl else "KB lines"),"crit":sum(1 for q in v if q.get("priority")=="P1"),"hrs":len(v)})
# lenses/panels from dashboard.yaml
dy=L(f"{K}/.metis/dashboard.yaml")
PT={"overview":"Overview","sprint":"Current sprint","workload":"Workload","waiting":"Waiting / on hold","done":"Done recently","team":"Team","usage":"Devin usage","kb":"Knowledge base","questions":"VALIDATE_KB questions","mine":"My work"}
LZ={"manager":["overview","sprint","workload","waiting","done","team","usage","kb","questions"],"tech_lead":["overview","sprint","workload","waiting","usage","kb","questions"],"product_owner":["overview","sprint","waiting","done","kb","questions"],"developer":["mine","sprint","waiting","usage","kb","questions"]}
lenses=[{"id":k,"label":k.replace("_"," ").title(),"focus":"tabs: "+", ".join(v),"panels":v} for k,v in (dy.get("lenses") or LZ).items()]
panels={k:{"kind":"kb" if k in("kb","questions") else "usage" if k=="usage" else "jira","title":v} for k,v in PT.items()}
kb={}
for d in sorted(os.listdir(K)):
    p=f"{K}/{d}"
    if d.startswith(".") or d=="Archive": continue
    fs=[f for f in glob.glob(p+"/**/*",recursive=True) if os.path.isfile(f)] if os.path.isdir(p) else [p]
    kb[d]={"files":len(fs),"bytes":sum(os.path.getsize(f) for f in fs)}
ntab=sum(1 for n in g["nodes"] if n["type"]=="table")
counts={"tables":ntab,"finance":sum(1 for n in g["nodes"] if n["type"]=="table" and re.search(r"FNCL|FIN|PMT|RMT|CST",n["name"])),"jobs":len(jb),"job_io":sum(len(v["r"])+len(v["w"]) for v in jb.values()),
 "lineage":sum(lc.values()),"code_joins":sum(len((ld(f'{p}/09_DB_SEMANTIC_LAYER.yaml').get('joins') or [])) for _,p in DBS),"screens":len(screens),"endpoints":len(endpoints),"questions":len(qs)}
vq=sum(len(re.findall(r"^## ",open(f).read(),re.M)) for f in glob.glob(f"{K}/db/**/10_DB_VERIFIED_QUERIES.md",recursive=True))
DATA=dict(objects=objects,rels=rels,objTables=objTables,endpoints=endpoints,screens=screens,jobs=jobs,systems=systems,states=states,metrics=metrics,rules=rules,processes=processes,phrases=vq,
 chains=chains,counts=counts,lineage=lineage,lgCounts=lgCounts,lgTriples=lgTriples,hubs=hubs,sub=sub,stories=stories,testScreens=testScreens,tableTest=tableTest,pack=pack,arc=arc,gates=gates,lenses=lenses,panels=panels,kb=kb,G=G)
json.dump(DATA,open(_o.path.join(WORK,"argus/mag_data.json"),"w"),separators=(",",":"),default=list)
print({k:(len(v) if hasattr(v,"__len__") else v) for k,v in DATA.items()}, "sub",len(sub["nodes"]),len(sub["edges"]),"G",len(gids),len(ge))
