#!/usr/bin/env python3
"""Detect the team this Devin session belongs to and write kb/.metis/team.yaml (read only, GET requests only).

    python3 detect_team.py [--work ~/metis-work] [--repos ~/repos]

Order: APM number (org knowledge notes, then srcAPM* secret names) -> preset team/settings/teams/<APM>.yaml
(if any) -> connected repos (~/repos) -> working Jira / Confluence tokens (srcAPM<apm>* env vars, first one
that answers 200) -> Jira project and IT Team values -> Confluence space and team root page -> Snowflake
schemas named in the repo param files. Anything it cannot decide is listed under `open:`.
"""
import argparse, glob, json, os, re, ssl, subprocess, sys, urllib.request, urllib.parse, collections
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = '/opt/.devin/plugins/cache'
JIRA = 'https://jira.elevancehealth.com'
CONF = 'https://confluence.elevancehealth.com'
CA = os.path.expanduser('~/.certs/wellpoint_chain.pem')


def ctx():
    c = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else ssl.create_default_context()
    return c


def get(url, token, timeout=60):
    r = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as f:
            return 200, json.load(f)
    except urllib.error.HTTPError as e:
        return e.code, None
    except ssl.SSLError:
        if os.environ.get('METIS_TLS_VERIFY', '1') != '0':
            return 'SSLError (set METIS_TLS_VERIFY=0 only if the certificate cannot be fixed)', None
        with urllib.request.urlopen(r, context=ssl._create_unverified_context(), timeout=timeout) as f:
            return 200, json.load(f)
    except Exception as e:
        return str(type(e).__name__), None


def knowledge_notes():
    out = {}
    for p in glob.glob(f'{CACHE}/*/*/skills/*/SKILL.md'):
        if 'knowledge' not in p.split('/')[-5]:
            continue
        out[p.split('/')[-2]] = open(p, errors='ignore').read()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default=os.path.expanduser('~/metis-work'))
    ap.add_argument('--repos', default=os.path.expanduser('~/repos'))
    a = ap.parse_args()
    notes = knowledge_notes()
    T = {'detected_by': 'team/tools/detect_team.py', 'open': []}
    # 1. APM
    apms = collections.Counter()
    for n in notes:
        for m in re.findall(r'apm(\d{7})-', n):
            apms[m] += 3
    for k in os.environ:
        m = re.match(r'srcAPM(\d{7})', k)
        if m:
            apms[m.group(1)] += 1
    if not apms:
        T['open'].append('No APM number found in knowledge notes or secrets')
        apm = None
    else:
        apm = apms.most_common(1)[0][0]
    T['apm'] = f'APM{apm}' if apm else None
    T['apm_candidates'] = [f'APM{k}' for k, _ in apms.most_common()]
    ctxnote = next((v for k, v in notes.items() if k.startswith(f'apm{apm}-') and k.endswith('-context')), '')
    m = re.search(r'^# APM\d+\s*-\s*(.+)$', ctxnote, re.M)
    T['application'] = re.sub(r'\s+Context$', '', m.group(1).strip()) if m else None
    mp = notes.get('apm-leader-mapping-jira-mapping', '')
    row = next((l for l in mp.splitlines() if f'APM{apm}' in l), '')
    T['apm_mapping_row'] = row.strip() or None
    # 2. preset
    preset = os.path.join(HERE, '..', 'settings', 'teams', f'APM{apm}.yaml')
    P = yaml.safe_load(open(preset)) if apm and os.path.exists(preset) else {}
    T['preset'] = os.path.basename(preset) if P else None
    T['pipeline'] = P.get('pipeline', 'team')
    T['team'] = P.get('team', {})
    # 3. repos
    repos = []
    for d in sorted(glob.glob(a.repos + '/*/.git')):
        root = os.path.dirname(d)
        g = lambda *c: subprocess.run(['git', '-C', root, *c], capture_output=True, text=True).stdout.strip()
        url = g('remote', 'get-url', 'origin')
        name = re.sub(r'\.git$', '', url.rstrip('/').split('/')[-1])
        repos.append({'name': name, 'path': root, 'remote': re.sub(r'^.*/proxy/', 'https://', url), 'branch': g('rev-parse', '--abbrev-ref', 'HEAD'),
                      'commit': g('rev-parse', '--short', 'HEAD'), 'remote_branches': len(g('branch', '-r').splitlines()), 'files': len(g('ls-files').splitlines())})
    T['repos'] = repos
    if not repos:
        T['open'].append(f'No git repos under {a.repos}')
    # 4. tokens
    cand = sorted(k for k in os.environ if apm and k.lower().startswith(f'srcapm{apm}'.lower()))
    T['secrets_seen'] = cand
    def pick(kind, url_fn):
        res = {}
        for k in sorted(cand, key=lambda x: (not x.endswith('_PAT'), x)):
            if kind.lower() not in k.lower():
                continue
            code, _ = get(url_fn(), os.environ[k])
            res[k] = code
            if code == 200:
                return k, res
            if code in (401, 403):
                continue
        return None, res
    jk, jr = pick('Jira', lambda: JIRA + '/rest/api/2/myself')
    ck, cr = pick('Conf', lambda: CONF + '/rest/api/space?limit=1')
    T['jira'] = {'base_url': JIRA, 'secret': jk, 'checks': jr}
    T['confluence'] = {'base_url': CONF, 'secret': ck, 'checks': cr}
    if not jk:
        T['open'].append(f'No working Jira token among {cand} (401/403 = rotate token)')
    if not ck:
        T['open'].append(f'No working Confluence token among {cand} (401/403 = rotate token)')
    # 5. Jira project / IT team
    proj = P.get('jira', {}).get('project')
    if not proj:
        m = re.search(r'\|\s*([A-Z][A-Z0-9]+)\s*\|\s*$', row) or re.search(r'\b([A-Z]{2,10})\b(?=[^|]*$)', row)
        proj = m.group(1) if m else None
    T['jira']['project'] = proj
    T['jira']['team_field'] = P.get('jira', {}).get('team_field', 'customfield_12479')
    if jk and proj:
        jql = urllib.parse.quote(f'project={proj} AND updated>=-90d')
        cnt = collections.Counter()
        for start in range(0, 2000, 500):
            code, d = get(f'{JIRA}/rest/api/2/search?jql={jql}&fields={T["jira"]["team_field"]}&maxResults=500&startAt={start}', os.environ[jk], 120)
            if code != 200 or not d:
                break
            for i in d['issues']:
                v = i['fields'].get(T['jira']['team_field'])
                v = v.get('value') if isinstance(v, dict) else (v[0].get('value') if isinstance(v, list) and v and isinstance(v[0], dict) else (v[0] if isinstance(v, list) and v else v))
                cnt[str(v)] += 1
            if start + 500 >= d.get('total', 0):
                break
        T['jira']['it_teams_90d'] = dict(cnt.most_common())
    tv = P.get('jira', {}).get('team_value')
    if not tv and T['jira'].get('it_teams_90d'):
        key = (T['application'] or '').split()[-1].upper()
        hits = [t for t in T['jira']['it_teams_90d'] if key and key[:3] in t.upper()]
        tv = hits[0] if len(hits) == 1 else None
        if not tv:
            T['open'].append(f'IT Team for {T["apm"]} not decided; candidates {list(T["jira"]["it_teams_90d"])[:8]}')
    T['jira']['team_value'] = tv
    T['jira']['sister_teams'] = [t for t in T['jira'].get('it_teams_90d', {}) if t != tv and t != 'None']
    # 6. Confluence
    space = P.get('confluence', {}).get('space')
    if not space:
        m = re.search(r'\b(?:space(?: key)?|Confluence)\s*[:=]?\s*([A-Z0-9]{3,10})\b', ctxnote + '\n' + mp)
        space = m.group(1) if m and '{' not in m.group(1) else None
    T['confluence']['space'] = space
    T['confluence']['team_root_title'] = P.get('confluence', {}).get('team_root_title')
    T['confluence']['team_root_ids'] = P.get('confluence', {}).get('team_root_ids', [])
    if not space:
        T['open'].append('Confluence space key not found')
    # 7. Snowflake schemas named in params
    sch = collections.Counter(); dbs = collections.Counter()
    for r in repos:
        for f in subprocess.run(['git', '-C', r['path'], 'ls-files', '*.json'], capture_output=True, text=True).stdout.split():
            try:
                t = open(os.path.join(r['path'], f), errors='ignore').read()
            except OSError:
                continue
            sch.update(re.findall(r'"(CRCA_[A-Z_]+|EDL_[A-Z_]+)"', t))
            dbs.update(re.findall(r'"([DTUP]01_[A-Z0-9_]+)"', t))
    T['snowflake'] = {'mcp_server_prefix': 'snowflakenonprodmcp', 'dev_db': P.get('snowflake', {}).get('dev_db', 'D01_CRCA'),
                      'sit_db': P.get('snowflake', {}).get('sit_db', 'T01_CRCA'),
                      'team_schemas': P.get('snowflake', {}).get('team_schemas', []),
                      'schemas_in_params': dict(sch.most_common(25)), 'databases_in_params': dict(dbs.most_common(10))}
    T['devin'] = {'knowledge_notes': sorted(notes), 'wiki_repos': [f"bitbucket.elevancehealth.com/{r['remote'].split('bitbucket.elevancehealth.com/')[-1]}" for r in repos]}
    os.makedirs(a.work + '/kb/.metis', exist_ok=True)
    yaml.safe_dump(T, open(a.work + '/kb/.metis/team.yaml', 'w'), sort_keys=False, allow_unicode=True, width=200)
    print(f"APM {T['apm']} ({T['application']}) pipeline={T['pipeline']} preset={T['preset']}")
    print(f"repos: {[r['name'] for r in repos]}")
    print(f"jira: {proj} team={tv} secret={jk} | confluence: {space} secret={ck}")
    print('open:', T['open'] or 'none')


if __name__ == '__main__':
    main()
