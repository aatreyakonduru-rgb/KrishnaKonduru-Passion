#!/usr/bin/env python3
"""Team-neutral Mētis KB generator. Reads kb/.metis/team.yaml (from detect_team.py) and the evidence saved in
kb/_EVIDENCE (Snowflake queries, Confluence pages and attachments, Jira 12-month pull, Devin wiki, Devin resources)
and writes a source-tagged KB into kb/. Read only towards every source; local files only.

    python3 team_kb.py [~/metis-work]
"""
import collections, datetime, glob, json, os, re, subprocess, sys
import yaml

W = os.path.abspath(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/metis-work'))
KB = W + '/kb'; EV = KB + '/_EVIDENCE'; TODAY = datetime.date.today().isoformat()
T = yaml.safe_load(open(KB + '/.metis/team.yaml'))
TEAM = T.get('team', {}); TNAME = TEAM.get('name') or T.get('application') or T['apm']
SF = T.get('snowflake', {}); DB0 = SF.get('dev_db', 'D01_CRCA')
PREF = tuple(SF.get('table_prefixes') or ())
QS = []


def wr(p, s):
    p = os.path.join(KB, p); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write(s.rstrip() + '\n')


def q(key, text, typ, pri, role, ctx, blocks):
    qid = f'Q-{len(QS) + 1:04d}'
    QS.append({'id': qid, 'key': key, 'question': text, 'type': typ, 'priority': pri, 'answer_role': role, 'context': ctx,
               'blocks': blocks, 'possible_answers': [], 'status': 'open', 'answer': None, 'answered_by': None,
               'answered_on': None, 'raised_on': TODAY, 'raised_by_build': 'team_kb.py'})
    return f'[?: {qid}]'


def qry(i):
    p = f'{EV}/queries/{i}.json'
    return json.load(open(p)) if os.path.exists(p) else []


def E(s): return f'[E: {s}]'


# ---------------- profile for verify_kb
prof_p = KB + '/.metis/kb-profile.yaml'
prof = yaml.safe_load(open(prof_p)) if os.path.exists(prof_p) else {}
prof.setdefault('product', {}).update({'name': TNAME, 'short_name': TEAM.get('short_name', ''), 'apm': T['apm']})
src = prof.setdefault('sources', {})
src['workspace_root'] = os.path.dirname(T['repos'][0]['path']) if T['repos'] else os.path.expanduser('~/repos')
src['repos'] = {r['name']: os.path.basename(r['path']) for r in T['repos']}
src.setdefault('jira', {})['secret'] = T['jira'].get('secret')
src.setdefault('confluence', {}).update({'secret': T['confluence'].get('secret'), 'spaces': [T['confluence'].get('space')]})
yaml.safe_dump(prof, open(prof_p, 'w'), sort_keys=False)

# ---------------- query .sql stubs (verify_kb needs <id>.sql next to <id>.json)
for j in glob.glob(f'{EV}/queries/*.json'):
    s = j[:-5] + '.sql'
    if not os.path.exists(s) and '.page' not in j:
        open(s, 'w').write(f'-- Read-only INFORMATION_SCHEMA query run through MCP snowflakenonprodmcp (sql_exec_tool); result in {os.path.basename(j)}\n')

# ---------------- Snowflake catalogue
tabs = {}
for i in ('CATALOG-TABLES-DEV-CRCA_ALL',):
    for r in qry(i):
        tabs[(r['TABLE_SCHEMA'], r['TABLE_NAME'])] = dict(r, q=i)
cols = collections.defaultdict(list)
for i in [os.path.basename(p)[:-5] for p in glob.glob(f'{EV}/queries/CATALOG-COLUMNS-*.json') if '.page' not in p]:
    for r in qry(i):
        cols[(r['TABLE_SCHEMA'], r['TABLE_NAME'])].append(dict(r, q=i))
byname = collections.defaultdict(list)
for k in tabs: byname[k[1]].append(k)
sit = {r['TABLE_NAME'] for r in qry('CATALOG-TABLES-SIT-CRCA_FIN')}

# ---------------- repos: SQL / Python parsing
TOK = r'((?:\$\{?\w+\}?|"?\w+"?)(?:\.(?:\$\{?\w+\}?|"?\w+"?)){0,2})'
TGT = [('INSERT', re.compile(r'\bINSERT\s+(?:OVERWRITE\s+)?INTO\s+' + TOK, re.I)), ('MERGE', re.compile(r'\bMERGE\s+INTO\s+' + TOK, re.I)),
       ('UPDATE', re.compile(r'^\s*UPDATE\s+' + TOK, re.I | re.M)), ('DELETE', re.compile(r'\bDELETE\s+FROM\s+' + TOK, re.I)),
       ('TRUNCATE', re.compile(r'\bTRUNCATE\s+(?:TABLE\s+)?(?:IF\s+EXISTS\s+)?' + TOK, re.I)),
       ('CREATE', re.compile(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:LOCAL\s+|GLOBAL\s+)?TEMP(?:ORARY)?\s+|TRANSIENT\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?' + TOK, re.I))]
SRC = re.compile(r'\b(?:FROM|JOIN|USING)\s+' + TOK, re.I)
KW = {'SELECT', 'DUAL', 'TABLE', 'LATERAL', 'VALUES', 'IDENTIFIER', 'INFORMATION_SCHEMA', 'WHERE', 'THE', 'ON'}
HDR = re.compile(r'#?\s*(TITLE|FILENAME|DESCRIPTION|TARGET TABLES?|SOURCE TABLES?)\s*:\s*(.+)', re.I)


def strip_comments(t):
    t = re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), t, flags=re.S)
    return re.sub(r'--[^\n]*', '', t)


def tname(raw):
    s = raw.replace('"', '').upper(); last = s.split('.')[-1]
    last = re.sub(r'\$\{?(\w+)\}?', r'{\1}', last)
    return last, s


def match_cat(last):
    if '{' in last:
        rx = re.compile('^' + re.escape(last).replace(r'\{', '{').replace(r'\}', '}').replace('{', '(?P<').replace('}', '>[A-Z0-9_]+)') + '$') if False else \
            re.compile('^' + re.sub(r'\\\{\w+\\\}', '[A-Z0-9_]+', re.escape(last)) + '$')
        return sorted({k for n, ks in byname.items() if rx.match(n) for k in ks})
    return byname.get(last, [])


R = {}  # repo -> data
for rp in T['repos']:
    root = rp['path']; name = rp['name']
    files = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True).stdout.split('\n')
    files = [f for f in files if f]
    scripts = {}
    for f in files:
        ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
        if ext not in ('sql', 'py'):
            continue
        txt = open(os.path.join(root, f), errors='ignore').read(); lines = txt.split('\n')
        hdr = {}
        for n, l in enumerate(lines[:40], 1):
            m = HDR.search(l)
            if m and m.group(2).strip():
                hdr.setdefault(m.group(1).upper().split()[0], (m.group(2).strip()[:220], n))
        body = strip_comments(txt) if ext == 'sql' else txt
        tg = collections.defaultdict(set); sr = collections.defaultdict(set)
        for n, l in enumerate(body.split('\n'), 1):
            for op, rx in TGT:
                for m in rx.finditer(l):
                    last, full = tname(m.group(1))
                    if last not in KW and len(last) > 2: tg[last].add((op, n))
            if ext == 'sql':
                for m in SRC.finditer(l):
                    last, full = tname(m.group(1))
                    if last not in KW and len(last) > 3 and not last.isdigit() and '(' not in last: sr[last].add(n)
        params = sorted(set(re.findall(r'\$\{(\w+)\}', txt)))
        funcs = [(m.group(1), txt[:m.start()].count('\n') + 1) for m in re.finditer(r'^def\s+(\w+)\s*\(', txt, re.M)] if ext == 'py' else []
        scripts[f] = {'ext': ext, 'lines': len(lines), 'hdr': hdr, 'tg': tg, 'sr': {k: v for k, v in sr.items() if k not in tg}, 'params': params, 'funcs': funcs}
    R[name] = {'root': root, 'files': files, 'scripts': scripts, 'meta': rp}


def mod_of(f):
    p = f.split('/')
    if p[:2] == ['scripts', 'sql'] and len(p) > 3: return 'sql/' + p[2]
    if p[:2] == ['scripts', 'sql']: return 'sql/(root)'
    if p[0] == 'scripts' and len(p) > 2: return p[1]
    return p[0] if len(p) > 1 else '(root)'


# ---------------- module docs + lineage
lineage = []; used_tables = collections.defaultdict(set)
mods_index = []
for name, D in R.items():
    mods = collections.defaultdict(list)
    for f in D['files']: mods[mod_of(f)].append(f)
    for m, fl in sorted(mods.items()):
        sc = [f for f in fl if f in D['scripts']]
        slug = m.replace('/', '_').replace('(', '').replace(')', '')
        L = [f'# Module {m} ({name})', '', f'Files under this folder of {name} at {D["meta"]["branch"]}@{D["meta"]["commit"]}: {len(fl)} ({len(sc)} SQL/Python). {E("kb:context/TEAM_PROFILE.md")}', '']
        exts = collections.Counter(f.rsplit('.', 1)[-1].lower() if '.' in f else '-' for f in fl)
        L += [f'- File types: ' + ', '.join(f'{k} {v}' for k, v in exts.most_common()) + f' {E("kb:context/TEAM_PROFILE.md")}', '']
        if sc:
            L += ['## Scripts', '', '| Script | Purpose (header) | Writes | Reads | Source |', '|---|---|---|---|---|']
        for f in sorted(sc):
            s = D['scripts'][f]
            d = s['hdr'].get('DESCRIPTION') or s['hdr'].get('TITLE')
            purpose = d[0].replace('|', '/') if d else ''
            ln = d[1] if d else 1
            tag = E(f'{name}/{f}:{ln}') if d else E(f'{name}/{f}:1')
            wt = sorted(s['tg']); rd = sorted(s['sr'])
            L.append(f"| `{f.split('/')[-1]}` | {purpose[:160] or '(no header)'} | {', '.join(wt[:6])}{' +' + str(len(wt) - 6) if len(wt) > 6 else ''} | {', '.join(rd[:6])}{' +' + str(len(rd) - 6) if len(rd) > 6 else ''} | {tag} |")
            for t, occ in s['tg'].items():
                op, n = sorted(occ, key=lambda x: x[1])[0]
                lineage.append({'repo': name, 'script': f, 'op': op, 'table': t, 'line': n, 'catalog': ['.'.join(k) for k in match_cat(t)][:5]})
                used_tables[t].add(f)
            for t, ns in s['sr'].items():
                lineage.append({'repo': name, 'script': f, 'op': 'READ', 'table': t, 'line': min(ns), 'catalog': ['.'.join(k) for k in match_cat(t)][:5]})
                used_tables[t].add(f)
        pys = [f for f in sc if D['scripts'][f]['ext'] == 'py']
        if pys:
            L += ['', '## Python functions', '']
            for f in pys:
                for fn, n in D['scripts'][f]['funcs'][:25]:
                    L.append(f'- `{f.split("/")[-1]}`: `{fn}()` {E(f"{name}/{f}:{n}")}')
        pr = collections.Counter(p for f in sc for p in D['scripts'][f]['params'])
        if pr:
            L += ['', f'## Parameters used (${{...}} placeholders) {E("kb:lineage/SCRIPT_TABLE_LINEAGE.yaml")}', '', ', '.join(f'`{k}` ({v})' for k, v in pr.most_common(30))]
        js = [f for f in fl if f.endswith('.json')]
        if js:
            L += ['', '## Parameter / config files', '']
            for f in js[:60]:
                L.append(f'- `{f}` {E(f"{name}/{f}:1")}')
            if len(js) > 60: L.append(f'- and {len(js) - 60} more JSON files in this folder {E("kb:context/TEAM_PROFILE.md")}')
        wr(f'etl/{slug}.md', '\n'.join(L))
        mods_index.append((m, slug, len(fl), len(sc)))

yaml.safe_dump({'source': 'regex parse of INSERT/MERGE/UPDATE/DELETE/TRUNCATE/CREATE targets and FROM/JOIN sources (comments removed); ${param} names kept as {param}',
                'edges': lineage}, open(KB + '/lineage/SCRIPT_TABLE_LINEAGE.yaml', 'w') if os.makedirs(KB + '/lineage', exist_ok=True) is None else None, sort_keys=False, width=200)

# ---------------- DB docs
team_schemas = SF.get('team_schemas') or []
reg = []
for sch in team_schemas:
    ts = sorted(k for k in tabs if k[0] == sch and (not PREF or sch == 'CRCA_FIN_ANTM' or k[1].startswith(PREF)))
    L = [f'# Schema {DB0}.{sch}', '', f'Tables and views read from {DB0}.INFORMATION_SCHEMA (DEV, read only). {E("query:CATALOG-TABLES-DEV-CRCA_ALL")}', '']
    if sch != 'CRCA_FIN_ANTM' and PREF:
        L += [f'- Only tables whose names start with {", ".join(PREF)} are listed here (team scope from team/settings/teams/{T["apm"]}.yaml). {E("settings:snowflake.table_prefixes")}' if False else
              f'- Only tables whose names start with {", ".join(PREF)} are listed (team scope set in .metis/team.yaml). {E("kb:context/TEAM_PROFILE.md")}', '']
    L += ['| Table | Type | Rows (DEV) | Columns | In SIT | Used by repo scripts | Last altered | Source |', '|---|---|---|---|---|---|---|---|']
    for k in ts:
        t = tabs[k]; c = cols.get(k, [])
        cq = c[0]['q'] if c else None
        L.append(f"| [{k[1]}](tables/{sch}.{k[1]}.md) | {t['TABLE_TYPE']} | {t['ROW_COUNT'] or ''} | {len(c) or ''} | {'yes' if k[1] in sit else ('no' if sch == 'CRCA_FIN_ANTM' else '')} | {len(used_tables.get(k[1], ()))} | {t['LAST_ALTERED']} | {E('query:CATALOG-TABLES-DEV-CRCA_ALL')} |")
        reg.append({'key': f'{DB0}.{sch}.{k[1]}', 'schema': sch, 'name': k[1], 'type': t['TABLE_TYPE'], 'rows': t['ROW_COUNT'], 'columns': len(c),
                    'used_by': sorted(used_tables.get(k[1], ())), 'evidence': 'query:CATALOG-TABLES-DEV-CRCA_ALL'})
        if c:
            CL = [f'# {DB0}.{sch}.{k[1]}', '', f'{t["TABLE_TYPE"]}, {t["ROW_COUNT"] or 0} rows in DEV, last altered {t["LAST_ALTERED"]}. {E("query:CATALOG-TABLES-DEV-CRCA_ALL")}', '',
                  f'## Columns {E("query:" + cq)}', '', '| # | Column | Type | Nullable |', '|---|---|---|---|']
            CL += [f"| {r['ORDINAL_POSITION']} | {r['COLUMN_NAME']} | {r['DATA_TYPE']} | {r['IS_NULLABLE']} |" for r in sorted(c, key=lambda r: int(r['ORDINAL_POSITION']))]
            us = sorted(used_tables.get(k[1], ()))
            if us:
                CL += ['', f'## Scripts that touch it {E("kb:lineage/SCRIPT_TABLE_LINEAGE.yaml")}', ''] + [f'- `{u}`' for u in us]
            wr(f'db/tables/{sch}.{k[1]}.md', '\n'.join(CL))
    wr(f'db/{sch}.md', '\n'.join(L))
yaml.safe_dump({'database': DB0, 'tables': reg}, open(KB + '/db/DB_TABLE_REGISTRY.yaml', 'w'), sort_keys=False, width=200)

# ---------------- drift
cat_names = set(byname)
repo_only = sorted(t for t in used_tables if '{' not in t and t not in cat_names and (not PREF or t.startswith(PREF)))
fin_unused = sorted(k[1] for k in tabs if k[0] == 'CRCA_FIN_ANTM' and k[1] not in used_tables and not any('{' in u and re.match('^' + re.sub(r'\\\{\w+\\\}', '[A-Z0-9_]+', re.escape(u)) + '$', k[1]) for u in used_tables))
qd = q('DRIFT', f'{len(repo_only)} team-prefixed tables written or read by repo scripts are not in {DB0} (DEV). Are they created at run time, dropped, or only in higher environments?', 'data', 'P2', 'data lead',
       [f'{E("kb:db/DB_DRIFT.md")}'], ['db/DB_DRIFT.md'])
L = ['# Database drift: repo scripts vs DEV catalogue', '', f'Compares table names parsed from the repo scripts with {DB0}.INFORMATION_SCHEMA. {E("kb:lineage/SCRIPT_TABLE_LINEAGE.yaml")} {E("query:CATALOG-TABLES-DEV-CRCA_ALL")}', '',
     f'## In the repo, not in {DB0} ({len(repo_only)}) {qd}', ''] + [f'- `{t}` used by {len(used_tables[t])} script(s), e.g. `{sorted(used_tables[t])[0]}`' for t in repo_only] + \
    ['', f'## In {DB0}.CRCA_FIN_ANTM, no script names it ({len(fin_unused)}) {E("query:CATALOG-TABLES-DEV-CRCA_ALL")}', ''] + [f'- `{t}`' for t in fin_unused]
wr('db/DB_DRIFT.md', '\n'.join(L))

# ---------------- Confluence
idx = json.load(open(EV + '/confluence/_INDEX.json')) if os.path.exists(EV + '/confluence/_INDEX.json') else []
RT = T['confluence'].get('team_root_title'); RI = set(T['confluence'].get('team_root_ids') or [])
teamp = [p for p in idx if (RT and RT in ' > '.join(p['path'])) or p['id'] in RI]
att = json.load(open(EV + '/confluence_att/_ATTACHMENTS.json')) if os.path.exists(EV + '/confluence_att/_ATTACHMENTS.json') else []
L = [f'# Confluence pages of {TNAME}', '', f'{len(idx)} pages read from space {T["confluence"].get("space")} (bearer token, GET only); {len(teamp)} sit under "{RT}". {E("file:confluence-index.json")}', '',
     '| Page | Path | Version | Updated | Source |', '|---|---|---|---|---|']
import shutil; os.makedirs(EV + '/files', exist_ok=True)
if os.path.exists(EV + '/confluence/_INDEX.json'): shutil.copy(EV + '/confluence/_INDEX.json', EV + '/files/confluence-index.json')
for p in sorted(teamp, key=lambda p: (' > '.join(p['path']), p['title'])):
    if os.path.exists(f"{EV}/confluence/{p['id']}-v{p['version']}.txt"):
        L.append(f"| {p['title'].replace('|', '/')} | {' > '.join(p['path'][2:]) or '-'} | {p['version']} | {p['updated'][:10]} | {E('confluence:' + p['id'] + '@v' + str(p['version']))} |")
if att:
    L += ['', f'## Attachments on these pages ({len(att)}) {E("file:confluence-attachments.json")}', '', '| Attachment | Page | Read as | Text file |', '|---|---|---|---|']
    shutil.copy(EV + '/confluence_att/_ATTACHMENTS.json', EV + '/files/confluence-attachments.json')
    L += [f"| {a['title'].replace('|', '/')} | {a['page_title'].replace('|', '/')} | {a.get('mode', 'listed')} | {a.get('file', '')} |" for a in att]
wr('context/CONFLUENCE_TEAM_PAGES.md', '\n'.join(L))
others = collections.Counter(p['path'][2] if len(p['path']) > 2 else (p['path'][1] if len(p['path']) > 1 else p['title']) for p in idx if p not in teamp)

# ---------------- Jira (team issues from 12-month pull)
JL = W + '/stage/jira12m/issues.jsonl'
I = [json.loads(l) for l in open(JL)] if os.path.exists(JL) else []
TV = T['jira'].get('team_value')
TI = [i for i in I if TV in (i.get('team') or [])]
os.makedirs(EV + '/jira', exist_ok=True)
for i in TI:
    json.dump({k: i.get(k) for k in ('key', 'type', 'status', 'cat', 'created', 'resolved', 'labels', 'points', 'team', 'components', 'fix', 'summary')},
              open(f"{EV}/jira/{i['key']}.json", 'w'), indent=1)
L = [f'# Jira work of {TV}', '', f'{len(TI)} issues of project {T["jira"]["project"]} with IT Team = {TV} created or resolved in the 12-month window (of {len(I)} project issues read, GET only). {E("file:jira12m-meta.json")}', '']
json.dump({'issues_read': len(I), 'team_issues': len(TI), 'team_value': TV, 'project': T['jira']['project'], 'read_on': TODAY,
           'by_status': collections.Counter(i['status'] for i in TI), 'by_type': collections.Counter(i['type'] for i in TI)}, open(EV + '/files/jira12m-meta.json', 'w'), indent=1)
L += ['## By type and status ' + E('file:jira12m-meta.json'), '', '| Type | Count |', '|---|---|'] + [f'| {k} | {v} |' for k, v in collections.Counter(i['type'] for i in TI).most_common()]
L += ['', '| Status | Count |', '|---|---|'] + [f'| {k} | {v} |' for k, v in collections.Counter(i['status'] for i in TI).most_common()]
opn = sorted([i for i in TI if i.get('cat') != 'done'], key=lambda i: i['created'], reverse=True)
L += ['', f'## Open work ({len(opn)})', '', '| Key | Type | Status | Summary | Source |', '|---|---|---|---|---|']
L += [f"| {i['key']} | {i['type']} | {i['status']} | {(i['summary'] or '').replace('|', '/')[:120]} | {E('jira:' + i['key'])} |" for i in opn[:300]]
epics = [i for i in TI if i['type'] == 'Epic']
if epics:
    L += ['', f'## Epics ({len(epics)})', ''] + [f"- {i['key']} {i['status']}: {(i['summary'] or '')[:140]} {E('jira:' + i['key'])}" for i in epics]
wr('context/JIRA_TEAM_WORK.md', '\n'.join(L))

# ---------------- Devin wiki: split full contents into pages
WF = EV + '/wiki/devin_wiki_crcafin_full.md'; wiki = []
if os.path.exists(WF):
    txt = open(WF).read(); parts = re.split(r'^# Page: (.+)$', txt, flags=re.M)
    for n in range(1, len(parts), 2):
        title = parts[n].strip(); body = parts[n + 1]
        fn = f'WIKI-{(n + 1) // 2:02d}-' + re.sub(r'[^A-Za-z0-9]+', '-', title)[:50].strip('-') + '.md'
        open(EV + '/files/' + fn, 'w').write(f'repo: {T["devin"]["wiki_repos"][0] if T["devin"]["wiki_repos"] else ""}\npage: {title}\ncaptured: {TODAY}\n\n{body}')
        srcs = sorted(set(re.findall(r'\[([\w./-]+\.(?:sql|py|json))(?::\d+(?:-\d+)?)?\]\(', body)))
        wiki.append((title, fn, len(body), srcs))
L = ['# Devin wiki (DeepWiki) pages', '', f'{len(wiki)} pages read with devin_read_wiki_contents for {", ".join(T["devin"]["wiki_repos"])}. The wiki is AI-written; its claims are kept as a pointer, not as KB facts. {E("file:" + "WIKI-01-Overview.md")}' if wiki else '# Devin wiki', '',
     '| # | Page | Chars | Repo files it cites (checked to exist) | Source |', '|---|---|---|---|---|']
allf = {f for D in R.values() for f in D['files']}
for n, (t, fn, c, s) in enumerate(wiki, 1):
    ok = [x for x in s if x in allf]
    L.append(f'| {n} | {t} | {c} | {len(ok)}/{len(s)} | {E("file:" + fn)} |')
wr('context/DEVIN_WIKI.md', '\n'.join(L))

# ---------------- Existing team KB (Devin knowledge notes, plugin skills, playbooks)
kn = sorted(glob.glob(EV + '/files/devin-knowledge-*.md'))
L = ['# Existing knowledge Devin already holds', '', f'Knowledge notes, playbooks and automations read from the org (read only). {E("file:devin-playbooks.txt")}', '', '## Knowledge notes', '']
team_kb_tables = {}
for p in kn:
    fn = os.path.basename(p); t = open(p, errors='ignore').read()
    m = re.search(r'knowledge_name:\s*"?([^"\n]+)', t); nm = m.group(1) if m else fn
    ph = '{' in t and re.search(r'\{(jira_project_name|it_team|confluence_space_key)\}', t)
    mentions = sorted(set(re.findall(r'\b((?:VB|WORK|VBC)_FNC_[A-Z0-9_]+)\b', t)))
    if mentions: team_kb_tables[fn] = mentions
    L.append(f'- {nm}: {len(t)} chars' + (f', names {len(mentions)} FIN tables' if mentions else '') + (' — has unfilled placeholders' if ph else '') + f' {E("file:" + fn)}')
    if ph:
        L[-1] += ' ' + q('KN-' + fn, f'Knowledge note "{nm}" still has template placeholders ({{jira_project_name}}, {{it_team}}...). Should it say Jira project {T["jira"]["project"]}, IT Team {TV}, space {T["confluence"].get("space")}?', 'access', 'P2', 'manager', [E('file:' + fn)], ['context/EXISTING_TEAM_KB.md'])
for fn, ms in team_kb_tables.items():
    ok = [m for m in ms if m in cat_names]; miss = [m for m in ms if m not in cat_names]
    L += ['', f'## Tables named in {fn} vs {DB0} {E("file:" + fn)} {E("query:CATALOG-TABLES-DEV-CRCA_ALL")}', '',
          f'- {len(ok)} of {len(ms)} exist in {DB0}; used by repo scripts: {sum(1 for m in ms if m in used_tables)}.']
    if miss:
        L.append(f'- Not in {DB0}: ' + ', '.join(f'`{m}`' for m in miss[:40]) + ' ' + q('KNT-' + fn, f'{len(miss)} tables named in knowledge note {fn} are not in {DB0}: {", ".join(miss[:10])}... Renamed, SIT/PROD only, or out of date?', 'data', 'P2', 'data lead', [E('file:' + fn)], ['context/EXISTING_TEAM_KB.md']))
pb = open(EV + '/files/devin-playbooks.txt').read() if os.path.exists(EV + '/files/devin-playbooks.txt') else ''
L += ['', '## Playbooks', ''] + [f'- {l.strip()[2:][:160]} {E("file:devin-playbooks.txt")}' for l in pb.splitlines() if l.strip().startswith('- ')]
au = open(EV + '/files/devin-automations.txt').read() if os.path.exists(EV + '/files/devin-automations.txt') else ''
L += ['', '## Automations', ''] + [f'- {l.strip()[:160]} {E("file:devin-automations.txt")}' for l in au.splitlines() if l.startswith('auto-')]
sk = sorted(glob.glob('/opt/.devin/plugins/cache/*/*/skills/*/SKILL.md'))
L += ['', '## Plugin skills installed in this session', '', f'- {len(sk)} skills across plugins: ' + ', '.join(sorted({p.split("/")[-5].replace("account-upload_", "").rsplit("-", 1)[0] for p in sk})) + f' {E("file:devin-plugin-skills.txt")}']
open(EV + '/files/devin-plugin-skills.txt', 'w').write('\n'.join(sk))
wr('context/EXISTING_TEAM_KB.md', '\n'.join(L))

# ---------------- Team profile and system overview
L = [f'# Team profile: {TNAME} ({T["apm"]})', '', f'Detected before the build by team/tools/detect_team.py; saved as .metis/team.yaml. {E("file:team.yaml")}', '',
     f'- Application: {T.get("application")} {E("file:team.yaml")}', f'- APM mapping row: {T.get("apm_mapping_row")} {E("file:devin-knowledge-apm-leader-mapping-jira-mapping.md")}',
     f'- Jira: project {T["jira"]["project"]}, IT Team field {T["jira"]["team_field"]} = {TV}; token {T["jira"]["secret"]} (checks {T["jira"]["checks"]}) {E("file:team.yaml")}',
     f'- Confluence: space {T["confluence"]["space"]}, team root "{RT}" {sorted(RI)}; token {T["confluence"]["secret"]} (checks {T["confluence"]["checks"]}) {E("file:team.yaml")}',
     f'- Snowflake: {DB0} (DEV), {SF.get("sit_db")} (SIT) via MCP {SF.get("mcp_server_prefix")}; role {(qry("IDENTITY-NONPROD") or [{}])[0].get("ROLE")} {E("query:IDENTITY-NONPROD")}',
     f'- Sister IT Teams in {T["jira"]["project"]} (last 90 days): {", ".join(T["jira"].get("sister_teams", [])[:10])} {E("file:team.yaml")}', '', '## Repos', '',
     '| Repo | Branch@commit | Remote branches | Files | Source |', '|---|---|---|---|---|']
L += [f"| {r['name']} | {r['branch']}@{r['commit']} | {r['remote_branches']} | {r['files']} | {E('file:team.yaml')} |" for r in T['repos']]
shutil.copy(KB + '/.metis/team.yaml', EV + '/files/team.yaml')
wr('context/TEAM_PROFILE.md', '\n'.join(L))

sch_rows = qry('DISCOVERY-SCHEMAS-DEV-CRCA')
L = [f'# System overview: {TNAME}', '', f'Counts from the sources read on {TODAY}. {E("kb:context/TEAM_PROFILE.md")}', '',
     f'- Repo files: {sum(len(D["files"]) for D in R.values())}; SQL/Python scripts parsed: {sum(len(D["scripts"]) for D in R.values())}; modules: {len(mods_index)} {E("kb:context/TEAM_PROFILE.md")}',
     f'- Script→table links: {sum(1 for e in lineage if e["op"] != "READ")} writes, {sum(1 for e in lineage if e["op"] == "READ")} reads, {len(used_tables)} distinct table names {E("kb:lineage/SCRIPT_TABLE_LINEAGE.yaml")}',
     f'- {DB0} schemas: {len(sch_rows)}; team schemas documented: {", ".join(team_schemas)}; tables in registry: {len(reg)} {E("query:DISCOVERY-SCHEMAS-DEV-CRCA")}',
     f'- Confluence: {len(idx)} pages in {T["confluence"]["space"]}, {len(teamp)} team pages, {len(att)} attachments {E("kb:context/CONFLUENCE_TEAM_PAGES.md")}',
     f'- Jira: {len(TI)} team issues in 12 months, {len(opn)} open {E("kb:context/JIRA_TEAM_WORK.md")}',
     f'- Devin wiki pages: {len(wiki)}; knowledge notes: {len(kn)} {E("kb:context/DEVIN_WIKI.md")}', '',
     '## Modules', '', '| Module | Files | Scripts | Doc |', '|---|---|---|---|'] + [f'| {m} | {n} | {s} | [etl/{sl}.md](../etl/{sl}.md) {E("kb:etl/" + sl + ".md")} |' for m, sl, n, s in mods_index]
L += ['', f'## Business purpose {q("PURPOSE", f"In one paragraph, what does {TNAME} deliver to the business, and who are its users? (No source states it in plain words; the Devin wiki is AI-written.)", "business", "P1", "product owner", [E("kb:context/DEVIN_WIKI.md")], ["context/SYSTEM_OVERVIEW.md"])}', '',
      'Not stated by a primary source yet; see the question.']
wr('context/SYSTEM_OVERVIEW.md', '\n'.join(L))

# ---------------- standard questions
q('OWNERS', f'Who owns the {TNAME} KB answers: product owner, dev lead, data lead, ETL lead (names)?', 'access', 'P1', 'manager', [E('kb:context/TEAM_PROFILE.md')], ['_QUESTIONS/VALIDATE_KB.yaml'])
q('SVC-TOKENS', f'The service tokens {[k for k, v in T["jira"]["checks"].items() if v != 200] + [k for k, v in T["confluence"]["checks"].items() if v != 200]} answered 401; only the _PAT tokens work. Should the service-account tokens be rotated?', 'access', 'P2', 'manager', [E('file:team.yaml')], ['context/TEAM_PROFILE.md'])
q('PROD', f'UAT/PROD Snowflake have no MCP connection here; the KB documents DEV ({DB0}) and SIT table lists only. Is DEV structure the same as PROD for the FIN schemas?', 'data', 'P2', 'data lead', [E('query:CATALOG-TABLES-SIT-CRCA_FIN')], ['db/'])

# ---------------- register + README
os.makedirs(KB + '/_QUESTIONS', exist_ok=True)
yaml.safe_dump({'questions': QS}, open(KB + '/_QUESTIONS/VALIDATE_KB.yaml', 'w'), sort_keys=False, allow_unicode=True, width=200)
TV_ = ['| # | What needs confirming | Why it is open | Who can confirm | Priority | Status | Answer | Answered by |', '|---|---|---|---|---|---|---|---|']
TV_ += [f"| {x['id']} | {x['question'].replace('|', '/')} | {' '.join(x['context']).replace('|', '/')} | {x['answer_role']} | {x['priority']} | Open | | |" for x in QS]
wr('TO_VALIDATE.md', '# Open questions\n\n' + '\n'.join(TV_))
docs = sorted(os.path.relpath(p, KB) for p in glob.glob(KB + '/**/*.md', recursive=True) if '/_EVIDENCE/' not in p and '/tables/' not in p)
wr('README.md', '\n'.join([f'# {TNAME} knowledge base ({T["apm"]})', '', f'Built locally by Mētis team-kb-refresh on {TODAY}; read only from every source. {E("kb:context/TEAM_PROFILE.md")}', '',
                           '## Contents', ''] + [f'- [{d}]({d})' for d in docs] + ['', f'- db/tables/: {len(glob.glob(KB + "/db/tables/*.md"))} table pages']))
print(f'KB: {len(docs)} docs, {len(glob.glob(KB + "/db/tables/*.md"))} table pages, {len(lineage)} lineage edges, {len(QS)} questions, team issues {len(TI)}, conf team pages {len(teamp)}, wiki {len(wiki)}')
