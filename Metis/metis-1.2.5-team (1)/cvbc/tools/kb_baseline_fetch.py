#!/usr/bin/env python3
"""Read-only: pull every Jira issue of the project created or resolved in the baseline window, plus everything after the
KB start date, with status history. Writes ~/metis-work/stage/jira12m/issues.jsonl. Token: env var named by kb-profile.yaml sources.jira.secret (team.yaml jira.secret), else srcAPM1081911UEPJira."""
import json,os,ssl,sys,time,datetime,urllib.request,urllib.parse,urllib.error,yaml
W=os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work'));K=W+'/kb';OUT=W+'/stage/jira12m'
C=yaml.safe_load(open(K+'/.metis/kb-impact.yaml'))
start=datetime.date.fromisoformat(str(C['kb_start_date']));b0=start.replace(year=start.year-C['baseline_months']//12) if C['baseline_months']%12==0 else start-datetime.timedelta(days=30*C['baseline_months'])
_ty=K+'/.metis/team.yaml';_sec=(yaml.safe_load(open(_ty)).get('jira',{}).get('secret') if os.path.exists(_ty) else None) or yaml.safe_load(open(K+'/.metis/kb-profile.yaml'))['sources']['jira'].get('secret','srcAPM1081911UEPJira')
T=os.environ.get(_sec) or os.environ['srcAPM1081911UEPJira']
B=os.environ.get('METIS_JIRA_BASE','https://jira.elevancehealth.com')+'/rest/api/2';ctx=ssl.create_default_context() if os.environ.get('METIS_TLS_VERIFY','1')!='0' else ssl._create_unverified_context()
def g(p,**q):
    u=B+p+'?'+urllib.parse.urlencode(q)
    for a in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'Authorization':'Bearer '+T,'Accept':'application/json'}),context=ctx,timeout=180))
        except urllib.error.HTTPError as e:
            if e.code in (401,403): sys.exit(f'Jira {e.code}: token needs rotation; not retrying')
            time.sleep(5*(a+1))
        except Exception: time.sleep(5*(a+1))
    raise SystemExit('Jira unreachable')
jql=f'project = {C["project"]} AND (created >= "{b0}" OR resolved >= "{b0}") ORDER BY key ASC'
F=','.join(['issuetype','status','created','resolutiondate','labels','assignee','reporter','priority','components','fixVersions','summary',C['points_field'],C['sprint_field'],C['team_field'],C['defect_found_field'],'environment'])
os.makedirs(OUT,exist_ok=True);n=0;at=0
with open(OUT+'/issues.jsonl','w') as fh:
    while True:
        r=g('/search',jql=jql,fields=F,expand='changelog',startAt=at,maxResults=100)
        for i in r['issues']:
            f=i['fields'];ch=[]
            for h in (i.get('changelog') or {}).get('histories',[]):
                for it in h['items']:
                    if it['field'] in ('status','labels','assignee','Sprint'): ch.append([h['created'],it['field'],it.get('fromString'),it.get('toString')])
            v=lambda x:(x or {}).get('value') if isinstance(x,dict) else ([y.get('value') for y in x] if isinstance(x,list) and x and isinstance(x[0],dict) else x)
            fh.write(json.dumps({'key':i['key'],'type':(f.get('issuetype') or {}).get('name'),'status':(f.get('status') or {}).get('name'),'cat':((f.get('status') or {}).get('statusCategory') or {}).get('key'),
              'created':f.get('created'),'resolved':f.get('resolutiondate'),'labels':f.get('labels'),'assignee':(f.get('assignee') or {}).get('displayName'),'assignee_email':(f.get('assignee') or {}).get('emailAddress'),
              'reporter':(f.get('reporter') or {}).get('displayName'),'priority':(f.get('priority') or {}).get('name'),'points':f.get(C['points_field']),'team':v(f.get(C['team_field'])),
              'found_in':v(f.get(C['defect_found_field'])),'components':[x['name'] for x in f.get('components') or []],'fix':[x['name'] for x in f.get('fixVersions') or []],
              'sprints':len(f.get(C['sprint_field']) or []),'summary':f.get('summary'),'history':ch})+'\n');n+=1
        at+=len(r['issues']);print(f'{at}/{r["total"]}',flush=True)
        if not r['issues'] or at>=r['total']: break
json.dump({'jql':jql,'fields':F,'read_at':datetime.datetime.now().isoformat(timespec='minutes'),'issues':n,'baseline_from':str(b0),'kb_start':str(start)},open(OUT+'/_meta.json','w'),indent=1)
print('done',n)
