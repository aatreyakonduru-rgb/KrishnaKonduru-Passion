import json,yaml,collections,re,os,pickle
W='/home/ubuntu/metis-work';K=W+'/kb';Q=K+'/_EVIDENCE/queries'
D=json.load(open(W+'/argus/mag_data.json'));g=pickle.load(open(W+'/graph.pkl','rb'));E=g['edges']
S=json.load(open(W+'/build/summary.json'));IO=S['io']
tn=lambda i:i.split('.')[-1]
def mod(f): return f.split('/')[0]
# cat
use=collections.defaultdict(lambda:{'r':set(),'w':set()})
for k,v in IO.items():
    for j in v['read_by']: use[tn(k)]['r'].add(mod(j[0]))
    for j in v['written_by']: use[tn(k)]['w'].add(mod(j[0]))
cat={}
for env,db in (('DEV','D01_CRCA'),('SIT','T01_CRCA')):
    cols=collections.defaultdict(list)
    for c in json.load(open(f'{Q}/CATALOG-COLUMNS-{env}-CRCA.json')): cols[(c['TABLE_SCHEMA'],c['TABLE_NAME'])].append(c['COLUMN_NAME'])
    for t in json.load(open(f'{Q}/CATALOG-TABLES-{env}-CRCA.json')):
        u=use.get(t['TABLE_NAME'].upper(),{'r':set(),'w':set()});cl=cols.get((t['TABLE_SCHEMA'],t['TABLE_NAME']),[])
        cat.setdefault(db,{}).setdefault(t['TABLE_SCHEMA'],[]).append([t['TABLE_NAME'],t['TABLE_TYPE'][0],t.get('ROW_COUNT') or '',len(cl),cl[:200],sorted(u['r']),sorted(u['w'])])
D['cat']=cat
# flow zones
Z=['Enterprise sources (EDL, CQDM, ACV, CFF, CREM)','UI configuration (CRCA_UI_ANTM*)','Member & attribution (CRCA_MRM_ANTM*)','Staging (CRCA_ANTM_STG)','PRF scorecard (CRCA_PRF_ANTM)','PHM care gaps (CRCA_PHM_ANTM)','Other CRCA']
def zone(k):
    p=k.split('.')
    if len(p)<3: return None
    db,s=p[0],p[1]
    if db!='D01_CRCA': return 0
    if s.startswith('CRCA_UI_ANTM'): return 1
    if s.startswith('CRCA_MRM_ANTM'): return 2
    if s=='CRCA_ANTM_STG': return 3
    if s.startswith('CRCA_PRF_ANTM'): return 4
    if s.startswith('CRCA_PHM_ANTM'): return 5
    return 6
T={};Sc=[];Ed=collections.Counter()
def tid(k):
    if k not in T: T[k]=[len(T),zone(k),k.split('.')[1],tn(k)]
    return T[k][0]
jobs=collections.defaultdict(lambda:[set(),set()])
for k,v in IO.items():
    if zone(k) is None: continue
    for j in v['read_by']: jobs[j[0]][0].add(k)
    for j in v['written_by']: jobs[j[0]][1].add(k)
for j,(r,w) in sorted(jobs.items()):
    if not w: continue
    si=len(Sc);Sc.append(j)
    for a in r:
        for b in w:
            if a!=b: Ed[(tid(a),tid(b),si)]+=1
tabs=sorted(T.values());D['flow']={'zones':Z,'t':[[x[1],x[2],x[3]] for x in tabs],'s':Sc,'e':[list(k) for k in Ed]}
# modTables (app modules -> tables via uses)
mt=collections.defaultdict(set)
for e in E:
    if e['rel']=='uses': mt[mod(e['from'].split(':',1)[1])].add(tn(e['to']))
for j,(r,w) in jobs.items(): mt[mod(j)]|={tn(x) for x in r|w}
D['modTables']={k:sorted(v) for k,v in mt.items()}
# systems: inbound sources and outbound to Magnolia
inb=collections.defaultdict(set)
for k,v in IO.items():
    p=k.split('.')
    if len(p)==3 and (p[0]!='D01_CRCA' or p[1].startswith(('CRCA_UI','CRCA_MRM'))) and v['read_by']: inb[p[0]+'.'+p[1]].add(p[2])
sy=[];i=0
for s,v in sorted(inb.items(),key=lambda kv:-len(kv[1])):
    i+=1;sy.append({'id':f'INB-{i:03d}','dir':'in','name':f'{s} → CVBC Scorecard ETL','sys':s,'tables':sorted(v)[:12]})
mag={tn(k) for k,v in IO.items() if any(j[0].startswith('magnolia/') for j in v['written_by'])}
if mag: i+=1;sy.append({'id':f'OUT-{i:03d}','dir':'out','name':'CRCA_PRF_ANTM → Magnolia reporting','sys':'Magnolia reporting','tables':sorted(mag)[:12]})
D['systems']=sy
# states from param lists
st=[]
for l in open('/home/ubuntu/repos/crcaprf-develop/scripts/sql/param/cvbc_prf_params_dev.json'):
    m=re.match(r'\s*"([^"]+)"\s*:\s*"(.*)",?\s*$',l)
    if m and m.group(2).count("'")>=4:
        vals=re.findall(r"'([^']*)'",m.group(2))
        st.append({'name':m.group(1),'desc':'dev param list (cvbc_prf_params_dev.json)','values':[[v,''] for v in vals[:20]]})
D['states']=st[:25]
# metrics: measure-like columns on PRF tables
reg=yaml.load(open(K+'/db/DB_TABLE_REGISTRY.yaml'),Loader=yaml.CSafeLoader);mets=[]
for t in reg['tables']:
    if t['schema']!='CRCA_PRF_ANTM': continue
    for c in t['columns']:
        n=c['name'] if isinstance(c,dict) else c
        if re.search(r'(_RT|_RATE|_SCR|_PCT|_AMT|_CNT|_NBR_VAL|_WT)$',n) and len(mets)<40: mets.append({'label':n,'area':'CRCA_PRF_ANTM','means':f"{t['name']}.{n}"})
D['metrics']=mets
# processes: statement order inside the biggest jobs (real order within the file)
pr=[]
for mname in ('scorecard-sql','magnolia'):
    for r in sorted(S['summary']['etl'][mname],key=lambda r:-r['stmts'])[:2]:
        doc=open(f"{K}/etl/{mname}/jobs/{r['job']}.md").read()
        rows=re.findall(r'^\| (\d+) \| ([\d-]+) \| ([A-Z ]+) \| ([^|]+) \| ([^|]*) \|',doc,re.M)
        pr.append({'name':r['job'],'desc':f"Statement order inside {r['path']} ({len(rows)} steps). Run order between files is open (Q-0004).",
                   'stages':[{'stage':f"{a}_{tg.strip().split('.')[-1]}"[:40],'tables':[x.strip().split('.')[-1] for x in rd.split(',') if x.strip()][:6],'trigger':'file start' if a=='1' else 'previous statement'} for a,ln,kd,tg,rd in rows[:12]]})
D['processes']=pr
# chains: most-read tables, writers and readers
ch=[];lay=lambda j:'ETL' if j.split('/')[0] in('scorecard-sql','magnolia','orchestration') else 'APP'
for k,v in sorted(IO.items(),key=lambda kv:-(len(kv[1]['read_by'])+len(kv[1]['written_by'])))[:8]:
    rd={j[0] for j in v['read_by']};wr={j[0] for j in v['written_by']};n=len(rd)+len(wr)
    ch.append({'id':f'DC-{len(ch)+1:03d}','attr':tn(k),'name':f"{tn(k)} ({k.split('.')[1]})",'risk':'CRITICAL' if n>40 else 'HIGH' if n>15 else 'MEDIUM' if n>5 else 'LOW',
      'w':[{'layer':lay(j),'item':j[:70],'action':'writes'} for j in sorted(wr)[:4]],'r':[{'layer':lay(j),'item':j[:70],'action':'reads'} for j in sorted(rd)[:5]],
      'ch':[{'layer':'DB','action':f'Change {tn(k)} in {k.split(".")[1]}','effort':'MEDIUM'}]+[{'layer':'ETL','action':f'Recheck {len(wr)} writer and {len(rd)} reader jobs','effort':'HIGH' if n>15 else 'MEDIUM'}]})
D['chains']=ch
# rules from the domain context (sourced in context/DOMAIN_CONTEXT.md)
D['rules']=[{'kind':'query_rules','rule':l.split(' [E:')[0][2:]} for l in open(K+'/context/DOMAIN_CONTEXT.md') if l.startswith('- ') and '[E:' in l][:17]
D['counts'].update({'screens':0,'questions':len(yaml.safe_load(open(K+'/_QUESTIONS/VALIDATE_KB.yaml'))['questions'])})
D['sources']={'ontology':'kb/CROSS-LAYER/ONTOLOGY.yaml','graph':'kb/CROSS-LAYER/LINK_GRAPH.yaml','manifest':'kb/KNOWLEDGE-MANIFEST.yaml','dev':'kb/db/DB_TABLE_REGISTRY.yaml','sit':'kb/db/environments/sit/CATALOG_SNAPSHOT.yaml','gates':'kb/_QUESTIONS/VALIDATE_KB.yaml','roles':'kb/.metis/TEAM_ROSTER.yaml'}
# arc: tables used together by the same job
co=collections.Counter();epc=collections.Counter()
for j in D['jobs']:
    ts=sorted(set(j['r'])|set(j['w']))
    for t in ts: epc[t]+=1
    for i in range(len(ts)):
        for k in range(i+1,len(ts)): co[(ts[i],ts[k])]+=1
at=[t for t,_ in epc.most_common(40)]
D['arc']={'tables':at,'links':[[a,b,n] for (a,b),n in co.most_common(400) if a in at and b in at][:150],'eps':{t:epc[t] for t in at}}
json.dump(D,open(W+'/argus/mag_data.json','w'),separators=(',',':'),default=list)
print({k:(len(v) if hasattr(v,'__len__') else v) for k,v in D.items()},os.path.getsize(W+'/argus/mag_data.json')//1000,'KB')
