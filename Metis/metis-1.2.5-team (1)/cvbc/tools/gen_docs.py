import json,os,yaml,collections,re,sys
W='/home/ubuntu/metis-work';KB=W+'/kb';ST=sys.argv[1];REPO='ncr_dna1_crcaprf_files';ROOT='/home/ubuntu/repos/crcaprf-develop'
def tag(p,a,b=None): return f'[E: {REPO}/{p}:{a}'+(f'-{b}' if b and b!=a else '')+']'
def wr(p,s):
    p=os.path.join(ST,p);os.makedirs(os.path.dirname(p),exist_ok=True);open(p,'w').write(s)
S=json.load(open(W+'/build/summary.json'));IO=S['io'];SUM=S['summary']
REG=yaml.safe_load(open(KB+'/db/DB_TABLE_REGISTRY.yaml'));CAT={t['key']:t for t in REG['tables']}
def short(n): return n.replace('D01_CRCA.','')
# ---------------- questions (ids assigned in this order from Q-0001)
Q=[]
def q(text,typ,pri,ctx,blocks,role=None):
    Q.append({'question':text,'type':typ,'priority':pri,'context':ctx,'blocks':blocks,'possible_answers':[],**({'answer_role':role} if role else {})}); return 'Q-%04d'%len(Q)
QDB=q('Which Snowflake database does the ETL connection use in dev? The SQL names only schemas (for example ${etl_stp_prf_antm_schma}); the KB resolves them to D01_CRCA.','data','P1',
 ['The param file gives schema names without a database [E: ncr_dna1_crcaprf_files/scripts/sql/param/cvbc_prf_params_dev.json:1-190]','The migration tool config names D01_CRCA for dev [E: ncr_dna1_crcaprf_files/scripts/sql/python/migration_assist_tool/config/ddl_config.json:142]'],['etl/','db/TABLE_USAGE.md'])
QUAT=q('UAT, preprod and prod Snowflake are not reachable from this session (no connection). Who can provide a read-only connection, or a catalogue export, for U01/P01_CRCA?','access','P1',['Only the non-prod connection is configured [E: settings:sources.workspace_root]'],['db/DB_OVERVIEW.md'])
QROLE=q('Who holds each team role (dev lead, ETL lead, data lead, architect, manager, product owner, business analyst, security lead, operations)? The roster from Jira has names but no roles.','access','P1',['Roster from the CVBC Scorecard board [E: file:TEAM_ROSTER.yaml]'],['context/TEAM.md'])
QSCH=q('How are the SQL jobs scheduled and in what order do they run in each run type (SCCALC, SCBNCHMRK, CAREGAPS)? The repo has no scheduler file; the order is not shown in code.','etl-batch','P1',['Job ids are mapped in the source engine trigger [E: ncr_dna1_crcaprf_files/scripts/sql/python/cvbc_snflk_sc_src_engn_job_trigger.py:1-441]'],['etl/README.md'])
QMISS=q('Tables written or read by the ETL that are not in the dev catalogue (listed in etl/TABLE_IO.md under "Not in the dev catalogue"): are they dropped, renamed, in another database, or created at run time?','data','P2',['Catalogue query [E: query:CATALOG-TABLES-DEV-CRCA]'],['etl/TABLE_IO.md'])
QDRIFT=q('The dev and SIT catalogues differ (see db/DB_DRIFT.yaml). Which side is correct for the current release?','data','P2',['Drift report [E: query:CATALOG-TABLES-SIT-CRCA]'],['db/DB_DRIFT.yaml'])
QSPAN=q('Attribution span: the KT notes describe "Winner Takes All", the code only has POINT_IN_TIME, ANY_TIME_IN_MP and POINT_IN_TIME-OTHER_DUALS. Which is current?','business','P1',['Knowledge note open question [E: file:devin-knowledge-cvbc-scorecard-knowledge.md]','Dev params [E: ncr_dna1_crcaprf_files/scripts/sql/param/cvbc_prf_params_dev.json:44-45]'],['context/DOMAIN_CONTEXT.md'])
QBR=q('Which branch is the KB baseline: develop (5af0e18, documented here), feature/CRCA_PRF_DEC_REL (f82a0d1) or master (9e10839)? master has one Magnolia file not on develop.','application','P2',['Branches read [E: settings:sources.repo_branches]'],['context/SYSTEM_OVERVIEW.md'])
QSTK=q('Stack detection found "schema = [" in migration_assist_tool/config/batch_run.json. Confirm it is a parser artefact and not a schema.','application','P3',['[E: ncr_dna1_crcaprf_files/scripts/sql/python/migration_assist_tool/config/batch_run.json:1-405]'],['context/SYSTEM_OVERVIEW.md'])
QSCOPE=q('Are the migration tool sources (SQL Server TennCare_EoC, MySQL audit metadata) in scope for this KB, or tooling only?','application','P3',['[E: ncr_dna1_crcaprf_files/scripts/sql/python/migration_assist_tool/config/sql_server_config.json:1-45]'],['modules/migration-assist-tool/README.md'])
QBIZ=q('What business meaning does each PRF output table carry (what a row is, who consumes it)? The catalogue has no table comments for most tables.','business','P2',['[E: query:CATALOG-TABLES-DEV-CRCA]'],['db/TABLE_USAGE.md'])
QWIKI=q('The Devin wiki has no page on cvbc_scorecard_copilot (develop only). Is the Copilot released or experimental?','application','P3',['[E: file:WIKI-03-python-tools.md]'],['modules/cvbc-scorecard-copilot/README.md'])
os.makedirs(ST,exist_ok=True); yaml.safe_dump({'questions':Q},open(ST+'/_new_questions.yaml','w'),sort_keys=False,width=200)
# ---------------- ETL module READMEs + TABLE_IO
mdesc={'scorecard-sql':'Snowflake SQL loads in scripts/sql, scripts/sql/automation and scripts/sql/Adhoc','magnolia':'Snowflake SQL loads for the Magnolia reporting layer (scripts/sql/magnolia_scripts)'}
top=['# ETL overview','',f'Three ETL modules from `{REPO}` (branch develop). [E: settings:etl.modules]','',
     f'- Run order and scheduling are not shown in the repo. [?: {QSCH}]',f'- Schemas are resolved with the dev param file; the database is taken as D01_CRCA. [?: {QDB}]','',
     '| Module | Files | Lines | Source |','|---|---|---|---|']
for mod,rows in SUM['etl'].items():
    if mod=='orchestration':
        top.append(f"| orchestration | {len(rows)} | {sum(r.get('n',0) for r in rows)} | [E: kb:etl/orchestration/README.md] |"); continue
    top.append(f"| {mod} | {len(rows)} | {sum(r['n'] for r in rows)} | [E: kb:etl/{mod}/README.md] |")
    md=[f'# ETL module: {mod}','',f'{mdesc[mod]}. [E: settings:etl.modules]','','| Job | Title | Lines | Writes | Reads | Doc |','|---|---|---|---|---|---|']
    for r in sorted(rows,key=lambda r:r['path']):
        md.append(f"| `{r['path']}` | {(r['title'][0] or '').replace('|','/')} | {r['n']} | {', '.join(short(x) for x in r['writes'][:4]) or '-'} | {len(r['reads'])} tables | [E: kb:etl/{mod}/jobs/{r['job']}.md] |")
    wr(f'etl/{mod}/README.md','\n'.join(md)+'\n')
o=['# ETL module: orchestration','','Python job scripts in scripts/sql/python (top level). [E: settings:etl.modules]','','| File | Lines | Functions | First docstring line | Doc |','|---|---|---|---|---|']
for r in SUM['etl']['orchestration']:
    if r: o.append(f"| `{r['file']}` | {r['n']} | {r['funcs']} | {r['doc'].replace('|','/')[:100]} | [E: kb:etl/orchestration/files/{os.path.basename(r['file'])}.md] |")
wr('etl/orchestration/README.md','\n'.join(o)+'\n')
wr('etl/README.md','\n'.join(top)+'\n')
t=['# Table input/output contract (ETL)','','Every permanent table the SQL jobs write or read, with the job and line. Built from the job documents. [E: kb:etl/README.md]','',
   '| Table | In dev catalogue | Written by | Read by |','|---|---|---|---|']
miss=[]
for n in sorted(IO):
    v=IO[n]; inc=n in CAT
    if not inc: miss.append(n)
    w=', '.join(sorted({f"{j[0].split('/')[-1]}:{j[2]}" for j in v['written_by']})[:6]); r=', '.join(sorted({j[0].split('/')[-1] for j in v['read_by']})[:6])
    srcs=[(j[1],j[2]) for j in v['written_by'][:1]+v['read_by'][:1]]
    tg=' '.join(tag(p,l) for p,l in srcs)
    t.append(f"| `{short(n)}` | {'yes [E: query:CATALOG-TABLES-DEV-CRCA]' if inc else f'no [?: {QMISS}]'} | {w or '-'} | {r or '-'} {tg} |")
t+=['','## Not in the dev catalogue','',f'{len(miss)} tables are named by the ETL but not found in the dev catalogue of the schemas read. [?: {QMISS}]','']
t+=[f'- `{n}` [?: {QMISS}]' for n in miss]
wr('etl/TABLE_IO.md','\n'.join(t)+'\n')
# ---------------- app READMEs
for mod,rows in SUM['app'].items():
    rows=[r for r in rows if r]
    md=[f'# Module: {mod}','',f'Python module from `{REPO}` (branch develop). [E: settings:app.modules]','',f'- Files: {len(rows)}, lines: {sum(r["n"] for r in rows)}, HTTP endpoints: {sum(r["routes"] for r in rows)}. [E: kb:modules/{mod}/files]','',
        '| File | Lines | Endpoints | Functions | Tables named | Doc |','|---|---|---|---|---|---|']
    for r in rows: md.append(f"| `{r['file']}` | {r['n']} | {r['routes']} | {r['funcs']} | {len(r['tables'])} | [E: kb:modules/{mod}/files/{os.path.basename(r['file'])}.md] |")
    if mod=='migration-assist-tool': md+=['',f'- Scope of the SQL Server and MySQL sources is open. [?: {QSCOPE}]']
    if mod=='cvbc-scorecard-copilot': md+=['',f'- Release status is open. [?: {QWIKI}]']
    wr(f'modules/{mod}/README.md','\n'.join(md)+'\n')
# ---------------- DB docs
sch=json.load(open(KB+'/_EVIDENCE/queries/DISCOVERY-SCHEMAS-DEV-CRCA.json'))
d=['# Database overview: D01_CRCA (dev reference)','','Read only through the non-prod Snowflake connection. [E: query:IDENTITY-NONPROD]','',
   f'- D01_CRCA has {len(sch)} schemas. [E: query:DISCOVERY-SCHEMAS-DEV-CRCA]',f'- SIT (T01_CRCA) is compared in db/DB_DRIFT.yaml. [E: query:CATALOG-TABLES-SIT-CRCA]',f'- UAT, preprod and prod have no connection. [?: {QUAT}]','',
   '## Schemas with objects','','| Schema | Objects | Tables | Views | Source |','|---|---|---|---|---|']
for r in sch:
    if int(r['N_OBJECTS'])>0: d.append(f"| {r['SCHEMA_NAME']} | {r['N_OBJECTS']} | {r['N_TABLES']} | {r['N_VIEWS']} | [E: query:DISCOVERY-SCHEMAS-DEV-CRCA] |")
wr('db/DB_OVERVIEW.md','\n'.join(d)+'\n')
u=['# PRF table usage (CRCA_PRF_ANTM)','','Every base table in D01_CRCA.CRCA_PRF_ANTM with its columns and the ETL jobs that write or read it. [E: query:CATALOG-COLUMNS-DEV-CRCA]','',
   f'- Business meaning of each table is open. [?: {QBIZ}]','','| Table | Columns | Rows (catalogue) | Written by | Read by | Source |','|---|---|---|---|---|---|']
tr=json.load(open(KB+'/_EVIDENCE/queries/CATALOG-TABLES-DEV-CRCA.json')); rc={(x['TABLE_SCHEMA'],x['TABLE_NAME']):x.get('ROW_COUNT') for x in tr}
for k,tb in sorted(CAT.items()):
    if tb['schema']!='CRCA_PRF_ANTM': continue
    v=IO.get(k,{'written_by':[],'read_by':[]})
    w=', '.join(sorted({j[0].split('/')[-1] for j in v['written_by']})[:5]) or '-'; r=', '.join(sorted({j[0].split('/')[-1] for j in v['read_by']})[:5]) or '-'
    u.append(f"| `{tb['name']}` | {len(tb['columns'])} | {rc.get((tb['schema'],tb['name']),'')} | {w} | {r} | [E: query:CATALOG-TABLES-DEV-CRCA] [E: kb:etl/TABLE_IO.md] |")
wr('db/TABLE_USAGE.md','\n'.join(u)+'\n')
# ---------------- context: Confluence index, Jira snapshot, team
ci=json.load(open(KB+'/_EVIDENCE/confluence/_INDEX.json'))
c=['# Confluence CVBN index','',f'{len(ci)} pages read from space CVBN, saved with their version. [E: settings:sources.confluence.spaces]','','| Page | Path | Updated | Source |','|---|---|---|---|']
for p in sorted(ci,key=lambda p:(' > '.join(p['path']),p['title'])):
    c.append(f"| {p['title'].replace('|','/')} | {' > '.join(p['path'][1:]).replace('|','/')[:90]} | {p['updated'][:10]} | [E: confluence:{p['id']}@v{p['version']}] |")
wr('context/CONFLUENCE_INDEX.md','\n'.join(c)+'\n')
ros=yaml.safe_load(open(KB+'/.metis/TEAM_ROSTER.yaml'))
tm=['# Team (from Jira)','',f"People on the CVBC Scorecard board issues ({ros['source']}). [E: file:TEAM_ROSTER.yaml]",'',f'- Roles are not in Jira. [?: {QROLE}]','','| Name | Assigned | Reported | Sample issues |','|---|---|---|---|']
for p in ros['team']: tm.append(f"| {p['name']} | {p['assigned_issues']} | {p['reported_issues']} | {' '.join('[E: jira:%s]'%k for k in p['sample_issues'][:3])} |")
wr('context/TEAM.md','\n'.join(tm)+'\n')
js=json.load(open(KB+'/_EVIDENCE/jira/_SNAPSHOT.json')); iss=[json.load(open(f"{KB}/_EVIDENCE/jira/{k}.json")) for k in js['issue_keys']]
j=['# Jira snapshot: CVBC Scorecard board','',f"Read {js['read_at']}, filter `{js['jql_open']}`. [E: file:jira-snapshot.json]",'','## By status','']
for s,n in collections.Counter(i['status'] for i in iss).most_common(): j.append(f'- {s}: {n} [E: file:jira-snapshot.json]')
j+=['','## By type','']
for s,n in collections.Counter(i['type'] for i in iss).most_common(): j.append(f'- {s}: {n} [E: file:jira-snapshot.json]')
j+=['','## Open epics and stories touching ETL or tables (latest 40 by update)','']
for i in sorted([i for i in iss if i['status_category']!='Done'],key=lambda i:i['updated'],reverse=True)[:40]:
    j.append(f"- {i['key']} {i['summary'].replace('[','(').replace(']',')')[:110]} ({i['status']}) [E: jira:{i['key']}]")
wr('context/JIRA_SNAPSHOT.md','\n'.join(j)+'\n')
print(len(Q),'questions',len(miss),'missing')
