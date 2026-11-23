import json,os,ssl,urllib.request,urllib.parse,sys
B=os.environ.get('METIS_CONF_BASE','https://confluence.elevancehealth.com');T=os.environ['CONF'];ctx=ssl.create_default_context() if os.environ.get('METIS_TLS_VERIFY','1')!='0' else ssl._create_unverified_context()
OUT=os.path.expanduser(os.environ.get('METIS_WORK','~/metis-work'))+'/kb/_EVIDENCE/confluence_att'
def get(path,**p):
    u=B+path+('?'+urllib.parse.urlencode(p) if p else '')
    r=urllib.request.Request(u,headers={'Authorization':'Bearer '+T,'Accept':'application/json'})
    with urllib.request.urlopen(r,context=ctx,timeout=120) as f: return json.load(f)
idx=json.load(open('kb/_EVIDENCE/confluence/_INDEX.json'))
TY='kb/.metis/team.yaml'
if os.path.exists(TY):
    import yaml;TC=yaml.safe_load(open(TY)).get('confluence',{});RT=TC.get('team_root_title');RI=set(TC.get('team_root_ids') or [])
    team=[p for p in idx if (RT and RT in str(p['path'])) or p['title']==RT or p['id'] in RI]
else:
    team=[p for p in idx if 'CVBC Scorecard' in str(p['path']) or p['title']=='CVBC Scorecard' or p['id'] in ('1398627261','1857799702','1698976716','1750769822','1750769827','1750764005','1750769853')]
inv=[]
for i,p in enumerate(team):
    try: d=get(f"/rest/api/content/{p['id']}/child/attachment",limit=200,expand='version')
    except urllib.error.HTTPError as e:
        print('HTTP',e.code,p['id']);
        if e.code in (401,403): sys.exit(1)
        continue
    for a in d['results']:
        inv.append({'page':p['id'],'page_title':p['title'],'id':a['id'],'title':a['title'],'mediaType':a.get('metadata',{}).get('mediaType'),'size':a.get('extensions',{}).get('fileSize'),'version':a['version']['number'],'download':a['_links']['download']})
json.dump(inv,open(OUT+'/_ATTACHMENTS.json','w'),indent=1)
import collections
print(len(team),'team pages,',len(inv),'attachments,',sum(a['size'] or 0 for a in inv)//1024,'KB')
print(collections.Counter(os.path.splitext(a['title'])[1].lower() for a in inv).most_common())
