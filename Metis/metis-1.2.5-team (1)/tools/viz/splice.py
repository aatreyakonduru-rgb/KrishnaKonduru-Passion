import re,json,sys,datetime,os
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),".."))
import site_paths
S=site_paths.load()
t=open('argus.html').read()
i=t.index('const DATA=')+len('const DATA=')
d,end=json.JSONDecoder().raw_decode(t,i)
new=open('mag_data.json').read()
t=t[:i]+new+t[end:]
t=re.sub(r"const DATA_ASOF='[^']*'","const DATA_ASOF='%s'"%datetime.date.today().strftime('%d %b %Y'),t)
t=t.replace('__TITLE__',S.title).replace('__SHORT__',S.short)  # placeholders in assets/gallery/gallery_template.html
t=t.replace("concat(arr.length>10?[{l:`+ ${arr.length-10} more`}]:[])","concat(arr.length>10?[mk(`+ ${arr.length-10} more`,arr.slice(10),f)]:[])")
t=t.replace('const mk=(l,arr,f)=>','const mk=function mk(l,arr,f){return ').replace("concat(arr.length>10?[mk(`+ ${arr.length-10} more`,arr.slice(10),f)]:[])});","concat(arr.length>10?[mk(`+ ${arr.length-10} more`,arr.slice(10),f)]:[])})};",1)
t=t.replace('"Lineage, impact & Argus"','"Lineage & impact"').replace('Argus','Mētis')
t=t.replace('</body>','<script>'+open('patch.js').read()+'</script></body>',1)
if len(sys.argv)>1:
    t=t.replace('</body>','''<script>window.addEventListener('load',()=>{const out=[];VIEWS.forEach((v,i)=>{try{document.getElementById('stage').innerHTML='';v.f();out.push('OK '+i+' '+v.name+' '+document.getElementById('stage').innerHTML.length)}catch(e){out.push('ERR '+i+' '+v.name+' '+e.message)}});document.body.setAttribute('data-test',out.join('|'))})</script></body>''')
exec(open('banner.py').read())
open(sys.argv[1] if len(sys.argv)>1 else 'VIZ_GALLERY.html','w').write(t)
