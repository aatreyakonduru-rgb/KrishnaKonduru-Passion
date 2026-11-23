"""Build the Mētis query index (SQLite + FTS5) from the KB, the repos, the KB graph and the Snowflake catalogue.
Read-only on every input; writes only kb_index.sqlite next to this file."""
import os as _o
import sys as _s;_s.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo

import os,re,json,sqlite3,pickle,glob,datetime,sys
H=_o.path.expanduser("~");KB=KBROOT;REPOS=REPOSROOT;RQ=_o.path.join(WORK,"raw-query-json")
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"kb_index.sqlite")
TXT={".md",".yaml",".yml",".json",".sql",".py",".java",".js",".jsx",".ts",".tsx",".xml",".properties",".sh",".tf",".tfvars",".txt",".html",".css",".scss",".groovy",".gradle",".feature",".cfg",".ini",".conf",".bteq",".ksh",".hql",".csv",".env.example",".toml",".kt",".scala",".r",".ps1",".bat",".cmd",".dockerfile",".j2",".tpl",".graphql"}
SKIPD={".git","node_modules","dist","build","target",".venv","venv","__pycache__",".idea",".gradle","coverage"}
SKIPF=re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.min\.(js|css))$")
SECRET=re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key|access[_-]?key)[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}{]{4,})")
PEM=re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",re.S)
def red(t):
    t=PEM.sub("[REDACTED PRIVATE KEY]",t)
    return SECRET.sub(lambda m:m.group(1)+("${...}" if m.group(2).startswith("$") else "[REDACTED]"),t)
def chunks(text,n=60):
    L=text.split("\n")
    for i in range(0,len(L),n): yield i+1,"\n".join(L[i:i+n])
if os.path.exists(OUT): os.remove(OUT)
db=sqlite3.connect(OUT);c=db.cursor()
c.executescript("""
PRAGMA journal_mode=OFF;PRAGMA synchronous=OFF;
CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT);
CREATE TABLE files(id INTEGER PRIMARY KEY,src TEXT,repo TEXT,path TEXT,ext TEXT,bytes INT,indexed INT,note TEXT);
CREATE VIRTUAL TABLE text_fts USING fts5(src UNINDEXED,repo UNINDEXED,path UNINDEXED,line UNINDEXED,body,tokenize="unicode61 tokenchars '_$.'");
CREATE TABLE nodes(id TEXT PRIMARY KEY,type TEXT,name TEXT);
CREATE TABLE edges(src TEXT,rel TEXT,dst TEXT,source TEXT,defined_in TEXT);
CREATE TABLE cat_tables(env TEXT,db TEXT,schema TEXT,schema_family TEXT,variant TEXT,table_name TEXT,table_type TEXT,row_count TEXT,ncol INT,comment TEXT);
CREATE TABLE cat_columns(db TEXT,schema TEXT,table_name TEXT,column_name TEXT,data_type TEXT,ordinal INT,nullable TEXT,comment TEXT);
CREATE TABLE flow(src_schema TEXT,src_table TEXT,src_layer TEXT,dst_schema TEXT,dst_table TEXT,dst_layer TEXT,script TEXT);
CREATE VIRTUAL TABLE name_fts USING fts5(kind UNINDEXED,key UNINDEXED,name,tokenize="unicode61 tokenchars '_$.'");
""")
now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
c.execute("INSERT INTO meta VALUES('built_at',?)",(now,))
nf=nc=0
def add_tree(src,root,repo_of):
    global nf,nc
    for d,ds,fs in os.walk(root):
        ds[:]=[x for x in ds if x not in SKIPD and not (src=="kb" and x=="_REGEN")]
        for f in fs:
            p=os.path.join(d,f);rel=os.path.relpath(p,root);ext=os.path.splitext(f)[1].lower() or f.lower()
            try: sz=os.path.getsize(p)
            except OSError: continue
            repo=repo_of(rel);note=""
            ok=(ext in TXT or f.lower() in("dockerfile","jenkinsfile","makefile","readme")) and not SKIPF.search(f)
            if ok and sz>25_000_000: ok=False;note="too large for text index (covered by graph/catalog tables)" if src=="kb" else "too large for text index"
            c.execute("INSERT INTO files(src,repo,path,ext,bytes,indexed,note) VALUES(?,?,?,?,?,?,?)",(src,repo,rel,ext,sz,int(ok),note if ok is False and note else ("binary/other" if not ok else "")))
            nf+=1
            if not ok: continue
            try: t=open(p,encoding="utf-8",errors="replace").read()
            except Exception: continue
            t=red(t)
            for ln,b in chunks(t):
                if b.strip(): c.execute("INSERT INTO text_fts VALUES(?,?,?,?,?)",(src,repo,rel,ln,b));nc+=1
add_tree("kb",KB,lambda r:S.short)
for r in (sorted(os.listdir(REPOS)) if os.path.isdir(REPOS) else []):
    if os.path.isdir(os.path.join(REPOS,r)): add_tree("repo",os.path.join(REPOS,r),lambda rel,r=r:r)
db.commit();print("files",nf,"chunks",nc,flush=True)
g=pickle.load(open(WORK+"/graph.pkl","rb"))
c.executemany("INSERT OR IGNORE INTO nodes VALUES(?,?,?)",[(n["id"],n.get("type"),n.get("name")) for n in g["nodes"]])
c.executemany("INSERT INTO edges VALUES(?,?,?,?,?)",[(e["from"],e["rel"],e["to"],e.get("source"),e.get("defined_in")) for e in g["edges"]])
c.executemany("INSERT INTO name_fts VALUES('node',?,?)",[(n["id"],n.get("name") or n["id"]) for n in g["nodes"] if n.get("type")!="column"])
print("graph",len(g["nodes"]),len(g["edges"]),flush=True)
VAR=re.compile(r"_(NOGBD)$");TIER=re.compile(r"_(ALLPHI_DETOK|ALLPHI|NOPHI|NOHAPHI|FEPNOHAPHI|HANOFEPPHI|DETOK)$")
def fam(s):
    v=[];x=s
    m=VAR.search(x)
    if m: v.append(m.group(1));x=x[:m.start()]
    m=TIER.search(x)
    if m: v.append(m.group(1));x=x[:m.start()]
    return x,("+".join(reversed(v)) or "BASE")
n=0
for f in sorted(glob.glob(RQ+"/ALLSCH-*.json")):
    dbn=os.path.basename(f)[7:-5];env=(S.viz.get("env_by_db_prefix") or {}).get(dbn[:3],dbn[:3])  # viz.env_by_db_prefix, e.g. {D01: dev}
    rows=json.load(open(f))
    for s,t,ty,rc,nc_,cm in rows:
        fa,va=fam(s);c.execute("INSERT INTO cat_tables VALUES(?,?,?,?,?,?,?,?,?,?)",(env,dbn,s,fa,va,t,ty,rc,int(nc_ or 0),cm));n+=1
    c.executemany("INSERT INTO name_fts VALUES('table',?,?)",[(f"{dbn}.{r[0]}.{r[1]}",f"{dbn}.{r[0]}.{r[1]}") for r in rows])
print("catalog tables",n,flush=True)
m=0
for f in sorted(glob.glob(RQ+"/CATALOG-COLUMNS-*.json")):
    for r in json.load(open(f)):
        if isinstance(r,dict):
            c.execute("INSERT INTO cat_columns VALUES(?,?,?,?,?,?,?,?)",(r.get("TABLE_CATALOG"),r.get("TABLE_SCHEMA"),r.get("TABLE_NAME"),r.get("COLUMN_NAME"),r.get("DATA_TYPE"),int(r.get("ORDINAL_POSITION") or 0),r.get("IS_NULLABLE"),r.get("COMMENT")));m+=1
print("catalog columns",m,flush=True)
F=json.load(open(WORK+"/argus/mag_data.json"))["flow"]
c.executemany("INSERT INTO flow VALUES(?,?,?,?,?,?,?)",[(F["t"][a][1],F["t"][a][2],F["zones"][F["t"][a][0]],F["t"][b][1],F["t"][b][2],F["zones"][F["t"][b][0]],F["s"][s]) for a,b,s in F["e"]])
c.executescript("""CREATE INDEX e1 ON edges(src);CREATE INDEX e2 ON edges(dst);CREATE INDEX t1 ON cat_tables(table_name);CREATE INDEX t2 ON cat_tables(db,schema);
CREATE INDEX c1 ON cat_columns(table_name);CREATE INDEX c2 ON cat_columns(column_name);CREATE INDEX f1 ON flow(dst_table);CREATE INDEX f2 ON flow(src_table);""")
db.commit();db.execute("VACUUM");db.close()
print("done",OUT,round(os.path.getsize(OUT)/1e6),"MB")
