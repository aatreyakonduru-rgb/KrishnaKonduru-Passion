"""Devin org resources (playbooks, automations, schedules, knowledge notes, skills, rules), repo inventory -> context/DEVIN_RESOURCES.md;
team roster -> one VALIDATE_KB question per person (build/_roster_questions.yaml, merge with questions.py add)."""
import glob,json,os,re,shutil,subprocess,yaml
W=os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work'));K=W+'/kb';F=K+'/_EVIDENCE/files'
TEAM=re.compile(r'CVBC|APM1081911|Scorecard|PRFPHM|PCMS|Magnolia|crcaprf|SCRCRD|CRCA',re.I)
KNOW=('org-knowledge','account-knowledge','org-default','account-uep-hub')
def esc(s): return (s or '').replace('|','/').replace('[','(').replace(']',')').strip()
L=['# Devin resources available to the team','','What Devin itself holds for APM1081911: playbooks, automations, schedules, knowledge notes, plugin skills and rules, and the repos on this VM.','']
# playbooks
pl=open(F+'/devin-playbooks.txt').read()
rows=re.findall(r'- (playbook-[0-9a-f]+)( \[enterprise\])?: (.+)',pl)
L+=[f'## Playbooks ({len(rows)})','','| Playbook | Level | Macro | Team-specific | Overview | Source |','|---|---|---|---|---|---|']
for i,ent,t in rows:
    p=F+f'/devin-playbook-{i}.md';b=open(p).read() if os.path.exists(p) else ''
    mac=(re.search(r'^Macro: (\S+)',b,re.M) or [None,'-'])[1]
    ov=re.search(r'## Overview\s*\n+(.+)',b);ov=esc(ov.group(1))[:220] if ov else ''
    L.append(f"| {esc(t)} | {'enterprise' if ent else 'organization'} | `{mac}` | {'yes' if TEAM.search(t+' '+b[:3000]) else 'no'} | {ov} | [E: file:{os.path.basename(p) if b else 'devin-playbooks.txt'}] |")
for n in ('automations','schedules'):
    t=open(F+f'/devin-{n}.txt').read().strip()
    L+=['',f'## {n.title()}','',f'- {esc(t.splitlines()[0]) if t else "none"} [E: file:devin-{n}.txt]']
# plugins: latest revision of each
L+=['','## Knowledge notes, skills and rules from Devin plugins','','| Plugin | Kind | Name | Team-specific | Description | Source |','|---|---|---|---|---|---|']
inv=[]
for pd in sorted(glob.glob('/opt/.devin/plugins/cache/*')):
    revs=sorted(glob.glob(pd+'/*/'),key=os.path.getmtime)
    if not revs: continue
    r=revs[-1];plug=os.path.basename(pd).replace('account-upload_','').rsplit('-',1)[0]
    for f in sorted(glob.glob(r+'**/SKILL.md',recursive=True)+glob.glob(r+'rules/*.md')):
        kind='skill' if f.endswith('SKILL.md') else 'rule';name=os.path.basename(os.path.dirname(f)) if kind=='skill' else os.path.basename(f)[:-3]
        t=open(f,errors='ignore').read();d=re.search(r'^description:\s*"?(.+?)"?\s*$',t,re.M);d=d.group(1) if d else t.strip().split('\n')[0]
        inv.append({'plugin':plug,'kind':kind,'name':name,'description':d,'path':f.replace(r,'')})
        if any(plug.startswith(k) for k in KNOW):
            ev=f'devin-note-{plug}-{name}.md';shutil.copy(f,F+'/'+ev);kind='knowledge note' if plug.endswith('knowledge') else kind
        else: ev='devin-skills-inventory.json'
        if any(plug.startswith(k) for k in KNOW) or TEAM.search(name+' '+d):
            L.append(f"| {plug} | {kind} | {name} | {'yes' if TEAM.search(name+' '+t[:4000]) else 'no'} | {esc(d)[:200]} | [E: file:{ev}] |")
json.dump(inv,open(F+'/devin-skills-inventory.json','w'),indent=1)
c={};[c.__setitem__(i['plugin'],c.get(i['plugin'],0)+1) for i in inv]
L+=['',f"- All plugin skills and rules: {len(inv)} ({', '.join(f'{k} {v}' for k,v in c.items())}); the table lists knowledge plugins in full and other plugins' team-specific items only [E: file:devin-skills-inventory.json]."]
# repos on the VM
rep=[]
for d in sorted(glob.glob(os.path.expanduser('~/repos/*'))):
    g=lambda *a:subprocess.run(['git','-C',d,*a],capture_output=True,text=True).stdout.strip()
    if not g('rev-parse','HEAD'): continue
    rep.append({'dir':os.path.basename(d),'remote':re.sub(r'//[^@/]+@','//',g('remote','get-url','origin')),'branch':g('rev-parse','--abbrev-ref','HEAD'),'commit':g('rev-parse','--short','HEAD'),'files':len(g('ls-files').splitlines()),'remote_branches':len(g('branch','-r').splitlines())})
json.dump(rep,open(F+'/repos-inventory.json','w'),indent=1)
L+=['','## Repos on this VM','','| Folder | Remote | Branch | Commit | Files | Remote branches | Source |','|---|---|---|---|---|---|---|']
L+=[f"| {r['dir']} | {r['remote']} | {r['branch']} | {r['commit']} | {r['files']} | {r['remote_branches']} | [E: file:repos-inventory.json] |" for r in rep]
open(K+'/context/DEVIN_RESOURCES.md','w').write('\n'.join(L)+'\n')
# roster -> questions
ros=yaml.safe_load(open(K+'/.metis/TEAM_ROSTER.yaml'));Q=[]
for p in ros['team']:
    if p.get('role'): continue
    Q.append({'question':f"Team roster: is {p['name']} ({p.get('email') or 'no email in Jira'}) on the CVBC Scorecard team, and what is their role (dev lead, ETL lead, data lead, architect, manager, product owner, business analyst, security lead, operations, developer, tester, or not on the team)?",
      'type':'access','priority':'P2','context':[f"Assignee on {p['assigned_issues']} and reporter on {p['reported_issues']} CVBC Scorecard board issues [E: file:TEAM_ROSTER.yaml]"]+[f'Sample issue [E: jira:{k}]' for k in p['sample_issues'][:2]],
      'blocks':['context/TEAM.md','.metis/TEAM_ROSTER.yaml'],'possible_answers':[],'answer_role':'manager'})
yaml.safe_dump({'questions':Q},open(W+'/build/_roster_questions.yaml','w'),sort_keys=False,width=200)
print(len(rows),'playbooks,',len(inv),'plugin skills/rules,',len(rep),'repos;',len(Q),'roster questions')
