"""Fill the gallery data for a team KB (after make_graph.py and build_data_cvbc.py) and write argus/gallery.html.

    python3 team_gallery.py

Business areas are the repo modules; zones are the team schemas; every value comes from LINK_GRAPH.yaml,
the Snowflake catalog evidence, the repo param files or the KB context files.
"""
import collections, datetime, glob, json, os, pickle, re, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('METIS_WORK', os.path.expanduser('~/metis-work'))
K = os.environ.get('METIS_KB', W + '/kb')
Q = K + '/_EVIDENCE/queries'
L = lambda p: yaml.load(open(p), Loader=yaml.CSafeLoader) if os.path.isfile(p) else {}
T = L(K + '/.metis/team.yaml')
prof = L(K + '/.metis/kb-profile.yaml')
NAME = (T.get('team') or {}).get('name') or 'Team'
SHORT = (T.get('team') or {}).get('short_name') or ''
SCH = (T.get('snowflake') or {}).get('team_schemas') or []
DEVDB = (T.get('snowflake') or {}).get('dev_db') or ''
D = json.load(open(W + '/argus/mag_data.json'))
g = pickle.load(open(W + '/graph.pkl', 'rb'))
E = g['edges']
nm = lambda i: i.split(':', 1)[1]
tn = lambda k: k.split('.')[-1]
mod_of = {nm(e['from']): nm(e['to']) for e in E if e['rel'] == 'part of'}
short_mod = lambda m: m.replace('scripts/sql/', '').replace('scripts/', '')
IO = collections.defaultdict(lambda: {'read_by': set(), 'written_by': set()})
for e in E:
    if e['rel'] in ('reads', 'writes') and e['to'].startswith('table:'):
        IO[nm(e['to'])]['read_by' if e['rel'] == 'reads' else 'written_by'].add(nm(e['from']))
for j in D['jobs']:
    full = next((s for s in mod_of if s.endswith('/' + j['id'])), None)
    if full:
        j['desc'] = 'job in ' + short_mod(mod_of[full])
# business areas = modules
area_t = collections.defaultdict(collections.Counter)
for k, v in IO.items():
    for j in v['read_by'] | v['written_by']:
        if j in mod_of:
            area_t[short_mod(mod_of[j])][tn(k)] += 1
areas = sorted(area_t, key=lambda a: -sum(area_t[a].values()))[:12]
D['objects'] = [{'id': a, 'label': a, 'table': area_t[a].most_common(1)[0][0], 'aliases': [a], 'key': '', 'types': 0} for a in areas]
D['objTables'] = {a: [t for t, _ in area_t[a].most_common(12)] for a in areas}
rels = []
for i, a in enumerate(areas):
    for b in areas[i + 1:]:
        sh = set(area_t[a]) & set(area_t[b])
        if sh:
            t = max(sh, key=lambda x: area_t[a][x] + area_t[b][x])
            rels.append({'name': f'{a} shares {t} with {b}', 'fo': a, 'to': b, 'ft': t, 'tt': t, 'card': f'{len(sh)} shared tables'})
D['rels'] = sorted(rels, key=lambda r: -int(r['card'].split()[0]))[:16]
# catalog
use = collections.defaultdict(lambda: {'r': set(), 'w': set()})
for k, v in IO.items():
    use[tn(k)]['r'] |= {short_mod(mod_of.get(j, j)) for j in v['read_by']}
    use[tn(k)]['w'] |= {short_mod(mod_of.get(j, j)) for j in v['written_by']}
cols = collections.defaultdict(list)
for f in glob.glob(Q + '/CATALOG-COLUMNS-*.json'):
    if '.page' in f:
        continue
    for c in json.load(open(f)):
        cols[(c['TABLE_SCHEMA'], c['TABLE_NAME'])].append(c['COLUMN_NAME'])
cat = {}
for f in sorted(glob.glob(Q + '/CATALOG-TABLES-*.json')):
    if '.page' in f:
        continue
    env = f.split('CATALOG-TABLES-')[1].split('-')[0]
    db = DEVDB if env == 'DEV' else (T.get('snowflake') or {}).get('sit_db') or env
    seen = {x[0] for s in cat.get(db, {}).values() for x in s}
    for t in json.load(open(f)):
        if t['TABLE_NAME'] in seen and t['TABLE_SCHEMA'] in cat.get(db, {}):
            continue
        u = use.get(t['TABLE_NAME'].upper(), {'r': set(), 'w': set()})
        cl = cols.get((t['TABLE_SCHEMA'], t['TABLE_NAME']), [])
        cat.setdefault(db, {}).setdefault(t['TABLE_SCHEMA'], []).append(
            [t['TABLE_NAME'], (t.get('TABLE_TYPE') or 'T')[0], t.get('ROW_COUNT') or '', len(cl), cl[:80], sorted(u['r']), sorted(u['w'])])
D['cat'] = cat
# flow zones = team schemas
Z = [s for s in SCH] + ['Other %s schemas' % DEVDB]
zone = lambda k: SCH.index(k.split('.')[1]) if k.split('.')[1] in SCH else len(SCH)
TT, Sc, Ed = {}, [], collections.Counter()
def tid(k):
    if k not in TT:
        TT[k] = [len(TT), zone(k), k.split('.')[1], tn(k)]
    return TT[k][0]
jobs = collections.defaultdict(lambda: [set(), set()])
for k, v in IO.items():
    for j in v['read_by']:
        jobs[j][0].add(k)
    for j in v['written_by']:
        jobs[j][1].add(k)
for j, (r, w) in sorted(jobs.items()):
    if not w:
        continue
    si = len(Sc)
    Sc.append(j)
    for a in r:
        for b in w:
            if a != b:
                Ed[(tid(a), tid(b), si)] += 1
D['flow'] = {'zones': Z, 't': [[x[1], x[2], x[3]] for x in sorted(TT.values())], 's': Sc, 'e': [list(k) for k in Ed]}
D['modTables'] = {a: sorted(area_t[a]) for a in area_t}
# systems: schemas outside the team schemas that the jobs read; team tables read by other schemas' jobs not known
inb = collections.defaultdict(set)
for k, v in IO.items():
    if k.split('.')[1] not in SCH and v['read_by']:
        inb[k.rsplit('.', 1)[0]].add(tn(k))
D['systems'] = [{'id': f'INB-{i + 1:03d}', 'dir': 'in', 'name': f'{s} → {NAME} jobs', 'sys': s, 'tables': sorted(v)[:12]}
                for i, (s, v) in enumerate(sorted(inb.items(), key=lambda kv: -len(kv[1])))]
# states: value lists in the repo param files
st = []
root = (prof.get('sources') or {}).get('workspace_root') or os.path.expanduser('~/repos')
for rd in ((prof.get('sources') or {}).get('repos') or {}).values():
    for f in sorted(glob.glob(os.path.join(root, rd, '**/*param*/**/*.json'), recursive=True) + sorted(glob.glob(os.path.join(root, rd, '**/*param*.json'), recursive=True))):
        for l in open(f, errors='ignore'):
            m = re.match(r'\s*"([^"]+)"\s*:\s*"(.*)",?\s*$', l)
            if m and m.group(2).count("'") >= 4 and len(st) < 25 and m.group(1) not in {s['name'] for s in st}:
                st.append({'name': m.group(1), 'desc': 'param list (%s)' % os.path.relpath(f, os.path.join(root, rd)),
                           'values': [[v, ''] for v in re.findall(r"'([^']*)'", m.group(2))[:20]]})
D['states'] = st
# metrics: measure-like columns of the main team schema
mets = []
for (s, t), cl in sorted(cols.items()):
    if SCH and s != SCH[0]:
        continue
    for n in cl:
        if re.search(r'(_RT|_RATE|_SCR|_SCORE|_PCT|_AMT|_CNT|_PMPM|_WT)$', n) and len(mets) < 40:
            mets.append({'label': n, 'area': s, 'means': f'{t}.{n}'})
D['metrics'] = mets
# processes: statement order inside the biggest jobs (lineage line order)
lin = L(K + '/lineage/SCRIPT_TABLE_LINEAGE.yaml').get('edges') or []
bys = collections.defaultdict(list)
for e in lin:
    bys[e['script']].append(e)
pr = []
for s, es in sorted(bys.items(), key=lambda kv: -len(kv[1]))[:4]:
    es = sorted(es, key=lambda e: e['line'])
    wr = [e for e in es if e['op'] != 'READ']
    stages = []
    for i, w in enumerate(wr[:12]):
        nxt = wr[i + 1]['line'] if i + 1 < len(wr) else 10 ** 9
        rd = [e['table'] for e in es if e['op'] == 'READ' and w['line'] <= e['line'] < nxt]
        stages.append({'stage': f"{w['op']}_{w['table']}"[:40], 'tables': sorted(set(rd))[:6], 'trigger': 'file start' if i == 0 else 'previous statement'})
    pr.append({'name': os.path.basename(s), 'desc': f'Statement order inside {s} ({len(wr)} write statements, line order). Run order between files: see VALIDATE_KB.', 'stages': stages})
D['processes'] = pr
ch = []
for k, v in sorted(IO.items(), key=lambda kv: -(len(kv[1]['read_by']) + len(kv[1]['written_by'])))[:8]:
    rd, wr = v['read_by'], v['written_by']
    n = len(rd) + len(wr)
    ch.append({'id': f'DC-{len(ch) + 1:03d}', 'attr': tn(k), 'name': f"{tn(k)} ({k.split('.')[1]})",
               'risk': 'CRITICAL' if n > 40 else 'HIGH' if n > 15 else 'MEDIUM' if n > 5 else 'LOW',
               'w': [{'layer': 'ETL', 'item': j[:70], 'action': 'writes'} for j in sorted(wr)[:4]],
               'r': [{'layer': 'ETL', 'item': j[:70], 'action': 'reads'} for j in sorted(rd)[:5]],
               'ch': [{'layer': 'DB', 'action': f"Change {tn(k)} in {k.split('.')[1]}", 'effort': 'MEDIUM'},
                      {'layer': 'ETL', 'action': f'Recheck {len(wr)} writer and {len(rd)} reader jobs', 'effort': 'HIGH' if n > 15 else 'MEDIUM'}]})
D['chains'] = ch
rules = []
for f in ('context/SYSTEM_OVERVIEW.md', 'context/TEAM_PROFILE.md', 'context/EXISTING_TEAM_KB.md'):
    p = os.path.join(K, f)
    if os.path.isfile(p):
        rules += [{'kind': f.split('/')[-1][:-3].lower(), 'rule': l.split(' [E:')[0][2:]} for l in open(p) if l.startswith('- ') and '[E:' in l]
D['rules'] = rules[:17]
D['counts'].update({'screens': 0, 'questions': len((L(K + '/_QUESTIONS/VALIDATE_KB.yaml').get('questions') or []))})
D['sources'] = {'ontology': 'kb/CROSS-LAYER/ONTOLOGY.yaml', 'graph': 'kb/CROSS-LAYER/LINK_GRAPH.yaml', 'manifest': 'kb/README.md',
                'dev': 'kb/db/DB_TABLE_REGISTRY.yaml', 'sit': 'kb/db/DB_DRIFT.md', 'gates': 'kb/_QUESTIONS/VALIDATE_KB.yaml', 'roles': 'kb/.metis/team.yaml'}
co, epc = collections.Counter(), collections.Counter()
for j in D['jobs']:
    ts = sorted(set(j['r']) | set(j['w']))
    for t in ts:
        epc[t] += 1
    for i in range(len(ts)):
        for k in range(i + 1, len(ts)):
            co[(ts[i], ts[k])] += 1
at = [t for t, _ in epc.most_common(40)]
D['arc'] = {'tables': at, 'links': [[a, b, n] for (a, b), n in co.most_common(400) if a in at and b in at][:150], 'eps': {t: epc[t] for t in at}}
# stories: Jira keys in commit messages -> files changed -> tables those files read or write
import subprocess
pk = (T.get('jira') or {}).get('project') or 'CVBC'
ftab = collections.defaultdict(set)
for e in lin:
    ftab[e['script']].add(e['table'])
sto = collections.defaultdict(set)
for rd in ((prof.get('sources') or {}).get('repos') or {}).values():
    r = subprocess.run(['git', '-C', os.path.join(root, rd), 'log', '--all', '--name-only', '--format=@@%s'], capture_output=True, text=True).stdout
    keys = []
    for l in r.splitlines():
        if l.startswith('@@'):
            keys = sorted(set(re.findall(r'\b%s-\d+\b' % re.escape(pk), l)))
        elif l.strip() and keys:
            for k in keys:
                sto[k].add(l.strip())
D['stories'] = [{'id': k, 'files': [{'f': f, 't': sorted(ftab.get(f, ()))[:12]} for f in sorted(v)[:40]]} for k, v in sorted(sto.items(), key=lambda kv: -len(kv[1]))[:30]]
json.dump(D, open(W + '/argus/mag_data.json', 'w'), separators=(',', ':'), default=list)
# splice into the gallery template
tpl = open(os.path.join(HERE, '..', '..', 'cvbc', 'assets', 'gallery_template_cvbc.html')).read()
i = tpl.index('const DATA=') + len('const DATA=')
_, end = json.JSONDecoder().raw_decode(tpl, i)
t = tpl[:i] + open(W + '/argus/mag_data.json').read() + tpl[end:]
t = re.sub(r"const DATA_ASOF='[^']*'", "const DATA_ASOF='%s'" % datetime.date.today().strftime('%d %b %Y'), t)
label = f'{NAME} ({SHORT})' if SHORT else NAME
t = t.replace('CVBC KNOWLEDGE BASE', label.upper() + ' KNOWLEDGE BASE').replace('CVBC KB - Visualization gallery', label + ' KB - Visualization gallery').replace('crcaui/UI-KB/', 'kb/')
t = t.replace('CVBC ', NAME + ' ').replace('CVBC_ONTOLOGY.yaml', 'CROSS-LAYER/ONTOLOGY.yaml')
for a, b in [('const G=DATA.gates.filter(g=>/^SDLC/.test(g.id)),n=G.length', 'let G=DATA.gates.filter(g=>/^SDLC/.test(g.id));if(!G.length)G=DATA.gates;const n=G.length'),
             ('const cols=["screen","endpoint","table","job","system"],{nodes,edges}=lgNodes(cols.concat([]))', 'const cols=DATA.screens.length?["screen","endpoint","table","job","system"]:["job","table","endpoint","system"],{nodes,edges}=lgNodes(cols.concat([]))'),
             ('const scr=by.screen.map(n=>n.id);let i=0;light(scr[0]);', 'const scr=by[cols[0]].map(n=>n.id);let i=0;if(scr.length)light(scr[0]);'),
             ('The Argus approval gates in the order approval-gates.yaml lists them.', 'The KB review steps from VALIDATE_KB, grouped by question type and the role that answers.')]:
    t = t.replace(a, b)
t = t.replace('let cur=DATA.stories[0].id;', 'if(!DATA.stories.length){$("#stage").innerHTML="<p>No Jira keys in the commit messages.</p>";return}let cur=DATA.stories[0].id;')
open(W + '/argus/gallery.html', 'w').write(t)
print({k: (len(v) if hasattr(v, '__len__') else v) for k, v in D.items()}, 'gallery', len(t))
