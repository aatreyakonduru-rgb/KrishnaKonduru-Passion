import os as _o
import sys as _s;_s.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo
import pickle,json,os,collections
g=pickle.load(open(_o.path.join(WORK,"graph.pkl"),"rb"))
adj=collections.defaultdict(list)
for e in g["edges"]:
    if e["rel"]=="has column": continue
    adj[e["from"]].append((e["rel"],e["to"]))
D=json.load(open("mag_data.json"));n=0
for ep in D["endpoints"]:
    k="endpoint:"+ep["id"];r=set(ep["r"]);w=set(ep["w"]);seen={k};fr=[k]
    for d in range(4):
        nx=[]
        for f in fr:
            for rel,to in adj.get(f,[]):
                if to.startswith("table:"):
                    t=to[6:].split(".")[-1].strip('"').upper()
                    (r if rel=="reads" else w if rel=="writes" else set()).add(t)
                elif to not in seen and not to.startswith(("endpoint:","screen:","repo","module")):
                    seen.add(to);nx.append(to)
        fr=nx
    ep["r"]=sorted(r);ep["w"]=sorted(w);n+=bool(r or w)
json.dump(D,open("mag_data.json","w"),separators=(",",":"))
print("endpoints with tables",n,"of",len(D["endpoints"]))
c=collections.Counter(to.split(":")[0] for k in list(adj)[:0] for _,to in adj[k])
print(collections.Counter((e["from"].split(":")[0],e["rel"],e["to"].split(":")[0]) for e in g["edges"] if e["from"].startswith(("handler:","endpoint:"))).most_common(8))
mt=collections.defaultdict(set)
for e in g["edges"]:
    if e["from"].startswith("handler:") and e["rel"] in("reads","writes") and e["to"].startswith("table:"):
        mt[e["from"].split(":")[1]].add(e["to"][6:].split(".")[-1].strip('"').upper())
D["modTables"]={k:sorted(v) for k,v in mt.items()}
json.dump(D,open("mag_data.json","w"),separators=(",",":"))
print({k:len(v) for k,v in mt.items()})
