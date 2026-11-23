import os as _o
import json,os,re,subprocess,collections,html,sys
sys.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."))
import site_paths
S=site_paths.load()
R=S.repos;J=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"joins.json")))
PROJ=S.projects()  # from viz.source_link; empty = evidence is shown without a link
T={};E=[]
def tid(q):
    s,t=q.split(".",1) if "." in q else ("",q)
    if t not in T: T[t]=[len(T),t,set()]
    if s: T[t][2].add(s)
    return T[t][0]
agg=collections.defaultdict(lambda:[collections.Counter(),[],0])
for p in J["pairs"]:
    a,b=tid(p["a"]),tid(p["b"])
    if a==b: continue
    k=(min(a,b),max(a,b));x=agg[k];x[0].update(p["cols"]);x[2]+=p["n"]
    for e in p["ev"]:
        if len(x[1])<6 and e not in x[1]: x[1].append(e)
tabs=[[t[1],sorted(t[2])] for t in sorted(T.values())]
edges=[[a,b,n,dict(c.most_common(5)),ev] for (a,b),(c,ev,n) in agg.items()]
D={"t":tabs,"e":edges,"proj":PROJ,"url":(S.source_link()[1] or "")}
page=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"erd_template.html")).read().replace("__DATA__",json.dumps(D,separators=(",",":")))
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"ERD_JOINS.html"),"w").write(page)
print(len(tabs),"tables",len(edges),"relationships")
