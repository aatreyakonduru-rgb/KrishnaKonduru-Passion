"""Capture all 21 mock screens as WebP files with headless Edge, in parallel.

Output: <workspace>/Metis-2.0.0-screens/NN-name.webp (1200 x 582), next to Metis-2.0.0-Strategy.html.
Existing files are kept unless you pass --force.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image  # noqa: E402
from common import CSS  # noqa: E402
import screens_a as a  # noqa: E402
import screens_b as b  # noqa: E402
import screens_c as c  # noqa: E402
import screens_d as d  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "Metis-2.0.0-screens")
TMP = os.path.join(ROOT, ".bob", "tmp", "shots")
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

SHOTS = [
    ("01-home", a.s1), ("02-kb-files", a.s2), ("03-kb-map", a.s3), ("04-impact", a.s4),
    ("05-ask", b.s5), ("06-approve", b.s6), ("07-run-refresh", b.s7), ("08-questions", b.s8),
    ("09-feedback", c.s9), ("10-promote", c.s10), ("11-teams", c.s11), ("12-settings", c.s12),
    ("13-audit", c.s13), ("14-coverage", d.s14), ("15-golden-questions", d.s15),
    ("16-context-pack", d.s16), ("17-ticket-impact", d.s17), ("18-onboarding", d.s18),
    ("19-live-run", d.s19), ("20-glossary", d.s20), ("21-detected-setup", d.s21),
]
W, H = 1200, 582
EXTRA = ("body{background:#fff}.wrap{max-width:none;padding:0;margin:0}.sc{margin:0}"
         ".sc h2,.sc p.why{display:none}.fr{border:0;border-radius:0;height:%dpx}" % H)
FORCE = "--force" in sys.argv


def shoot(item):
    name, fn = item
    dest = os.path.join(OUT, name + ".webp")
    if os.path.exists(dest) and not FORCE:
        return "%-22s kept" % name
    html_path = os.path.join(TMP, name + ".html")
    png_path = os.path.join(TMP, name + ".png")
    prof = os.path.join(TMP, "profile-" + name)
    page = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>%s%s</style></head>'
            '<body><div class="wrap">%s</div></body></html>' % (CSS, EXTRA, fn()))
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    if os.path.exists(png_path):
        os.remove(png_path)
    try:
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--user-data-dir=" + prof, "--screenshot=" + png_path,
                        "--window-size=%d,%d" % (W, H + 120), "file:///" + html_path.replace("\\", "/")],
                       capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "%-22s TIMEOUT" % name
    if not os.path.exists(png_path):
        return "%-22s FAILED" % name
    im = Image.open(png_path).convert("RGB").crop((0, 0, W, H))
    im.save(dest, "WEBP", quality=82, method=6)
    return "%-22s %6.1f KB" % (name, os.path.getsize(dest) / 1024)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        for line in pool.map(shoot, SHOTS):
            print(line, flush=True)
    print("done:", OUT)
