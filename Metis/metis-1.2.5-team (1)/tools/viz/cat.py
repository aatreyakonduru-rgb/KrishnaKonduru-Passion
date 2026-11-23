import os as _o
import sys as _s;_s.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo
import json,pickle,collections,os,glob
RQ=_o.path.join(WORK,"raw-query-json")
g=pickle.load(open(_o.path.join(WORK,"graph.pkl"),"rb"))
use=collections.defaultdict(lambda:{"r":set(),"w":set()})
for e in g["edges"]:
    if e["to"].startswith("table:") and e["rel"] in("reads","writes"):
        p=e.get("defined_in","").split("/"); m=p[1] if len(p)>2 else p[0]
        use[e["to"].split(":",1)[1].split(".")[-1].strip('"').upper()]["r" if e["rel"]=="reads" else "w"].add(m)
cat={}
# viz.catalogs in the profile: [{env, db, name}] -> files raw-query-json/CATALOG-TABLES-<env>-<name>.json (and -COLUMNS-)
for env,db,k in [(c["env"],c.get("db",""),c["name"]) for c in S.list_of("catalogs") if isinstance(c,dict) and c.get("env") and c.get("name")]:
    f=f"{RQ}/CATALOG-TABLES-{env}-{k}.json"
    if not os.path.exists(f): continue
    cols=collections.defaultdict(list)
    cf=f"{RQ}/CATALOG-COLUMNS-{env}-{k}.json"
    if os.path.exists(cf):
        for c in json.load(open(cf)):
            if isinstance(c,dict): cols[(c.get("TABLE_SCHEMA"),c.get("TABLE_NAME"))].append(c.get("COLUMN_NAME"))
    for t in json.load(open(f)):
        if not isinstance(t,dict): continue
        d=cat.setdefault(t["TABLE_CATALOG"],{}).setdefault(t["TABLE_SCHEMA"],[])
        u=use.get(t["TABLE_NAME"].upper(),{"r":set(),"w":set()})
        cl=cols.get((t["TABLE_SCHEMA"],t["TABLE_NAME"]),[])
        d.append([t["TABLE_NAME"],t["TABLE_TYPE"][0],t.get("ROW_COUNT") or "",len(cl),cl[:200],sorted(u["r"]),sorted(u["w"])])
p="mag_data.json";D=json.load(open(p));D["cat"]=cat;json.dump(D,open(p,"w"),separators=(",",":"))
print({db:{s:len(v) for s,v in x.items() if len(v)>20} for db,x in cat.items()}, os.path.getsize(p)//1e6,"MB")
