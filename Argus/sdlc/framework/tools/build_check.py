#!/usr/bin/env python3
"""Install, lint, test and build the Acme Claims components the way their Dockerfiles do.

Pulls npm and pip packages from Artifactory, so it needs ARTIFACTORY_TOKEN (and optionally
ARTIFACTORY_USER) in the environment. The token is written only to a temporary npm config
and to pip's environment, and is masked in every log line. Logs go outside the repo, under
~/.sdlc/build-check/<timestamp>/.

    build_check.py                          # every component
    build_check.py --component web --component api
    build_check.py --dry-run                # print the plan, needs no token
    build_check.py --keep-going             # carry on after a failing step

This checks that the code builds and its tests pass. It does not build or push images; Tekton
does that after the merge.
"""
import argparse
import base64
import datetime
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REGISTRY = "https://artifactory.acme.example/artifactory"
NPM_REGISTRY = f"{REGISTRY}/api/npm/npm-releases/"
PIP_INDEX = f"{REGISTRY}/api/pypi/pypi-releases/simple"
PIP_EXTRA = f"{REGISTRY}/api/pypi/pypi-snapshots/simple"

NODE_BUILD_ENV = {"CLIENT_BUSINS_TYPE": "acme", "NEXT_TELEMETRY_DISABLED": "1"}
PY_TEST_ENV = {"DJANGO_ENV": "base", "DEBUG": "True", "TESTING": "True", "SECRETKEY": "build-check-only"}

# component -> list of (step, cwd relative to repo root, command, extra env)
PLAN = {
    "web": [
        ("mfe install", "web/microfrontends/generic-dashboard", ["npm", "install", "--legacy-peer-deps"], {}),
        ("mfe build", "web/microfrontends/generic-dashboard", ["npm", "run", "build"], {}),
        ("install", "web", ["npm", "install", "--legacy-peer-deps"], {}),
        ("lint", "web", ["npm", "run", "lint"], {}),
        ("test", "web", ["npx", "jest", "--ci"], {}),
        ("build", "web", ["npx", "next", "build"], NODE_BUILD_ENV),
    ],
    "web-portal": [
        ("install", "web-portal", ["npm", "install", "--legacy-peer-deps"], {}),
        ("lint", "web-portal", ["npm", "run", "lint"], {}),
        ("build", "web-portal", ["npm", "run", "build"], NODE_BUILD_ENV),
    ],
    "web-admin": [
        ("install", "web-admin", ["npm", "install", "--legacy-peer-deps"], {}),
        ("lint", "web-admin", ["npm", "run", "lint"], {}),
        ("build", "web-admin", ["npm", "run", "build"], NODE_BUILD_ENV),
    ],
    "api": [
        ("install", "api", ["{venv}/bin/pip", "install", "-r", "requirements.txt"], {}),
        ("install dev", "api", ["{venv}/bin/pip", "install", "-e", ".[dev]"], {}),
        ("django check", "api", ["{venv}/bin/python", "manage.py", "check"], PY_TEST_ENV),
        ("test", "api", ["{venv}/bin/python", "-m", "pytest", "-q",
                               "--ds=acme_api.settings.base"], PY_TEST_ENV),
    ],
    "api-portal": [
        ("install", "api-portal", ["{venv}/bin/pip", "install", "-r", "requirements.txt"], {}),
        ("compile", "api-portal", ["{venv}/bin/python", "-m", "compileall", "-q", "app"], {}),
    ],
}
PYTHON_COMPONENTS = {"api", "api-portal"}


def credentials():
    token = os.environ.get("ARTIFACTORY_TOKEN", "").strip()
    user = os.environ.get("ARTIFACTORY_USER", "").strip()
    if not token or token.upper().startswith("PLACEHOLDER"):
        return None, None
    return user, token


def npm_userconfig(user, token, directory):
    host = NPM_REGISTRY.split("://", 1)[1]
    lines = [f"registry={NPM_REGISTRY}"]
    if user:
        auth = base64.b64encode(f"{user}:{token}".encode()).decode()
        lines += [f"//{host}:_auth={auth}", "always-auth=true"]
    else:
        lines.append(f"//{host}:_authToken={token}")
    path = os.path.join(directory, "npmrc")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def pip_env(user, token):
    cred = f"{user}:{token}" if user else f"token:{token}"
    def with_cred(url):
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{cred}@{rest}"
    return {"PIP_INDEX_URL": with_cred(PIP_INDEX), "PIP_EXTRA_INDEX_URL": with_cred(PIP_EXTRA),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


def mask(text, secrets):
    for s in secrets:
        if s:
            text = text.replace(s, "****")
    return text


def run_step(cmd, cwd, env, log_path, secrets):
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(mask("$ " + " ".join(cmd) + "\n", secrets))
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            log.write(mask(line, secrets))
        return proc.wait()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--component", action="append", choices=sorted(PLAN))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--log-dir", default=os.path.expanduser("~/.sdlc/build-check"))
    a = ap.parse_args(argv)
    components = a.component or list(PLAN)

    if a.dry_run:
        for comp in components:
            print(f"## {comp}")
            for step, cwd, cmd, env in PLAN[comp]:
                extra = " ".join(f"{k}={v}" for k, v in env.items())
                print(f"- {step}: (cd {cwd} && {extra + ' ' if extra else ''}{' '.join(cmd)})")
        return 0

    user, token = credentials()
    if not token:
        print("SKIP: artifactory — credential not yet provisioned (ARTIFACTORY_TOKEN not set)")
        return 5

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = os.path.join(a.log_dir, stamp)
    os.makedirs(log_dir, exist_ok=True)
    secrets = [token, base64.b64encode(f"{user}:{token}".encode()).decode() if user else ""]
    results, failed = [], False
    with tempfile.TemporaryDirectory(prefix="sdlc-build-") as tmp:
        base_env = dict(os.environ)
        base_env["NPM_CONFIG_USERCONFIG"] = npm_userconfig(user, token, tmp)
        base_env.update(pip_env(user, token))
        for comp in components:
            venv = os.path.join(tmp, f"venv-{comp}")
            if comp in PYTHON_COMPONENTS:
                subprocess.run([sys.executable, "-m", "venv", venv], check=True)
            for step, cwd, cmd, extra in PLAN[comp]:
                if failed and not a.keep_going:
                    results.append((comp, step, "SKIP", ""))
                    continue
                cmd = [c.replace("{venv}", venv) for c in cmd]
                log_path = os.path.join(log_dir, f"{comp}-{step.replace(' ', '-')}.log")
                code = run_step(cmd, os.path.join(ROOT, cwd), {**base_env, **extra}, log_path, secrets)
                status = "PASS" if code == 0 else f"FAIL ({code})"
                failed = failed or code != 0
                results.append((comp, step, status, log_path))

    print("| Component | Step | Result | Log |")
    print("|---|---|---|---|")
    for comp, step, status, log in results:
        print(f"| {comp} | {step} | {status} | {log} |")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
