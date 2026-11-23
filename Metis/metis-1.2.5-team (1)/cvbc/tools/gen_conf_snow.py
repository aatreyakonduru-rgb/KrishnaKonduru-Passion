"""Team Confluence pages + attachments -> context/CONFLUENCE_TEAM.md; extra Snowflake metadata -> db/DB_TEAM_SCHEMAS.md."""
import json,os,re,shutil,collections
K=os.environ.get('METIS_KB','/home/ubuntu/metis-work/kb');E=K+'/_EVIDENCE';Q=E+'/queries'
idx=json.load(open(E+'/confluence/_INDEX.json'));byid={p['id']:p for p in idx}
att=json.load(open(E+'/confluence_att/_ATTACHMENTS.json')) if os.path.exists(E+'/confluence_att/_ATTACHMENTS.json') else []
TEAMROOT=('1750769822','1750769827','1750764005','1750769853','1857799702','1698976716')
team=[p for p in idx if 'CVBC Scorecard' in str(p['path']) or p['title']=='CVBC Scorecard' or p['id'] in TEAMROOT]
def tag(p): return f"[E: confluence:{p['id']}@v{p['version']}]"
def body(p):
    t=open(f"{E}/confluence/{p['id']}-v{p['version']}.txt").read().split('\n\n',1);t=t[1] if len(t)>1 else ''
    return [l.strip(' |') for l in t.split('\n') if len(l.strip(' |'))>2]
ap=collections.defaultdict(list)
for a in att:
    if a.get('file'):
        n='conf-att-'+a['file'];shutil.copy(E+'/confluence_att/'+a['file'],E+'/files/'+n);a['ev']=n;ap[a['page']].append(a)
def path(p):
    s=p['path'];s=s if isinstance(s,list) else [s]
    return ' > '.join(x for x in s if x)
L=['# CVBC Scorecard team pages in Confluence (CVBN)','',
 f'{len(team)} pages belong to the team: the "CVBC Scorecard" squad page, everything under it, and the CVBC Development / Data Modelling / Database Migrations pages {tag(byid["1750769921"])}.',
 f'{len(att)} attachments on those pages were listed and read where the format allows; test results and job trackers are read for sheet names and headers only, because they may hold member data [E: file:conf-att-index.json].','']
shutil.copy(E+'/confluence_att/_ATTACHMENTS.json',E+'/files/conf-att-index.json')
c=collections.Counter(a['mode'] for a in att)
L+=['## Attachments read','','| How read | Files | Source |','|---|---|---|']+[f'| {m} | {n} | [E: file:conf-att-index.json] |' for m,n in c.most_common()]+['']
groups=collections.defaultdict(list)
for p in team:
    s=p['path'] if isinstance(p['path'],list) else [p['path']]
    g=s[3] if len(s)>3 and s[2]=='CVBC Scorecard' else (p['title'] if p['id']=='1750769921' else (s[2] if len(s)>2 else (s[1] if len(s)>1 else 'CVBC')))
    groups[g].append(p)
for g,ps in sorted(groups.items()):
    L+=[f'## {g}','']
    for p in sorted(ps,key=lambda p:p['title']):
        b=body(p);L.append(f"### {p['title']}");L.append('');L.append(f"- Page {p['id']} v{p['version']}, updated {p['updated'][:10]}, path {path(p) or '(space root)'} {tag(p)}")
        if b:
            L.append(f"- Page text ({len(b)} lines; first lines verbatim): "+' / '.join(b[:12]).replace('[','(').replace(']',')')[:1200]+' '+tag(p))
        else: L.append(f'- The page body has no text; its content is in attachments or macros {tag(p)}')
        for a in ap.get(p['id'],[]):
            t=open(E+'/files/'+a['ev']).read().split('\n\n',1);t=t[1] if len(t)>1 else ''
            sheets=re.findall(r'^## sheet: (.+)$',t,re.M)
            d=f"- Attachment **{a['title'].replace('[','(').replace(']',')')}** ({a['mode']}"+(f"; sheets: {', '.join(sheets[:15])}" if sheets else '')+f") [E: file:{a['ev']}]"
            L.append(d)
            if a['mode']=='full':
                hdr=[l for l in t.split('\n') if l and not l.startswith(('## sheet','('))][:6]
                for h in hdr: L.append(f"  - {h.replace('[','(').replace(']',')')[:400]} [E: file:{a['ev']}]")
        L.append('')
open(K+'/context/CONFLUENCE_TEAM.md','w').write('\n'.join(L)+'\n')
# ---- Snowflake
def J(n): return json.load(open(f'{Q}/{n}.json'))
d,s=J('CATALOG-TABLESTATS-DEV-PRFPHM'),{(r['TABLE_SCHEMA'],r['TABLE_NAME']):r for r in J('CATALOG-TABLESTATS-SIT-PRFPHM')}
M=['# Team schemas in Snowflake: CRCA_PRF_ANTM and CRCA_PHM_ANTM','',
 'Read only through the non-prod connection; counts are catalogue values, no table data was read [E: query:IDENTITY-NONPROD].',
 f"- The connection role sees {len(J('DISCOVERY-DATABASES-NONPROD'))} databases [E: query:DISCOVERY-DATABASES-NONPROD].",
 f"- D01_ACV (enterprise source database) has {len(J('DISCOVERY-SCHEMAS-DEV-ACV'))} schemas [E: query:DISCOVERY-SCHEMAS-DEV-ACV].",
 f"- D01_CRCA has no stored procedures, functions, sequences or pipes visible to this role; it has views and stages [E: query:CATALOG-OBJECTCOUNTS-DEV-CRCA].",
 f"- The definitions of all {len(J('CATALOG-VIEWDEF-ACCESS-DEV-PRF'))} PRF/PHM views (ALLPHI/NOPHI/NOHAPHI) are hidden from this role, so view-to-table mapping is not read [E: query:CATALOG-VIEWDEF-ACCESS-DEV-PRF]. Who can grant view-definition access is not known",'',
 '## Tables (D01 dev vs T01 SIT)','','| Schema | Table | D01 rows | D01 bytes | D01 created | D01 last changed | T01 rows | T01 last changed | Source |','|---|---|---|---|---|---|---|---|---|']
for r in d:
    t=s.get((r['TABLE_SCHEMA'],r['TABLE_NAME']),{})
    M.append(f"| {r['TABLE_SCHEMA']} | {r['TABLE_NAME']} | {r['ROW_COUNT']} | {r['BYTES']} | {r['CREATED']} | {r['LAST_ALTERED']} | {t.get('ROW_COUNT','not in T01')} | {t.get('LAST_ALTERED','')} | [E: query:CATALOG-TABLESTATS-DEV-PRFPHM] [E: query:CATALOG-TABLESTATS-SIT-PRFPHM] |")
only=[k for k in s if k not in {(r['TABLE_SCHEMA'],r['TABLE_NAME']) for r in d}]
if only: M+=['',f"- In T01 but not D01: {', '.join(f'{a}.{b}' for a,b in only)} [E: query:CATALOG-TABLESTATS-SIT-PRFPHM]"]
M+=['','## Stages (D01_CRCA)','','| Schema | Stage | Type | Region | Created | Source |','|---|---|---|---|---|---|']
M+=[f"| {r['STAGE_SCHEMA']} | {r['STAGE_NAME']} | {r['STAGE_TYPE']} | {r['STAGE_REGION']} | {r['CREATED']} | [E: query:CATALOG-STAGES-DEV-CRCA] |" for r in J('CATALOG-STAGES-DEV-CRCA')]
M+=['','## Object counts by schema (D01_CRCA)','','| Kind | Schema | Count | Source |','|---|---|---|---|']+[f"| {r['K']} | {r['S']} | {r['N']} | [E: query:CATALOG-OBJECTCOUNTS-DEV-CRCA] |" for r in J('CATALOG-OBJECTCOUNTS-DEV-CRCA')]
open(K+'/db/DB_TEAM_SCHEMAS.md','w').write('\n'.join(M)+'\n')
print(len(team),'team pages',len(att),'attachments ->',len(L),'lines; db',len(M),'lines')
