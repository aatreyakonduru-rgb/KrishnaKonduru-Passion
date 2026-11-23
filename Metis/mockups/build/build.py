"""Assemble all screens into mockups/metis-ui-mockups.html."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CSS  # noqa: E402
import screens_a as a  # noqa: E402
import screens_b as b  # noqa: E402
import screens_c as c  # noqa: E402
import screens_d as d  # noqa: E402

parts = [a.s1(), a.s2(), a.s3(), a.s4(), b.s5(), b.s6(), b.s7(), b.s8(),
         c.s9(), c.s10(), c.s11(), c.s12(), c.s13(),
         d.s14(), d.s15(), d.s16(), d.s17(), d.s18(), d.s19(), d.s20(), d.s21()]
names = ["Home", "KB files", "KB map", "Impact", "Ask", "Approve", "Refresh", "Questions",
         "Feedback", "Promote", "Teams", "Settings", "Audit",
         "Coverage", "Golden Qs", "Context pack", "Ticket impact", "Onboarding", "Live run", "Glossary", "Detected setup"]
nav = "".join('<a href="#s%d">%d %s</a>' % (i + 1, i + 1, n) for i, n in enumerate(names))
html = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Metis dashboard mock screens</title>'
        '<style>%s</style></head><body><div class="nav"><b>Metis mock screens</b>%s</div><div class="wrap">'
        '<div class="note"><b>Mock-ups only.</b> Names and numbers are made up. Compact layout: icon rail, list pane, '
        'wide work area, details pane, status bar. Environments are chosen in the top strip and defined in Settings.</div>'
        '%s<div class="foot">Made with IBM Bob</div></div></body></html>' % (CSS, nav, "".join(parts)))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "metis-ui-mockups.html")
with open(out, "w", encoding="utf-8") as fh:
    fh.write(html)
print("wrote", len(html), "bytes,", len(parts), "screens")
