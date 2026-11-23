"""Add Devin wiki evidence to the KB: copy answers to _EVIDENCE/files, write context/DEVIN_WIKI.md, append a cited wiki section to each module/ETL/DB README."""
import glob,os,re,shutil,collections
K=os.environ.get('METIS_KB','/home/ubuntu/metis-work/kb');R='bitbucket.elevancehealth.com/AEDLNC/ncr_dna1_crcaprf_files'
W=sorted(glob.glob(K+'/_EVIDENCE/wiki/WIKI-*.md'))
for f in W: shutil.copy(f,K+'/_EVIDENCE/files/')
def clean(s): return re.sub(r'\s+',' ',re.sub(r'<cite[^>]*/>','',s)).strip()
def first_para(t):
    body=t.split('\n\n',1)[1] if '\n\n' in t else t
    for p in body.split('\n\n'):
        p=p.strip()
        if p and not p.startswith(('#','|','```','Wiki pages','View this search','*','-','1.')): return clean(p)
    return ''
def sections(t): return sorted({(m.group(2),m.group(1)) for m in re.finditer(r'\[([^\]]+) \('+re.escape(R)+r'\)\]\(/wiki/[^#]+#([\d.]+)\)',t)},key=lambda x:[int(n) for n in x[0].split('.')])
info={os.path.basename(f):(open(f).read()) for f in W}
allsec=collections.defaultdict(set)
for n,t in info.items():
    for s,title in sections(t): allsec[(s,title)].add(n)
L=['# Devin wiki (DeepWiki) for ncr_dna1_crcaprf_files','',f'The org has one indexed wiki repo, {R} [E: file:WIKI-04-overview-sections.md].',
   f'{len(W)} wiki answers were saved under _EVIDENCE/wiki and _EVIDENCE/files [E: file:{os.path.basename(W[0])}].','','## Wiki sections cited by the answers','','| Section | Title | Answer files |','|---|---|---|']
for (s,title),ns in sorted(allsec.items(),key=lambda x:[int(n) for n in x[0][0].split('.')]):
    L.append(f'| {s} | {title} | {", ".join(sorted(ns))} [E: file:{sorted(ns)[0]}] |')
L+=['','## What each answer says (first paragraph, verbatim)','']
for n,t in info.items():
    q=re.search(r'^question: (.*)$',t,re.M); p=first_para(t)
    if p: L.append(f'- **{n}** ({q.group(1) if q else ""}): {p} [E: file:{n}]')
L+=['','Sections 1.x, 2.1, 3.1, 3.2 and 4.2 were not returned by any wiki answer; the wiki was read through questions only, there is no page-listing tool [?: Q-0012].','']
open(K+'/context/DEVIN_WIKI.md','w').write('\n'.join(L))
MAP={'etl/scorecard-sql/README.md':['07-scorecard-pipeline','16-care-gaps-benchmarks','19-sec3-31-32','23-run-requests','24-risk-earned','08-param-files'],
 'etl/magnolia/README.md':['10-magnolia'],'etl/orchestration/README.md':['09-orchestration','18-sec2x'],
 'modules/migration-assist-tool/README.md':['12-migration-tool','05-section5-tools'],'modules/vldtn-table-manager/README.md':['11-test-automation','21-sec42'],
 'modules/cvbc-scorecard-copilot/README.md':['13-copilot'],'db/DB_OVERVIEW.md':['14-db-schemas','08-param-files'],'context/SYSTEM_OVERVIEW.md':['17-sec1','04-overview-sections','15-deploy-branches','22-sec53']}
for doc,keys in MAP.items():
    p=K+'/'+doc; t=open(p).read().split('\n## From the Devin wiki')[0].rstrip()
    out=['','## From the Devin wiki','']
    for k in keys:
        n=f'WIKI-{k}.md'
        if n not in info: continue
        secs='; '.join(f'{s} {title}' for s,title in sections(info[n])) or 'no section cited'
        out.append(f'- Wiki sections: {secs} [E: file:{n}]')
        fp=first_para(info[n])
        if fp: out.append(f'- Wiki summary: {fp} [E: file:{n}]')
    open(p,'w').write(t+'\n'+'\n'.join(out)+'\n')
print(len(W),'wiki answers,',len(allsec),'sections,',len(MAP),'docs updated')
