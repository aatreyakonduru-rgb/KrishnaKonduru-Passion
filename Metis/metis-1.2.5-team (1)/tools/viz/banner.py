import os as _o
import sys as _s;_s.path.insert(0,_o.path.join(_o.path.dirname(_o.path.abspath(__file__)),".."));import site_paths;S=site_paths.load();WORK=S.work;KBROOT=S.kb;REPOSROOT=S.repos;LOGO=S.logo
import base64,os,html as _h
logo=base64.b64encode(open(LOGO,"rb").read()).decode() if LOGO else ""
img=f'<img class="plogo" src="data:image/png;base64,{logo}" alt="{_h.escape(S.short)}">' if logo else ""
a=t.index('<header>'); b=t.index('</header>')+len('</header>')
t=t[:a]+f'''<header>
 <div class="r1"><div class="hl">{img}<span class="pt">{_h.escape(S.org.upper() or S.name.upper())}</span></div>
  <b>{_h.escape(S.title)}</b><small id="asof"></small></div>
 <div class="r2"><span id="groups"></span><span id="tabs"></span><button class="tog" id="theme">Dark</button></div>
 <svg style="display:none"><g id="lg-dots"></g></svg>
</header>'''+t[b:]
css='''<style>
header{background:#fff;color:#231e33;border-bottom:2px solid #5009b5}
[data-theme=dark] header{background:#1f1b2b;color:#ece8f7}
.r1{display:grid;grid-template-columns:1fr auto 1fr;height:28px;padding:0 12px;border-bottom:1px solid var(--line)}
.r1 .hl{display:flex;align-items:center;gap:8px}.plogo{height:18px}.pt{font-size:11px;letter-spacing:2px;color:var(--sub);white-space:nowrap}
.r1 b{color:var(--p);font-size:13px}[data-theme=dark] .r1 b{color:#c9b5ff}.r1 small{justify-self:end;color:var(--sub);opacity:1}
.r2{display:flex;align-items:center;gap:8px;height:30px;padding:0 12px}#groups{display:flex;gap:4px;flex-shrink:0;white-space:nowrap}#tabs{display:flex;flex:1;min-width:0;height:100%;overflow-x:auto;scrollbar-width:thin}.r2 .sp{flex:1}
.grp{border:1px solid var(--line);color:var(--sub);padding:1px 10px}.grp.on{background:var(--p);color:#fff;border-color:var(--p)}
.tab{background:none;color:var(--sub);border-radius:0;border-bottom:3px solid transparent;padding:5px 10px}
.tab:hover{background:rgba(90,98,117,.06)}.tab.on{background:none;color:var(--p);border-bottom-color:var(--p)}
.tog{background:none;border:1px solid var(--line);color:var(--sub)}
.cap,footer{display:none!important}
#stage{left:0;right:0;bottom:0;border-radius:0;border-left:0;border-right:0;overflow:auto}
#zbar{left:252px!important;right:auto!important;bottom:12px!important;flex-direction:row!important}
.r2{display:none!important}
#side{position:fixed;left:0;bottom:0;width:240px;background:var(--card);border-right:1px solid var(--line);overflow-y:auto;overflow-x:hidden;z-index:4;box-sizing:border-box;padding:10px 0 12px;font-size:12.5px}
#side .sg{font-size:10.5px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--sub);padding:12px 16px 4px}
#side .sv{display:block;width:100%;text-align:left;background:none;border:0;border-left:3px solid transparent;border-radius:0;padding:5px 16px 5px 13px;color:var(--ink,#231e33);cursor:pointer;font:inherit}
#side .sv:hover{background:var(--pale)}#side .sv.on{border-left-color:var(--p);background:var(--pale);color:var(--p);font-weight:600}
#side #find{box-sizing:border-box;margin:0 12px 4px!important;width:calc(100% - 24px)!important;color:inherit!important;background:var(--bg,#f5f5f5)!important;border:1px solid var(--line)!important}
#side .ft{display:flex;justify-content:space-between;align-items:center;padding:12px 16px 0;border-top:1px solid var(--line);margin-top:10px}
#info,#ctl{margin-left:240px}#stage{left:240px!important}
#info{padding:6px 16px!important}#ctl{min-height:34px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}#ctl{padding-left:16px}
</style></head>'''
t=t.replace('</head>',css.replace('#5009b5',S.primary),1)
t=t.replace("\"Good for: \"+v.use;","\"Good for: \"+v.use;document.querySelectorAll('.tab').forEach(b=>{const w=VIEWS.find(x=>x.name==b.textContent);if(w)b.title=w.desc+' Good for: '+w.use});",1)
