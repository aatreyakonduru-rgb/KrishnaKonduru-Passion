#!/usr/bin/env python3
"""Mētis visual pages: VISUALIZATION/ in the KB folder, drawn only from files the KB already sources.

    python3 gen_visuals.py <kb>

Reads CROSS-LAYER/LINK_GRAPH.yaml, ONTOLOGY.yaml, IMPACT_MATRIX.yaml, QA_COVERAGE.yaml, the table registry,
_QUESTIONS/VALIDATE_KB.yaml and the verify report. Writes index.html, ONTOLOGY.html (animated graph, flows,
lineage, impact paths, coverage, open questions), ERD.html, KB_MANIFEST.html and KB_HEALTH.html. Every link
shown carries the source of the link it draws; nothing is added here.
"""
import datetime
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_registry  # noqa: E402
import kb_manifest  # noqa: E402
import verify_kb  # noqa: E402

CSS = """*{box-sizing:border-box}body{margin:0;font:14px/1.5 'Segoe UI',system-ui,Arial;color:#1f1b2e;background:#f6f4fb}
header{display:flex;align-items:baseline;gap:12px;padding:12px 22px;background:#fff;border-bottom:1px solid #e4defa}
header h1{font-size:18px;margin:0}header span{color:#6b6480;font-size:13px}main{padding:16px 22px}
.embedded header,.embedded footer{display:none}.embedded body{background:#fff}.embedded main{padding:0}
nav.nav-groups{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
.grp-btn{border:1px solid #d9d2f5;background:#fff;border-radius:8px;padding:6px 14px;cursor:pointer;font:inherit;font-weight:600;color:#5b21b6}
.grp-btn:hover{background:#ede8f9;border-color:#5b21b6}
.grp-btn.on{background:#5b21b6;color:#fff;border-color:#5b21b6}
.nav-subtabs-wrap{margin:0 0 14px}
nav.sub-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:5px 8px;background:#ece7f8;border-radius:8px;align-items:center}
nav.sub-tabs[hidden]{display:none}
nav.sub-tabs.single{display:none}
.tab-btn{border:1px solid transparent;background:transparent;border-radius:6px;padding:5px 11px;cursor:pointer;font:inherit;font-size:13px;color:#4c1d95}
.tab-btn:hover{background:#fff;border-color:#d9d2f5}
.tab-btn.on{background:#fff;color:#5b21b6;font-weight:600;border-color:#cfc6f0;box-shadow:0 1px 2px rgba(91,33,182,.1)}
nav.tabs{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 14px}nav.tabs button{border:1px solid #d9d2f5;background:#fff;border-radius:8px;padding:6px 11px;cursor:pointer;font:inherit}
nav.tabs button.on{background:#5b21b6;color:#fff;border-color:#5b21b6}section[hidden]{display:none}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}.card{background:#fff;border:1px solid #e4defa;border-radius:12px;padding:14px}
.card b{font-size:26px;color:#5b21b6;display:block}a.card{text-decoration:none;color:inherit}a.card:hover{border-color:#7c3aed}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}td,th{border:1px solid #e4defa;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#efeafd}code{font-size:12px;color:#4c1d95;word-break:break-all}input,select{padding:6px 8px;border:1px solid #cfc6f0;border-radius:8px;font:inherit}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chip{border-radius:14px;padding:3px 10px;border:1px solid #cfc6f0;background:#fff;cursor:pointer;font-size:12px}
.chip.off{opacity:.35}.wrap{display:grid;grid-template-columns:1fr 340px;gap:12px}canvas,svg.flow{background:#fff;border:1px solid #e4defa;border-radius:12px;width:100%}
#side{background:#fff;border:1px solid #e4defa;border-radius:12px;padding:12px;max-height:640px;overflow:auto;font-size:13px}
.muted{color:#6b6480}.p1{color:#b91c1c;font-weight:600}.p2{color:#b45309}.p3{color:#047857}
@keyframes dash{to{stroke-dashoffset:-24}}.flowline{stroke-dasharray:6 6;animation:dash 1s linear infinite}
footer{padding:12px 22px;color:#6b6480;font-size:12px}"""
COLORS = ["#7c3aed", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#6366f1", "#14b8a6", "#84cc16", "#a855f7", "#64748b", "#f97316"]


def load(p):
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def page(title, sub, body, data, js=""):
    d = json.dumps(data, default=str).replace("</", "<\\/")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>%s</style>"
            "<script>if(self!==top)document.documentElement.className='embedded'</script></head><body>"
            "<header><h1>%s</h1><span>%s</span></header><main>%s</main>"
            "<footer>Built by Mētis from the KB files. Every link shown names its source; nothing on this page is "
            "added by the page itself.</footer><script>var D=%s;function esc(s){var d=document.createElement('div');"
            "d.textContent=s==null?'':String(s);return d.innerHTML}function tabs(){"
            "var grpBtns=document.querySelectorAll('.grp-btn'),subNavs=document.querySelectorAll('.sub-tabs'),"
            "tabBtns=document.querySelectorAll('.tab-btn'),sections=document.querySelectorAll('main>section');"
            "if(!grpBtns.length){var b=document.querySelectorAll('nav.tabs button');"
            "b.forEach(function(x){x.onclick=function(){b.forEach(function(y){y.classList.remove('on');var el=document.getElementById(y.dataset.t);if(el)el.hidden=true});"
            "x.classList.add('on');var target=document.getElementById(x.dataset.t);if(target)target.hidden=false;history.replaceState(null,'','#'+x.dataset.t);if(window.onTab)onTab(x.dataset.t)}});"
            "var h=location.hash.slice(1);var s=h&&document.querySelector('nav.tabs button[data-t=\"'+h+'\"]');(s||b[0])&&(s||b[0]).click();"
            "}else{"
            "function activateTab(tId,updateHash){"
            "var btn=document.querySelector('.tab-btn[data-t=\"'+tId+'\"]')||document.querySelector('.tab-btn[data-t=\"sec-'+tId+'\"]');"
            "if(!btn&&tId.startsWith('sec-'))btn=document.querySelector('.tab-btn[data-t=\"'+tId.slice(4)+'\"]');"
            "if(!btn)return false;"
            "var grp=btn.dataset.grp,targetId=btn.dataset.t;"
            "grpBtns.forEach(function(g){var on=g.dataset.grp===grp;g.classList.toggle('on',on);g.setAttribute('aria-selected',on?'true':'false')});"
            "subNavs.forEach(function(sn){var on=sn.dataset.grp===grp;sn.hidden=!on});"
            "tabBtns.forEach(function(tb){var on=tb===btn;tb.classList.toggle('on',on);tb.setAttribute('aria-selected',on?'true':'false')});"
            "sections.forEach(function(sec){var on=sec.id===targetId;sec.hidden=!on});"
            "if(updateHash!==false)history.replaceState(null,'','#'+targetId);"
            "if(window.onTab)onTab(targetId);return true}"
            "function activateGroup(grpId){var sn=document.querySelector('.sub-tabs[data-grp=\"'+grpId+'\"]');if(!sn)return;"
            "var firstTab=sn.querySelector('.tab-btn.on')||sn.querySelector('.tab-btn');if(firstTab)activateTab(firstTab.dataset.t)}"
            "grpBtns.forEach(function(gb){gb.onclick=function(){activateGroup(gb.dataset.grp)}});"
            "tabBtns.forEach(function(tb){tb.onclick=function(){activateTab(tb.dataset.t)}});"
            "function handleArrows(list,items){list.addEventListener('keydown',function(e){"
            "var arr=Array.from(items).filter(function(x){return !x.hidden&&x.offsetParent!==null});"
            "var idx=arr.indexOf(document.activeElement);if(idx<0)return;"
            "if(e.key==='ArrowRight'||e.key==='ArrowDown'){e.preventDefault();var next=arr[(idx+1)%%arr.length];next.focus();next.click()}"
            "else if(e.key==='ArrowLeft'||e.key==='ArrowUp'){e.preventDefault();var prev=arr[(idx-1+arr.length)%%arr.length];prev.focus();prev.click()}"
            "else if(e.key==='Home'){e.preventDefault();arr[0].focus();arr[0].click()}"
            "else if(e.key==='End'){e.preventDefault();arr[arr.length-1].focus();arr[arr.length-1].click()}})}"
            "var grpNav=document.querySelector('.nav-groups');if(grpNav)handleArrows(grpNav,grpBtns);"
            "subNavs.forEach(function(sn){handleArrows(sn,sn.querySelectorAll('.tab-btn'))});"
            "var h=location.hash.slice(1),matched=false;"
            "if(h){matched=activateTab(h,false);if(!matched&&h.startsWith('grp-')){activateGroup(h.slice(4));matched=true}}"
            "if(!matched)activateTab('overview',false)}"
            "setTimeout(function(){scrollTo(0,0)},0);window.addEventListener('load',function(){setTimeout(function(){scrollTo(0,0)},60)})}"
            "%s</script></body></html>") % (title, CSS, title, sub, body, d, js)


ONTO_JS = r"""
var N=D.nodes,E=D.edges,byId={},types=[],col={};N.forEach(function(n,i){byId[n.id]=n;if(types.indexOf(n.type)<0)types.push(n.type)});
types.forEach(function(t,i){col[t]=D.colors[i%D.colors.length]});var off={};if(N.length>300)off['column']=true;
function chips(id,cb){var h=types.map(function(t){return "<span class='chip"+(off[t]?" off":"")+"' data-t='"+esc(t)+"' style='border-color:"+col[t]+"'>"+esc(t)+"</span>"}).join('');
var el=document.getElementById(id);el.innerHTML=h;el.querySelectorAll('.chip').forEach(function(c){c.onclick=function(){off[c.dataset.t]=!off[c.dataset.t];c.classList.toggle('off');cb()}})}
function edgeRows(list){return '<table><tr><th>From</th><th>Link</th><th>To</th><th>Source</th></tr>'+list.map(function(e){return '<tr><td>'+esc(e.from)+'</td><td>'+esc(e.rel)+'</td><td>'+esc(e.to)+'</td><td><code>'+esc(e.source)+'</code></td></tr>'}).join('')+'</table>'}
// animated force graph
var cv,cx,P=[],L=[],sel=null,hot={},t0=0,q='';function setup(){cv=document.getElementById('cv');cx=cv.getContext('2d');var W=cv.width=cv.clientWidth*2,H=cv.height=1280;
var keep=N.filter(function(n){return !off[n.type]&&(!q||n.id.toLowerCase().indexOf(q)>=0||E.some(function(e){return (e.from==n.id&&e.to.toLowerCase().indexOf(q)>=0)||(e.to==n.id&&e.from.toLowerCase().indexOf(q)>=0)}))}).slice(0,600);
var ix={};P=keep.map(function(n,i){ix[n.id]=i;var a=i*2.4;return {n:n,x:W/2+Math.cos(a)*(80+i*1.5),y:H/2+Math.sin(a)*(80+i*1.5),vx:0,vy:0}});
L=E.filter(function(e){return e.from in ix&&e.to in ix}).map(function(e){return {a:P[ix[e.from]],b:P[ix[e.to]],e:e}});
document.getElementById('gcount').textContent=P.length+' shown of '+N.length+' things, '+L.length+' links'+(keep.length>=600?' (first 600; filter or search to narrow)':'')}
function step(){var W=cv.width,H=cv.height,k=P.length>200?0.4:1;for(var i=0;i<P.length;i++){var p=P[i];for(var j=i+1;j<P.length;j++){var o=P[j],dx=p.x-o.x,dy=p.y-o.y,d2=dx*dx+dy*dy+0.01;if(d2>90000)continue;var f=1800*k/d2;p.vx+=dx*f;p.vy+=dy*f;o.vx-=dx*f;o.vy-=dy*f}
p.vx+=(W/2-p.x)*0.0015;p.vy+=(H/2-p.y)*0.0015}L.forEach(function(l){var dx=l.b.x-l.a.x,dy=l.b.y-l.a.y,d=Math.sqrt(dx*dx+dy*dy)+0.01,f=(d-110)*0.004;l.a.vx+=dx/d*f*d*0.05;l.a.vy+=dy/d*f*d*0.05;l.b.vx-=dx/d*f*d*0.05;l.b.vy-=dy/d*f*d*0.05});
P.forEach(function(p){p.vx*=0.82;p.vy*=0.82;p.x=Math.max(20,Math.min(W-320,p.x+p.vx));p.y=Math.max(20,Math.min(H-20,p.y+p.vy))})}
function draw(ts){if(!cv||document.getElementById('graph').hidden){requestAnimationFrame(draw);return}step();var ph=(ts||0)/1000;cx.clearRect(0,0,cv.width,cv.height);
L.forEach(function(l){var h=hot[l.e.from+'>'+l.e.to];cx.strokeStyle=h?'#7c3aed':'rgba(91,33,182,.18)';cx.lineWidth=h?4:1.5;cx.beginPath();cx.moveTo(l.a.x,l.a.y);cx.lineTo(l.b.x,l.b.y);cx.stroke();
var u=((ph*0.35+(l.a.x%7)/7)%1);cx.fillStyle=h?'#7c3aed':'rgba(124,58,237,.55)';cx.beginPath();cx.arc(l.a.x+(l.b.x-l.a.x)*u,l.a.y+(l.b.y-l.a.y)*u,h?6:3,0,7);cx.fill()});
P.forEach(function(p){var s=sel==p.n.id;cx.fillStyle=col[p.n.type];cx.beginPath();cx.arc(p.x,p.y,s?14:9,0,7);cx.fill();if(s||P.length<120||hot[p.n.id]){cx.fillStyle='#1f1b2e';cx.font='22px Segoe UI';cx.fillText(p.n.name.slice(0,40),p.x+14,p.y+6)}});requestAnimationFrame(draw)}
function pick(id){sel=id;hot={};var n=byId[id];if(!n)return;var ins=E.filter(function(e){return e.to==id}),outs=E.filter(function(e){return e.from==id});
var m=D.matrix[id];if(m)m.chain.forEach(function(c){c.via.forEach(function(s){hot[s.from+'>'+s.to]=1;hot[s.to]=1;hot[s.from]=1})});
document.getElementById('side').innerHTML='<b>'+esc(n.name)+'</b> <span class=muted>'+esc(n.type)+'</span>'+(m?'<p>Changing it moves '+m.chain.length+' things (highlighted). <a href="#impact" onclick="showImpact(\''+esc(id)+'\')">See the chain</a></p>':'')+'<h4>Links out</h4>'+edgeRows(outs)+'<h4>Links in</h4>'+edgeRows(ins)}
function hit(ev){var r=cv.getBoundingClientRect(),x=(ev.clientX-r.left)*cv.width/r.width,y=(ev.clientY-r.top)*cv.height/r.height,b=null,bd=900;P.forEach(function(p){var d=(p.x-x)*(p.x-x)+(p.y-y)*(p.y-y);if(d<bd){bd=d;b=p}});if(b)pick(b.n.id)}
// flows: follow sourced links screen -> endpoint -> ... -> table -> job
function flows(){var out={},rin={};E.forEach(function(e){(out[e.from]=out[e.from]||[]).push(e);(rin[e.to]=rin[e.to]||[]).push(e)});
function nxt(id){var n=byId[id];if(n&&(n.type=='table'||n.type=='view'))return (rin[id]||[]).filter(function(e){return e.rel=='reads'&&byId[e.from]&&byId[e.from].type=='job'}).map(function(e){return {e:e,to:e.from}});
return (out[id]||[]).filter(function(e){return byId[e.to]&&byId[e.to].type!='column'&&byId[e.to].type!='test'}).map(function(e){return {e:e,to:e.to}})}
var starts=N.filter(function(n){return n.type=='screen'||n.type=='component'}).map(function(n){return n.id});if(!starts.length)starts=N.filter(function(n){return n.type=='endpoint'}).map(function(n){return n.id});
var res=[];function dfs(id,ids,path){var ns=nxt(id).filter(function(x){return ids.indexOf(x.to)<0});if(!ns.length||ids.length>7){if(path.length)res.push({ids:ids,path:path});return}ns.forEach(function(x){dfs(x.to,ids.concat([x.to]),path.concat([x.e]))})}
starts.forEach(function(s){dfs(s,[s],[])});function score(r){var t=byId[r.ids[r.ids.length-1]].type;return (t=='table'||t=='job'?100:0)+r.ids.length}
res.sort(function(a,b){return score(b)-score(a)});return res.slice(0,40)}
var FL=[];function drawFlow(i){var f=FL[i];if(!f)return;var p=f.path,ids=f.ids,w=170,h=110,W=ids.length*w+40;
var s="<svg class=flow viewBox='0 0 "+W+" "+h+"'>";p.forEach(function(e,k){s+="<line class=flowline x1="+(20+k*w+140)+" y1=50 x2="+(20+(k+1)*w)+" y2=50 stroke='#7c3aed' stroke-width=3 />"});
ids.forEach(function(id,k){var n=byId[id];s+="<rect x="+(20+k*w)+" y=25 width=140 height=50 rx=10 fill='"+col[n.type]+"' opacity=.9 /><text x="+(90+k*w)+" y=47 fill='#fff' font-size=12 text-anchor=middle>"+esc(n.type)+"</text><text x="+(90+k*w)+" y=64 fill='#fff' font-size=11 text-anchor=middle>"+esc(n.name.slice(0,22))+"</text>"});
document.getElementById('flowsvg').innerHTML=s+"</svg>";document.getElementById('flowsrc').innerHTML=edgeRows(p)}
var playT=null;function play(){var i=0;clearInterval(playT);drawFlow(0);playT=setInterval(function(){i=(i+1)%FL.length;document.getElementById('flowpick').value=i;drawFlow(i)},3500)}
// lineage: jobs between the tables they read and write
function lineage(){var J=N.filter(function(n){return n.type=='job'});if(!J.length){document.getElementById('linsvg').innerHTML='<p class=muted>No job links in the KB yet.</p>';return}
var R=E.filter(function(e){return byId[e.from]&&byId[e.from].type=='job'&&(e.rel=='reads'||e.rel=='writes')}),ins=[],outs=[];R.forEach(function(e){var a=e.rel=='reads'?ins:outs;if(a.indexOf(e.to)<0)a.push(e.to)});
var rowH=34,H=Math.max(J.length,ins.length,outs.length)*rowH+40,W=1000,pos={};ins.forEach(function(t,i){pos['i'+t]=[150,30+i*rowH]});J.forEach(function(j,i){pos[j.id]=[500,30+i*rowH]});outs.forEach(function(t,i){pos['o'+t]=[850,30+i*rowH]});
var s="<svg class=flow viewBox='0 0 "+W+" "+H+"'><text x=150 y=16 text-anchor=middle font-size=12 fill='#6b6480'>Tables read</text><text x=500 y=16 text-anchor=middle font-size=12 fill='#6b6480'>Jobs</text><text x=850 y=16 text-anchor=middle font-size=12 fill='#6b6480'>Tables written</text>";
R.forEach(function(e){var a=e.rel=='reads'?pos['i'+e.to]:pos[e.from],b=e.rel=='reads'?pos[e.from]:pos['o'+e.to];s+="<path class=flowline d='M"+(a[0]+70)+","+a[1]+" C"+(a[0]+200)+","+a[1]+" "+(b[0]-200)+","+b[1]+" "+(b[0]-70)+","+b[1]+"' stroke='#7c3aed' fill=none stroke-width=2><title>"+esc(e.source)+"</title></path>"});
function box(p,label,c){return "<rect x="+(p[0]-70)+" y="+(p[1]-12)+" width=140 height=24 rx=6 fill='"+c+"' /><text x="+p[0]+" y="+(p[1]+4)+" fill='#fff' font-size=11 text-anchor=middle>"+esc(label.slice(0,24))+"</text>"}
ins.forEach(function(t){s+=box(pos['i'+t],byId[t]?byId[t].name:t,'#0ea5e9')});J.forEach(function(j){s+=box(pos[j.id],j.name,'#7c3aed')});outs.forEach(function(t){s+=box(pos['o'+t],byId[t]?byId[t].name:t,'#10b981')});
document.getElementById('linsvg').innerHTML=s+'</svg><p class=muted>Hover a line to see its source.</p>'+edgeRows(R)}
function typeTable(id,ts){var rows=N.filter(function(n){return ts.indexOf(n.type)>=0});document.getElementById(id).innerHTML=rows.length?rows.map(function(n){return '<h4>'+esc(n.name)+' <span class=muted>'+esc(n.type)+'</span></h4>'+edgeRows(E.filter(function(e){return e.from==n.id||e.to==n.id}))}).join(''):'<p class=muted>None in the KB yet.</p>'}
function showImpact(id){var b=document.querySelector('button[data-t=impact]');if(b)b.click();document.getElementById('iq').value=byId[id]?byId[id].name:id;impact()}
function impact(){var q=document.getElementById('iq').value.toLowerCase(),ks=Object.keys(D.matrix).filter(function(k){return !q||k.toLowerCase().indexOf(q)>=0}).slice(0,30);
document.getElementById('ires').innerHTML=ks.map(function(k){var m=D.matrix[k];return '<h4>If '+esc(m.type)+' '+esc(m.name)+' changes</h4><p>'+Object.keys(m.moves_by_type).map(function(t){return '<b>'+m.moves_by_type[t].length+'</b> '+esc(t)}).join(', ')+'</p><table><tr><th>Moves</th><th>Because (each step with its source)</th></tr>'+m.chain.map(function(c){return '<tr><td>'+esc(c.moves)+'</td><td>'+c.via.map(function(s){return esc(s.from)+' <i>'+esc(s.rel)+'</i> '+esc(s.to)+' <code>'+esc(s.source)+'</code>'}).join('<br>')+'</td></tr>'}).join('')+'</table>'}).join('')||'<p class=muted>No impact entries match.</p>'}
window.onTab=function(t){if(t=='graph'&&!cv){setup();cv.onclick=hit;requestAnimationFrame(draw)}};
document.addEventListener('DOMContentLoaded',function(){});tabs();
chips('gchips',function(){setup()});document.getElementById('gq').oninput=function(){q=this.value.toLowerCase();setup()};
FL=flows();document.getElementById('flowpick').innerHTML=FL.map(function(p,i){return '<option value='+i+'>'+p.ids.map(function(x){return esc(byId[x].name)}).join(' → ')+'</option>'}).join('');
document.getElementById('flowpick').onchange=function(){clearInterval(playT);drawFlow(+this.value)};if(FL.length)drawFlow(0);else document.getElementById('flowsvg').innerHTML='<p class=muted>No screen or endpoint links in the KB yet.</p>';
lineage();typeTable('bo',['business object','entity']);typeTable('rules',['rule','state']);typeTable('proc',['process','step']);typeTable('apps',['screen','component','endpoint','class']);
document.getElementById('rels').innerHTML='<table><tr><th>Relation</th><th>Count</th></tr>'+Object.keys(D.rels).sort().map(function(k){return '<tr><td>'+esc(k)+'</td><td>'+D.rels[k]+'</td></tr>'}).join('')+'</table>';
document.getElementById('tables').innerHTML=D.tables.length?'<input id=tq placeholder="Search a table or column"><div id=tres></div>':'<p class=muted>No table registry yet (catalogue queries not saved).</p>';
function tdraw(){var q=(document.getElementById('tq')||{}).value||'';q=q.toLowerCase();document.getElementById('tres').innerHTML='<table><tr><th>Table</th><th>Type</th><th>Columns</th><th>Source</th></tr>'+D.tables.filter(function(t){return !q||(t.key||t.schema+'.'+t.name).toLowerCase().indexOf(q)>=0||t.columns.some(function(c){return c.name.toLowerCase().indexOf(q)>=0})}).slice(0,300).map(function(t){return '<tr><td>'+esc(t.key||t.schema+'.'+t.name)+'</td><td>'+esc(t.type)+'</td><td>'+t.columns.map(function(c){return esc(c.name)+' <span class=muted>'+esc(c.data_type)+'</span>'}).join(', ')+'</td><td><code>'+esc(t.source)+'</code></td></tr>'}).join('')+'</table>'}
if(D.tables.length){document.getElementById('tq').oninput=tdraw;tdraw()}
document.getElementById('iq').oninput=impact;impact();
var cov=D.coverage;document.getElementById('qa').innerHTML=(cov.test_sources_read?'':'<p class=muted>No test repo links in the KB yet, so nothing shows as tested.</p>')+Object.keys(cov.items||{}).map(function(t){var it=cov.items[t],s=cov.summary[t];return '<h4>'+esc(t)+': '+s.tested+' of '+s.total+' have tests</h4><table><tr><th>Name</th><th>Tested by</th></tr>'+it.map(function(x){return '<tr><td>'+esc(x.name)+'</td><td>'+(x.tested_by.length?x.tested_by.map(function(b){return esc(b.test)+(b.direct?' <code>'+esc(b.source)+'</code>':' <span class=muted>(through linked items)</span>')}).join('<br>'):'<span class=p1>none found</span>')+'</td></tr>'}).join('')+'</table>'}).join('');
document.getElementById('openq').innerHTML='<h4>Open questions ('+D.questions.length+')</h4><table><tr><th>Id</th><th>Priority</th><th>Who answers</th><th>Question</th><th>Status</th></tr>'+D.questions.map(function(x){return '<tr><td>'+esc(x.id)+'</td><td class='+esc(String(x.priority).toLowerCase())+'>'+esc(x.priority)+'</td><td>'+esc(x.answer_role)+'</td><td>'+esc(x.question)+'</td><td>'+esc(x.status)+'</td></tr>'}).join('')+'</table><p><a href="../_QUESTIONS/VALIDATE_KB.html">Open VALIDATE_KB</a></p><h4>Links left out because their source did not check out ('+D.rejected.length+')</h4><table><tr><th>Where</th><th>Why</th></tr>'+D.rejected.map(function(r){return '<tr><td>'+esc(r.at)+'</td><td>'+esc(r.reason)+'</td></tr>'}).join('')+'</table>';
var ov=document.getElementById('ovtypes');ov.innerHTML=types.map(function(t){return "<div class=card style='border-left:5px solid "+col[t]+"'><b>"+N.filter(function(n){return n.type==t}).length+"</b>"+esc(t)+"</div>"}).join('');
"""

GROUPS = [
    ("overview", "Overview", [
        ("overview", "Overview"),
    ]),
    ("explore", "Explore", [
        ("graph", "Graph"),
        ("flows", "Play the main flows"),
        ("impact", "Impact paths"),
    ]),
    ("domain", "Domain", [
        ("sec-bo", "Business objects"),
        ("sec-rels", "Relationships"),
        ("sec-rules", "States and rules"),
        ("sec-proc", "Processes"),
    ]),
    ("data", "Data and code", [
        ("sec-tables", "Tables and columns"),
        ("lineage", "Jobs and lineage"),
        ("sec-apps", "Screens and APIs"),
    ]),
    ("quality", "Quality", [
        ("sec-qa", "QA coverage"),
        ("sec-openq", "Open questions and sources"),
    ]),
]


def ontology_body(nodes, edges, questions, rejected):
    grp_html = ["<nav class='nav-groups' role='tablist' aria-label='Navigation groups'>"]
    sub_html = ["<div class='nav-subtabs-wrap'>"]
    for g_id, g_label, tabs in GROUPS:
        grp_html.append("<button class='grp-btn' data-grp='%s' role='tab' aria-selected='false' aria-controls='sub-%s'>%s</button>" % (g_id, g_id, g_label))
        single_cls = " single" if len(tabs) == 1 and tabs[0][0] == g_id else ""
        sub_html.append("<nav class='sub-tabs%s' id='sub-%s' data-grp='%s' role='tablist' aria-label='%s tabs' hidden>" % (single_cls, g_id, g_id, g_label))
        for t_id, t_label in tabs:
            sub_html.append("<button class='tab-btn' data-t='%s' data-grp='%s' role='tab' aria-selected='false' aria-controls='%s'>%s</button>" % (t_id, g_id, t_id, t_label))
        sub_html.append("</nav>")
    grp_html.append("</nav>")
    sub_html.append("</div>")

    nav = "".join(grp_html) + "".join(sub_html)
    sec = {
        "overview": "<div class=cards><div class=card><b>%d</b>things</div><div class=card><b>%d</b>sourced links</div>"
                    "<div class=card><b>%d</b>open questions</div><div class=card><b>%d</b>links left out</div></div>"
                    "<h3>Things by type</h3><div class=cards id=ovtypes></div>" % (len(nodes), len(edges), len(questions), len(rejected)),
        "flows": "<p>Each flow follows sourced links from a screen (or an endpoint) to the data behind it. "
                 "<select id=flowpick></select> <button onclick='play()'>Play all</button></p><div id=flowsvg></div><div id=flowsrc></div>",
        "graph": "<p><input id=gq placeholder='Search a thing'> <span id=gcount class=muted></span></p><div id=gchips class=chips></div>"
                 "<div class=wrap><canvas id=cv height=640></canvas><div id=side><p class=muted>Click a dot to see its links and their sources, "
                 "and to light up everything that moves when it changes.</p></div></div>",
        "lineage": "<div id=linsvg></div>",
        "impact": "<p><input id=iq placeholder='Table, column, endpoint, screen or job' size=50></p><div id=ires></div>",
    }
    all_tabs = [t for _, _, ts in GROUPS for t in ts]
    inner_ids = {
        "sec-bo": "bo", "sec-rels": "rels", "sec-rules": "rules", "sec-proc": "proc",
        "sec-tables": "tables", "sec-apps": "apps", "sec-qa": "qa", "sec-openq": "openq",
    }
    sections = []
    for t_id, _ in all_tabs:
        if t_id in sec:
            sections.append("<section id='%s' role='tabpanel' aria-labelledby='%s' hidden>%s</section>" % (t_id, t_id, sec[t_id]))
        else:
            in_id = inner_ids.get(t_id, t_id)
            sections.append("<section id='%s' role='tabpanel' aria-labelledby='%s' hidden><div id='%s'></div></section>" % (t_id, t_id, in_id))
    return nav + "".join(sections)


DRIFT_JS = r"""
function dd(){var q=document.getElementById('dq').value.toLowerCase(),r=D.diffs.filter(function(x){return !q||JSON.stringify(x).toLowerCase().indexOf(q)>=0});
document.getElementById('dt').innerHTML=r.length?'<table><tr><th>Table</th><th>Column</th><th>Difference</th><th>Environment</th><th>Sources</th></tr>'+r.map(function(x){return '<tr><td>'+esc(x.table)+'</td><td>'+esc(x.column||'')+'</td><td>'+esc(x.change)+'</td><td>'+esc(x.env)+'</td><td><code>'+esc(x.sources.join(' '))+'</code></td></tr>'}).join('')+'</table>':'<p class=muted>'+(D.diffs.length?'No match.':'No differences, or only one environment has a saved catalogue.')+'</p>'}
document.getElementById('dq').oninput=dd;dd();
"""


def main(argv=None):
    import html as h
    argv = sys.argv[1:] if argv is None else argv
    kb = argv[0]
    out = os.path.join(kb, "VISUALIZATION")
    os.makedirs(out, exist_ok=True)
    cl = os.path.join(kb, "CROSS-LAYER")
    g, onto = load(os.path.join(cl, "LINK_GRAPH.yaml")), load(os.path.join(cl, "ONTOLOGY.yaml"))
    mx, cov = load(os.path.join(cl, "IMPACT_MATRIX.yaml")), load(os.path.join(cl, "QA_COVERAGE.yaml"))
    settings = load(os.path.join(kb, ".metis", "kb-profile.yaml"))
    reg = load(os.path.join(gen_registry.db_docs(kb, settings), "DB_TABLE_REGISTRY.yaml"))
    qs = [q for q in (load(os.path.join(kb, "_QUESTIONS", "VALIDATE_KB.yaml")).get("questions") or [])
          if q.get("status") not in ("answered", "closed")]
    nodes, edges, rejected = g.get("nodes") or [], g.get("edges") or [], g.get("rejected") or []
    product = (settings.get("product") or {}).get("name") or "Knowledge base"
    built = "Built %s" % datetime.date.today().isoformat()
    data = {"nodes": nodes, "edges": edges, "rejected": rejected, "rels": onto.get("relations") or {}, "colors": COLORS,
            "matrix": {k: {"type": v["type"], "name": v["name"], "moves_by_type": v["moves_by_type"], "chain": v["chain"]}
                       for k, v in (mx.get("entries") or {}).items()},
            "coverage": {"test_sources_read": cov.get("test_sources_read"), "summary": cov.get("summary") or {}, "items": cov.get("items") or {}},
            "tables": reg.get("tables") or [], "questions": [{k: q.get(k) for k in ("id", "priority", "answer_role", "question", "status")} for q in qs]}
    body = ontology_body(nodes, edges, qs, rejected)
    files = {}
    files["ONTOLOGY.html"] = page("Ontology and link graph", "%s &middot; %s" % (product, built), body, data, ONTO_JS)
    # ERD
    tabs_ = {t.get("key") or "%s.%s" % (t["schema"], t["name"]): t for t in data["tables"]}
    rels = [e for e in edges if e["rel"] in ("references", "joins") and e["from"].startswith("column:") and e["to"].startswith("column:")]
    files["ERD.html"] = page("Entity relationship diagram", "%s &middot; %s" % (product, built),
                             "<p>Relationships come only from declared keys and joins the code runs. Hover a line for its source.</p><div id=erd></div><div id=erdsrc></div>",
                             {"tables": tabs_, "rels": rels}, ERD_JS)
    man = kb_manifest.collect(kb, git=False)
    files["KB_MANIFEST.html"] = page("KB manifest", "%s &middot; %s" % (product, built),
                                     "<p><input id=mq placeholder='Search a file'> <span id=mc class=muted></span></p><div id=mt></div>", {"files": man}, MAN_JS)
    rep = verify_kb.Checker(kb).run()
    pri = {}
    for q in qs:
        pri[q.get("priority")] = pri.get(q.get("priority"), 0) + 1
    role = {}
    for q in qs:
        role[q.get("answer_role")] = role.get(q.get("answer_role"), 0) + 1
    health = ("<div class=cards><div class=card><b>%d</b>documents checked</div><div class=card><b>%d</b>source tags</div>"
              "<div class=card><b>%d</b>source problems</div><div class=card><b>%d</b>open questions</div></div>"
              "<h3>Open questions by priority</h3>%s<h3>Open questions by who answers</h3>%s<h3>Source problems</h3>%s"
              "<h3>Links left out of the graph</h3>%s") % (
        rep["files"], rep["tags"], len(rep["problems"]), len(qs), kv(pri), kv(role),
        rows(rep["problems"], ("file", "line", "problem")) if rep["problems"] else "<p>None.</p>",
        rows(rejected, ("at", "reason")) if rejected else "<p>None.</p>")
    files["KB_HEALTH.html"] = page("KB health report", "%s &middot; %s" % (product, built), health, {})
    stack = load(os.path.join(kb, ".metis", "stack.yaml"))
    det = load(os.path.join(kb, ".metis", "DETECTED_STACK.yaml"))
    items = stack.get("items") or det.get("items") or []
    state = ("Approved by %s on %s" % (h.escape(str(stack.get("approved_by"))), h.escape(str(stack.get("approved_on"))))
             if stack else "Detected, not approved yet" if det else "Not detected yet")
    srows = [{"area": i.get("category"), "what": i.get("name") + (" = %s" % i["value"] if i.get("value") else ""),
              "database type": i.get("engine", ""), "repo": i.get("repo"), "environment": i.get("env", ""),
              "source": "; ".join(i.get("sources") or [])} for i in items]
    uns = [{"setting": u.get("key"), "repo": u.get("repo"), "environment": u.get("env") or "", "source": u.get("source")}
           for u in det.get("unresolved") or []]
    files["TECH_STACK.html"] = page("Tech stack", "%s &middot; %s" % (product, built),
                                    "<p><b>%s</b>. Every row comes from a file and line in the repos, or from a VALIDATE_KB answer.</p>%s"
                                    "<h3>Set outside the repos (asked in VALIDATE_KB)</h3>%s" % (
                                        state, rows(srows, ("area", "what", "database type", "repo", "environment", "source")) if srows else "<p>None.</p>",
                                        rows(uns, ("setting", "repo", "environment", "source")) if uns else "<p>None.</p>"), {})
    dr = load(os.path.join(gen_registry.db_docs(kb, settings), "DB_DRIFT.yaml"))
    diffs = dr.get("differences") or []
    dbs = reg.get("databases") or []
    drift = ("<p>Reference environment: <b>%s</b>. Environments compared: %s. Tables are matched by database label, schema and "
             "table name, so the same database can have a different name in each environment.</p>"
             "<h3>Databases in the reference environment</h3>%s<h3>Differences</h3>"
             "<p><input id=dq placeholder='Search a table, column or environment'></p><div id=dt></div>") % (
        h.escape(str(dr.get("reference_environment") or reg.get("reference_environment") or "not set")),
        h.escape(", ".join(dr.get("environments") or [])) or "none",
        rows([dict(d, schemas=", ".join(d.get("schemas") or [])) for d in dbs], ("label", "database", "engine", "schemas")) if dbs else "<p>None.</p>")
    files["DB_DRIFT.html"] = page("Database drift between environments", "%s &middot; %s" % (product, built), drift,
                                  {"diffs": diffs}, DRIFT_JS)
    cards = [("ONTOLOGY.html#overview", "Ontology and link graph", "%d things, %d sourced links, animated" % (len(nodes), len(edges))),
             ("ONTOLOGY.html#flows", "Main flows", "screen to data, step by step"),
             ("ONTOLOGY.html#lineage", "Jobs and lineage", "tables each job reads and writes"),
             ("ONTOLOGY.html#impact", "Impact paths", "%d things with a change chain" % len(data["matrix"])),
             ("ONTOLOGY.html#sec-qa", "QA coverage", "what has tests"), ("ERD.html", "ERD", "%d relationships" % len(rels)),
             ("KB_HEALTH.html", "KB health report", "%d source problems, %d open questions" % (len(rep["problems"]), len(qs))),
             ("TECH_STACK.html", "Tech stack", "%d items, %s" % (len(items), state.split(" on ")[0].lower())),
             ("DB_DRIFT.html", "Database drift", "%d differences across %d environments" % (len(diffs), len(dr.get("environments") or []))),
             ("KB_MANIFEST.html", "KB manifest", "%d files" % len(man)), ("../_QUESTIONS/VALIDATE_KB.html", "VALIDATE_KB", "answer the open questions")]
    files["index.html"] = page("Visualizations", "%s &middot; %s" % (product, built),
                               "<div class=cards>" + "".join("<a class=card href='%s'><b style='font-size:16px'>%s</b><span class=muted>%s</span></a>" % c for c in cards) + "</div>", {})
    for name, text in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    print("%d pages -> %s" % (len(files), out))
    return 0


def kv(d):
    return "<table>" + "".join("<tr><td>%s</td><td>%s</td></tr>" % (k, v) for k, v in sorted(d.items(), key=str)) + "</table>" if d else "<p>None.</p>"


def rows(lst, keys):
    import html as h
    return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % k for k in keys),
                                              "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % h.escape(str(r.get(k, ""))) for k in keys) for r in lst))


ERD_JS = r"""
var T=D.tables,R=D.rels,used={};R.forEach(function(r){used[r.from.slice(7).replace(/\.[^.]+$/,'')]=1;used[r.to.slice(7).replace(/\.[^.]+$/,'')]=1});
var names=Object.keys(used).filter(function(k){return T[k]}).sort(),cols=Math.max(1,Math.ceil(Math.sqrt(names.length))),bw=230,pos={},hmax=0;
names.forEach(function(k,i){var t=T[k],keys=R.filter(function(r){return r.from.indexOf('column:'+k+'.')==0||r.to.indexOf('column:'+k+'.')==0}).map(function(r){return r.from.indexOf('column:'+k+'.')==0?r.from.slice(8+k.length):r.to.slice(8+k.length)});
var h=30+keys.length*18+10;pos[k]={x:20+(i%cols)*(bw+80),y:20+Math.floor(i/cols)*220,h:h,keys:keys.filter(function(v,j,a){return a.indexOf(v)==j})};hmax=Math.max(hmax,pos[k].y+h)});
var W=20+cols*(bw+80),s="<svg class=flow viewBox='0 0 "+W+" "+(hmax+30)+"'>";
R.forEach(function(r,ri){var a=r.from.slice(7).replace(/\.[^.]+$/,''),b=r.to.slice(7).replace(/\.[^.]+$/,'');if(!pos[a]||!pos[b])return;var p=pos[a],q=pos[b],ca=r.from.slice(8+a.length),cb=r.to.slice(8+b.length);
var ya=p.y+42+p.keys.indexOf(ca)*18+(r.rel=='joins'?4:-4),yb=q.y+42+q.keys.indexOf(cb)*18+(r.rel=='joins'?4:-4),right=q.x>=p.x,xa=right?p.x+bw:p.x,xb=right?q.x:q.x+bw,d=right?60:-60;if(a==b){xb=xa;d=80}
s+="<path class=flowline d='M"+xa+","+ya+" C"+(xa+d)+","+ya+" "+(xb-d)+","+yb+" "+xb+","+yb+"' stroke='"+(r.rel=='references'?'#7c3aed':'#0ea5e9')+"' fill=none stroke-width=3><title>"+esc(r.rel+': '+r.source)+"</title></path>"});
names.forEach(function(k){var p=pos[k];s+="<rect x="+p.x+" y="+p.y+" width="+bw+" height="+p.h+" rx=8 fill='#fff' stroke='#7c3aed'/><rect x="+p.x+" y="+p.y+" width="+bw+" height=26 rx=8 fill='#5b21b6'/><text x="+(p.x+8)+" y="+(p.y+18)+" fill='#fff' font-size=12>"+esc(k.slice(0,32))+"</text>";
p.keys.forEach(function(c,i){s+="<text x="+(p.x+8)+" y="+(p.y+46+i*18)+" font-size=12>"+esc(c)+"</text>"})});
document.getElementById('erd').innerHTML=names.length?s+'</svg><p class=muted>Purple: declared key. Blue: join the code runs.</p>':'<p class=muted>No declared keys or sourced joins in the KB yet.</p>';
document.getElementById('erdsrc').innerHTML='<table><tr><th>From</th><th>Kind</th><th>To</th><th>Source</th></tr>'+R.map(function(r){return '<tr><td>'+esc(r.from.slice(7))+'</td><td>'+esc(r.rel)+'</td><td>'+esc(r.to.slice(7))+'</td><td><code>'+esc(r.source)+'</code></td></tr>'}).join('')+'</table>';
"""

MAN_JS = r"""
function m(){var q=document.getElementById('mq').value.toLowerCase(),f=D.files.filter(function(x){return !q||x.path.toLowerCase().indexOf(q)>=0});document.getElementById('mc').textContent=f.length+' of '+D.files.length+' files';
document.getElementById('mt').innerHTML='<table><tr><th>File</th><th>Area</th><th>Source tags</th><th>Waiting on</th><th>Generated by</th><th>Bytes</th></tr>'+f.map(function(x){return '<tr><td><a href="../'+esc(x.path)+'">'+esc(x.path)+'</a></td><td>'+esc(x.kind)+'</td><td>'+(x.source_tags==null?'':x.source_tags)+'</td><td>'+esc((x.open_questions||[]).join(', '))+'</td><td>'+esc(x.generated_by||'')+'</td><td>'+x.bytes+'</td></tr>'}).join('')+'</table>'}
document.getElementById('mq').oninput=m;m();
"""

if __name__ == "__main__":
    sys.exit(main())
