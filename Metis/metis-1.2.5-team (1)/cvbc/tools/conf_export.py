import json,os,re,ssl,sys,time,urllib.request,urllib.parse,html
B=os.environ.get('METIS_CONF_BASE','https://confluence.elevancehealth.com');T=os.environ['CONF'];ctx=ssl.create_default_context() if os.environ.get('METIS_TLS_VERIFY','1')!='0' else ssl._create_unverified_context()
OUT=os.path.expanduser(os.environ.get('METIS_WORK','~/metis-work'))+'/kb/_EVIDENCE/confluence';os.makedirs(OUT,exist_ok=True)
def get(path,**p):
    u=B+path+('?'+urllib.parse.urlencode(p) if p else '')
    r=urllib.request.Request(u,headers={'Authorization':'Bearer '+T,'Accept':'application/json'})
    for a in range(3):
        try:
            with urllib.request.urlopen(r,context=ctx,timeout=120) as f: return json.load(f)
        except urllib.error.HTTPError as e:
            if e.code in(401,403): sys.exit('STOP %s'%e.code)
            if e.code<500: raise
        except Exception: time.sleep(3)
    raise SystemExit('failed '+u)
def text(s):
    s=re.sub(r'<(br|/p|/tr|/h\d|/li|/div)[^>]*>','\n',s);s=re.sub(r'<(td|th)[^>]*>',' | ',s)
    s=re.sub(r'<[^>]+>','',s);s=html.unescape(s);return re.sub(r'\n\s*\n+','\n\n',re.sub(r'[ \t]+',' ',s)).strip()
idx=[];start=0
while True:
    d=get('/rest/api/content/search',cql='space=%s and type=page'%os.environ.get('METIS_CONF_SPACE','CVBN'),limit=50,start=start,expand='version,ancestors,body.storage')
    for r in d['results']:
        v=r['version']['number'];anc=[a['title'] for a in r.get('ancestors',[])]
        t=text(r['body']['storage']['value'])
        open(f"{OUT}/{r['id']}-v{v}.txt",'w').write(f"# {r['title']}\npage_id: {r['id']}\nversion: {v}\nupdated: {r['version']['when']}\npath: {' > '.join(anc)}\nurl: {B}{r['_links']['webui']}\n\n{t}\n")
        idx.append({'id':r['id'],'title':r['title'],'version':v,'updated':r['version']['when'],'path':anc,'chars':len(t)})
    start+=len(d['results'])
    if len(d['results'])<50 or start>=2000: break
json.dump(idx,open(OUT+'/_INDEX.json','w'),indent=1);print('pages',len(idx),'chars',sum(i['chars'] for i in idx))
