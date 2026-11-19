#!/usr/bin/env python3
"""Read-only facts for promoting code from one environment to the next.

Reads the app repo (this checkout) and a clone of the deploy repo (`repo.deploy_slug` in
.devin/rules/sdlc-profile.json). Never merges, pushes or edits anything. /promote uses the
report to raise the pull requests.

    promote_check.py --list
    promote_check.py --from dev --to sit --deploy-repo ~/repos/<deploy repo>
    promote_check.py --from sit --to uat --service <service> --json
    promote_check.py --to sit --wait-for <app commit> --service <service> --timeout 1800

What it reports, per service (`repo.services`):
  * the image tag each environment runs now (tekton-values-<env>.yaml on the deploy branch)
  * app commits on the source branch that the target branch does not have (service path only)
  * config keys the source environment has and the target does not (keys only, never values)
  * for an environment with a `tag_branch`: tag updates there not yet merged to its deploy branch

The environments, their order and their branches are `workflow.environments` in the team
settings. One marked `verified: false` is refused unless --allow-unverified is given, and a
promotion that skips an environment in the order is refused unless --allow-skip is given.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import yaml

import team_links

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def load_workflow(data):
    """({env: settings}, [envs in promotion order]) from workflow.environments."""
    envs = ((data or {}).get("workflow") or {}).get("environments") or []
    if not envs:
        raise team_links.LinksError("the team settings have no workflow.environments "
                                    "(see the example in sdlc/kb/examples/acme/sdlc-profile.json)")
    table, order = {}, []
    for e in envs:
        name = (e or {}).get("name")
        if not name or name in table:
            raise team_links.LinksError("workflow.environments needs a unique name for each environment, got %r" % name)
        app = e.get("app_branch") or name
        table[name] = {
            "app_branch": app,
            "deploy_branch": e.get("deploy_branch") or app,
            "values": e.get("values") or name,
            "gate": e.get("gate"),
            "tag_branch": e.get("tag_branch"),
            "verified": e.get("verified", True) is not False,
        }
        if e.get("in_order", True) is not False:
            order.append(name)
    return table, order


try:
    PROFILE = team_links.load()
    ENVIRONMENTS, ORDER = load_workflow(PROFILE)
    SERVICES = list((PROFILE.get("repo") or {}).get("services") or [])
    DEPLOY_SLUG = (PROFILE.get("repo") or {}).get("deploy_slug") or ""
    if not SERVICES or DEPLOY_SLUG.count("/") != 1:
        raise team_links.LinksError("the team settings need repo.services and repo.deploy_slug (PROJECT/repo)")
except team_links.LinksError as exc:
    raise SystemExit("promote_check: %s" % exc) from None


def git(repo, *args, check=False):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def fetch(repo):
    subprocess.run(["git", "-C", repo, "-c", "http.sslVerify=false", "fetch", "-q", "origin"],
                   capture_output=True, text=True)


def read_yaml(repo, ref, path):
    text = git(repo, "show", f"origin/{ref}:{path}")
    if not text:
        return None
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None


def image_of(deploy, env, service):
    branch, suffix = ENVIRONMENTS[env]["deploy_branch"], ENVIRONMENTS[env]["values"]
    doc = read_yaml(deploy, branch, f"{service}/tekton-values-{suffix}.yaml")
    image = ((doc or {}).get("container") or {}).get("image")
    if not image:
        return None, None
    repo, _, tag = image.rpartition(":")
    return (repo, tag) if repo else (image, None)


def config_keys(deploy, env, service):
    branch, suffix = ENVIRONMENTS[env]["deploy_branch"], ENVIRONMENTS[env]["values"]
    doc = read_yaml(deploy, branch, f"{service}/values-{suffix}.yaml")
    if doc is None:
        return None
    keys = set(((doc.get("configmap") or {}).get("data") or {}).keys())
    keys |= {f"secret:{v}" for v in (((doc.get("secret") or {}).get("keys")) or {}).values()}
    return keys


def pending_commits(app, src_branch, dst_branch, service):
    out = git(app, "log", "--no-merges", "--format=%h %ad %an | %s", "--date=short",
              f"origin/{dst_branch}..origin/{src_branch}", "--", f"{service}/")
    return [line for line in out.splitlines() if line]


def tag_status(app, env, tag):
    if not tag:
        return "no tag"
    if not git(app, "cat-file", "-t", tag):
        return "tag not found in app repo"
    branch = ENVIRONMENTS[env]["app_branch"]
    tip = git(app, "rev-parse", f"origin/{branch}")
    if tip == tag:
        return f"matches origin/{branch} tip"
    if subprocess.run(["git", "-C", app, "merge-base", "--is-ancestor", tag, f"origin/{branch}"]).returncode == 0:
        behind = git(app, "rev-list", "--count", f"{tag}..origin/{branch}")
        return f"on origin/{branch}, {behind} commits behind its tip"
    return f"not on origin/{branch}"


def unmerged_tags(deploy, env):
    e = ENVIRONMENTS[env]
    out = git(deploy, "log", "--format=%h %ad %an | %s", "--date=short",
              f"origin/{e['deploy_branch']}..origin/{e['tag_branch']}")
    return [line for line in out.splitlines() if line]


def report(app, deploy, src, dst, services):
    rows = []
    for svc in services:
        _, src_tag = image_of(deploy, src, svc) if src else (None, None)
        dst_repo, dst_tag = image_of(deploy, dst, svc)
        src_keys = config_keys(deploy, src, svc) if src else None
        dst_keys = config_keys(deploy, dst, svc)
        rows.append({
            "service": svc,
            "source_tag": src_tag,
            "target_image": dst_repo,
            "target_tag": dst_tag,
            "target_tag_status": tag_status(app, dst, dst_tag),
            "pending_commits": pending_commits(app, ENVIRONMENTS[src]["app_branch"], ENVIRONMENTS[dst]["app_branch"], svc)
            if src else [],
            "keys_missing_in_target": sorted(src_keys - dst_keys) if src_keys is not None and dst_keys is not None else None,
            "keys_only_in_target": sorted(dst_keys - src_keys) if src_keys is not None and dst_keys is not None else None,
        })
    result = {"from": src, "to": dst,
              "app_branches": [ENVIRONMENTS[src]["app_branch"] if src else None, ENVIRONMENTS[dst]["app_branch"]],
              "deploy_branch": ENVIRONMENTS[dst]["deploy_branch"], "gate": ENVIRONMENTS[dst]["gate"],
              "services": rows}
    if ENVIRONMENTS[dst]["tag_branch"]:
        result["tag_branch"] = ENVIRONMENTS[dst]["tag_branch"]
        result["unmerged_tag_updates"] = unmerged_tags(deploy, dst)
    return result


def render_environments():
    lines = ["Promotion order: " + " -> ".join(ORDER), "",
             "| Environment | App branch | Deploy branch | Values file | Gate before promoting in | Tag written to |",
             "|---|---|---|---|---|---|"]
    for name, e in ENVIRONMENTS.items():
        label = name + ("" if name in ORDER else " (not in the order)") + ("" if e["verified"] else " (unverified)")
        tag = f"`{e['tag_branch']}`, merged by a person" if e["tag_branch"] else f"`{e['deploy_branch']}` directly"
        lines.append(f"| {label} | `{e['app_branch']}` | `{e['deploy_branch']}` | values-{e['values']}.yaml | "
                     f"{e['gate'] or 'none'} | {tag} |")
    return "\n".join(lines)


def render(result):
    src, dst = result["from"], result["to"]
    lines = [f"# Promotion check: {src or '-'} -> {dst}", "",
             f"App branches: `{result['app_branches'][0]}` -> `{result['app_branches'][1]}`. "
             f"Deploy branch: `{result['deploy_branch']}`.", ""]
    if result.get("gate"):
        lines += [f"Needs {result['gate']} signed before promoting to {dst}.", ""]
    for r in result["services"]:
        lines += [f"## {r['service']}", "",
                  f"- {dst} runs `{r['target_tag'] or 'none'}` ({r['target_tag_status']})"]
        if src:
            lines.append(f"- {src} runs `{r['source_tag'] or 'none'}`")
            lines.append(f"- {len(r['pending_commits'])} commits on `{result['app_branches'][0]}` "
                         f"not on `{result['app_branches'][1]}` touch this service")
            lines += [f"  - {c}" for c in r["pending_commits"][:20]]
            if len(r["pending_commits"]) > 20:
                lines.append(f"  - ... {len(r['pending_commits']) - 20} more")
            missing = r["keys_missing_in_target"]
            if missing is None:
                lines.append("- config keys: values file missing on one side")
            else:
                lines.append(f"- config keys in {src} but not {dst}: {', '.join(missing) or 'none'}")
                lines.append(f"- config keys only in {dst}: {', '.join(r['keys_only_in_target']) or 'none'}")
        lines.append("")
    if "unmerged_tag_updates" in result:
        pending = result["unmerged_tag_updates"]
        lines += [f"## {dst} tag updates waiting on `{result['tag_branch']}`", ""]
        lines += [f"- {c}" for c in pending] or ["- none"]
        lines.append("")
    return "\n".join(lines)


def wait_for(deploy, env, service, commit, timeout, interval):
    deadline = time.time() + timeout
    while True:
        fetch(deploy)
        _, tag = image_of(deploy, env, service)
        if tag and (tag == commit or tag.startswith(commit)):
            print(f"{service} {env} now runs {tag}")
            return 0
        if time.time() >= deadline:
            print(f"timed out: {service} {env} still runs {tag}")
            return 1
        time.sleep(interval)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", choices=sorted(ENVIRONMENTS))
    ap.add_argument("--to", dest="dst", choices=sorted(ENVIRONMENTS))
    ap.add_argument("--list", action="store_true", help="print the environments from the team settings and stop")
    ap.add_argument("--service", action="append", choices=SERVICES)
    ap.add_argument("--app-repo", default=ROOT)
    ap.add_argument("--deploy-repo", default=os.path.expanduser("~/repos/" + DEPLOY_SLUG.split("/")[-1]))
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--allow-unverified", action="store_true")
    ap.add_argument("--allow-skip", action="store_true", help="allow a promotion that skips an environment")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--wait-for", metavar="COMMIT")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--interval", type=int, default=60)
    a = ap.parse_args(argv)

    if a.list:
        print(render_environments())
        return 0
    if not a.dst:
        ap.error("--to is required (or --list)")
    for env in filter(None, (a.src, a.dst)):
        if not ENVIRONMENTS[env]["verified"] and not a.allow_unverified:
            ap.error(f"{env}: branch mapping is marked unverified in workflow.environments; "
                     "confirm it with the team that runs the deploys and pass --allow-unverified")
    if a.src and a.src in ORDER and a.dst in ORDER and ORDER.index(a.dst) != ORDER.index(a.src) + 1 \
            and not a.allow_skip:
        ap.error(f"{a.src} -> {a.dst} is not the next step in {' -> '.join(ORDER)}; "
                 "promote one environment at a time, or pass --allow-skip if that was agreed")
    if not os.path.isdir(os.path.join(a.deploy_repo, ".git")):
        ap.error(f"deploy repo clone not found at {a.deploy_repo}")
    services = a.service or SERVICES

    if not a.no_fetch:
        fetch(a.app_repo)
        fetch(a.deploy_repo)
    if a.wait_for:
        if len(services) != 1:
            ap.error("--wait-for needs exactly one --service")
        return wait_for(a.deploy_repo, a.dst, services[0], a.wait_for, a.timeout, a.interval)

    result = report(a.app_repo, a.deploy_repo, a.src, a.dst, services)
    print(json.dumps(result, indent=2) if a.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
