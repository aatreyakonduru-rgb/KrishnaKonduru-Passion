"""Review pages for Product Owners, BSAs and Scrum Masters: one look, one flow, used by Devin Cloud and Argus.

Each page is a single offline HTML file built on artifact_kit. Pages never call Jira or Devin
themselves: every Send / Approve button produces a short text block that is pasted back into the
Devin chat, and Devin previews the Jira change and waits for "approved" before anything is written
(see backlog_cli.py). Argus opens the same files in its artefact panel.

  backlog     the dashboard's Backlog grid: list on the left, the selected ticket in the middle,
              Groom, Edit, Point / poker, Move, Clone, Add note and New ticket
  new-ticket  business intake: source, business questions, draft epic/stories/sub-tasks with the
              rule-book checks, approve
  intake      guided intake questions, one at a time, with document attachments
  epics       epics drafted from a roadmap sheet: Edit, Upload document, Approve
  report      a tabbed report (release notes, migration status): Edit, Download PDF, Approve

    python3 review_pages.py <page> --data page.json --out page.html
"""
import argparse
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import artifact_kit  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "console"))
import backlog as bl  # noqa: E402

FOOTNOTE = "Acme Claims (APM0000000). Argus, Agentic SDLC Framework."
BLOCK = "SDLC-DASHBOARD-BACKLOG"
esc = html.escape

BASE_CSS = """
.sample{display:inline-block;font-size:.75rem;padding:.1rem .5rem;border-radius:999px;background:#fff4d6;color:#7a5600;margin-left:.5rem;vertical-align:middle}
.steps-bar{display:flex;gap:.5rem;margin:1rem 0 1.25rem;flex-wrap:wrap}
.steps-bar span{flex:1;min-width:140px;padding:.55rem .8rem;border-radius:8px;background:var(--a-surface-2,#eef1f7);font-size:.85rem;opacity:.75}
.steps-bar span.on{background:#e6e0ff;opacity:1;font-weight:600;color:#3d1a9e}
.steps-bar b{display:inline-block;width:1.4rem;height:1.4rem;border-radius:50%;background:#5b2bd6;color:#fff;text-align:center;line-height:1.4rem;font-size:.75rem;margin-right:.4rem}
.lead{margin:.25rem 0 1rem;opacity:.85}
.actionbar{position:sticky;bottom:0;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;padding:.8rem 1rem;margin-top:1.25rem;border-radius:10px;background:var(--a-surface,#fff);box-shadow:0 -2px 12px rgba(30,20,80,.12);z-index:5}
.actionbar .hint{margin-left:auto;font-size:.8rem;opacity:.7}
.a-btn.approve{background:#1f8a5b;border-color:#1f8a5b;color:#fff}
.a-btn.approve[aria-pressed=true]{background:#e7f6ee;color:#1f6b47}
body.editing [data-edit]{outline:2px dashed #8b6cf0;outline-offset:2px;border-radius:4px;background:rgba(139,108,240,.06)}
body.editing .edit-flag{display:inline-block}
.edit-flag{display:none;font-size:.75rem;color:#5b2bd6;margin-left:.5rem}
.send{display:none;margin-top:1rem}
.send.show{display:block}
.send textarea{width:100%;min-height:9rem;font-family:ui-monospace,monospace;font-size:.8rem}
.files{font-size:.8rem;margin:.4rem 0 0;padding-left:1.1rem}
.chip-ok{background:#e7f6ee;color:#1f6b47}.chip-warn{background:#fff4d6;color:#7a5600}.chip-new{background:#e6e0ff;color:#3d1a9e}.chip-no{background:#fde8e8;color:#9b1c1c}
.pill{display:inline-block;font-size:.75rem;padding:.12rem .55rem;border-radius:999px;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:1rem}
.card{border:1px solid var(--a-border,#dde2ee);border-radius:10px;padding:1rem 1.1rem;background:var(--a-surface,#fff)}
.card h3{margin:0 0 .35rem;font-size:1.05rem}
.card dl{display:grid;grid-template-columns:8.5rem 1fr;gap:.35rem .75rem;margin:.6rem 0;font-size:.9rem}
.card dt{opacity:.65}.card dd{margin:0}
.card .q{background:#fff9ea;border-left:3px solid #e0a800;padding:.5rem .7rem;border-radius:6px;margin:.5rem 0;font-size:.9rem}
.card .q textarea{width:100%;min-height:2.6rem;margin-top:.35rem}
.card .row{display:flex;gap:.5rem;margin-top:.75rem;flex-wrap:wrap}
.card.approved{border-color:#1f8a5b;box-shadow:0 0 0 2px rgba(31,138,91,.15)}
.chat{max-width:860px;margin:0 auto}
.bubble{padding:.8rem 1rem;border-radius:14px;margin:.5rem 0;max-width:85%;line-height:1.45}
.bubble.devin{background:#efeaff;border-top-left-radius:4px}
.bubble.me{background:#e8f2ff;margin-left:auto;border-top-right-radius:4px}
.bubble small{display:block;opacity:.6;font-size:.72rem;margin-bottom:.2rem}
.answer textarea{width:100%;min-height:5rem}
.suggest{display:flex;gap:.4rem;flex-wrap:wrap;margin:.5rem 0}
.suggest button{font-size:.8rem}
.progress{height:6px;border-radius:3px;background:#e6e8f0;margin:.5rem 0 1rem;overflow:hidden}
.progress i{display:block;height:100%;background:#5b2bd6;width:0}
.nav{display:flex;gap:.5rem;margin-top:.75rem}
.review li{margin:.4rem 0}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.75rem;margin:.5rem 0 1rem}
.m{border:1px solid var(--a-border,#dde2ee);border-radius:10px;padding:.7rem .9rem;background:var(--a-surface,#fff)}
.m b{display:block;font-size:1.5rem}.m span{font-size:.8rem;opacity:.7}
.bar{height:8px;border-radius:4px;background:#e6e8f0;overflow:hidden;margin-top:.4rem}.bar i{display:block;height:100%;background:#5b2bd6}
.a-table td,.a-table th{vertical-align:top}
[role=tabpanel]{padding-top:.75rem}
"""

BASE_JS = r"""
(function(){
  var body=document.body;
  function q(s,r){return (r||document).querySelector(s)}
  function qa(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))}
  var editBtn=q('#btn-edit');
  if(editBtn) editBtn.addEventListener('click',function(){
    var on=!body.classList.contains('editing');
    body.classList.toggle('editing',on);
    qa('[data-edit]').forEach(function(el){el.contentEditable=on?'true':'false'});
    editBtn.textContent=on?'Done editing':'Edit';
  });
  qa('input[type=file]').forEach(function(inp){
    inp.addEventListener('change',function(){
      var list=document.getElementById(inp.dataset.list);
      if(!list) return;
      Array.prototype.forEach.call(inp.files,function(f){
        var li=document.createElement('li');li.textContent=f.name;list.appendChild(li);
      });
    });
  });
  qa('[data-upload]').forEach(function(b){b.addEventListener('click',function(){document.getElementById(b.dataset.upload).click()})});
  qa('[data-approve]').forEach(function(b){b.addEventListener('click',function(){
    var card=document.getElementById(b.dataset.approve);
    var on=b.getAttribute('aria-pressed')!=='true';
    b.setAttribute('aria-pressed',String(on));
    b.textContent=on?'Approved \u2713':'Approve';
    if(card) card.classList.toggle('approved',on);
  })});
  function wbSaveTarget(text){
    // Opened from Argus (PC or Devin Cloud): a run's page goes back to that run, a dashboard block starts one.
    var l;try{l=(window.top||window).location;if(!/^https?:$/.test(l.protocol))return null}catch(err){return null}
    var m=l.pathname.match(/^\/(?:view|run)\/([a-f0-9]+)/);
    if(m)return {url:'/api/runs/'+m[1]+'/message',body:{text:text}};
    if(l.pathname==='/dashboard'&&/^#?\s*SDLC-[A-Z-]+ v\d/.test(text.trim()))return {url:'/api/blocks',body:{block:text}};
    return null;
  }
  function wbSave(text,state,done){
    var t=wbSaveTarget(text);if(!t)return false;
    fetch(t.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(t.body)})
      .then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.statusText);return j})})
      .then(function(j){state.textContent=j.id&&t.url==='/api/blocks'?'Saved. The run page opens; it shows the change and waits for your approval.':'Saved. The run shows the change and waits for your approval.';
        if(j.id&&t.url==='/api/blocks'){window.open('/run/'+j.id,'_blank')}if(done)done()})
      .catch(function(e){state.textContent='Could not save ('+e.message+'). Copy it and paste it into the Devin chat.'});
    return true;
  }
  window.acmeSend=function(text){
    var box=q('#send'),ta=q('#send textarea'),save=q('#btn-save');
    if(save){save.hidden=!wbSaveTarget(text);save.disabled=false}
    if(window.parent&&window.parent!==window){try{window.parent.postMessage({sdlc:'send',text:text},'*')}catch(err){}}
    ta.value=text;box.classList.add('show');ta.focus();ta.select();
    box.scrollIntoView({behavior:'smooth',block:'center'});
  };
  var saveBtn=q('#btn-save');
  if(saveBtn) saveBtn.addEventListener('click',function(){
    saveBtn.disabled=true;
    if(!wbSave(q('#send textarea').value,q('#copystate')))saveBtn.disabled=false;
  });
  var copy=q('#btn-copy');
  if(copy) copy.addEventListener('click',function(){
    var ta=q('#send textarea');ta.select();
    try{document.execCommand('copy');q('#copystate').textContent='Copied. Paste it into the Devin chat.'}
    catch(err){q('#copystate').textContent='Press Ctrl/Cmd+C to copy.'}
  });
})();
"""

SEND_PANEL = ('<div class="a-panel send" id="send"><div class="a-panel__head"><span class="a-panel__title">'
              'Ready to send</span></div><p>Opened from Argus, Save sends it to Devin, which shows the change and '
              'waits for your approval. Anywhere else, copy it and paste it into the Devin chat.</p>'
              '<textarea readonly aria-label="Text to paste into the Devin Cloud chat"></textarea><div class="row" style="display:flex;gap:.5rem;margin-top:.5rem">'
              '<button class="a-btn a-btn--primary" id="btn-save" type="button" hidden>Save</button>'
              '<button class="a-btn a-btn--primary" id="btn-copy" type="button">Copy</button>'
              '<span id="copystate" style="font-size:.85rem;opacity:.75"></span></div></div>')

BACKLOG_CSS = BASE_CSS + """
.bl-bar{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin:.5rem 0 1rem;font-size:.9rem}
.bl-bar label{display:inline-flex;gap:.3rem;align-items:center}
.bl-grid{display:grid;grid-template-columns:380px 1fr;gap:1rem;align-items:start}
.bl-list{border:1px solid var(--a-border,#dde2ee);border-radius:10px;background:var(--a-surface,#fff);max-height:78vh;overflow:auto}
.bl-group{padding:.45rem .8rem;font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.03em;background:#f3f0ff;color:#3d1a9e;position:sticky;top:0}
.bl-item{display:flex;gap:.5rem;padding:.55rem .8rem;border-top:1px solid var(--a-border,#eef0f5);cursor:pointer;font-size:.88rem}
.bl-item:hover{background:#faf8ff}.bl-item.sel{background:#ece6ff;box-shadow:inset 3px 0 0 #5b2bd6}
.bl-item .pill,.bl-item input{align-self:flex-start}.bl-item .pill{margin-top:.1rem}
.bl-item .k{font-weight:600;white-space:nowrap}.bl-item .s{flex:1}.bl-item .p{opacity:.7;white-space:nowrap}
.bl-detail{border:1px solid var(--a-border,#dde2ee);border-radius:10px;background:var(--a-surface,#fff);padding:1rem 1.2rem;min-height:60vh}
.bl-actions{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0;padding:.6rem 0;border-top:1px solid var(--a-border,#eef0f5);border-bottom:1px solid var(--a-border,#eef0f5)}
.bl-actions .a-btn[aria-pressed=true]{background:#5b2bd6;color:#fff;border-color:#5b2bd6}
.bl-panel{background:#faf9ff;border:1px solid #e3dcff;border-radius:10px;padding:.9rem 1rem}
.bl-panel h4{margin:0 0 .5rem}
.cardsrow{display:flex;gap:.5rem;flex-wrap:wrap;margin:.5rem 0}
.pcard{width:3.2rem;height:4.4rem;border-radius:8px;border:2px solid #cfc4ff;background:#fff;font-size:1.3rem;font-weight:700;cursor:pointer}
.pcard[aria-pressed=true]{background:#5b2bd6;color:#fff;border-color:#5b2bd6}
.chk{margin:.3rem 0;font-size:.9rem}.chk.bad::before{content:"\\2717  ";color:#b42318}.chk.ok::before{content:"\\2713  ";color:#1f8a5b}
.bl-panel select,.bl-panel textarea,.bl-panel input[type=text]{width:100%;margin:.25rem 0 .6rem}
"""

BACKLOG_CSS += (".bl-grp{display:inline-flex;flex-wrap:wrap;gap:.5rem;align-items:center;padding:2px 8px;"
                "border:1px solid rgb(var(--border-primary));border-radius:6px}")

BACKLOG_BODY = ('<p class="lead">Pick a ticket on the left to open it in the middle. Use the buttons to groom, edit, point, move, clone, split, hold, add a note or book a demo. '
 'Each button prepares a request for Devin. Devin shows the Jira change and waits for "approved" before anything is written.</p>'
 '<div class="bl-bar"><span class="bl-grp" role="group" aria-label="Show"><b>Show</b>'
 '<label><input type="checkbox" class="f-type" value="Story" checked> Stories</label>'
 '<label><input type="checkbox" class="f-type" value="Epic"> Epics</label>'
 '<label><input type="checkbox" class="f-type" value="Defect" checked> Defects</label>'
 '<label><input type="checkbox" id="f-groom" checked> Needs grooming only</label>'
 '<label><input type="checkbox" id="f-demo"> Demo needed only</label></span>'
 '<span class="bl-grp" role="group" aria-label="Group by"><b>Group by</b><label><input type="radio" name="grp" value="sp" checked> Specialty</label>'
 '<label><input type="radio" name="grp" value="ep"> Epic</label></span>'
 '<span class="bl-grp" role="search"><b>Search</b><input class="a-input" id="f-q" aria-label="Search key or title" placeholder="Search key or title" style="max-width:220px"></span>'
 '<button class="a-btn a-btn--outline" type="button" id="btn-new">+ New ticket</button></div>'
 '<div class="bl-grid"><div class="bl-list" id="list"></div><div class="bl-detail" id="detail"></div></div>'
 + SEND_PANEL)

BACKLOG_JS = r"""
(function(){
  var sel=null,act=null,picked={};
  function $(id){return document.getElementById(id)}
  function esc(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;')}
  function visible(){
    var types=[].map.call(document.querySelectorAll('.f-type:checked'),function(c){return c.value});
    var g=$('f-groom').checked,dm=$('f-demo').checked,q=$('f-q').value.toLowerCase();
    var rows=T.filter(function(x){return types.indexOf(x.t)>=0&&(dm?!!x.demo:(!g||x.groom))&&(!q||(x.k+' '+x.s).toLowerCase().indexOf(q)>=0)});
    return dm?rows.sort(function(a,b){return (a.demo==='ready'?0:1)-(b.demo==='ready'?0:1)}):rows;
  }
  function list(){
    var by=document.querySelector('input[name=grp]:checked').value,groups={},h='';
    visible().forEach(function(x){var g=by==='sp'?x.sp:(x.t==='Epic'?x.s:(x.ep||'No epic'));(groups[g]=groups[g]||[]).push(x)});
    Object.keys(groups).sort().forEach(function(g){
      h+='<div class="bl-group">'+esc(g)+' &middot; '+groups[g].length+'</div>';
      groups[g].forEach(function(x){
        h+='<div class="bl-item'+(sel&&sel.k===x.k?' sel':'')+'" data-k="'+x.k+'"><input type="checkbox" data-pick="'+x.k+'"'+(picked[x.k]?' checked':'')+' title="Select for a bulk move">'+
          '<span class="k">'+x.k+'</span><span class="s">'+esc(x.s)+'</span><span class="p">'+(x.pts==null?'&ndash;':x.pts+' pt')+'</span>'+
          (x.groom?'<span class="pill chip-warn" title="Needs grooming">G</span>':'')+
          (x.demo?'<span class="pill '+(x.demo==='ready'?'chip-ok':'chip-new')+'" title="'+(x.demo==='ready'?'Ready to demo':'Demo needed later')+'">&#127908;</span>':'')+'</div>';
      });
    });
    $('list').innerHTML=h||'<p style="padding:1rem">Nothing matches these filters.</p>';
    [].forEach.call(document.querySelectorAll('.bl-item'),function(el){el.onclick=function(ev){if(ev.target.dataset.pick)return;open(el.dataset.k)}});
    [].forEach.call(document.querySelectorAll('[data-pick]'),function(c){c.onchange=function(){picked[c.dataset.pick]=c.checked;if(act==='move')panel()}});
  }
  function open(k){sel=T.filter(function(x){return x.k===k})[0];act=null;list();detail()}
  function detail(){
    if(!sel){$('detail').innerHTML='<p class="lead">Select a story, epic or defect on the left.</p>';return}
    var x=sel,acts=[['groom','Groom'],['edit','Edit'],['point','Point / poker'],['move','Move'],['clone','Clone'],['note','Add note'],['hold','Hold']];
    if(x.t==='Epic')acts=acts.filter(function(a){return ['point','move','hold'].indexOf(a[0])<0});
    if((x.pts||0)>=13)acts.splice(3,0,['split','Split']);
    if(x.demo)acts.push(['demo',x.demo==='ready'?'Book demo':'Demo']);
    $('detail').innerHTML='<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap"><span class="pill chip-new">'+x.t+'</span><b>'+x.k+'</b>'+
      (x.groom?'<span class="pill chip-warn">Needs grooming</span>':'<span class="pill chip-ok">Ready</span>')+
      (x.demo==='ready'?'<span class="pill chip-ok">&#127908; Ready to demo</span>':x.demo?'<span class="pill chip-new">&#127908; Demo needed</span>':'')+'</div>'+
      '<h3 style="margin:.4rem 0">'+esc(x.s)+'</h3><div class="card" style="border:none;padding:0"><dl>'+
      (x.ep?'<dt>Epic</dt><dd>'+esc(x.ep)+'</dd>':'')+'<dt>Specialty</dt><dd>'+esc(x.sp)+'</dd>'+
      (x.t!=='Epic'?'<dt>Sprint</dt><dd>'+esc(x.sprint)+'</dd><dt>Points</dt><dd>'+(x.pts==null?'<em>Not pointed</em>':x.pts)+'</dd>':'')+
      '<dt>Status</dt><dd>'+esc(x.st)+'</dd><dt>Description</dt><dd>'+(x.d?esc(x.d):'<em>Not given</em>')+'</dd>'+
      '<dt>Acceptance criteria</dt><dd>'+(x.ac.length?'<ul style="margin:0;padding-left:1.1rem">'+x.ac.map(function(a){return '<li>'+esc(a)+'</li>'}).join('')+'</ul>':'<em>None</em>')+'</dd></dl></div>'+
      '<div class="bl-actions">'+acts.map(function(a){return '<button class="a-btn a-btn--outline" type="button" data-act="'+a[0]+'" aria-pressed="'+(act===a[0])+'">'+a[1]+'</button>'}).join('')+'</div><div id="panel"></div>';
    [].forEach.call(document.querySelectorAll('[data-act]'),function(b){b.onclick=function(){act=b.dataset.act;detail()}});
    panel();
  }
  function send(lines){acmeSend('SDLC-DASHBOARD-BACKLOG\n'+lines.join('\n')+'\nEND\nShow me the Jira change first; I will reply "approved".')}
  function panel(){
    var p=$('panel'),x=sel;if(!p||!act){if(p)p.innerHTML='';return}
    var h='';
    if(act==='groom'){
      h='<h4>Groom '+x.k+'</h4><p style="margin:.2rem 0 .5rem;font-size:.85rem;opacity:.75">Checked against the team\'s Jira rule book.</p>'+
        x.checks.map(function(c){return '<div class="chk '+c[0]+'">'+esc(c[1])+'</div>'}).join('')+
        '<label>Description</label><textarea class="a-input" id="g-d" aria-label="Description">'+esc(x.d)+'</textarea>'+
        '<label>Acceptance criteria, one per line</label><textarea class="a-input" id="g-ac" aria-label="Acceptance criteria, one per line" style="min-height:5rem">'+esc(x.ac.join('\n'))+'</textarea>'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){send(['action: groom','ticket: '+x.k,'description: '+$('g-d').value.trim(),'acceptance criteria:'].concat($('g-ac').value.split('\n').filter(Boolean).map(function(l){return '  - '+l})))};return;
    }
    if(act==='point'){
      h='<h4>Point '+x.k+'</h4>'+(x.devin?'<p style="margin:.2rem 0">Devin\'s card from the complexity matrix: <b>'+x.devin+'</b></p>':'')+
        '<div class="cardsrow">'+['1','2','3','5','8','13','?'].map(function(v){return '<button class="pcard" type="button" data-v="'+v+'" aria-pressed="false">'+v+'</button>'}).join('')+'</div>'+
        '<label><input type="radio" name="pm" value="solo" checked> Set the points now</label><br>'+
        '<label><input type="radio" name="pm" value="poker"> Start planning poker with:</label><div style="margin:.3rem 0 .6rem 1.4rem">'+
        TEAM.map(function(n){return '<label style="margin-right:.8rem"><input type="checkbox" class="pv" value="'+n+'"> '+n+'</label>'}).join('')+'</div>'+
        '<p style="font-size:.82rem;opacity:.75;margin:.2rem 0 .6rem">In poker, votes stay hidden until the facilitator reveals them. Each invitee votes from their own dashboard.</p>'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;var v='';
      [].forEach.call(p.querySelectorAll('.pcard'),function(b){b.onclick=function(){[].forEach.call(p.querySelectorAll('.pcard'),function(o){o.setAttribute('aria-pressed','false')});b.setAttribute('aria-pressed','true');v=b.dataset.v}});
      $('go').onclick=function(){var m=p.querySelector('input[name=pm]:checked').value;
        var who=[].map.call(p.querySelectorAll('.pv:checked'),function(c){return c.value});
        send(m==='solo'?['action: point','ticket: '+x.k,'points: '+(v||'not chosen')]:['action: poker start','ticket: '+x.k,'my vote: '+(v||'not chosen'),'voters: '+who.join(', ')])};return;
    }
    if(act==='edit'){
      var eps=T.filter(function(e){return e.t==='Epic'});
      h='<h4>Edit '+x.k+'</h4><label>Title</label><input type="text" class="a-input" id="e-s" aria-label="Title" value="'+esc(x.s)+'">'+
        '<label>Description</label><textarea class="a-input" id="e-d" aria-label="Description" style="min-height:5rem">'+esc(x.d)+'</textarea>'+
        (x.t!=='Epic'?'<label>Acceptance criteria, one per line</label><textarea class="a-input" id="e-ac" aria-label="Acceptance criteria, one per line" style="min-height:4rem">'+esc(x.ac.join('\n'))+'</textarea>'+
        '<label>Epic</label><select class="a-input" id="e-ep" aria-label="Epic"><option value="">(keep)</option>'+eps.map(function(e){return '<option value="'+e.k+'">'+e.k+' '+esc(e.s)+'</option>'}).join('')+'</select>':'')+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){var l=['action: edit','ticket: '+x.k];
        if($('e-s').value.trim()!==x.s)l.push('title: '+$('e-s').value.trim());
        if($('e-d').value.trim()!==(x.d||''))l.push('description: '+$('e-d').value.trim().replace(/\n/g,' '));
        if($('e-ac')&&$('e-ac').value.trim()!==x.ac.join('\n'))l=l.concat(['acceptance criteria:']).concat($('e-ac').value.split('\n').filter(Boolean).map(function(v){return '  - '+v}));
        if($('e-ep')&&$('e-ep').value)l.push('epic: '+$('e-ep').value);
        send(l)};return;
    }
    if(act==='split'){
      h='<h4>Split '+x.k+'</h4><p>'+x.pts+' points is too big for one sprint. Devin proposes two or three smaller stories, each with its own acceptance criteria, and shows them here for approval.</p>'+
        '<label>Anything Devin should know about where to split (optional)</label><input type="text" class="a-input" id="sp-w" aria-label="Where to split">'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){send(['action: split','ticket: '+x.k,'hint: '+$('sp-w').value.trim()])};return;
    }
    if(act==='hold'){
      var on=/hold/i.test(x.st);
      h='<h4>'+(on?'Resume ':'Put on hold ')+x.k+'</h4>'+(on?'':'<label>Why</label><input type="text" class="a-input" id="h-w">')+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){send(on?['action: resume','ticket: '+x.k]:['action: hold','ticket: '+x.k,'why: '+$('h-w').value.trim()])};return;
    }
    if(act==='move'){
      var keys=Object.keys(picked).filter(function(k){return picked[k]});if(keys.indexOf(x.k)<0)keys.unshift(x.k);
      h='<h4>Move '+keys.length+' ticket'+(keys.length>1?'s':'')+'</h4><p style="font-size:.85rem;margin:.2rem 0">'+keys.join(', ')+
        ' <span style="opacity:.7">(tick more on the left to move them together)</span></p>'+
        '<label>To</label><select class="a-input" id="m-to">'+SPRINTS.map(function(s){return '<option>'+s+'</option>'}).join('')+'</select>'+
        '<label>Why (optional)</label><input type="text" class="a-input" id="m-why">'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){send(['action: move','tickets: '+keys.join(', '),'to: '+$('m-to').value,'why: '+$('m-why').value.trim()])};return;
    }
    if(act==='clone'){
      h='<h4>Clone '+x.k+'</h4><label>New title</label><input type="text" class="a-input" id="c-t" value="'+esc(x.s)+' (copy)">'+
        '<label>Sprint</label><select class="a-input" id="c-s">'+SPRINTS.map(function(s){return '<option>'+s+'</option>'}).join('')+'</select>'+
        '<label><input type="checkbox" id="c-sub" checked> Copy the sub-tasks</label><br><br>'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){send(['action: clone','ticket: '+x.k,'title: '+$('c-t').value,'sprint: '+$('c-s').value,'copy sub-tasks: '+($('c-sub').checked?'yes':'no')])};return;
    }
    if(act==='demo'){
      h='<h4>Demo for '+x.k+'</h4><p style="font-size:.85rem;margin:.2rem 0 .6rem">'+(x.demo==='ready'?'The story is '+esc(x.st)+', so it can be shown to the business now.':'The story is still '+esc(x.st)+'. The demo can be booked ahead.')+'</p>'+
        '<label><input type="radio" name="dm" value="scheduled" checked> Book the demo (adds a comment; the label stays)</label><br>'+
        '<label><input type="radio" name="dm" value="given"> Demo given (takes the label off, with a comment)</label><br><br>'+
        '<label>Date</label><input type="text" class="a-input" id="d-when" placeholder="for example 21 Oct 2026, 10:00 ET">'+
        '<label>Audience</label><input type="text" class="a-input" id="d-who" placeholder="who is invited or who saw it">'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;$('go').onclick=function(){var w=$('d-when').value.trim(),a=$('d-who').value.trim();if(!w||!a){alert('Give the date and the audience.');return;}send(['action: demo '+p.querySelector('input[name=dm]:checked').value,'ticket: '+x.k,'date: '+w,'audience: '+a])};return;
    }
    if(act==='note'){
      h='<h4>Add a note to '+x.k+'</h4><textarea class="a-input" id="n-t" style="min-height:5rem" placeholder="The note as it should appear on the ticket"></textarea>'+
        '<input type="file" id="n-f" multiple hidden><button class="a-btn a-btn--outline" type="button" id="n-up">Attach documents</button><ul class="files" id="n-l"></ul>'+
        '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button>';
      p.innerHTML=h;var fs=[];$('n-up').onclick=function(){$('n-f').click()};
      $('n-f').onchange=function(ev){[].forEach.call(ev.target.files,function(f){fs.push(f.name);$('n-l').insertAdjacentHTML('beforeend','<li>'+esc(f.name)+'</li>')})};
      $('go').onclick=function(){send(['action: note','ticket: '+x.k,'note: '+$('n-t').value.trim()].concat(fs.length?['documents: '+fs.join(', ')+' (dropped into the chat next)']:[]))};return;
    }
  }
  $('btn-new').onclick=function(){
    sel=null;act=null;list();
    $('detail').innerHTML='<h3 style="margin-top:0">New ticket</h3><div class="bl-panel"><label>Type</label><select class="a-input" id="t-ty"><option>Story</option><option>Epic</option><option>Defect</option></select>'+
      '<label>Epic (for a story or defect)</label><select class="a-input" id="t-ep"><option></option>'+T.filter(function(x){return x.t==='Epic'}).map(function(x){return '<option>'+x.k+' '+esc(x.s)+'</option>'}).join('')+'</select>'+
      '<label>Paste notes, an email or meeting minutes. Devin drafts the ticket from them.</label><textarea class="a-input" id="t-n" style="min-height:7rem"></textarea>'+
      '<button class="a-btn a-btn--primary" type="button" id="go">Send to Devin</button></div>';
    $('go').onclick=function(){send(['action: new ticket','type: '+$('t-ty').value,'epic: '+$('t-ep').value,'notes: |'].concat($('t-n').value.split('\n').map(function(l){return '  '+l})))};
  };
  [].forEach.call(document.querySelectorAll('.f-type,#f-groom,#f-demo,input[name=grp]'),function(c){c.onchange=list});
  $('f-q').oninput=list;
  list();open('ACME-18710');
})();
"""

NEW_CSS = BASE_CSS + """
.wiz{max-width:1100px}
.stepper{display:flex;gap:.5rem;margin:.5rem 0 1.25rem;flex-wrap:wrap}
.stepper button{flex:1;min-width:150px;text-align:left;padding:.55rem .8rem;border-radius:8px;border:none;background:#eef1f7;font:inherit;font-size:.88rem;cursor:pointer;opacity:.75}
.stepper button.on{background:#e6e0ff;color:#3d1a9e;font-weight:600;opacity:1}
.stepper button.done{background:#e7f6ee;color:#1f6b47;opacity:1}
.stepper b{display:inline-block;width:1.4rem;height:1.4rem;border-radius:50%;background:#5b2bd6;color:#fff;text-align:center;line-height:1.4rem;font-size:.75rem;margin-right:.4rem}
.kinds{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.6rem;margin:.4rem 0 1rem}
.kind{border:2px solid #e3dcff;border-radius:10px;padding:.7rem .9rem;cursor:pointer;background:#fff}
.kind[aria-pressed=true]{border-color:#5b2bd6;background:#f5f2ff}
.kind b{display:block}.kind span{font-size:.82rem;opacity:.75}
.found{background:#f3f0ff;border-left:3px solid #5b2bd6;padding:.55rem .75rem;border-radius:6px;margin:.5rem 0;font-size:.9rem}
.affects{font-size:.82rem;margin:.35rem 0}.affects .pill{margin-right:.3rem}
.tree{margin:.5rem 0}
.node{border:1px solid var(--a-border,#dde2ee);border-radius:10px;padding:.7rem .9rem;margin:.5rem 0;background:#fff}
.node.lvl1{margin-left:1.6rem}.node.lvl2{margin-left:3.2rem;padding:.45rem .8rem;font-size:.9rem}
.node .top{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.node .ttl{font-weight:600;flex:1;min-width:200px}
.node .meta{font-size:.85rem;margin:.35rem 0}
.node .checks{display:flex;gap:.35rem;flex-wrap:wrap;margin:.35rem 0}
.node.approved{border-color:#1f8a5b;box-shadow:0 0 0 2px rgba(31,138,91,.15)}
.mini{font-size:.78rem;padding:.2rem .55rem}
"""

NEW_BODY = ('<div class="wiz"><p class="lead">Create an epic, stories or sub-tasks from a document or notes. Devin reads the source, asks the business questions it needs, '
 'and drafts the tickets with the team\'s Jira rules already checked. Nothing goes to Jira until the drafts are approved.</p>'
 '<div class="stepper" id="stepper"></div><div id="step"></div>' + SEND_PANEL + '</div>')

NEW_JS = r"""
(function(){
  var S=0,kind='epic',files=[],qi=0,ans=QS.map(function(){return ''}),ok={};
  var STEPS=['Source','Questions','Draft','Approve'];
  function $(id){return document.getElementById(id)}
  function esc(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;')}
  function chips(c){return c.map(function(x){return '<span class="pill '+(x[0]==='ok'?'chip-ok':'chip-no')+'">'+(x[0]==='ok'?'&#10003; ':'&#10007; ')+esc(x[1])+'</span>'}).join('')}
  function stepper(){$('stepper').innerHTML=STEPS.map(function(s,i){return '<button type="button" data-s="'+i+'" class="'+(i===S?'on':(i<S?'done':''))+'"><b>'+(i+1)+'</b>'+s+'</button>'}).join('');
    [].forEach.call(document.querySelectorAll('[data-s]'),function(b){b.onclick=function(){go(+b.dataset.s)}})}
  function go(n){S=n;stepper();[src,questions,draft,approve][S]();window.scrollTo(0,0)}
  function src(){
    var K=[['epic','New epic','With its stories and sub-tasks'],['stories','Stories under an epic','Pick the epic below'],['subtasks','Sub-tasks under a story','The team\'s standard set, then edit'],['roadmap','Epics from a roadmap sheet','Opens the roadmap review page']];
    $('step').innerHTML='<h3>What should Devin create?</h3><div class="kinds">'+K.map(function(k){return '<div class="kind" role="button" tabindex="0" data-k="'+k[0]+'" aria-pressed="'+(kind===k[0])+'"><b>'+k[1]+'</b><span>'+k[2]+'</span></div>'}).join('')+'</div>'+
      '<h3>Where does it come from?</h3><input type="file" id="f" multiple hidden>'+
      '<button class="a-btn a-btn--outline" type="button" id="up">Upload documents</button> <span style="font-size:.82rem;opacity:.7">BRD, email, meeting notes, screenshots</span><ul class="files" id="fl">'+files.map(function(n){return '<li>'+esc(n)+'</li>'}).join('')+'</ul>'+
      '<label style="display:block;margin-top:.8rem">Confluence link (optional)</label><input class="a-input" type="text" value="'+esc(SRC.link||'')+'" style="width:100%">'+
      '<label style="display:block;margin-top:.8rem">Or paste the request in plain words</label><textarea class="a-input" style="width:100%;min-height:6rem">'+esc(SRC.text||'')+'</textarea>'+
      '<div class="nav"><button class="a-btn a-btn--primary" type="button" id="nx">Read and continue</button></div>';
    [].forEach.call(document.querySelectorAll('.kind'),function(d){d.onclick=function(){kind=d.dataset.k;src()}});
    $('up').onclick=function(){$('f').click()};
    $('f').onchange=function(ev){[].forEach.call(ev.target.files,function(x){files.push(x.name)});src()};
    $('nx').onclick=function(){go(1)};
  }
  function questions(){
    if(qi>=QS.length){
      $('step').innerHTML='<h3>Check the answers</h3><ul class="review">'+QS.map(function(q,k){return '<li><b>'+q.topic+':</b> '+(ans[k]?esc(ans[k]):'<em>not answered</em>')+' <a href="#" data-k="'+k+'">change</a></li>'}).join('')+'</ul>'+
        '<div class="nav"><button class="a-btn a-btn--primary" type="button" id="nx">Draft the tickets</button></div>';
      [].forEach.call(document.querySelectorAll('[data-k]'),function(a){a.onclick=function(e){e.preventDefault();qi=+a.dataset.k;questions()}});
      $('nx').onclick=function(){go(2)};return;
    }
    var q=QS[qi];
    $('step').innerHTML='<div class="progress"><i style="width:'+(100*qi/QS.length)+'%"></i></div><p style="font-size:.85rem;opacity:.7;margin:0">Question '+(qi+1)+' of '+QS.length+'</p>'+
      '<div class="bubble devin" style="max-width:100%"><small>Devin &middot; '+q.topic+'</small>'+esc(q.q)+'</div>'+
      '<div class="found"><b>What Devin found:</b> '+esc(q.found)+'</div>'+
      '<div class="affects"><b>Your answer affects:</b> '+q.affects.map(function(a){return '<span class="pill chip-new">'+esc(a)+'</span>'}).join('')+'</div>'+
      '<div class="suggest">'+q.sug.map(function(s){return '<button class="a-btn a-btn--outline" type="button" data-sug="'+esc(s)+'">'+esc(s)+'</button>'}).join('')+'</div>'+
      '<textarea class="a-input" id="a" style="width:100%;min-height:4.5rem" placeholder="Type the answer, or click a suggestion">'+esc(ans[qi])+'</textarea>'+
      '<div class="nav"><button class="a-btn" type="button" id="bk">Back</button><button class="a-btn" type="button" id="sk">Not sure, skip</button><button class="a-btn a-btn--primary" type="button" id="nx">Next</button></div>';
    [].forEach.call(document.querySelectorAll('[data-sug]'),function(b){b.onclick=function(){var t=$('a');t.value=t.value?t.value+'; '+b.dataset.sug:b.dataset.sug}});
    $('nx').onclick=function(){ans[qi]=$('a').value.trim();qi++;questions()};
    $('sk').onclick=function(){ans[qi]='';qi++;questions()};
    $('bk').onclick=function(){ans[qi]=$('a').value.trim();if(qi>0){qi--;questions()}else go(0)};
  }
  function node(cls,id,title,meta,checks,extra){
    return '<div class="node '+cls+(ok[id]?' approved':'')+'" id="n-'+id+'"><div class="top"><span class="ttl" data-edit>'+esc(title)+'</span>'+
      (cls!=='lvl2'?'<button class="a-btn approve mini" type="button" data-ok="'+id+'" aria-pressed="'+(!!ok[id])+'">'+(ok[id]?'Approved &#10003;':'Approve')+'</button>':'')+
      '<button class="a-btn a-btn--outline mini" type="button" data-rm="'+id+'">Remove</button>'+(extra||'')+'</div>'+
      (meta?'<div class="meta" data-edit>'+meta+'</div>':'')+(checks?'<div class="checks">'+chips(checks)+'</div>':'')+'</div>';
  }
  function draft(){
    var t=TREE,h='<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap"><h3 style="margin:0;flex:1">Draft tickets</h3>'+
      '<button class="a-btn" type="button" id="btn-edit">Edit</button><button class="a-btn a-btn--outline" type="button" id="add">+ Add story</button></div>'+
      '<p style="font-size:.85rem;opacity:.75">Checked against the team\'s Jira rules. Red items must be fixed or split before approval.</p><div class="tree">';
    h+=node('', 'e', 'Epic: '+t.t, 'Owner '+esc(t.owner)+' &middot; '+esc(t.spec)+' &middot; Release '+esc(t.release)+' &middot; Size '+t.size, t.checks);
    t.stories.forEach(function(s,i){
      h+=node('lvl1','s'+i,'Story: '+s.t,'<b>'+s.pts+' points</b><ul style="margin:.3rem 0 0;padding-left:1.1rem">'+s.ac.map(function(a){return '<li>'+esc(a)+'</li>'}).join('')+'</ul>',s.checks,
        s.pts>=13?'<button class="a-btn a-btn--outline mini" type="button" data-split="'+i+'">Split</button>':'');
      h+='<div class="node lvl2"><b>Sub-tasks</b> <span style="opacity:.7">(team standard set)</span> '+SUB.map(function(x){return '<span class="pill chip-new" data-edit>'+esc(x)+'</span>'}).join(' ')+'</div>';
    });
    $('step').innerHTML=h+'</div><div class="nav"><button class="a-btn a-btn--primary" type="button" id="nx">Continue to approve</button></div>';
    var eb=$('btn-edit'),on=document.body.classList.contains('editing');eb.textContent=on?'Done editing':'Edit';
    [].forEach.call(document.querySelectorAll('[data-edit]'),function(el){el.contentEditable=on?'true':'false'});
    eb.onclick=function(){document.body.classList.toggle('editing');draft()};
    [].forEach.call(document.querySelectorAll('[data-ok]'),function(b){b.onclick=function(){ok[b.dataset.ok]=!ok[b.dataset.ok];draft()}});
    [].forEach.call(document.querySelectorAll('[data-rm]'),function(b){b.onclick=function(){var n=$('n-'+b.dataset.rm);n.style.opacity=.35;n.querySelector('.ttl').style.textDecoration='line-through'}});
    [].forEach.call(document.querySelectorAll('[data-split]'),function(b){b.onclick=function(){var s=TREE.stories[+b.dataset.split];
      TREE.stories.splice(+b.dataset.split,1,{t:'Show override history',pts:5,ac:[s.ac[0]],checks:[['ok','Acceptance criteria'],['ok','Points']]},{t:'Use approved overrides in reports',pts:8,ac:[s.ac[1]],checks:[['ok','Acceptance criteria'],['ok','Points']]});draft()}});
    $('add').onclick=function(){TREE.stories.push({t:'New story (edit the title)',pts:'?',ac:['Add acceptance criteria'],checks:[['bad','No points'],['bad','Acceptance criteria to confirm']]});draft()};
    $('nx').onclick=function(){go(3)};
  }
  function approve(){
    var n=TREE.stories.length,a=Object.keys(ok).filter(function(k){return ok[k]}).length,bad=TREE.stories.filter(function(s){return s.checks.some(function(c){return c[0]==='bad'})}).length;
    $('step').innerHTML='<h3>Approve and send</h3><div class="metrics"><div class="m"><b>1</b><span>epic</span></div><div class="m"><b>'+n+'</b><span>stories</span></div>'+
      '<div class="m"><b>'+(n*SUB.length)+'</b><span>sub-tasks</span></div><div class="m"><b>'+bad+'</b><span>items failing a rule</span></div></div>'+
      (bad?'<div class="a-callout"><p>'+bad+' item(s) still fail a Jira rule. Go back to Draft to fix or split them, or send them as questions for Devin.</p></div>':'')+
      '<p>Devin will show the exact Jira changes in the chat and create them after the reply "approved".</p>'+
      '<div class="nav"><button class="a-btn" type="button" id="bk">Back to draft</button><button class="a-btn approve" type="button" id="all">Approve all and send to Devin</button></div>';
    $('bk').onclick=function(){go(2)};
    $('all').onclick=function(){
      var t='SDLC-DASHBOARD-BACKLOG\naction: create\nkind: '+kind+'\nepic: '+TREE.t+' | owner '+TREE.owner+' | '+TREE.spec+' | '+TREE.release+'\n';
      TREE.stories.forEach(function(s){t+='story: '+s.t+' | '+s.pts+' points\n'+s.ac.map(function(x){return '  ac: '+x}).join('\n')+'\n  sub-tasks: standard set\n'});
      t+='answers:\n'+QS.map(function(q,k){return '  '+q.topic+': '+(ans[k]||'N/A')}).join('\n')+'\n';
      if(files.length)t+='documents: '+files.join(', ')+' (dropped into the chat next)\n';
      acmeSend(t+'END\nShow me the Jira changes first; I will reply "approved".');
    };
  }
  go(0);
})();
"""


GROOM_LABELS = {"needs_grooming", "needs_split", "needs-grooming", "needs-split"}


def _json(value):
    return json.dumps(value).replace("</", "<\\/")


def _page(title, body, css, js, sample):
    page = artifact_kit.render_page(title, body, footnote=FOOTNOTE, extra_css=css, extra_js=BASE_JS + js)
    if sample:
        head = '<h1 class="a-header__title">%s</h1>' % esc(title)
        page = page.replace(head, head[:-5] + '<span class="sample">Sample data</span></h1>', 1)
    return page


def _sprint(value):
    names = bl.sprint_names(value)
    return names[-1] if names else ""


def demo_ready_statuses():
    import team_links  # noqa: E402
    return list(((team_links.load().get("jira") or {}).get("statuses") or {}).get("demo_ready") or [])


def backlog_items(stories, epics, demo_ready=None):
    """Jira search results (issues with fields) -> rows for the Backlog grid, rule-book checks included."""
    rules, found = bl.specialty_rules(), bl.foundational_rules()
    ready = set(demo_ready_statuses() if demo_ready is None else demo_ready)
    by_key = {e.get("key"): e for e in epics}
    rows = []
    for issue in list(stories) + list(epics):
        f = issue.get("fields") or {}
        kind = ((f.get("issuetype") or {}).get("name") or "Story").title()
        kind = "Defect" if kind == "Bug" else kind
        labels = [str(x) for x in f.get("labels") or []]
        epic_key = f.get(bl.F_EPIC_LINK) or ""
        epic = by_key.get(epic_key) or {}
        ac = (f.get(bl.F_ACCEPTANCE) or "").strip()
        draft = {"type": kind, "summary": f.get("summary") or "", "description": f.get("description") or "",
                 "acceptance": ac, "epic": epic_key, "labels": labels, "points": f.get(bl.F_POINTS),
                 "priority": (f.get(bl.F_PRIORITY) or {}).get("value", ""), "subtasks": None}
        if kind == "Epic":
            draft["specialty"] = next((x for x in labels if x.lower() in {s.lower() for s in bl.specialties()}), "")
        checks = bl.precheck(draft)
        story = {"key": issue.get("key"), "summary": draft["summary"], "labels": labels}
        parent = {"key": epic_key, "summary": (epic.get("fields") or {}).get("summary", ""),
                  "labels": (epic.get("fields") or {}).get("labels") or []} if epic else None
        specialty = bl.bucket_of(story, parent if kind != "Epic" else story, rules, found)
        pts = f.get(bl.F_POINTS)
        groom = bool(GROOM_LABELS & {x.lower() for x in labels}) or any(c["severity"] == "high" for c in checks) \
            or (kind == "Story" and not pts) or (pts or 0) >= 13
        rows.append({
            "k": issue.get("key"), "t": kind, "s": draft["summary"], "sp": specialty or "Unsorted",
            "ep": "" if kind == "Epic" else ((epic.get("fields") or {}).get("summary") or epic_key),
            "pts": pts, "sprint": _sprint(f.get(bl.F_SPRINT)) or ("" if kind == "Epic" else "Backlog"),
            "st": (f.get("status") or {}).get("name", ""), "groom": groom,
            "demo": ("" if not set(bl.DEMO_LABELS) & set(labels) else
                     "ready" if (f.get("status") or {}).get("name", "") in ready else "due"),
            "d": (draft["description"] or "")[:1200],
            "ac": [ln.strip() for ln in ac.splitlines() if ln.strip()][:12],
            "checks": [["bad", c["text"]] for c in checks] or [["ok", "Follows the rule book"]],
            "devin": "",
        })
    return rows


def backlog_page(data):
    """The Backlog grid. data = {items, sprints, team, sample}."""
    js = "var T=%s,SPRINTS=%s,TEAM=%s;" % (_json(data.get("items") or []), _json(data.get("sprints") or ["Backlog"]),
                                           _json(data.get("team") or [])) + BACKLOG_JS
    return _page("Backlog review", BACKLOG_BODY, BACKLOG_CSS, js, data.get("sample"))


def new_ticket_page(data):
    """Business intake to draft tickets. data = {source, questions, tree, subtasks, sample}."""
    tree = data.get("tree") or {"t": "", "owner": "", "spec": "", "release": "", "size": "", "checks": [], "stories": []}
    js = "var QS=%s,TREE=%s,SUB=%s,SRC=%s;" % (
        _json(data.get("questions") or []), _json(tree), _json(data.get("subtasks") or list(bl.DEV_SUBTASKS)),
        _json(data.get("source") or {})) + NEW_JS
    return _page("Backlog: new epic, stories or sub-tasks", NEW_BODY, NEW_CSS, js, data.get("sample"))


STEPS3 = ('<div class="steps-bar"><span class="on"><b>1</b>Answer</span><span><b>2</b>Check the answers</span>'
          '<span><b>3</b>Send to Devin</span></div>')

INTAKE_BODY = ('<p class="lead">Devin asks one question at a time. Click a suggestion or type an answer, then press Next. '
    'Every answer can be changed on the last screen before it goes back to Devin.</p>'
    + STEPS3 +
    '<div class="chat"><p style="margin:0"><b>Requirement:</b> %(title)s</p>'
    '<div class="progress"><i id="bar"></i></div><p id="cnt" style="font-size:.85rem;opacity:.7;margin:0 0 .5rem"></p>'
    '<div id="log"></div>'
    '<div id="qwrap"><div class="bubble devin"><small>Devin &middot; <span id="qtopic"></span></small><span id="qtext"></span></div>'
    '<div class="answer"><p style="font-size:.8rem;opacity:.7;margin:.6rem 0 .2rem">Suggestions</p><div class="suggest" id="sug"></div>'
    '<textarea class="a-input" id="ans" placeholder="Type the answer, or click a suggestion"></textarea>'
    '<input type="file" id="qfile" multiple hidden><div style="margin-top:.5rem"><button class="a-btn a-btn--outline" id="qup" type="button">Attach documents</button>'
    '<span style="font-size:.8rem;opacity:.7;margin-left:.5rem">Screenshots, emails, spreadsheets or BRDs that help answer this question</span><ul class="files" id="qfiles"></ul></div>'
    '<div class="nav"><button class="a-btn" id="back" type="button">Back</button>'
    '<button class="a-btn" id="skip" type="button">Not sure, skip</button>'
    '<button class="a-btn a-btn--primary" id="next" type="button">Next</button></div></div></div>'
    '<div id="review" hidden><div class="a-panel"><div class="a-panel__head"><span class="a-panel__title">Check the answers</span></div>'
    '<ul class="review" id="revlist"></ul><input type="file" id="rfile" multiple hidden>'
    '<p style="margin:.75rem 0 .25rem"><b>Other documents</b> <span style="font-size:.8rem;opacity:.7">for the requirement as a whole</span></p><ul class="files" id="rfiles"></ul>'
    '<div class="nav"><button class="a-btn a-btn--outline" id="rup" type="button">Attach documents</button>'
    '<button class="a-btn approve" id="send-ans" type="button">Send answers to Devin</button></div></div></div>'
    + SEND_PANEL.replace("%","%%") + '</div>')

INTAKE_JS = r"""
(function(){
  var i=0,ans=QS.map(function(){return ''}),files=QS.map(function(){return []}),general=[];
  function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;')}
  function names(list){return list.length?' <span style="opacity:.7">(attached: '+list.map(esc).join(', ')+')</span>':''}
  function fill(ul,list){ul.innerHTML='';list.forEach(function(n){var li=document.createElement('li');li.textContent=n;ul.appendChild(li)})}
  document.getElementById('qup').onclick=function(){document.getElementById('qfile').click()};
  document.getElementById('rup').onclick=function(){document.getElementById('rfile').click()};
  document.getElementById('qfile').onchange=function(ev){Array.prototype.forEach.call(ev.target.files,function(f){files[i].push(f.name)});ev.target.value='';fill(document.getElementById('qfiles'),files[i])};
  document.getElementById('rfile').onchange=function(ev){Array.prototype.forEach.call(ev.target.files,function(f){general.push(f.name)});ev.target.value='';fill(document.getElementById('rfiles'),general)};
  var log=document.getElementById('log'),box=document.getElementById('ans'),sug=document.getElementById('sug'),
      bar=document.getElementById('bar'),cnt=document.getElementById('cnt'),qwrap=document.getElementById('qwrap'),
      rev=document.getElementById('review');
  function render(){
    log.innerHTML='';
    for(var k=0;k<i;k++){
      log.insertAdjacentHTML('beforeend','<div class="bubble devin"><small>Devin</small>'+QS[k][1]+'</div>'+
        '<div class="bubble me"><small>Answer</small>'+(ans[k]?esc(ans[k]):'<em>Skipped</em>')+names(files[k])+'</div>');
    }
    if(i<QS.length){
      qwrap.hidden=false;rev.hidden=true;
      document.getElementById('qtext').textContent=QS[i][1];
      document.getElementById('qtopic').textContent=QS[i][0];
      box.value=ans[i];sug.innerHTML='';fill(document.getElementById('qfiles'),files[i]);
      QS[i][2].forEach(function(s){var b=document.createElement('button');b.type='button';b.className='a-btn a-btn--outline';b.textContent=s;
        b.onclick=function(){box.value=box.value?box.value+'; '+s:s;box.focus()};sug.appendChild(b)});
      cnt.textContent='Question '+(i+1)+' of '+QS.length;box.focus();
    } else {
      qwrap.hidden=true;rev.hidden=false;
      var ul=document.getElementById('revlist');ul.innerHTML='';
      QS.forEach(function(q,k){var li=document.createElement('li');
        li.innerHTML='<b>'+q[0]+':</b> '+(ans[k]?esc(ans[k]):'<em>not answered</em>')+names(files[k])+' <a href="#" data-k="'+k+'">change</a>';ul.appendChild(li)});
      ul.querySelectorAll('a').forEach(function(a){a.onclick=function(ev){ev.preventDefault();i=+a.dataset.k;render()}});
      cnt.textContent='All questions answered';
    }
    bar.style.width=(100*i/QS.length)+'%';
  }
  document.getElementById('next').onclick=function(){ans[i]=box.value.trim();i++;render()};
  document.getElementById('skip').onclick=function(){ans[i]='';i++;render()};
  document.getElementById('back').onclick=function(){if(i>0){ans[i]=box.value.trim();i--;render()}};
  box.addEventListener('keydown',function(ev){if(ev.key==='Enter'&&(ev.ctrlKey||ev.metaKey)){document.getElementById('next').click()}});
  document.getElementById('send-ans').onclick=function(){
    var t='Intake answers for: '+REQ.title+(REQ.id?' ('+REQ.id+')':'')+'\n';
    var all=[];
    QS.forEach(function(q,k){t+='- '+q[0]+': '+(ans[k]||'N/A')+'\n';files[k].forEach(function(n){t+='    document: '+n+'\n';all.push(n)})});
    general.forEach(function(n){t+='- Other document: '+n+'\n';all.push(n)});
    if(all.length) t+='\nNext, drop these files into the chat: '+all.join(', ')+'\n';
    acmeSend(t);
  };
  render();
})();
"""


def intake_page(data):
    """Guided intake, one question at a time. data = {requirement: {id, title}, questions: [[topic, text, [suggestions]]], sample}."""
    req = data.get("requirement") or {}
    js = "var QS=%s,REQ=%s;" % (_json(data.get("questions") or []), _json({"id": req.get("id", ""), "title": req.get("title", "")})) + INTAKE_JS
    return _page("Intake: answer Devin's questions", INTAKE_BODY % {"title": esc(req.get("title", ""))}, BASE_CSS, js, data.get("sample"))


STATUS_KIND = {"ok": "chip-ok", "warn": "chip-warn", "no": "chip-no", "new": "chip-new"}


def _steps(active=0, labels=("Review", "Edit if needed", "Approve and send")):
    return '<div class="steps-bar">%s</div>' % "".join(
        '<span class="%s"><b>%d</b>%s</span>' % ("on" if i == active else "", i + 1, esc(l)) for i, l in enumerate(labels))


def _btn(label, id_, kind=""):
    return '<button class="a-btn %s" type="button" id="%s">%s</button>' % (kind, id_, esc(label))


def _actionbar(buttons, hint):
    return '<div class="actionbar a-no-print">%s<span class="hint">%s</span></div>' % ("".join(buttons), esc(hint))


def _pill(text, kind):
    return '<span class="pill %s">%s</span>' % (STATUS_KIND.get(kind, kind), esc(str(text)))


def _metrics(items):
    return '<div class="metrics">%s</div>' % "".join(
        '<div class="m"><b>%s</b><span>%s</span>%s</div>' % (esc(str(m[0])), esc(m[1]),
        '<div class="bar"><i style="width:%d%%"></i></div>' % int(m[2]) if len(m) > 2 else "") for m in items)


def _cell(c):
    return _pill(c["pill"], c.get("kind", "")) if isinstance(c, dict) else esc(str(c))


def _table(head, rows):
    return '<div class="a-table-scroll"><table class="a-table"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        "".join("<th>%s</th>" % esc(h) for h in head),
        "".join("<tr>%s</tr>" % "".join("<td data-edit>%s</td>" % _cell(c) for c in r) for r in rows))


def _block(b):
    """One block of a report tab: metrics, bullets, table, cards or a callout (all text, escaped here)."""
    if "metrics" in b:
        return _metrics(b["metrics"])
    if "bullets" in b:
        return ('<div class="a-panel"><div class="a-panel__head"><span class="a-panel__title">%s</span></div><ul data-edit>%s</ul></div>'
                % (esc(b.get("title", "")), "".join("<li>%s</li>" % esc(x) for x in b["bullets"])))
    if "table" in b:
        return _table(b["table"]["head"], b["table"]["rows"])
    if "cards" in b:
        return "".join('<div class="card" style="margin-bottom:1rem"><h3 data-edit>%s</h3><dl>%s</dl></div>' % (
            esc(c["title"]), "".join("<dt>%s</dt><dd data-edit>%s</dd>" % (esc(k), "<ul style='margin:0;padding-left:1.1rem'>%s</ul>" % "".join(
                "<li>&#10003; %s</li>" % esc(x) for x in v) if isinstance(v, list) else esc(str(v))) for k, v in c["fields"])) for c in b["cards"])
    if "callout" in b:
        return '<div class="a-callout"><p>%s</p></div>' % esc(b["callout"])
    raise ValueError("unknown report block: %s" % sorted(b))


def _tabs(items):
    btns = "".join('<button class="a-btn" role="tab" aria-controls="t-%d"%s>%s</button>' % (
        i, ' aria-selected="true"' if i == 0 else "", esc(t["title"])) for i, t in enumerate(items))
    panes = "".join('<section id="t-%d" role="tabpanel"%s>%s</section>' % (i, "" if i == 0 else " hidden",
                    "".join(_block(b) for b in t.get("blocks") or [])) for i, t in enumerate(items))
    return '<div class="a-tabs a-tabs--wrap" data-a-tabs role="tablist">%s</div>%s' % (btns, panes)


REPORT_JS = r"""
document.getElementById('btn-approve').onclick=function(){
  acmeSend('approved: '+document.body.dataset.label+'\n'+(document.body.dataset.edited?'(the edited text is pasted below)\n'+Array.prototype.map.call(document.querySelectorAll('[data-edit]'),function(x){return x.innerText.trim()}).filter(Boolean).join('\n')+'\n':'')+'Save it to the knowledge base and share the link.');
};
document.getElementById('btn-dl').onclick=function(){window.print()};
document.addEventListener('input',function(ev){if(ev.target.closest('[data-edit]'))document.body.dataset.edited='1'});
"""


def report_page(data):
    """A tabbed report (release notes, migration status). data = {title, label, lead, tabs: [{title, blocks}], sample}."""
    body = ('<p class="lead">%s</p>' % esc(data.get("lead", "")) + _steps() + _tabs(data.get("tabs") or [])
            + _actionbar([_btn("Edit", "btn-edit"), _btn("Download PDF", "btn-dl", "a-btn--outline"),
                          _btn("Approve", "btn-approve", "approve")], "Approve saves it to the knowledge base after Devin confirms.")
            + SEND_PANEL)
    js = "document.body.dataset.label=%s;" % _json(data.get("label") or data.get("title", "")) + REPORT_JS
    return _page(data.get("title", "Report"), body, BASE_CSS, js, data.get("sample"))


def _epic_card(i, d):
    def v(x):
        return esc(x) if x else "<em>Not given yet</em>"
    outs = "".join("<li>%s</li>" % esc(o) for o in d.get("outcomes") or []) or "<li><em>Not given yet</em></li>"
    qs = "".join('<div class="q"><b>Devin asks:</b> <span>%s</span><textarea class="a-input" placeholder="Answer here"></textarea></div>' % esc(x)
                 for x in d.get("questions") or [])
    status = d.get("status") or ("Ready" if not d.get("questions") else "%d question%s" % (len(d["questions"]), "s" if len(d["questions"]) > 1 else ""))
    cid = "e%d" % (i + 1)
    return ('<div class="card" id="%(id)s" data-row="%(row)s"><div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">'
            '<h3 data-edit>%(title)s</h3>%(st)s<span class="pill chip-new">%(spec)s</span><span class="edit-flag">editing</span></div>'
            '<dl><dt>Objective</dt><dd data-edit data-f="objective">%(obj)s</dd>'
            '<dt>Outcomes</dt><dd><ul style="margin:0;padding-left:1.1rem" data-edit data-f="outcomes">%(outs)s</ul></dd>'
            '<dt>Needed by</dt><dd data-edit data-f="needed by">%(due)s</dd><dt>Release</dt><dd data-edit data-f="release">%(fix)s</dd>'
            '<dt>Owner</dt><dd data-edit data-f="owner">%(owner)s</dd><dt>Source</dt><dd>%(src)s<ul class="files" id="%(id)s-files"></ul></dd></dl>'
            '%(qs)s<div class="row"><input type="file" id="%(id)s-up" data-list="%(id)s-files" multiple hidden>'
            '<button class="a-btn a-btn--outline" type="button" data-upload="%(id)s-up">Upload document</button>'
            '<button class="a-btn approve" type="button" data-approve="%(id)s" aria-pressed="false">Approve</button></div></div>') % dict(
        id=cid, row=esc(str(d.get("row", i + 1))), title=esc(d.get("title", "")), spec=esc(d.get("specialty") or "Unsorted"),
        st=_pill(status, "ok" if status == "Ready" else "warn"), obj=v(d.get("objective")), outs=outs, due=v(d.get("needed_by")),
        fix=v(d.get("release")), owner=v(d.get("owner")), src=v(d.get("source")), qs=qs)


EPICS_JS = r"""
document.getElementById('btn-send').onclick=function(){
  var t='Epic plan decisions ('+document.body.dataset.sheet+')\n';
  document.querySelectorAll('.card').forEach(function(c){
    var ok=c.querySelector('[data-approve]').getAttribute('aria-pressed')==='true';
    t+='\nrow '+c.dataset.row+' '+c.querySelector('h3').innerText.trim()+': '+(ok?'approved':'not approved yet')+'\n';
    if(document.body.dataset.edited) c.querySelectorAll('[data-f]').forEach(function(d){t+='  '+d.dataset.f+': '+d.innerText.trim().replace(/\n+/g,'; ')+'\n'});
    c.querySelectorAll('.q').forEach(function(q){var a=q.querySelector('textarea').value.trim();
      if(a) t+='  answer: '+q.querySelector('span').textContent.trim()+' -> '+a+'\n'});
    c.querySelectorAll('.files li').forEach(function(li){t+='  document to attach: '+li.textContent+' (drop the file into the chat)\n'});
  });
  acmeSend(t);
};
document.addEventListener('input',function(ev){if(ev.target.closest('[data-edit]'))document.body.dataset.edited='1'});
"""


def epics_page(data):
    """Epics drafted from a roadmap sheet. data = {sheet, epics: [{row, title, specialty, objective, outcomes, needed_by,
    release, owner, source, questions}], pages_read, sample}."""
    epics = data.get("epics") or []
    ready = sum(1 for d in epics if not d.get("questions"))
    nq = sum(len(d.get("questions") or []) for d in epics)
    body = ('<p class="lead">Devin read the roadmap sheet <b>%s</b> and drafted one epic per row. Each epic can be corrected, '
            'given a supporting document, and approved. Nothing goes to Jira until the approvals are sent back to Devin.</p>' % esc(data.get("sheet", ""))
            + _steps() + _metrics([(len(epics), "epics drafted"), (ready, "ready to approve"), (nq, "questions to answer"),
                                   (data.get("pages_read", 0), "Confluence pages read")])
            + '<div class="cards">%s</div>' % "".join(_epic_card(i, d) for i, d in enumerate(epics))
            + _actionbar([_btn("Edit", "btn-edit"), _btn("Send to Devin", "btn-send", "a-btn--primary")], "Approve each epic on its card, then Send.")
            + SEND_PANEL)
    js = "document.body.dataset.sheet=%s;" % _json(data.get("sheet", "")) + EPICS_JS
    return _page("Epics from the roadmap: review and approve", body, BASE_CSS, js, data.get("sample"))


PAGES = {"backlog": backlog_page, "new-ticket": new_ticket_page, "intake": intake_page,
         "epics": epics_page, "report": report_page}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("page", choices=sorted(PAGES))
    ap.add_argument("--data", required=True, help="JSON file with the page content")
    ap.add_argument("--out", required=True, help="where to write the HTML page")
    args = ap.parse_args(argv)
    with open(args.data, encoding="utf-8") as fh:
        data = json.load(fh)
    page = PAGES[args.page](data)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
