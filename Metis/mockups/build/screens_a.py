"""Screens 1-4: Home, KB files, KB map, Impact."""
from common import frame, screen


def s1():
    left = ('<div class="hd">Needs attention</div><div class="ls">'
            '<div class="it on"><span class="b1">&#9679;</span><div class="t">3 approvals waiting<div class="s">oldest 5 days</div></div></div>'
            '<div class="it"><span class="w1">&#9679;</span><div class="t">9 open questions<div class="s">2 assigned to you</div></div></div>'
            '<div class="it"><span class="w1">&#9679;</span><div class="t">17 stale pages<div class="s">Snowflake 14 weeks old</div></div></div>'
            '<div class="it"><span class="g1">&#9679;</span><div class="t">Last refresh passed<div class="s">212 of 212 citations</div></div></div>'
            '<div class="it"><span class="w1">&#9679;</span><div class="t">4 thumbs-down this week<div class="s">review in Feedback</div></div></div></div>')
    main = ('<div class="bd"><div class="kp"><div><b>412</b><span class="mu">KB files</span></div>'
            '<div><b class="g1">98.7%</b><span class="mu">Citations verified</span></div>'
            '<div><b class="w1">71%</b><span class="mu">SQL edges parsed</span></div>'
            '<div><b>86%</b><span class="mu">Answers rated up</span></div></div>'
            '<h4>Source freshness in SIT</h4><table><tr><th>Source</th><th>Last refreshed</th><th></th><th>Runs as</th></tr>'
            '<tr><td>Bitbucket code and DDL</td><td class="g1">2 days</td><td><span class="bar"><i style="width:95%"></i></span></td><td>FIN service account</td></tr>'
            '<tr><td>Jira Data Center</td><td class="g1">2 days</td><td><span class="bar"><i style="width:90%"></i></span></td><td>UEP service id</td></tr>'
            '<tr><td>Confluence</td><td class="w1">9 days</td><td><span class="bar"><i class="w" style="width:55%"></i></span></td><td>FIN service account</td></tr>'
            '<tr><td>Snowflake schema</td><td class="b1">14 weeks</td><td><span class="bar"><i class="b" style="width:15%"></i></span></td><td>signed-in person</td></tr></table>'
            '<h4 style="margin-top:8px">Recent activity</h4><table>'
            '<tr><td>PR #212 weekly refresh opened</td><td class="mu">today 06:02</td></tr>'
            '<tr><td>A. Rao approved #209 <span class="chip evi">evidence</span></td><td class="mu">11 Nov</td></tr>'
            '<tr><td>Rebuild for release 24.11 verified</td><td class="mu">7 Nov</td></tr></table></div>')
    return screen("s1", "1. Home", "Compact landing view. Left list is the work queue; main area is health and freshness. Environment picker is in the top strip.",
                  frame("home", main, left=left))


def s2():
    left = ('<div class="hd">KB files <span>412</span></div><div class="sr">Filter files...</div><div class="ls">'
            '<div class="tree"><div style="padding-left:8px"><b>&#9662; Database (118)</b></div>'
            '<div class="it on" style="padding-left:20px"><span class="chip src">table</span><div class="t">CLAIM_HDR<div class="s">AI summary ready</div></div></div>'
            '<div class="it" style="padding-left:20px"><span class="chip src">table</span><div class="t">CLAIM_LINE</div></div>'
            '<div class="it" style="padding-left:20px"><span class="chip src">table</span><div class="t">CLAIM_STG</div></div>'
            '<div style="padding-left:8px"><b>&#9656; ETL (64)</b></div><div style="padding-left:8px"><b>&#9656; Services (97)</b></div>'
            '<div style="padding-left:8px"><b>&#9656; APIs (73)</b></div><div style="padding-left:8px"><b>&#9656; UI (41)</b></div>'
            '<div style="padding-left:8px"><b>&#9656; Business rules (19)</b></div></div></div>')
    main = ('<div class="bd"><h4>AI summary</h4><p style="margin:0 0 6px">Header record for each insurance claim, one row per claim. Loaded nightly from CLAIM_STG. '
            'STATUS_CD drives claim routing in ClaimService and is masked for roles below FIN_ANALYST. '
            '<span class="cf m">Confidence: medium</span> <span class="mu">generated 12 Nov, not human-reviewed</span></p>'
            '<h4>Detailed description</h4><p style="margin:0 0 4px">The table has 19 columns. CLAIM_ID is the key. <span class="cite">fin-db/ddl/claim_hdr.sql:12</span> <span class="chip ok">verified</span></p>'
            '<p style="margin:0 0 4px">Loaded by LOAD_CLAIMS from CLAIM_STG. <span class="cite">fin-etl/load_claims.sql:44</span> <span class="chip ok">verified</span></p>'
            '<p style="margin:0 0 4px">STATUS_CD values are listed in Confluence. <span class="cite">confluence FIN-1182</span> <span class="chip wn">9 days old</span></p>'
            '<div class="co">Open question Q-0044: who sets STATUS_CD = X?</div>'
            '<div style="margin-top:6px"><span class="btn">&#128077; Useful</span> <span class="btn">&#128078; Not right</span> <span class="btn">Ask about this</span></div></div>')
    right = ('<h4>Properties</h4><table>'
             '<tr><td class="mu">Type</td><td>table</td></tr><tr><td class="mu">Environment</td><td>SIT</td></tr>'
             '<tr><td class="mu">Built under role</td><td>FIN_DEV_RO</td></tr><tr><td class="mu">Last approved</td><td>A. Rao, 11 Nov</td></tr>'
             '<tr><td class="mu">Citations</td><td>9 of 9 pass</td></tr><tr><td class="mu">Sensitivity</td><td>internal</td></tr></table>'
             '<h4 style="margin-top:8px">Where it sits in the chain</h4>'
             '<div class="co" style="background:#eff6ff;border-color:#bfdbfe">Layer 2 of 5: staging &rarr; <b>core table</b> &rarr; service &rarr; API &rarr; screen</div>'
             '<h4>Upstream (2)</h4><div>CLAIM_STG <span class="chip src">parsed</span><br>RAW_CLAIM_FEED <span class="chip wn">proposed</span></div>'
             '<h4 style="margin-top:6px">Downstream (5)</h4><div>LOAD_CLAIMS <span class="chip src">parsed</span><br>ClaimService <span class="chip src">parsed</span><br>GET /claims <span class="chip wn">proposed</span><br>RPT_OPEN_CLAIMS <span class="chip wn">proposed</span><br>Claims screen <span class="chip wn">proposed</span></div>'
             '<div style="margin-top:8px"><span class="btn">Open in map</span> <span class="btn">Impact</span></div>')
    return screen("s2", "2. KB files: list, summary, details", "Every KB file in a list. Selecting one shows an AI summary, the detailed description with citations, its properties, its place in the impact chain, and who is upstream and downstream.",
                  frame("kb", main, left=left, right=right))


def s3():
    svg = ('<svg viewBox="0 0 620 400" width="100%" height="100%"><defs><marker id="m" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#6b7280"/></marker></defs>'
           '<g stroke="#9aa3b0" stroke-width="1" fill="none" marker-end="url(#m)">'
           '<path d="M80 70 L170 110"/><path d="M80 140 L170 120"/><path d="M80 210 L170 150"/><path d="M240 120 L330 70"/><path d="M240 130 L330 130"/><path d="M240 140 L330 200"/>'
           '<path d="M395 70 L470 60"/><path d="M395 130 L470 120"/><path d="M395 200 L470 190"/><path d="M395 200 L470 270" stroke-dasharray="4 3"/><path d="M80 300 L170 300"/><path d="M240 300 L330 290"/><path d="M395 290 L470 330" stroke-dasharray="4 3"/></g>'
           '<g font-size="10" text-anchor="middle">'
           '<text x="80" y="22" font-weight="700" fill="#57606a">SOURCES</text><text x="205" y="22" font-weight="700" fill="#57606a">TABLES</text><text x="365" y="22" font-weight="700" fill="#57606a">JOBS AND SERVICES</text><text x="520" y="22" font-weight="700" fill="#57606a">APIS AND SCREENS</text>'
           '<rect x="20" y="55" width="80" height="26" rx="5" fill="#e5e7eb"/><text x="60" y="72">RAW_FEED</text>'
           '<rect x="20" y="125" width="80" height="26" rx="5" fill="#e5e7eb"/><text x="60" y="142">MEM_FEED</text>'
           '<rect x="20" y="195" width="80" height="26" rx="5" fill="#e5e7eb"/><text x="60" y="212">Confluence</text>'
           '<rect x="170" y="105" width="75" height="30" rx="5" fill="#2563eb"/><text x="207" y="124" fill="#fff" font-weight="700">CLAIM_HDR</text>'
           '<rect x="330" y="55" width="70" height="26" rx="5" fill="#dbeafe"/><text x="365" y="72">LOAD_CLAIMS</text>'
           '<rect x="330" y="117" width="70" height="26" rx="5" fill="#dbeafe"/><text x="365" y="134">ClaimService</text>'
           '<rect x="330" y="187" width="70" height="26" rx="5" fill="#dbeafe"/><text x="365" y="204">RPT_OPEN</text>'
           '<rect x="470" y="45" width="100" height="26" rx="5" fill="#dcfce7"/><text x="520" y="62">GET /claims</text>'
           '<rect x="470" y="107" width="100" height="26" rx="5" fill="#dcfce7"/><text x="520" y="124">POST /claims</text>'
           '<rect x="470" y="177" width="100" height="26" rx="5" fill="#fef3c7"/><text x="520" y="194">Claims screen</text>'
           '<rect x="470" y="257" width="100" height="26" rx="5" fill="#fef3c7"/><text x="520" y="274">Aging report</text>'
           '<rect x="20" y="287" width="80" height="26" rx="5" fill="#e5e7eb"/><text x="60" y="304">LINE_FEED</text>'
           '<rect x="170" y="285" width="75" height="30" rx="5" fill="#fee2e2"/><text x="207" y="304">CLAIM_LINE</text>'
           '<rect x="330" y="277" width="70" height="26" rx="5" fill="#dbeafe"/><text x="365" y="294">LineService</text>'
           '<rect x="470" y="317" width="100" height="26" rx="5" fill="#fee2e2"/><text x="520" y="334">unresolved SQL</text></g></svg>')
    left = ('<div class="hd">View</div><div class="ls"><div class="it on"><div class="t">By layer<div class="s">sources, tables, jobs, APIs, screens</div></div></div>'
            '<div class="it"><div class="t">By team<div class="s">backend, data, UI, middleware</div></div></div>'
            '<div class="it"><div class="t">By freshness<div class="s">colour by source age</div></div></div>'
            '<div class="it"><div class="t">By confidence<div class="s">colour by verified or proposed</div></div></div>'
            '<div class="it"><div class="t">Gaps only<div class="s">unparsed SQL, open questions</div></div></div></div>'
            '<div class="hd">Filters</div><div style="padding:6px 8px"><span class="sw"></span> parsed edges<br><span class="sw"></span> AI-proposed edges<br><span class="sw off"></span> other APMs<br><span class="sw"></span> unresolved</div>')
    right = ('<h4>Selected</h4><b>CLAIM_HDR</b> <span class="chip src">table</span><div class="mu">5 downstream, 2 upstream</div>'
             '<h4 style="margin-top:8px">Legend</h4>'
             '<span class="chip src">solid = parsed</span><br><span class="chip wn">dashed = AI-proposed</span><br><span class="chip er">red = unresolved</span>'
             '<h4 style="margin-top:8px">Map coverage</h4><div>412 nodes, 931 edges<br>71% edges parsed<br>11 SQL files not parsed</div>'
             '<div style="margin-top:8px"><span class="btn">Export PNG</span> <span class="btn">Export CSV</span></div>')
    main = '<div class="bd" style="padding:0;background:#fff">%s</div>' % svg
    tabs = '<div class="tabs"><span class="on">Whole KB</span><span>Neighbourhood of CLAIM_HDR</span><span>Cross-environment diff</span></div>'
    return screen("s3", "3. KB map: whole-KB visualisation", "The missing screen. All KB objects laid out by layer, with search, filters and colour modes. Click a node to see its details on the right; dashed lines mark edges not yet confirmed by a parser.",
                  frame("map", main, left=left, right=right, tabs=tabs))


def s4():
    left = ('<div class="hd">Start from</div><div class="sr">Pick a table, job, API...</div><div class="ls">'
            '<div class="it on"><span class="chip src">table</span><div class="t">CLAIM_HDR</div></div>'
            '<div class="it"><span class="chip src">table</span><div class="t">CLAIM_LINE</div></div>'
            '<div class="it"><span class="chip gr">job</span><div class="t">LOAD_CLAIMS</div></div></div>')
    main = ('<div class="bd"><div class="kp"><div><b>5</b><span class="mu">downstream</span></div><div><b>2</b><span class="mu">upstream</span></div><div><b class="w1">2</b><span class="mu">only proposed</span></div><div><b>3</b><span class="mu">owner teams</span></div></div>'
            '<h4>If CLAIM_HDR changes</h4><table><tr><th>Impacted</th><th>Type</th><th>Depth</th><th>Basis</th><th>Owner</th><th>Cite</th></tr>'
            '<tr><td>LOAD_CLAIMS</td><td>job</td><td>1</td><td><span class="chip src">parsed</span></td><td>Data</td><td class="cite">load_claims.sql:44</td></tr>'
            '<tr><td>ClaimService</td><td>service</td><td>1</td><td><span class="chip src">parsed</span></td><td>Backend</td><td class="cite">ClaimService.java:88</td></tr>'
            '<tr><td>GET /claims</td><td>API</td><td>2</td><td><span class="chip wn">proposed</span></td><td>Middleware</td><td class="cite">claims.yaml:31</td></tr>'
            '<tr><td>Claims screen</td><td>UI</td><td>3</td><td><span class="chip wn">proposed</span></td><td>UI</td><td class="cite">ClaimsPage.tsx:22</td></tr>'
            '<tr><td>RPT_OPEN_CLAIMS</td><td>report</td><td>2</td><td><span class="chip src">parsed</span></td><td>Data</td><td class="cite">open_claims.sql:9</td></tr></table>'
            '<div class="co">11 SQL files could not be parsed, so impact may be incomplete.</div>'
            '<span class="btn">Copy as ticket text</span> <span class="btn">Export CSV</span> <span class="btn">Notify owner teams</span></div>')
    return screen("s4", "4. Impact", "What breaks if I change this. Each row shows how it was found, who owns it and the source line. Depth and edge type are filters.",
                  frame("impact", main, left=left, tabs='<div class="tabs"><span class="on">Downstream</span><span>Upstream</span><span>Both</span></div>'))
