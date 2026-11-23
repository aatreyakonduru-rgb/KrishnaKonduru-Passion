"""Screens 14-20: Coverage, Golden questions, Context pack, Ticket to impact, Onboarding, Live run, Glossary."""
from common import frame, screen


def s14():
    left = ('<div class="hd">Coverage by type</div><div class="ls">'
            '<div class="it on"><div class="t">Repositories<div class="s">6 of 6 read</div></div></div>'
            '<div class="it"><div class="t">Tables<div class="s">118 of 131 have a file</div></div></div>'
            '<div class="it"><div class="t">Jobs and ETL<div class="s">64 of 70</div></div></div>'
            '<div class="it"><div class="t">APIs<div class="s">73 of 73</div></div></div>'
            '<div class="it"><div class="t">Screens<div class="s">41 of 52</div></div></div>'
            '<div class="it"><div class="t">SQL files parsed<div class="s">71% (11 failed)</div></div></div></div>')
    main = ('<div class="bd"><div class="kp"><div><b class="w1">90%</b><span class="mu">objects with a KB file</span></div><div><b class="w1">71%</b><span class="mu">edges from a parser</span></div><div><b class="b1">11</b><span class="mu">SQL files not parsed</span></div><div><b>38</b><span class="mu">objects with no owner</span></div></div>'
            '<h4>Exists in sources but not in the KB (tables)</h4><table><tr><th>Object</th><th>Where found</th><th>Why missing</th><th>Action</th></tr>'
            '<tr><td>CLAIM_AUDIT</td><td class="cite">fin-db/ddl/audit.sql:4</td><td>No page built</td><td><span class="btn">Add to next refresh</span></td></tr>'
            '<tr><td>TMP_LOAD_2</td><td class="cite">fin-etl/tmp.sql:1</td><td>Looks temporary</td><td><span class="btn">Exclude</span></td></tr>'
            '<tr><td>CLAIM_ADJ_V</td><td class="cite">fin-db/views/adj.sql:2</td><td>Parser failed (dynamic SQL)</td><td><span class="btn">Raise question</span></td></tr></table>'
            '<div class="co">Impact answers are only as complete as this page. Anything listed here can be missing from an impact result.</div></div>')
    right = ('<h4>Trend (last 6 refreshes)</h4><div class="mu">Objects with a file: 84, 85, 87, 88, 89, 90%<br>Edges parsed: 62, 64, 66, 69, 70, 71%</div>'
             '<h4 style="margin-top:8px">Unparsed SQL by reason</h4><table><tr><td>Dynamic SQL</td><td>6</td></tr><tr><td>Unsupported syntax</td><td>3</td></tr><tr><td>Missing schema</td><td>2</td></tr></table>')
    return screen("s14", "14. Coverage report", "What the KB does not know. Lists objects that exist in sources but have no file, SQL the parser could not read, and objects with no owner.",
                  frame("log", main, left=left, right=right))


def s15():
    left = ('<div class="hd">Question sets</div><div class="ls">'
            '<div class="it on"><div class="t">Claims core<div class="s">24 questions &middot; 92% pass</div></div></div>'
            '<div class="it"><div class="t">Member lookups<div class="s">18 &middot; 89% pass</div></div></div>'
            '<div class="it"><div class="t">From thumbs-down<div class="s">6 new &middot; not yet run</div></div></div></div>')
    main = ('<div class="bd"><div class="kp"><div><b class="g1">92%</b><span class="mu">pass, this refresh</span></div><div><b>94%</b><span class="mu">last release</span></div><div><b class="b1">-2 pts</b><span class="mu">change</span></div><div><b class="w1">publish waits</b><span class="mu">lead decides</span></div></div>'
            '<table><tr><th>Question</th><th>Expected</th><th>Now</th><th>Last</th></tr>'
            '<tr><td>Which jobs load CLAIM_HDR?</td><td>LOAD_CLAIMS</td><td class="g1">pass</td><td class="g1">pass</td></tr>'
            '<tr><td>What reads STATUS_CD?</td><td>3 objects</td><td class="b1">fail (2 found)</td><td class="g1">pass</td></tr>'
            '<tr><td>Who owns RAW_CLAIM_FEED?</td><td>Data team</td><td class="g1">pass</td><td class="g1">pass</td></tr>'
            '<tr><td>Is RPT_AGING used?</td><td>No</td><td class="w1">changed answer</td><td class="g1">pass</td></tr></table>'
            '<div class="co">The STATUS_CD answer got worse after this refresh: one read was lost. Look before approving.</div>'
            '<span class="btn p">Show what changed</span> <span class="btn">Add question</span> <span class="btn">Import from feedback</span></div>')
    return screen("s15", "15. Golden questions", "Known questions with approved answers, re-asked on every refresh. A drop in pass rate holds the approval until a lead looks.",
                  frame("fb", main, left=left))


def s16():
    left = ('<div class="hd">Build a pack from</div><div class="ls">'
            '<div class="it"><div class="t">Files I pick<div class="s">search and add</div></div></div>'
            '<div class="it on"><div class="t">A Jira ticket<div class="s">FIN-1432</div></div></div>'
            '<div class="it"><div class="t">A change (PR or diff)<div class="s">Bitbucket PR</div></div></div>'
            '<div class="it"><div class="t">A question<div class="s">use an Ask answer</div></div></div></div>')
    main = ('<div class="bd"><div style="display:flex;gap:8px;align-items:center"><b>Context pack: FIN-1432</b><span class="chip ol">SIT</span><span class="sp"></span><span class="mu">KB as of 12 Nov 2026, 06:02</span></div>'
            '<div style="margin:6px 0">Token budget: 6,000 &nbsp;<span class="bar" style="width:220px"><i style="width:68%"></i></span> &nbsp;4,080 used</div>'
            '<table><tr><th></th><th>Included</th><th>Why</th><th>Tokens</th></tr>'
            '<tr><td>&#9745;</td><td>CLAIM_HDR summary and columns</td><td>named in ticket</td><td>720</td></tr>'
            '<tr><td>&#9745;</td><td>LOAD_CLAIMS description</td><td>upstream, depth 1</td><td>540</td></tr>'
            '<tr><td>&#9745;</td><td>ClaimService, GET /claims</td><td>downstream, depth 1 to 2</td><td>1,010</td></tr>'
            '<tr><td>&#9745;</td><td>Impact list with citations</td><td>always</td><td>980</td></tr>'
            '<tr><td>&#9745;</td><td>Open questions Q-0044</td><td>blocks CLAIM_HDR</td><td>180</td></tr>'
            '<tr><td>&#9744;</td><td>RPT_OPEN_CLAIMS detail</td><td>depth 3, skipped for budget</td><td>650</td></tr></table>'
            '<div class="co">Every statement in the pack keeps its citation, so the agent can say where a fact came from.</div>'
            '<span class="btn p">Copy as Markdown</span> <span class="btn">Download</span> <span class="btn">Start Devin session with pack</span></div>')
    right = ('<h4>Options</h4><div><span class="sw"></span> Include upstream<br><span class="sw"></span> Include downstream<br><span class="sw"></span> Include open questions<br><span class="sw off"></span> Include AI-proposed edges<br><span class="sw"></span> Mark stale files</div>'
             '<h4 style="margin-top:8px">For agents</h4><div class="mu">The same pack can be fetched by an agent through a read tool (MCP or command line), using the same options.</div>'
             '<h4 style="margin-top:8px">Not included</h4><div class="mu">Sensitive files above your role. Other APMs.</div>')
    return screen("s16", "16. Context pack builder", "The KB's main output for AI sessions: a token-budgeted bundle with citations, built from a ticket, a change, files or a question.",
                  frame("ask", main, left=left, right=right))


def s17():
    main = ('<div class="bd"><div style="display:flex;gap:6px;align-items:center"><span class="inp" style="flex:1">FIN-1432</span><span class="btn p">Find impact</span></div>'
            '<div class="co" style="background:#eff6ff;border-color:#bfdbfe"><b>FIN-1432</b> Add STATUS_REASON to claim header. <span class="mu">Read from Jira with the UEP service id.</span></div>'
            '<div class="kp"><div><b>3</b><span class="mu">objects named</span></div><div><b>9</b><span class="mu">impacted</span></div><div><b>4</b><span class="mu">teams to tell</span></div><div><b class="w1">3</b><span class="mu">only proposed</span></div></div>'
            '<table><tr><th>Impacted</th><th>Type</th><th>Owner team</th><th>Basis</th><th>Suggested check</th></tr>'
            '<tr><td>LOAD_CLAIMS</td><td>job</td><td>Data</td><td><span class="chip src">parsed</span></td><td>Update insert list</td></tr>'
            '<tr><td>ClaimService</td><td>service</td><td>Backend</td><td><span class="chip src">parsed</span></td><td>Map new field</td></tr>'
            '<tr><td>GET /claims</td><td>API</td><td>Middleware</td><td><span class="chip wn">proposed</span></td><td>Contract test</td></tr>'
            '<tr><td>Claims screen</td><td>UI</td><td>UI</td><td><span class="chip wn">proposed</span></td><td>Show or hide field</td></tr></table>'
            '<div style="margin-top:6px"><span class="btn p">Post summary to ticket</span> <span class="btn">Copy as text</span> <span class="btn">Build context pack</span></div>'
            '<p class="mu">Posting uses the Jira service id. Text contains object names and citations only, so Jira\'s PHI and PII check is not triggered.</p></div>')
    return screen("s17", "17. Ticket to impact", "Paste a ticket key, get the impacted objects, owner teams and suggested checks. Matches how work arrives.",
                  frame("impact", main))


def s18():
    left = ('<div class="hd">Steps</div><div class="ls">'
            '<div class="it"><span class="g1">&#10003;</span><div class="t">1 APM and name</div></div>'
            '<div class="it"><span class="g1">&#10003;</span><div class="t">2 Repositories</div></div>'
            '<div class="it on"><span>3</span><div class="t">Confluence and Jira</div></div>'
            '<div class="it"><span>4</span><div class="t">Environments</div></div>'
            '<div class="it"><span>5</span><div class="t">Teams and approvers</div></div>'
            '<div class="it"><span>6</span><div class="t">Review and first build</div></div></div>')
    main = ('<div class="bd"><b>Step 3: Confluence and Jira</b><p class="mu" style="margin:2px 0 6px">Found from the APM and repos. Tick what is in scope.</p>'
            '<table><tr><th></th><th>Source</th><th>Found</th><th>Service account</th></tr>'
            '<tr><td>&#9745;</td><td>Confluence space FIN</td><td>212 pages</td><td>FIN svc</td></tr>'
            '<tr><td>&#9745;</td><td>Confluence space FIN-ARCH</td><td>48 pages</td><td>FIN svc</td></tr>'
            '<tr><td>&#9744;</td><td>Confluence space HR-POLICY</td><td>unrelated</td><td></td></tr>'
            '<tr><td>&#9745;</td><td>Jira project FIN</td><td>1,420 tickets</td><td>UEP service id</td></tr>'
            '<tr><td>&#9744;</td><td>Jira project FINOPS</td><td>310 tickets</td><td>UEP service id</td></tr></table>'
            '<div class="co">Credentials are not entered here. Each source uses the APM service account already stored as a Devin secret. <span class="chip ok">connection test passed</span></div>'
            '<span class="btn">Back</span> <span class="btn p">Next: environments</span></div>')
    right = ('<h4>What will be created</h4><div class="mu">A KB repo in Bitbucket with a folder per environment. A settings file. The first task: build SIT.</div>'
             '<h4 style="margin-top:8px">Needs an admin</h4><div class="mu">Devin secrets for the APM service accounts. Snowflake MCP access per user.</div>')
    return screen("s18", "18. Onboarding wizard", "How a new APM joins without hand-editing files: repos, spaces, environments, teams and approvers, then the first build.",
                  frame("set", main, left=left, right=right))


def s19():
    left = ('<div class="hd">Runs</div><div class="ls">'
            '<div class="it on"><span class="w1">&#9679;</span><div class="t">Refresh SIT<div class="s">running &middot; 14 min</div></div></div>'
            '<div class="it"><span class="g1">&#9679;</span><div class="t">Answer Q-0041<div class="s">done &middot; PR #211</div></div></div>'
            '<div class="it"><span class="b1">&#9679;</span><div class="t">Refresh DEV<div class="s">failed at verify</div></div></div></div>')
    main = ('<div class="bd"><div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><b>Refresh SIT</b><span class="chip wn">running</span><span class="sp"></span><span class="btn r">Stop</span></div>'
            '<table><tr><th>Step</th><th>Status</th><th>Time</th></tr>'
            '<tr><td>Clone repo and install Metis v2.0.0</td><td class="g1">done</td><td>1m</td></tr>'
            '<tr><td>Read Bitbucket, Jira, Confluence</td><td class="g1">done</td><td>6m</td></tr>'
            '<tr><td>Parse SQL and code</td><td class="g1">done</td><td>3m</td></tr>'
            '<tr><td>Write 17 files</td><td class="w1">running (11 of 17)</td><td>4m</td></tr>'
            '<tr><td>Verify citations</td><td class="mu">waiting</td><td></td></tr>'
            '<tr><td>Pattern scan</td><td class="mu">waiting</td><td></td></tr>'
            '<tr><td>Open one PR and close the session</td><td class="mu">waiting</td><td></td></tr></table>'
            '<h4 style="margin-top:8px">Log</h4><div class="cite" style="display:block;padding:4px 6px">06:14 wrote db/CLAIM_LINE.md<br>06:15 wrote etl/LOAD_CLAIMS.md</div></div>')
    right = ('<h4>Run</h4><table><tr><td class="mu">Started by</td><td>automation</td></tr><tr><td class="mu">Environment</td><td>SIT</td></tr><tr><td class="mu">Sources</td><td>Bitbucket, Jira</td></tr><tr><td class="mu">Cost so far</td><td>3.2 ACU</td></tr><tr><td class="mu">Limit</td><td>8 ACU</td></tr></table>'
             '<h4 style="margin-top:8px">If it fails</h4><div class="mu">The reason is shown here with a retry button. The session closes either way.</div>')
    return screen("s19", "19. Live run view", "Status, steps, cost and failure reasons for each task. One task, one PR, then the session closes.",
                  frame("run", main, left=left, right=right))


def s20():
    left = ('<div class="hd">Business terms</div><div class="sr">Search terms...</div><div class="ls">'
            '<div class="it on"><div class="t">Claim<div class="s">3 tables, 4 screens</div></div></div>'
            '<div class="it"><div class="t">Member<div class="s">5 tables</div></div></div>'
            '<div class="it"><div class="t">Provider<div class="s">UI configs</div></div></div>'
            '<div class="it"><div class="t">Adjustment<div class="s">2 jobs</div></div></div></div>')
    main = ('<div class="bd"><b>Claim</b> <span class="chip ol">business term</span><p style="margin:2px 0 6px">A request for payment for a service. Owned by Claims PO. <span class="cite">confluence FIN-1182</span></p>'
            '<table><tr><th>Where it lives</th><th>Objects</th></tr>'
            '<tr><td>Tables</td><td>CLAIM_HDR, CLAIM_LINE, CLAIM_STG</td></tr>'
            '<tr><td>Screens</td><td>Claims search, Claim detail, Adjustments, Aging</td></tr>'
            '<tr><td>Rules</td><td>Duplicate claim check, Status routing</td></tr>'
            '<tr><td>Reports</td><td>RPT_OPEN_CLAIMS, RPT_AGING</td></tr></table>'
            '<div style="margin-top:6px"><span class="btn">Suggest a synonym</span> <span class="btn">Propose a new term</span></div>'
            '<p class="mu">Terms are approved by a PO or BSA, then a lead. They are used by Ask and the context pack.</p></div>')
    return screen("s20", "20. Business glossary", "A view for PO and BSA: business terms mapped to tables, screens, rules and reports.",
                  frame("kb", main, left=left))



def s21():
    left = ('<div class="hd">Detected</div><div class="ls">'
            '<div class="it on"><div class="t">All<div class="s">11 checks &middot; 4 need attention</div></div></div>'
            '<div class="it"><div class="t">Devin organisation<div class="s">1 check</div></div></div>'
            '<div class="it"><div class="t">Repositories<div class="s">2 checks</div></div></div>'
            '<div class="it"><div class="t">Service accounts<div class="s">4 checks</div></div></div>'
            '<div class="it"><div class="t">MCP servers<div class="s">2 checks</div></div></div>'
            '<div class="it"><div class="t">Secrets (names only)<div class="s">2 checks</div></div></div></div>')
    main = ('<div class="bd"><div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><b>Detected setup</b>'
            '<span class="mu">scanned 13 Nov 06:02 in a Devin session</span><span class="sp"></span>'
            '<span class="btn">Re-scan</span> <span class="btn p">Save as expected setup</span></div>'
            '<table><tr><th>Area</th><th>Detected</th><th>Expected</th><th>Status</th></tr>'
            '<tr><td>Devin org</td><td>FIN (caller: Devin session)</td><td>FIN</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>KB repo</td><td>fin-kb, write allowed</td><td>fin-kb</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>Code repos</td><td>fin-claims-app, fin-etl-jobs, fin-reports</td><td>fin-claims-app, fin-etl-jobs</td><td><span class="chip wn">1 extra</span></td></tr>'
            '<tr><td>Bitbucket account</td><td>svc-fin-bb &middot; read, open PR</td><td>svc-fin-bb</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>Jira Data Center</td><td>UEP service id &middot; read, write &middot; FIN, CLM visible</td><td>UEP id, FIN</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>Confluence</td><td>token set, call returned 401</td><td>svc-fin-conf</td><td><span class="chip er">fails</span></td></tr>'
            '<tr><td>Artifactory</td><td>svc-fin-art &middot; read only</td><td>read only</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>MCP: Snowflake</td><td>org-level, per-user sign-in, cannot be tested here</td><td>per-user</td><td><span class="chip wn">not testable</span></td></tr>'
            '<tr><td>MCP: Atlassian</td><td>not configured</td><td>not used</td><td><span class="chip gr">n/a</span></td></tr>'
            '<tr><td>Secret JIRA_TOKEN</td><td>present</td><td>present</td><td><span class="chip ok">match</span></td></tr>'
            '<tr><td>Secret CONFLUENCE_TOKEN</td><td>missing</td><td>present</td><td><span class="chip er">missing</span></td></tr></table>'
            '<p class="mu">Differences from the expected setup show here and on Home. The expected setup is saved in the KB repo after a lead approves it.</p></div>')
    right = ('<h4>How it was found</h4><table>'
             '<tr><td class="mu">Run by</td><td>Devin session, FIN org</td></tr>'
             '<tr><td class="mu">Repos</td><td>Devin API and git remotes</td></tr>'
             '<tr><td class="mu">Accounts</td><td>one read-only call each</td></tr>'
             '<tr><td class="mu">MCP</td><td>Devin MCP config files</td></tr>'
             '<tr><td class="mu">Secrets</td><td>names only</td></tr></table>'
             '<h4 style="margin-top:8px">Never stored</h4><div class="mu">Token values, passwords, cookies, row data. Only names, hosts, access level and the result of each check.</div>'
             '<h4 style="margin-top:8px">Limits</h4><div class="mu">Sees only what this Devin session can see. Per-user sign-ins, such as Snowflake, are checked when a person runs the scan.</div>')
    tabs = '<div class="tabs"><span>Environments</span><span class="on">Detected setup</span><span>Connections</span><span>Refresh schedule</span><span>Confidence rules</span><span>Sensitivity</span></div>'
    return screen("s21", "21. Settings: detected setup", "Mētis scans the machine and Devin organisation it runs in, and lists repos, service accounts, MCP servers and secret names, with differences from the expected setup.",
                  frame("set", main, left=left, right=right, tabs=tabs))
