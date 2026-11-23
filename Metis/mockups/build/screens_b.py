"""Screens 5-8: Ask, Approve, Refresh, Questions."""
from common import frame, screen


def s5():
    left = ('<div class="hd">Conversations</div><div class="ls"><div class="it on"><div class="t">What breaks if I drop STATUS_CD?<div class="s">today</div></div></div>'
            '<div class="it"><div class="t">Which jobs load CLAIM_LINE?<div class="s">yesterday</div></div></div>'
            '<div class="it"><div class="t">Who owns RAW_CLAIM_FEED?<div class="s">10 Nov</div></div></div></div>')
    main = ('<div class="bd"><div class="bub me">What loads CLAIM_HDR and what breaks if I drop STATUS_CD?</div>'
            '<div class="bub bot"><b>LOAD_CLAIMS</b> loads CLAIM_HDR nightly from CLAIM_STG <span class="cite">[1]</span>. STATUS_CD is read by <b>ClaimService.getStatus</b> <span class="cite">[2]</span> and report <b>RPT_OPEN_CLAIMS</b> <span class="cite">[3]</span>. Dropping it breaks all three.'
            '<div style="margin-top:6px"><span class="cf h">Confidence: High</span> <span class="mu">5 of 5 claims cited, 1 source 9 days old</span></div>'
            '<div class="mu" style="margin-top:3px">Why this level: every claim has a parsed edge or a verified quote. Confluence evidence is 9 days old. Not checked: other APMs.</div>'
            '<div style="margin-top:6px"><span class="btn">&#128077;</span> <span class="btn">&#128078;</span> <span class="btn">Open impact</span> <span class="btn">Copy as ticket text</span></div></div>'
            '<div class="bub bot" style="background:#fff7ed;border:1px solid #fed7aa"><b>You marked this answer as not right. Why?</b><br>'
            '<span class="chip ol">Wrong fact</span> <span class="chip ol">Missing something</span> <span class="chip ol">Out of date</span> <span class="chip ol">Unclear</span> <span class="chip ol">Other</span>'
            '<div class="inp" style="display:block;margin:5px 0;height:34px">Tell us what is wrong. Optional detail helps the lead fix it.</div><span class="btn p">Send</span></div>'
            '<div class="inp" style="display:block;margin-top:8px">Ask a question about this KB...</div></div>')
    right = ('<h4>Answer basis</h4><table><tr><td class="cite">[1]</td><td>load_claims.sql:44</td></tr><tr><td class="cite">[2]</td><td>ClaimService.java:88</td></tr><tr><td class="cite">[3]</td><td>open_claims.sql:9</td></tr></table>'
             '<h4 style="margin-top:8px">Confidence is built from</h4><table><tr><td>Citations pass</td><td class="g1">5/5</td></tr><tr><td>Parsed edges</td><td class="g1">3 of 4</td></tr><tr><td>Source freshness</td><td class="w1">9 days</td></tr><tr><td>Human reviewed</td><td class="w1">no</td></tr></table>'
             '<p class="mu">Confidence is a band (High, Medium, Low), checked against ratings over time. Thumbs-down reasons go to the lead on the Feedback screen. Nothing changes in the KB until a lead approves.</p>')
    return screen("s5", "5. Ask, with confidence and feedback", "Answers show a confidence level and the reasons for it. Thumbs-down asks why. The reason is logged and shown to leads on a separate screen (screen 9).",
                  frame("ask", main, left=left, right=right))


def s6():
    left = ('<div class="hd">Pending, riskiest first <span>3</span></div><div class="ls">'
            '<div class="it on"><div class="t"><b>#212 Data team</b><div class="s"><span class="chip er">high impact</span> 9 files &middot; 8 h</div></div></div>'
            '<div class="it"><div class="t"><b>#213 Backend team</b><div class="s"><span class="chip wn">medium</span> 5 files &middot; 8 h</div></div></div>'
            '<div class="it"><div class="t"><b>#211 Answer Q-0041</b><div class="s"><span class="chip ok">low impact</span> 2 files &middot; 2 d</div></div></div></div>')
    main = ('<div class="bd"><div style="display:flex;gap:6px;align-items:center;margin-bottom:6px"><b>#212 Weekly refresh: Data team files</b><span class="chip ol">SIT</span><span class="sp"></span>'
            '<span class="btn r">Reject</span><span class="btn g">Approve</span></div>'
            '<div class="kp"><div><b>9</b><span class="mu">files changed</span></div><div><b class="g1">212/212</b><span class="mu">citations pass</span></div><div><b>3</b><span class="mu">new questions</span></div></div>'
            '<span class="chip ok">Bitbucket</span> <span class="chip ok">Jira</span> <span class="chip ok">Confluence</span> <span class="chip gr">Snowflake not refreshed</span>'
            '<h4 style="margin-top:8px">db/CLAIM_HDR.md, change 1 of 4</h4>'
            '<div class="dl"><s>The table has 18 columns.</s> <span class="cite">claim_hdr.sql:12</span></div>'
            '<div class="ad">The table has 19 columns, including STATUS_CD. <span class="cite">claim_hdr.sql:31 "STATUS_CD VARCHAR(2)"</span> <span class="chip ok">quote found</span></div>'
            '<div class="co">Source change: fin-db ddl/claim_hdr.sql, 4c1d9e0 to 7be41a2</div></div>')
    right = ('<h4>Files in this change</h4><div>&#9679; db/CLAIM_HDR.md (4)<br>&#9679; db/CLAIM_LINE.md (2)<br>&#9679; etl/LOAD_CLAIMS.md (3)<br>&#9679; app/ClaimService.md (1)<br><span class="mu">+10 more</span></div>'
             '<h4 style="margin-top:8px">Who can approve this</h4><div>Data files: Data lead<br>Service files: Backend lead<br><span class="chip wn">You can approve 11 of 14</span></div>'
             '<h4 style="margin-top:8px">Reviewer note</h4><div class="inp" style="display:block;height:34px">Required only on reject</div>'
             '<p class="mu">Approval is logged with your name and time, in the KB repo.</p>')
    return screen("s6", "6. Approve changes", "Lead reviews each changed claim next to its quote. One click to approve; a reason is asked only on reject. The refresh opens one PR per owning team, so the right lead approves each. Rights follow the team setup (screen 11).",
                  frame("appr", main, left=left, right=right))


def s7():
    main = ('<div class="bd"><div style="display:grid;grid-template-columns:1.1fr 1fr;gap:10px"><div><h4>Sources</h4>'
            '<table><tr><td><span class="sw"></span></td><td><b>Bitbucket code and DDL</b><div class="mu">FIN service account &middot; 6 repos &middot; 4 changed</div></td></tr>'
            '<tr><td><span class="sw"></span></td><td><b>Jira Data Center</b><div class="mu">UEP service id &middot; 11 new tickets</div></td></tr>'
            '<tr><td><span class="sw off"></span></td><td><b>Confluence</b><div class="mu">2 spaces</div></td></tr>'
            '<tr><td><span class="sw"></span></td><td><b>Snowflake schema</b> <span class="chip wn">needs you signed in</span><div class="mu">Runs as you, role FIN_DEV_RO</div></td></tr>'
            '<tr><td><span class="sw off"></span></td><td><b>Snowflake config tables</b> <span class="chip er">not classified</span><div class="mu">Disabled until the owner classifies them</div></td></tr></table>'
            '<h4 style="margin-top:8px">Scope</h4><span class="chip ol">&#9673; Stale files only (17)</span> <span class="chip ol">&#9675; Chosen modules</span> <span class="chip ol">&#9675; Everything</span></div>'
            '<div><h4>Before you start</h4><table><tr><td class="mu">Environment</td><td>SIT</td></tr><tr><td class="mu">Files touched</td><td>about 17</td></tr><tr><td class="mu">Estimated cost</td><td>about 6 ACU</td></tr><tr><td class="mu">Estimated time</td><td>25 to 40 min</td></tr><tr><td class="mu">Result</td><td>1 PR, 1 session, then closes</td></tr><tr><td class="mu">Not refreshed</td><td>Confluence</td></tr></table>'
            '<div class="co">Files built from Confluence keep old claims, marked "last refreshed 9 days ago".</div>'
            '<span class="btn p">Start task</span> <span class="btn">Schedule weekly</span> <span class="btn">Dry run</span></div></div></div>')
    left = ('<div class="hd">Recent runs</div><div class="ls"><div class="it"><div class="t">12 Nov weekly<div class="s"><span class="chip ok">PR #212</span></div></div></div>'
            '<div class="it"><div class="t">5 Nov weekly<div class="s"><span class="chip ok">PR #209</span></div></div></div>'
            '<div class="it"><div class="t">30 Oct manual<div class="s"><span class="chip er">failed</span></div></div></div></div>')
    return screen("s7", "7. Run a refresh", "The lead chooses which sources to run. Unavailable options show why. Cost and result are stated before the task starts.",
                  frame("run", main, left=left))


def s8():
    left = ('<div class="hd">Open <span>9</span></div><div class="ls">'
            '<div class="it on"><span class="chip er">P1</span><div class="t"><b>Q-0044</b><div class="s">Who sets STATUS_CD = X?</div></div></div>'
            '<div class="it"><span class="chip wn">P2</span><div class="t"><b>Q-0041</b><div class="s">Claim status codes</div></div></div>'
            '<div class="it"><span class="chip wn">P2</span><div class="t"><b>Q-0039</b><div class="s">Owner of raw claim feed</div></div></div>'
            '<div class="it"><span class="chip gr">P3</span><div class="t"><b>Q-0036</b><div class="s">Is RPT_AGING used?</div></div></div></div>')
    main = ('<div class="bd"><b>Q-0044: Who sets STATUS_CD = X?</b> <span class="chip er">blocks 3 files</span><h4 style="margin-top:6px">Evidence so far</h4>'
            '<p style="margin:0">The value is checked here <span class="cite">load_claims.sql:51 "WHEN X"</span>, but no code that sets it was found.</p>'
            '<h4 style="margin-top:6px">Your answer</h4><div class="inp" style="display:block;height:54px">Type the answer. Cite a file or page if you can.</div>'
            '<div style="margin-top:6px"><span class="btn">Assign to...</span> <span class="btn">Attach evidence</span> <span class="btn p">Submit</span></div>'
            '<p class="mu">An answer becomes a task, then a PR, then a lead approves. Anyone on the team can answer.</p></div>')
    right = ('<h4>Blocks</h4><div>CLAIM_HDR<br>ClaimService<br>RPT_OPEN_CLAIMS</div><h4 style="margin-top:8px">Suggested people</h4>'
             '<div>S. Iyer, Backend<br>P. Gomez, BSA</div>')
    return screen("s8", "8. Questions", "What the KB could not work out. Anyone on the team can answer, assign it to someone, and a lead approves.",
                  frame("q", main, left=left, right=right))
