"""Put the CVBC gallery data into the gallery page template and apply the CVBC fixes."""
import json,re,datetime,sys,os
A=os.path.dirname(os.path.abspath(__file__));TPL=sys.argv[1] if len(sys.argv)>1 else os.path.join(os.path.dirname(A),'assets','gallery_template_cvbc.html')
t=open(TPL).read()
i=t.index('const DATA=')+len('const DATA=');d,end=json.JSONDecoder().raw_decode(t,i)
t=t[:i]+open(os.path.join(os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work')),'argus/mag_data.json')).read()+t[end:]
t=re.sub(r"const DATA_ASOF='[^']*'","const DATA_ASOF='%s'"%datetime.date.today().strftime('%d %b %Y'),t)
t=t.replace('CVBC KNOWLEDGE BASE','CVBC SCORECARD (PRFPHM) KNOWLEDGE BASE').replace('crcaui/UI-KB/','kb/')
for a,b in [('const G=DATA.gates.filter(g=>/^SDLC/.test(g.id)),n=G.length','let G=DATA.gates.filter(g=>/^SDLC/.test(g.id));if(!G.length)G=DATA.gates;const n=G.length'),
 ('const cols=["screen","endpoint","table","job","system"],{nodes,edges}=lgNodes(cols.concat([]))','const cols=DATA.screens.length?["screen","endpoint","table","job","system"]:["job","table","endpoint","system"],{nodes,edges}=lgNodes(cols.concat([]))'),
 ('const scr=by.screen.map(n=>n.id);let i=0;light(scr[0]);','const scr=by[cols[0]].map(n=>n.id);let i=0;if(scr.length)light(scr[0]);'),
 ('"Five columns from what a user sees to where the data goes: screen, API call, table, ETL job, outside system. Click a screen','"Columns from where data is processed to where it goes (screen, API call, table, ETL job, outside system; with no screens it starts at the ETL job). Click a dot in the first column'),
 ('The Argus approval gates in the order approval-gates.yaml lists them.','The KB review steps from VALIDATE_KB, grouped by question type and the role that answers.')]:
    t=t.replace(a,b)
open(os.path.join(os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work')),'argus','gallery.html'),'w').write(t);print('gallery',len(t))
