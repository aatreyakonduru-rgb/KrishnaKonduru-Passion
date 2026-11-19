"""Argus maintenance jobs: shared reads that one scheduled Devin Cloud run does for every person's Argus.

    python3 tools/argus_maintenance.py nightly-dashboard-data [--dry-run]

nightly-dashboard-data reads Jira once for every roster person's dashboard (gen_dashboard.py --all) and saves
the Jira answers to context/dashboard-data/jira-reads.json. Each Argus builds its person's pages from that file
instead of reading Jira itself. The file is committed straight to the KB branch with a normal push (never a
force push), approved by the solution lead; anything else changed in the checkout stops the job.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "console"))

import gen_dashboard  # noqa: E402
import sdlc_profile as team  # noqa: E402

DATA_REL = os.path.relpath(os.path.join(team.FRAMEWORK_DIR, "context", "dashboard-data", "jira-reads.json"),
                           team.ROOT).replace(os.sep, "/")
APPROVER = "Resource 3 (resource3)"
GIT_ENV = {"SDLC_OWNER": "resource3", "GIT_TERMINAL_PROMPT": "0"}


def git(*args, check=True):
    done = subprocess.run(["git", "-c", "http.sslVerify=false"] + list(args), cwd=team.ROOT, capture_output=True,
                          text=True, env=dict(os.environ, **GIT_ENV))
    if check and done.returncode:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), (done.stderr or done.stdout)[-400:]))
    return done.stdout.strip()


def nightly_dashboard_data(dry_run=False):
    branch = team.KB_BRANCH
    if git("status", "--porcelain"):
        raise RuntimeError("the checkout has other changes; nothing was committed")
    git("fetch", "-q", "origin", branch)
    git("checkout", "-q", "-B", "devin/argus-maintenance-%s" % time.strftime("%Y%m%d"), "origin/" + branch)
    done = gen_dashboard.build_all(tempfile.mkdtemp(prefix="argus-maint-"), save_to=os.path.join(team.ROOT, DATA_REL))
    print("Built %d dashboards; %d failed." % (len(done["built"]), len(done["failed"])))
    if not done["built"]:
        raise RuntimeError("no dashboard built, so no data to share: %s" % done["failed"])
    changed = [line[3:] for line in git("status", "--porcelain").splitlines()]
    if changed != [DATA_REL]:
        raise RuntimeError("only %s may change, found %s; nothing was committed" % (DATA_REL, changed))
    if dry_run:
        print("dry run: would commit %s and push it to %s" % (DATA_REL, branch))
        return 0
    git("add", DATA_REL)
    git("commit", "-q", "-m", "Argus maintenance: nightly dashboard data %s" % time.strftime("%Y-%m-%d"),
        "-m", "Jira answers for %d dashboards, read once for every Argus." % len(done["built"]),
        "-m", "Approved-by: %s\nPushed-by: Argus maintenance job" % APPROVER)
    head = git("rev-parse", "HEAD")
    git("checkout", "-q", "-B", branch, "origin/" + branch)
    git("merge", "--no-ff", "-q", "-m", "Argus maintenance: merge nightly dashboard data", head)
    git("push", "-q", "origin", branch)
    print("pushed %s to %s" % (DATA_REL, branch))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", choices=["nightly-dashboard-data"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        return nightly_dashboard_data(args.dry_run)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
