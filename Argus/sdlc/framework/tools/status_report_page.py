"""Put a status report on the shared Acme Claims page look (purple header, light/dark, print).

    python3 tools/status_report_page.py REPORT.html [REPORT.html ...] [-o OUT_DIR]

Pages that already use the kit are left alone. Acme Claims ticket keys become Jira links.
"""
import argparse, glob, html as H, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifact_kit
COL=[(r'#fff\b(?!f)','rgb(var(--bg-elevated))'),(r'#ffffff\b','rgb(var(--bg-elevated))'),(r'#1f2328\b','rgb(var(--text-primary))'),
     (r'#57606a\b','rgb(var(--text-secondary))'),(r'#f7f8fa\b','rgb(var(--tint-secondary))'),(r'#e5e7eb\b','rgb(var(--border-primary))'),
     (r'#3b82d4\b','rgb(var(--text-accent))')]
DROP={'*','*,*::before,*::after','body','html','.page','.header','.header h1','.header .meta','.container','.slide-container','h1'}
HEAD_DROP={'.meta','.slide-header','.slide-title','.slide-subtitle','.team-badge'}
MORE=[(r'#(222|333|111827|1e293b|0f172a|1f2937|24292f)\b','rgb(var(--text-primary))'),
      (r'#(555|666|777|6b7280|64748b|475569|4b5563|374151)\b','rgb(var(--text-secondary))'),
      (r'#(ddd|e2e8f0|cbd5e1|d0d7de|e1e4e8|eaecef|d1d5db)\b','rgb(var(--border-primary))'),
      (r'#(f5f5f5|fafafa|f8fafc|f6f8fa|f9fafb|f3f4f6|f1f5f9)\b','rgb(var(--tint-secondary))')]
BROWSE='https://jira.acme.example/browse/'
def link_keys(h):
    parts=re.split(r'(<a\b.*?</a>|<!--.*?-->|<[^>]+>)',h,flags=re.S)
    for i in range(0,len(parts),2):
        parts[i]=re.sub(r'\b(ACME-\d+)\b',lambda m:'<a class="key-link" href="%s%s" target="_blank" rel="noopener">%s</a>'%(BROWSE,m.group(1),m.group(1)),parts[i])
    return ''.join(parts)


def convert(p, out_dir=None):
    s=open(p).read()
    if 'a-header__title' in s:
        return None
    css=s.split('<style>',1)[1].split('</style>',1)[0] if '<style>' in s else ''
    body=s.split('<body>',1)[1].rsplit('</body>',1)[0] if '<body>' in s else re.split(r'<body[^>]*>',s,1)[1].rsplit('</body>',1)[0]
    title=re.sub(r'<[^>]+>','',re.search(r'<title>(.*?)</title>',s,re.S).group(1)).strip()
    sub=''
    hm=re.search(r'<div class="header">(.*?)</div>\s*(?=<div class="section"|<!--)',body,re.S)
    hc=None
    if not hm:
        hc=re.search(r'<div class="(?:container|slide-container)">\s*(?:<!--.*?-->\s*)?(<h1[^>]*>(.*?)</h1>\s*((?:<div class="meta">.*?</div>\s*)*)|<div class="slide-header">\s*((?:<div[^>]*>.*?</div>\s*)*)</div>)',body,re.S)
        if hc:
            if hc.group(2) is not None:
                title=re.sub(r'<[^>]+>','',hc.group(2)).strip()
                sub=' · '.join(re.sub(r'\s+',' ',m).strip() for m in re.findall(r'<div class="meta">(.*?)</div>',hc.group(3),re.S))
            else:
                inner=re.findall(r'<div class="([^"]+)">(.*?)</div>',hc.group(4),re.S)
                title=re.sub(r'<[^>]+>','',dict(inner).get('slide-title',title)).strip()
                sub=' · '.join(re.sub(r'\s+',' ',v).strip() for k,v in inner if k!='slide-title')
            body=body.replace(hc.group(1),'',1)
    if hm:
        h1=re.search(r'<h1[^>]*>(.*?)</h1>',hm.group(1),re.S); title=re.sub(r'<[^>]+>','',h1.group(1)).strip() if h1 else title
        sub=' · '.join(re.sub(r'\s+',' ',m).strip() for m in re.findall(r'<div class="meta">(.*?)</div>',hm.group(1),re.S))
        body=body.replace(hm.group(0),'',1)
    body=re.sub(r'^\s*<div class="page">','',body,1); 
    if hm: body=re.sub(r'</div>\s*$','',body.rstrip(),1)
    rules=[]
    for sel,decl in re.findall(r'([^{}]+)\{([^{}]*)\}',re.sub(r'/\*.*?\*/','',css,flags=re.S)):
        sel=sel.strip()
        if sel in DROP or sel.startswith('@') or (hc and sel in HEAD_DROP): continue
        rules.append('%s{%s}'%(', '.join('.sr '+x.strip() for x in sel.split(',')),decl.strip()))
    c='\n'.join(rules)
    for a,b in COL+MORE: c=re.sub(a,b,c,flags=re.I)
    sub=re.sub(r'Generated:\s*','as of ',sub)
    c+='\n.sr a.key-link{color:rgb(var(--text-accent));font-weight:600;text-decoration:none}.sr a.key-link:hover{text-decoration:underline}'
    c+='\n.sr a.key-link,.sr a[href*="/browse/"]{white-space:nowrap}\n.sr{font-size:14px;line-height:1.6}'
    title=H.unescape(title)
    out=artifact_kit.render_page(title,'<div class="sr">%s</div>'%link_keys(body),subtitle=sub,extra_css=c)
    dest=os.path.join(out_dir or os.path.dirname(p),os.path.basename(p))
    open(dest,'w').write(out)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="+")
    ap.add_argument("-o", "--out", default=None, help="write here instead of over the report")
    args = ap.parse_args(argv)
    for p in args.reports:
        dest = convert(p, args.out)
        print(("wrote %s" % dest) if dest else ("already on the kit: %s" % p))


if __name__ == "__main__":
    main()
