import json,os,ssl,urllib.request,zipfile,re,io,html,sys
B=os.environ.get('METIS_CONF_BASE','https://confluence.elevancehealth.com');T=os.environ['CONF'];ctx=ssl.create_default_context() if os.environ.get('METIS_TLS_VERIFY','1')!='0' else ssl._create_unverified_context()
W=os.path.expanduser(os.environ.get('METIS_WORK','~/metis-work'));O=W+'/kb/_EVIDENCE/confluence_att';RAW=W+'/conf_att_raw';os.makedirs(RAW,exist_ok=True)
inv=json.load(open(O+'/_ATTACHMENTS.json'))
FULL=re.compile(r'dictionary|mapping|approach|design|handover|ddl|release note|tool v|kt recording|work items',re.I)
def xml_text(b): return html.unescape(re.sub(r'<[^>]+>',' ',b.decode('utf8','ignore')))
def xlsx(p,full):
    z=zipfile.ZipFile(p);ss=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        ss=[html.unescape(re.sub(r'<[^>]+>','',m)) for m in re.findall(r'<si>(.*?)</si>',z.read('xl/sharedStrings.xml').decode('utf8','ignore'),re.S)]
    wb=z.read('xl/workbook.xml').decode('utf8','ignore');names=re.findall(r'<sheet [^>]*name="([^"]+)"',wb)
    out=[]
    for i,n in enumerate(names,1):
        f=f'xl/worksheets/sheet{i}.xml'
        if f not in z.namelist(): continue
        x=z.read(f).decode('utf8','ignore');rows=re.findall(r'<row[^>]*>(.*?)</row>',x,re.S)
        out.append(f'## sheet: {html.unescape(n)} ({len(rows)} rows)')
        lim=len(rows) if full else 1
        for r in rows[:min(lim,400)]:
            cells=[]
            for c in re.finditer(r'<c ([^>]*?)(?:/>|>(.*?)</c>)',r,re.S):
                a,body=c.group(1),c.group(2) or '';v=re.search(r'<v>(.*?)</v>',body,re.S);t=re.search(r'<t[^>]*>(.*?)</t>',body,re.S)
                if 't="s"' in a and v: cells.append(ss[int(v.group(1))] if int(v.group(1))<len(ss) else '')
                elif t: cells.append(html.unescape(t.group(1)))
                elif v: cells.append(v.group(1))
            if any(s.strip() for s in cells): out.append(' | '.join(s.replace('\n',' ').strip() for s in cells))
        if not full and len(rows)>1: out.append(f'(data rows not copied: may hold member data; {len(rows)-1} rows)')
    return '\n'.join(out)
res=[]
for a in inv:
    ext=os.path.splitext(a['title'])[1].lower();fn=f"{a['page']}-{a['id']}{ext}";p=RAW+'/'+fn
    if not os.path.exists(p):
        r=urllib.request.Request(B+a['download'],headers={'Authorization':'Bearer '+T})
        try:
            with urllib.request.urlopen(r,context=ctx,timeout=300) as f: open(p,'wb').write(f.read())
        except urllib.error.HTTPError as e:
            print('HTTP',e.code,a['title']);
            if e.code in (401,403): sys.exit(1)
            continue
    full=bool(FULL.search(a['title'])) and not re.search(r'test result|test case|tracker',a['title'],re.I)
    try:
        if ext in ('.xlsx','.xlsm'): txt=xlsx(p,full);mode='full' if full else 'headers'
        elif ext in ('.docx','.pptx'):
            z=zipfile.ZipFile(p);txt='\n'.join(xml_text(z.read(n)) for n in sorted(z.namelist()) if re.match(r'(word/document|ppt/slides/slide\d+)\.xml',n));mode='full'
        elif ext in ('.sql','.csv'):
            txt=open(p,errors='ignore').read();mode='full' if ext=='.sql' else 'headers'
            if ext=='.sql' and re.search(r'insert|values',txt,re.I) and re.search(r'mbr|member',txt,re.I): txt='\n'.join(l for l in txt.split('\n') if not re.search(r'values|insert',l,re.I))
            txt=txt if ext=='.sql' else txt.split('\n')[0]
        elif ext=='.zip': txt='\n'.join(zipfile.ZipFile(p).namelist());mode='listing'
        else: txt='';mode='title only (email/image not copied)'
    except Exception as e: txt='';mode='unreadable: '+type(e).__name__
    txt=re.sub(r'[ \t]+',' ',txt)
    txt=re.sub(r'\b[A-Z]{0,3}\d{9,12}\b','[ID-MASKED]',re.sub(r'\b\d{3}-\d{2}-\d{4}\b','[SSN-MASKED]',txt))
    out=f"{a['page']}-{a['id']}.txt"
    open(O+'/'+out,'w').write(f"# {a['title']}\nattachment_id: {a['id']} v{a['version']}\npage: {a['page']} ({a['page_title']})\nmedia: {a['mediaType']}\nmode: {mode}\n\n{txt[:200000]}\n")
    res.append({**a,'file':out,'mode':mode,'chars':len(txt)})
json.dump(res,open(O+'/_ATTACHMENTS.json','w'),indent=1)
import collections;print(len(res),'saved',collections.Counter(r['mode'] for r in res),sum(r['chars'] for r in res),'chars')
