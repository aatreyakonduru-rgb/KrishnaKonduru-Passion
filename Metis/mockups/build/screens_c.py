"""Screens 9-12: Feedback review, Promote, Audit, Teams, Settings."""
from common import frame, screen


def s9():
    left = ('<div class="hd">Thumbs-down <span>11</span></div><div class="ls">'
            '<div class="it on"><span class="chip er">wrong</span><div class="t">Answer on STATUS_CD<div class="s">S. Iyer &middot; today</div></div></div>'
            '<div class="it"><span class="chip wn">outdated</span><div class="t">KB file RPT_AGING<div class="s">M. Chen &middot; 2 d</div></div></div>'
            '<div class="it"><span class="chip gr">unclear</span><div class="t">Answer on LOAD_CLAIMS<div class="s">P. Gomez &middot; 3 d</div></div></div></div>')
    main = ('<div class="bd"><div class="kp"><div><b>86%</b><span class="mu">answers rated up</span></div><div><b>11</b><span class="mu">down this month</span></div><div><b class="w1">4</b><span class="mu">need a decision</span></div></div>'
            '<b>Answer on STATUS_CD</b> <span class="cf m">Confidence shown: Medium</span><h4 style="margin-top:6px">Reason from S. Iyer</h4><p style="margin:0">Category: Wrong fact. "RPT_OPEN_CLAIMS stopped reading STATUS_CD last release."</p>'
            '<h4 style="margin-top:6px">What the KB used</h4><span class="cite">open_claims.sql:9</span> <span class="chip wn">file changed after last refresh</span>'
            '<div style="margin-top:8px"><span class="btn p">Start a fix task</span> <span class="btn">Create a question</span> <span class="btn">Dismiss with reason</span></div>'
            '<p class="mu">Every decision here is logged with your name and reason. It does not change the KB on its own.</p></div>')
    right = ('<h4>Reasons this month</h4><table><tr><td>Wrong fact</td><td>4</td></tr><tr><td>Out of date</td><td>3</td></tr><tr><td>Missing something</td><td>2</td></tr><tr><td>Unclear</td><td>2</td></tr></table>'
             '<h4 style="margin-top:8px">Most flagged files</h4><div>RPT_OPEN_CLAIMS (3)<br>CLAIM_HDR (2)</div>'
             '<h4 style="margin-top:8px">Confidence vs rating</h4><div class="mu">High-band answers rated up 94%. Low-band rated up 41%. If this gap shrinks, the bands need retuning.</div>')
    return screen("s9", "9. Feedback review (leads)", "Where thumbs-down reasons land. Leads see the reason, what the KB used, and decide: fix, ask a question, or dismiss. All logged.",
                  frame("fb", main, left=left, right=right))


def s10():
    main = ('<div class="bd"><div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><b>Rebuild next environment</b><span class="chip ol">SIT</span>&rarr;<span class="chip ol">UAT1</span><span class="sp"></span><span class="mu">Trigger: release 24.11</span></div>'
            '<div class="kp"><div><b>412</b><span class="mu">in SIT</span></div><div><b>398</b><span class="mu">same in UAT1</span></div><div><b class="w1">11</b><span class="mu">differ</span></div><div><b class="b1">3</b><span class="mu">only in SIT</span></div></div>'
            '<table><tr><th>File</th><th>Difference</th><th>Why</th></tr>'
            '<tr><td>CLAIM_HDR</td><td>UAT1 has 20 columns, SIT has 19</td><td><span class="chip src">source</span></td></tr>'
            '<tr><td>LOAD_CLAIMS</td><td>Runs hourly in UAT1</td><td><span class="chip src">source</span></td></tr>'
            '<tr><td>PROVIDER_CFG</td><td>Different config keys</td><td><span class="chip evi">evidence</span></td></tr></table>'
            '<div class="co">Nothing is copied from SIT. UAT1 is rebuilt from its own sources, then compared.</div>'
            '<span class="btn p">Rebuild UAT1</span> <span class="btn">Dry run</span> <span class="btn d">PROD locked: not enabled for this APM</span></div>')
    left = ('<div class="hd">Environments</div><div class="ls"><div class="it"><div class="t">DEV<div class="s">refreshed 2 d</div></div></div><div class="it on"><div class="t">SIT<div class="s">refreshed 1 d</div></div></div>'
            '<div class="it"><div class="t">UAT1<div class="s">rebuilt 7 Nov</div></div></div><div class="it"><div class="t">UAT2<div class="s">not built</div></div></div>'
            '<div class="it"><div class="t">PREPROD<div class="s">not built</div></div></div><div class="it"><div class="t">IR<div class="s">not built</div></div></div><div class="it"><div class="t">PROD &#128274;<div class="s">disabled</div></div></div></div>')
    return screen("s10", "10. Compare and promote", "Promote means rebuild the next environment from its own sources, then compare. Environment list comes from Settings.",
                  frame("prom", main, left=left, tabs=""))


def s11():
    main = ('<div class="bd"><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px"><div><h4>Teams and roles</h4>'
            '<table><tr><th>Team</th><th>Members</th><th>Approves</th></tr>'
            '<tr><td>Backend</td><td>6</td><td>services, APIs</td></tr><tr><td>Middleware</td><td>3</td><td>integration, queues</td></tr>'
            '<tr><td>Data</td><td>5</td><td>tables, ETL, lineage</td></tr><tr><td>UI</td><td>4</td><td>screens, configs</td></tr>'
            '<tr><td>AI</td><td>2</td><td>models, prompts</td></tr><tr><td>Infra</td><td>2</td><td>environments, pipelines</td></tr>'
            '<tr><td>PO and BSA</td><td>3</td><td>business rules, questions</td></tr></table>'
            '<p><span class="btn">Add team</span> <span class="btn">Import from Okta groups</span></p></div>'
            '<div><h4>Who can do what</h4><table><tr><th>Action</th><th>Lead</th><th>Member</th><th>PO/BSA</th><th>Reader</th></tr>'
            '<tr><td>Read KB</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>'
            '<tr><td>Ask</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td></tr>'
            '<tr><td>Answer question</td><td>&#10003;</td><td>&#10003;</td><td>&#10003;</td><td></td></tr>'
            '<tr><td>Start refresh</td><td>&#10003;</td><td>&#10003;</td><td></td><td></td></tr>'
            '<tr><td>Approve own area</td><td>&#10003;</td><td></td><td>business only</td><td></td></tr>'
            '<tr><td>Approve any</td><td>one named lead</td><td></td><td></td><td></td></tr>'
            '<tr><td>Rebuild an environment</td><td>&#10003;</td><td></td><td></td><td></td></tr></table>'
            '<div class="co">Approver lists are stored in the KB repo. A change to them needs approval from a second person.</div></div></div></div>')
    left = ('<div class="hd">Teams</div><div class="ls"><div class="it on"><div class="t">Backend</div></div><div class="it"><div class="t">Middleware</div></div><div class="it"><div class="t">Data</div></div>'
            '<div class="it"><div class="t">UI</div></div><div class="it"><div class="t">AI</div></div><div class="it"><div class="t">Infra</div></div><div class="it"><div class="t">PO and BSA</div></div></div>')
    return screen("s11", "11. Teams and approval rights", "Not only UI developers. Define teams (backend, middleware, data, UI, AI, infra, PO, BSA) and which kinds of files each can approve.",
                  frame("team", main, left=left))


def s12():
    main = ('<div class="bd"><h4>Environments</h4><table><tr><th>Name</th><th>Snowflake MCP</th><th>Data</th><th>Sources</th><th>Refresh</th><th>On</th></tr>'
            '<tr><td>DEV</td><td>FIN-DEV</td><td>desensitised</td><td>Bitbucket, Jira, Confluence, Snowflake</td><td>weekly</td><td><span class="sw"></span></td></tr>'
            '<tr><td>SIT</td><td>FIN-SIT</td><td>desensitised</td><td>Bitbucket, Jira, Confluence, Snowflake</td><td>weekly</td><td><span class="sw"></span></td></tr>'
            '<tr><td>UAT1</td><td>not set</td><td>masked</td><td>Bitbucket, Jira, Confluence</td><td>on release</td><td><span class="sw"></span></td></tr>'
            '<tr><td>UAT2</td><td>not set</td><td>masked</td><td>Bitbucket, Jira, Confluence</td><td>on release</td><td><span class="sw off"></span></td></tr>'
            '<tr><td>PREPROD</td><td>not set</td><td>masked</td><td>Bitbucket, Jira, Confluence</td><td>on release</td><td><span class="sw off"></span></td></tr>'
            '<tr><td>IR</td><td>not set</td><td>masked</td><td>Bitbucket, Jira, Confluence</td><td>on release</td><td><span class="sw off"></span></td></tr>'
            '<tr><td>PROD</td><td>not set</td><td>to confirm</td><td>locked</td><td>on release</td><td><span class="sw off"></span></td></tr></table>'
            '<p><span class="btn">Add environment</span> <span class="btn">Reorder promotion path</span></p>'
            '<h4>Connections</h4><span class="chip ok">Bitbucket: FIN service account</span> <span class="chip ok">Jira DC: UEP service id</span> <span class="chip ok">Confluence</span> <span class="chip wn">Snowflake MCP: per signed-in user</span>'
            '<h4 style="margin-top:8px">Rules</h4><div><span class="sw"></span> Require reason on thumbs-down &nbsp; <span class="sw"></span> Pattern scan before PR (required for PROD) &nbsp; <span class="sw"></span> Pull the KB each time the app wakes</div></div>')
    tabs = '<div class="tabs"><span class="on">Environments</span><span>Detected setup</span><span>Connections</span><span>Refresh schedule</span><span>Confidence rules</span><span>Sensitivity</span></div>'
    return screen("s12", "12. Settings: environments are configurable", "Environments (DEV, SIT, UAT1, UAT2, PREPROD, IR, PROD, or your own) are defined here, not in code. Each has its own sources, data type and schedule.",
                  frame("set", main, tabs=tabs))


def s13():
    main = ('<div class="bd"><table><tr><th>When</th><th>Env</th><th>Who</th><th>Action</th><th>Type</th><th>Detail</th><th>Role</th><th>PR</th></tr>'
            '<tr><td>13 Nov 09:14</td><td>SIT</td><td>K. Konduru</td><td>Approved</td><td><span class="chip src">source</span></td><td>claim_hdr.sql 4c1d9e0 to 7be41a2</td><td>FIN_DEV_RO</td><td>#212</td></tr>'
            '<tr><td>12 Nov 16:40</td><td>SIT</td><td>S. Iyer</td><td>Answered Q-0041</td><td><span class="chip evi">evidence</span></td><td>9 claims added</td><td>n/a</td><td>#211</td></tr>'
            '<tr><td>12 Nov 11:05</td><td>SIT</td><td>S. Iyer</td><td>Thumbs-down</td><td><span class="chip gr">feedback</span></td><td>"RPT_OPEN_CLAIMS stopped reading STATUS_CD"</td><td>n/a</td><td></td></tr>'
            '<tr><td>12 Nov 10:02</td><td>SIT</td><td>M. Chen</td><td>Rejected</td><td><span class="chip evi">evidence</span></td><td>"Quotes do not match new page"</td><td>n/a</td><td>#208</td></tr>'
            '<tr><td>7 Nov 14:21</td><td>UAT1</td><td>A. Rao</td><td>Rebuild approved</td><td><span class="chip src">source</span></td><td>Release 24.11, Snowflake not refreshed</td><td>FIN_DEV_RO</td><td>#198</td></tr></table>'
            '<p class="mu">Entries are written to the KB repo so they survive the Devin machine being recycled. Names come from the signed-in Devin user.</p></div>')
    tabs = '<div class="tabs"><span class="on">All</span><span>Approvals</span><span>Feedback</span><span>Settings changes</span><span>Refresh runs</span></div>'
    return screen("s13", "13. Audit log", "Who, when, source change or evidence change, which role was used. Export for reviewers.",
                  frame("log", main, tabs=tabs))
