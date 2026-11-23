"""Build the visualization pages of a team KB (ontology/link graph, lineage, impact, ERD, tech stack, KB health).

    python3 team_viz.py [<kb>]

Writes kb/lineage/SCRIPT_TABLE.links.yaml (script -> table reads/writes, script -> module, from the lineage file)
and kb/db/CODE_JOINS.links.yaml (column joins the SQL runs), every link with its file:line source, then runs
gen_graph.py, gen_matrix.py, detect_stack.py and gen_visuals.py. Tables are linked only when the catalog has them.
"""
import collections, glob, os, re, subprocess, sys, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', '..', 'tools')
KB = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/metis-work/kb'))
L = lambda p: yaml.load(open(p), Loader=yaml.CSafeLoader) if os.path.isfile(p) else {}
T = L(KB + '/.metis/team.yaml')
prof = L(KB + '/.metis/kb-profile.yaml')
pref = (T.get('snowflake') or {}).get('team_schemas') or []
root = (prof.get('sources') or {}).get('workspace_root') or os.path.expanduser('~/repos')
repos = (prof.get('sources') or {}).get('repos') or {}
reg = L(KB + '/db/DB_TABLE_REGISTRY.yaml').get('tables') or []
by_name = collections.defaultdict(list)
for t in reg:
    by_name[t['name'].upper()].append(t)
rank = lambda t: (pref.index(t['schema']) if t['schema'] in pref else len(pref), t['key'])


def table_key(name):
    c = by_name.get(name.strip('"').split('.')[-1].upper())
    return sorted(c, key=rank)[0]['key'] if c else None


def module_of(script):
    p = script.split('/')
    return '/'.join(p[:3]) if len(p) > 3 else '/'.join(p[:-1]) or script


links, mods, left = [], set(), 0
for e in L(KB + '/lineage/SCRIPT_TABLE_LINEAGE.yaml').get('edges') or []:
    k = table_key(e['table']) if e.get('catalog') else None
    if not k:
        left += 1
        continue
    src = '[E: %s/%s:%s]' % (e['repo'], e['script'], e['line'])
    links.append({'from': {'type': 'job', 'name': e['script']}, 'rel': 'reads' if e['op'] == 'READ' else 'writes',
                  'to': {'type': 'table', 'name': k}, 'source': src})
    if e['script'] not in mods:
        mods.add(e['script'])
        links.append({'from': {'type': 'job', 'name': e['script']}, 'rel': 'part of',
                      'to': {'type': 'module', 'name': module_of(e['script'])}, 'source': '[E: %s/%s:1]' % (e['repo'], e['script'])})
os.makedirs(KB + '/lineage', exist_ok=True)
yaml.safe_dump({'links': links}, open(KB + '/lineage/SCRIPT_TABLE.links.yaml', 'w'), sort_keys=False, width=200)

# joins the SQL runs: FROM/JOIN <table> <alias> ... <alias>.<col> = <alias>.<col>
cols = collections.defaultdict(set)
for f in glob.glob(KB + '/_EVIDENCE/queries/CATALOG-COLUMNS-*.json'):
    try:
        for c in yaml.load(open(f), Loader=yaml.CSafeLoader) or []:
            cols[(c.get('TABLE_SCHEMA'), c.get('TABLE_NAME'))].add(c.get('COLUMN_NAME'))
    except Exception:
        pass
TB = re.compile(r'\b(?:FROM|JOIN)\s+((?:[\w${}"]+\.){0,2}[\w"]+)\s+(?:AS\s+)?(\w+)', re.I)
EQ = re.compile(r'\b(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\b')
KW = {'ON', 'WHERE', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'JOIN', 'GROUP', 'ORDER', 'UNION', 'SET', 'USING', 'LATERAL', 'CROSS', 'OUTER', 'QUALIFY', 'WHEN', 'AND', 'AS'}
joins, seen = [], set()
for repo, d in repos.items():
    base = os.path.join(root, d)
    for f in sorted(glob.glob(base + '/**/*.sql', recursive=True)):
        txt = re.sub(r'--[^\n]*', lambda m: ' ' * len(m.group()), open(f, errors='ignore').read())
        al = {}
        for m in TB.finditer(txt):
            if m.group(2).upper() in KW:
                continue
            k = table_key(m.group(1))
            if k:
                al[m.group(2).upper()] = k
        for m in EQ.finditer(txt):
            a, ca, b, cb = m.group(1).upper(), m.group(2).upper(), m.group(3).upper(), m.group(4).upper()
            if a not in al or b not in al or al[a] == al[b]:
                continue
            ka, kb = al[a], al[b]
            sa, sb = ka.split('.')[-2:], kb.split('.')[-2:]
            if cols and (ca not in cols.get(tuple(sa), ()) or cb not in cols.get(tuple(sb), ())):
                continue
            pair = tuple(sorted([(ka, ca), (kb, cb)]))
            if pair in seen:
                continue
            seen.add(pair)
            line = txt.count('\n', 0, m.start()) + 1
            joins.append({'from': {'type': 'column', 'name': '%s.%s' % (ka, ca)}, 'rel': 'joins',
                          'to': {'type': 'column', 'name': '%s.%s' % (kb, cb)},
                          'source': '[E: %s/%s:%d]' % (repo, os.path.relpath(f, base), line)})
yaml.safe_dump({'links': joins}, open(KB + '/db/CODE_JOINS.links.yaml', 'w'), sort_keys=False, width=200)
print('links', len(links), 'left out (no catalog table)', left, 'joins', len(joins))
for cmd in (['gen_graph.py', KB], ['gen_matrix.py', KB], ['detect_stack.py', 'detect', KB, '--all', '--no-questions'], ['gen_visuals.py', KB]):
    r = subprocess.run([sys.executable, os.path.join(TOOLS, cmd[0])] + cmd[1:], capture_output=True, text=True)
    print(cmd[0], r.returncode, (r.stdout + r.stderr).strip()[-400:])
