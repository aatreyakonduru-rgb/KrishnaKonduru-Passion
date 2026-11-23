#!/usr/bin/env python3
"""KB usage efficiency gain. Reads ~/metis-work/stage/jira12m/issues.jsonl (kb_baseline_fetch.py) and
~/metis-work/stage/devin_sessions_raw.txt (devin_session_search pages), writes:
  kb/_EVIDENCE/files/kb-gain-jira.json, kb-gain-devin.json   (aggregates, no names)
  kb/context/KB_EFFICIENCY_GAIN.md                          (baseline + post-KB doc, source-tagged)
  kb/VISUALIZATION/KB_EFFICIENCY_GAIN.html                  (dashboard tab; monthly charts, line at KB start)
  build/_gain_questions.yaml                                (questions the sources cannot answer)
The whole monthly series is recomputed from Jira on every run, so the charts grow as months pass after kb_start_date."""
import json,os,re,sys,statistics as st,datetime as dt,html,yaml,collections
W=os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work'));K=W+'/kb'
if sys.argv[1:]==['ids']:
    # after questions.py add: swap the Q-GAIN-* placeholders for the register ids
    G=json.load(open(W+'/build/_gain_qids.json'));R={q['question']:q['id'] for q in yaml.safe_load(open(K+'/_QUESTIONS/VALIDATE_KB.yaml'))['questions']}
    p=K+'/context/KB_EFFICIENCY_GAIN.md';t=open(p).read()
    for g,qq in G.items(): t=t.replace('Q-GAIN-'+g,R[qq])
    open(p,'w').write(t);print('ids set',len(G));sys.exit()
W=os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work'));K=W+'/kb';EV=K+'/_EVIDENCE/files'
C=yaml.safe_load(open(K+'/.metis/kb-impact.yaml'));TEAM=C['team_value'];AIL={l.lower() for l in C['ai_labels']}
START=dt.date.fromisoformat(str(C['kb_start_date']));B0=START.replace(year=START.year-1);TODAY=dt.date.today()
meta=json.load(open(W+'/stage/jira12m/_meta.json'))
D=lambda s:dt.datetime.fromisoformat(s[:19]).date() if s else None
DONE={'done','closed','resolved','cancelled','canceled','complete','completed','deployed','released','abandoned'}
DEF={t.lower() for t in C['defect_types']}
def mon(d): return d.strftime('%Y-%m')
months=[];d=B0.replace(day=1)
while d<=TODAY: months.append(mon(d)); d=(d+dt.timedelta(days=32)).replace(day=1)
I=[json.loads(l) for l in open(W+'/stage/jira12m/issues.jsonl')]
def team(i):
    t=i.get('team'); t=t[0] if isinstance(t,list) and t else t
    return t or '(no IT Team)'
def ai(i): return any(l.lower() in AIL for l in i.get('labels') or [])
def ai_added(i):
    for h in i['history']:
        if h[1]=='labels' and any(a in (h[3] or '').lower().split() for a in AIL) and not any(a in (h[2] or '').lower().split() for a in AIL): return D(h[0])
    return D(i['created']) if ai(i) else None
def started(i):
    for h in sorted(i['history']):
        if h[1]=='status' and (h[3] or '').lower() not in DONE: return D(h[0])
    return None
def reopened(i): return sum(1 for h in i['history'] if h[1]=='status' and (h[2] or '').lower() in DONE and (h[3] or '').lower() not in DONE)
def q(v,p):
    v=sorted(v); return round(v[min(len(v)-1,int(p*(len(v)-1)+.5))],1) if v else None
def agg(rows):
    res=[i for i in rows if i['resolved'] and i['cat']=='done']
    lt=[(D(i['resolved'])-D(i['created'])).days for i in res if i['type']!='Epic']
    ct=[(D(i['resolved'])-s).days for i in res if i['type']!='Epic' for s in [started(i)] if s and s<=D(i['resolved'])]
    pts=[float(i['points']) for i in res if isinstance(i.get('points'),(int,float))]
    return {'resolved':len(res),'stories_resolved':sum(1 for i in res if i['type'] in('Story','Task','Sub-task','Sub-Task')),
            'points_resolved':round(sum(pts),1),'lead_days_median':q(lt,.5),'lead_days_p75':q(lt,.75),'cycle_days_median':q(ct,.5),'cycle_days_p75':q(ct,.75),
            'defects_resolved':sum(1 for i in res if (i['type'] or '').lower() in DEF),'reopened_issues':sum(1 for i in res if reopened(i)),
            'carried_over_sprints':sum(1 for i in res if i['sprints']>1),'ai_used_resolved':sum(1 for i in res if ai(i))}
def created_agg(rows): return {'created':len(rows),'defects_created':sum(1 for i in rows if (i['type'] or '').lower() in DEF)}
teams=collections.Counter(team(i) for i in I)
SIS=[t for t,_ in teams.most_common() if t!=TEAM and t!='(no IT Team)'][:8]
out={'source':{'jql':meta['jql'],'read_at':meta['read_at'],'issues':len(I)},'kb_start_date':str(START),'baseline_from':str(B0),'team':TEAM,'sister_teams':SIS,
     'definitions':{'resolved':'statusCategory Done and resolutiondate set, by resolution month','lead_days':'created to resolved, calendar days, Epics excluded',
       'cycle_days':'first status change to a not-done status, to resolved','defect':'issue type in '+', '.join(C['defect_types']),
       'reopened':'any status change from a done status back to a not-done status','ai_used':'label in '+', '.join(C['ai_labels'])},'teams':{}}
for t in [TEAM]+SIS:
    R=[i for i in I if team(i)==t];T={'monthly':{},'baseline':{},'after_kb':{}}
    for m in months:
        T['monthly'][m]={**agg([i for i in R if i['resolved'] and mon(D(i['resolved']))==m]),**created_agg([i for i in R if mon(D(i['created']))==m])}
    bl=[i for i in R if i['resolved'] and B0<=D(i['resolved'])<START];af=[i for i in R if i['resolved'] and D(i['resolved'])>=START]
    T['baseline']={**agg(bl),**created_agg([i for i in R if B0<=D(i['created'])<START])};T['after_kb']={**agg(af),**created_agg([i for i in R if D(i['created'])>=START])}
    T['baseline_ai_used']=agg([i for i in bl if ai(i)]);T['baseline_not_ai']=agg([i for i in bl if not ai(i)])
    T['after_kb_ai_used']=agg([i for i in af if ai(i)]);T['after_kb_not_ai']=agg([i for i in af if not ai(i)])
    fa=[ai_added(i) for i in R if ai(i)];fa=[x for x in fa if x];T['ai_label_first_seen']=str(min(fa)) if fa else None
    T['found_in']=dict(collections.Counter(str(i.get('found_in')) for i in R if (i['type'] or '').lower() in DEF and i.get('found_in')).most_common(10))
    T['types']=dict(collections.Counter(i['type'] for i in R).most_common(12))
    asg=collections.defaultdict(list)
    for i in R:
        if i.get('assignee'): asg[i['assignee']].append(D(i['created']))
    T['people_first_seen_in_window']=sum(1 for v in asg.values() if min(v)>=B0+dt.timedelta(days=60))
    out['teams'][t]=T
json.dump(out,open(EV+'/kb-gain-jira.json','w'),indent=1)
# Devin sessions
S=[];raw=open(W+'/stage/devin_sessions_raw.txt').read() if os.path.exists(W+'/stage/devin_sessions_raw.txt') else ''
for l in raw.splitlines():
    if not l.startswith('- '): continue
    p=[x.strip() for x in l[2:].split(' | ')];kv={x.split('=',1)[0]:x.split('=',1)[1] for x in p[2:] if '=' in x}
    S.append({'id':p[0],'title':p[1],'created':dt.datetime.utcfromtimestamp(int(kv.get('created',0))).date(),'acus':float(kv.get('acus_consumed',0) or 0),
              'origin':kv.get('origin'),'category':kv.get('category'),'keys':re.findall(r'\b'+re.escape(C['project'])+r'-\d+\b',p[1])})
tkeys={i['key'] for i in I if team(i)==TEAM}
dv={'source':'devin_session_search(created_after=baseline_from), saved in stage/devin_sessions_raw.txt','sessions':len(S),'acus':round(sum(s['acus'] for s in S),1),
    'first_session':str(min((s['created'] for s in S),default='')),'monthly':{},'team_ticket_sessions':0,'team_ticket_acus':0.0}
for m in months:
    ss=[s for s in S if mon(s['created'])==m];tt=[s for s in ss if set(s['keys'])&tkeys]
    dv['monthly'][m]={'sessions':len(ss),'acus':round(sum(s['acus'] for s in ss),1),'team_ticket_sessions':len(tt),'team_ticket_acus':round(sum(s['acus'] for s in tt),1)}
tt=[s for s in S if set(s['keys'])&tkeys];dv['team_ticket_sessions']=len(tt);dv['team_ticket_acus']=round(sum(s['acus'] for s in tt),1)
dv['baseline']={'sessions':sum(1 for s in S if s['created']<START),'acus':round(sum(s['acus'] for s in S if s['created']<START),1)}
dv['after_kb']={'sessions':sum(1 for s in S if s['created']>=START),'acus':round(sum(s['acus'] for s in S if s['created']>=START),1)}
dv['usd_per_acu']=C.get('usd_per_acu')
json.dump(dv,open(EV+'/kb-gain-devin.json','w'),indent=1)
# Markdown
TJ='[E: file:kb-gain-jira.json]';TD='[E: file:kb-gain-devin.json]';me=out['teams'][TEAM];b=me['baseline']
f=lambda v:'n/a' if v is None else (f'{v:,}' if isinstance(v,int) else str(v))
L=[f'# KB usage efficiency gain ({TEAM})','',f'Baseline window: {B0} to {START-dt.timedelta(days=1)} (12 months before the KB start date {START}). Read-only from Jira project {C["project"]} ({len(I):,} issues created or resolved since {B0}, read {meta["read_at"]}) and Devin session history. {TJ}','',
 f'- KB start date {START} is a setting in .metis/kb-impact.yaml, not read from a source. [?: Q-GAIN-START]',
 f'- Every refresh recomputes the whole monthly series from Jira, so months after {START} are added to the charts as they pass. {TJ}','',
 '## Definitions','']+[f'- {k}: {v}. {TJ}' for k,v in out['definitions'].items()]+['',
 '## Baseline for the team','','| Measure | Baseline (12 months) | After KB start | Source |','|---|---|---|---|']
for k in ['resolved','stories_resolved','points_resolved','lead_days_median','lead_days_p75','cycle_days_median','cycle_days_p75','defects_created','defects_resolved','reopened_issues','carried_over_sprints','ai_used_resolved']:
    L.append(f'| {k} | {f(b.get(k))} | {f(me["after_kb"].get(k))} | {TJ} |')
L+=['',f'Table read from kb-gain-jira.json teams["{TEAM}"]. {TJ}','',
 '## AI-used label inside the baseline','',f'- {sum(1 for i in I if team(i)==TEAM and ai(i)):,} team issues carry an ai-used label; first seen {me["ai_label_first_seen"]}. AI use therefore started before the KB, so the KB gain is measured on top of it. {TJ}',
 f'- Baseline resolved with ai-used: {me["baseline_ai_used"]["resolved"]} (median lead {f(me["baseline_ai_used"]["lead_days_median"])} days); without: {me["baseline_not_ai"]["resolved"]} (median lead {f(me["baseline_not_ai"]["lead_days_median"])} days). {TJ}',
 f'- Whether the ai-used label is applied the same way by everyone, and whether tickets without it really used no AI or KB, is open. [?: Q-GAIN-LABEL]','',
 '## Sister teams (same Jira project, baseline window)','','| IT Team | Resolved | Median lead days | Median cycle days | Defects created | ai-used resolved | Source |','|---|---|---|---|---|---|---|']
for t in [TEAM]+SIS:
    x=out['teams'][t]['baseline'];L.append(f'| {t} | {f(x["resolved"])} | {f(x["lead_days_median"])} | {f(x["cycle_days_median"])} | {f(x["defects_created"])} | {f(x["ai_used_resolved"])} | {TJ} |')
L+=['',f'Sister teams are the {len(SIS)} largest other IT Team values in project {C["project"]}. {TJ}',f'- Which sister team is the fairest comparison group is open. [?: Q-GAIN-SISTER]','',
 '## Devin usage','',f'- {dv["sessions"]} org sessions, {dv["acus"]} ACUs since {B0}; first session {dv["first_session"]}. Before the KB start: {dv["baseline"]["sessions"]} sessions / {dv["baseline"]["acus"]} ACUs. {TD}',
 f'- Sessions whose title names a {TEAM} Jira key: {dv["team_ticket_sessions"]} ({dv["team_ticket_acus"]} ACUs). Sessions are tied to the team only through a Jira key in the title; per-person mapping needs the Devin org member list. [?: Q-GAIN-DEVINMAP]',
 f'- Dollars per ACU are not set; cost is shown in ACUs. [?: Q-GAIN-PRICE]','',
 '## Not in any source (asked in VALIDATE_KB)','',
 '- Onboarding: who joined in the baseline window, days to their first finished ticket, KT sessions needed. [?: Q-GAIN-ONBOARD]',
 '- Hours per story point or per ticket, to turn days saved into hours and dollars. [?: Q-GAIN-HOURS]',
 '- Time spent answering production or data questions before the KB. [?: Q-GAIN-SUPPORT]',
 '- Which statuses count as work started for cycle time. [?: Q-GAIN-STATUS]','',
 '## How the gain is calculated','',
 f'- Gain per measure = baseline value minus the value for months after {START}, for the team, compared with the same change for sister teams over the same months (difference in differences). {TJ}',
 f'- Within the team after {START}: ai-used tickets (assumed to use the KB) against tickets without the label. {TJ}',
 f'- ACU change = ACUs per team ticket session before and after; dollars = ACUs x usd_per_acu once given. {TD}']
open(K+'/context/KB_EFFICIENCY_GAIN.md','w').write('\n'.join(L)+'\n')
# Questions
def Q(i,qs,typ,pri,role,ctx):return {'question':qs,'type':typ,'priority':pri,'answer_role':role,'context':ctx,'blocks':['context/KB_EFFICIENCY_GAIN.md'],'possible_answers':[],'_gid':i}
QS=[Q('START',f'Is {START} the date the {C.get("team_name",TEAM)} team starts using the Mētis KB (the end of the 12-month baseline)? If not, which date?','business','P1','manager',[f'Set in .metis/kb-impact.yaml [E: file:kb-gain-jira.json]']),
 Q('ONBOARD','Onboarding baseline: who joined the '+C.get('team_name',TEAM)+' team in the last 12 months, how many days until each finished their first ticket on their own, and how many KT sessions or hours did each need?','business','P1','manager',[f'{me["people_first_seen_in_window"]} assignees first appear in Jira 60+ days into the window; Jira does not show join dates or KT effort [E: file:kb-gain-jira.json]']),
 Q('LABEL','Is the ai-used label applied on every ticket where AI (Devin, Copilot) or the KB helped, by everyone? Which tickets are the agreed exceptions that will not use the KB?','business','P1','manager',[f'ai-used first seen {me["ai_label_first_seen"]} on team issues [E: file:kb-gain-jira.json]']),
 Q('SISTER',f'Which sister team(s) are a fair comparison group for {TEAM} (similar work, not using the KB)?','business','P2','manager',['Largest other IT Team values in '+C['project']+': '+', '.join(SIS[:5])+' [E: file:kb-gain-jira.json]']),
 Q('HOURS','How many hours is one story point (or an average story) for this team, and what hourly cost should be used to turn days saved into dollars?','business','P2','manager',['Jira has story points but no hours or cost [E: file:kb-gain-jira.json]']),
 Q('SUPPORT','Before the KB, how long did it usually take to answer a production or data question (for example a scorecard number someone queried), and how many such questions per month?','business','P2','tech lead',['Not recorded in Jira for this team [E: file:kb-gain-jira.json]']),
 Q('STATUS','Which Jira statuses mean work has started (for cycle time)? The KB uses the first move to any not-done status.','application','P3','tech lead',['Definition in KB_EFFICIENCY_GAIN [E: file:kb-gain-jira.json]']),
 Q('DEVINMAP','Who can grant read access to the Devin org member list (org.membership.view), so Devin sessions and ACUs can be tied to each team member?','access','P2','manager',[f'Only {dv["team_ticket_sessions"]} sessions name a team Jira key in the title [E: file:kb-gain-devin.json]']),
 Q('PRICE','What is the price per ACU, and who gave it?','business','P3','manager',['usd_per_acu not set [E: file:kb-gain-devin.json]'])]
json.dump({q['_gid']:q['question'] for q in QS},open(W+'/build/_gain_qids.json','w'))
yaml.safe_dump([{k:v for k,v in q.items() if k!='_gid'} for q in QS],open(W+'/build/_gain_questions.yaml','w'),sort_keys=False,allow_unicode=True)
# Charts
def svg(title,series,unit,kind='bar'):
    Wd,H,pl,pb=760,220,46,34;ms=months;vals=[v for s in series for v in s[2] if v is not None];mx=max(vals+[1])
    x=lambda i:pl+i*(Wd-pl-10)/max(1,len(ms));bw=(Wd-pl-10)/max(1,len(ms))/max(1,len(series))*0.8
    y=lambda v:H-pb-(v/mx)*(H-pb-20)
    g=[f'<svg viewBox="0 0 {Wd} {H}" width="100%" style="max-width:{Wd}px;background:#fff;border:1px solid #ddd;border-radius:6px"><text x="8" y="14" font-size="12" font-weight="600">{html.escape(title)}</text>']
    for k in range(5): v=mx*k/4;g.append(f'<line x1="{pl}" x2="{Wd-10}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#eee"/><text x="{pl-4}" y="{y(v)+3:.1f}" font-size="9" text-anchor="end">{v:.0f}</text>')
    si=ms.index(mon(START)) if mon(START) in ms else len(ms)
    g.append(f'<line x1="{x(si):.1f}" x2="{x(si):.1f}" y1="18" y2="{H-pb}" stroke="#C00" stroke-dasharray="4 3"/><text x="{x(si)+(3 if si<len(ms)*0.7 else -3):.1f}" y="28" font-size="9" fill="#C00" text-anchor="{"start" if si<len(ms)*0.7 else "end"}">KB start {START}</text>')
    for j,(nm,col,vs) in enumerate(series):
        if kind=='bar':
            for i,v in enumerate(vs):
                if v: g.append(f'<rect x="{x(i)+j*bw+2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{H-pb-y(v):.1f}" fill="{col}"><title>{nm} {ms[i]}: {v}</title></rect>')
        else:
            pts=' '.join(f'{x(i)+bw/2:.1f},{y(v):.1f}' for i,v in enumerate(vs) if v is not None)
            g.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>')
            g+= [f'<circle cx="{x(i)+bw/2:.1f}" cy="{y(v):.1f}" r="2.5" fill="{col}"><title>{nm} {ms[i]}: {v}</title></circle>' for i,v in enumerate(vs) if v is not None]
        g.append(f'<rect x="{pl+j*170}" y="{H-12}" width="10" height="8" fill="{col}"/><text x="{pl+j*170+14}" y="{H-5}" font-size="9">{html.escape(nm)}</text>')
    for i,m in enumerate(ms):
        if i%2==0: g.append(f'<text x="{x(i)+2:.1f}" y="{H-pb+12}" font-size="8">{m}</text>')
    return ''.join(g)+'</svg>'
M=me['monthly'];get=lambda d,k:[d[m].get(k) for m in months]
sm={}
for t in SIS[:3]:
    sm[t]=out['teams'][t]['monthly']
cols=['#7A3E9D','#1F77B4','#FF7F0E','#2CA02C']
charts=[svg('Tickets resolved per month',[(TEAM,cols[0],get(M,'resolved'))],'n'),
 svg('Median lead time (days, created to resolved)',[(TEAM,cols[0],get(M,'lead_days_median'))]+[(t,cols[k+1],get(sm[t],'lead_days_median')) for k,t in enumerate(sm)],'d','line'),
 svg('Median cycle time (days, started to resolved)',[(TEAM,cols[0],get(M,'cycle_days_median'))],'d','line'),
 svg('Defects created per month',[(TEAM,'#D62728',get(M,'defects_created'))],'n'),
 svg('Resolved with ai-used label vs without',[('ai-used',cols[2],get(M,'ai_used_resolved')),('no label',cols[1],[(a or 0)-(b or 0) for a,b in zip(get(M,'resolved'),get(M,'ai_used_resolved'))])],'n'),
 svg('Story points resolved per month',[(TEAM,cols[3],get(M,'points_resolved'))],'n'),
 svg('Devin sessions per month (whole org) and those naming a team ticket',[('all sessions',cols[1],[dv['monthly'][m]['sessions'] for m in months]),('team ticket sessions',cols[0],[dv['monthly'][m]['team_ticket_sessions'] for m in months])],'n'),
 svg('Devin ACUs per month (whole org) and on team tickets',[('all ACUs',cols[1],[dv['monthly'][m]['acus'] for m in months]),('team ticket ACUs',cols[0],[dv['monthly'][m]['team_ticket_acus'] for m in months])],'n')]
rows=''.join(f'<tr><td>{k}</td><td>{f(b.get(k))}</td><td>{f(me["after_kb"].get(k))}</td></tr>' for k in ['resolved','points_resolved','lead_days_median','cycle_days_median','defects_created','reopened_issues','carried_over_sprints','ai_used_resolved'])
sis=''.join(f'<tr><td>{html.escape(t)}</td>'+''.join(f'<td>{f(out["teams"][t]["baseline"].get(k))}</td>' for k in ['resolved','lead_days_median','cycle_days_median','defects_created','ai_used_resolved'])+'</tr>' for t in [TEAM]+SIS)
CSS='<style>body{font-family:Segoe UI,Arial,sans-serif;margin:16px;color:#222}h1{font-size:20px;color:#500}h2{font-size:15px;margin-top:22px}.s{color:#666;font-size:12px}table{border-collapse:collapse;font-size:12px;margin:6px 0}td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}th{background:#f4eef8}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:12px}</style>'
page=f'<!doctype html><html><head><meta charset=utf-8><title>Efficiency gain from KB</title>{CSS}</head><body><h1>Efficiency gain from the KB — {html.escape(TEAM)}</h1><p class=s>Baseline {B0} → {START-dt.timedelta(days=1)} (left of the red line). Months after the KB start date {START} are added on each refresh. Jira project {C["project"]}, {len(I):,} issues read {meta["read_at"]}; Devin {dv["sessions"]} sessions. Sources: kb/_EVIDENCE/files/kb-gain-jira.json, kb-gain-devin.json; doc kb/context/KB_EFFICIENCY_GAIN.md.</p>'+\
 f'<h2>Team: baseline vs after KB start</h2><table><tr><th>Measure</th><th>Baseline 12 months</th><th>After KB start</th></tr>{rows}</table>'+\
 f'<div class=g>{"".join(charts)}</div><h2>Sister teams, baseline window</h2><table><tr><th>IT Team</th><th>Resolved</th><th>Median lead days</th><th>Median cycle days</th><th>Defects created</th><th>ai-used resolved</th></tr>{sis}</table>'+\
 '<h2>Still needed (VALIDATE_KB)</h2><p class=s>KB start date, onboarding baseline, ai-used label rules and exceptions, sister team choice, hours per point, support time, start statuses, Devin member list access, price per ACU.</p></body></html>'
os.makedirs(K+'/VISUALIZATION',exist_ok=True);open(K+'/VISUALIZATION/KB_EFFICIENCY_GAIN.html','w').write(page)
print('teams',[TEAM]+SIS,'baseline',b,'devin',dv['sessions'],dv['acus'])
