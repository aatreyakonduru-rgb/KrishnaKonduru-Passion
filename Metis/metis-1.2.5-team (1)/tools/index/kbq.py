"""Query the Mētis index.  python3 kbq.py <cmd> ...
  search "<words>" [--src kb|repo] [--repo R] [-n 20]   full-text over every KB file and repo file (path:line hits)
  table <NAME>        every DB/schema/variant holding NAME, columns, lineage (loads in/out), graph links
  node <text>         find graph nodes by name and show their links
  columns <COLUMN>    tables that have a column with this name
  flow <TABLE> [--up|--down] [--depth 3]   SQL-script lineage through VBC -> VBSR -> PHD layers
  schemas [DB]        schema families, variants and table counts
  sql "<SELECT ...>"  read-only SQL on the index"""
import sqlite3,sys,os,argparse,collections
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),"kb_index.sqlite")
con=sqlite3.connect(f"file:{DB}?mode=ro",uri=True);cur=con.cursor()
def q(s,a=()): return cur.execute(s,a).fetchall()
def fts(s): return " ".join('"%s"'%w.replace('"','') for w in s.split())
ap=argparse.ArgumentParser(add_help=False);ap.add_argument("cmd");ap.add_argument("arg",nargs="?",default="")
ap.add_argument("--src");ap.add_argument("--repo");ap.add_argument("-n",type=int,default=20);ap.add_argument("--up",action="store_true");ap.add_argument("--down",action="store_true");ap.add_argument("--depth",type=int,default=3)
a=ap.parse_args()
if a.cmd=="search":
    w="text_fts MATCH ?";p=[fts(a.arg)]
    if a.src: w+=" AND src=?";p.append(a.src)
    if a.repo: w+=" AND repo=?";p.append(a.repo)
    for s,r,path,ln,snip in q(f"SELECT src,repo,path,line,snippet(text_fts,4,'[',']',' … ',14) FROM text_fts WHERE {w} ORDER BY rank LIMIT ?",p+[a.n]):
        print(f"{r}/{path}:{ln}  {snip.replace(chr(10),' ')}")
elif a.cmd=="table":
    t=a.arg.upper().split(".")[-1]
    rows=q("SELECT db,schema,schema_family,variant,table_type,row_count,ncol FROM cat_tables WHERE table_name=? ORDER BY db,schema",(t,))
    print(f"# {t}: in {len(rows)} db.schema locations")
    for r in rows: print("  %s.%s  family=%s variant=%s type=%s rows=%s cols=%s"%r)
    cols=q("SELECT DISTINCT column_name,data_type FROM cat_columns WHERE table_name=? ORDER BY ordinal",(t,))
    if cols: print("# columns (%d):"%len(cols),", ".join(f"{c} {d}" for c,d in cols[:200]))
    for lab,sql in [("loaded from","SELECT src_schema||'.'||src_table,script FROM flow WHERE dst_table=?"),("feeds","SELECT dst_schema||'.'||dst_table,script FROM flow WHERE src_table=?")]:
        r=q(sql,(t,));print(f"# {lab} ({len(r)}):");[print("  ",x,"via",s) for x,s in r[:40]]
    r=q("SELECT e.src,e.rel,e.source FROM edges e WHERE e.dst LIKE ? AND e.rel IN('reads','writes') LIMIT 60",("table:%"+t,))
    print(f"# code that reads/writes it ({len(r)}):");[print("  ",s,rel,"|",src) for s,rel,src in r]
elif a.cmd=="node":
    for k,nm in q("SELECT key,name FROM name_fts WHERE kind='node' AND name_fts MATCH ? LIMIT ?",(fts(a.arg),a.n)):
        print("##",k)
        for s,rel,d,src in q("SELECT src,rel,dst,source FROM edges WHERE src=? OR dst=? LIMIT 40",(k,k)): print("  ",s,"-",rel,"->",d,"|",src)
elif a.cmd=="columns":
    for r in q("SELECT db,schema,table_name,data_type FROM cat_columns WHERE column_name=? ORDER BY db,schema LIMIT 500",(a.arg.upper(),)): print("  %s.%s.%s %s"%r)
elif a.cmd=="flow":
    t=a.arg.upper().split(".")[-1];seen={t};fr=[t]
    for d in range(a.depth):
        nx=[]
        for x in fr:
            sql="SELECT src_table,src_layer,script FROM flow WHERE dst_table=?" if not a.down else "SELECT dst_table,dst_layer,script FROM flow WHERE src_table=?"
            for y,l,s in q(sql,(x,)):
                if y not in seen: seen.add(y);nx.append(y);print("  "*(d+1)+f"{'<-' if not a.down else '->'} {y} [{l}] via {s}")
        fr=nx
elif a.cmd=="schemas":
    w="WHERE db=?" if a.arg else "";p=(a.arg.upper(),) if a.arg else ()
    for r in q(f"SELECT db,schema_family,variant,COUNT(*) FROM cat_tables {w} GROUP BY 1,2,3 ORDER BY 1,2,3",p): print("  %s  %-28s %-22s %d"%r)
elif a.cmd=="sql":
    if not a.arg.strip().lower().startswith(("select","with")): sys.exit("read-only: SELECT/WITH only")
    for r in q(a.arg): print(r)
else: print(__doc__)
