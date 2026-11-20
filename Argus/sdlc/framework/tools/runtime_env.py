#!/usr/bin/env python3
"""Where is Argus running: Devin Cloud or Devin Local, and what does that change.

One module answers it for every tool, hook and skill, so nothing else has to guess:

  runtime_env.py detect            JSON: runtime, how it was decided, confidence
  runtime_env.py config            the effective config (config.json + the runtime overlay + config.local.json)
  runtime_env.py probe             a fingerprint with no secret values, to learn what each side really exposes
  runtime_env.py hook              SessionStart hook: tells the agent the runtime as additional context

Devin documents no variable that says "cloud" or "local", so nothing here pretends to read one.
Order of evidence, strongest first:

  1. SDLC_RUNTIME=cloud|local            you said so; always wins
  2. SDLC_DEVIN_TRANSPORT                this repo's own switch: bridge = hosted in a Cloud session, api = on a PC
  3. Windows or macOS                    Cloud VMs are Linux, so these are Local (inference, medium confidence)
  4. Linux with DEVIN_API_KEY and the Jira token both in the environment
                                         what the Cloud VM gets from org secrets (low confidence: a Linux PC
                                         can set them too, so this alone is a guess)
  5. nothing conclusive                  runtime "unknown", handled as Local: no auto commit or push

`unknown` is the safe side on purpose. A wrong "local" costs a manual push; a wrong "cloud" would push
for a person who did not ask. Run `probe` once in each environment and tighten step 4 with what it shows.
"""
import argparse
import copy
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DEVIN_DIR = os.path.join(ROOT, ".devin")
CLOUD, LOCAL, UNKNOWN = "cloud", "local", "unknown"
CLOUD_KEY_ENV = "DEVIN_API_KEY"
DEFAULT_JIRA_ENV = "ACME_JIRA_TOKEN"  # the profile's jira.token_env replaces this at install


def jira_token_env(root=ROOT):
    try:
        with open(os.path.join(root, ".devin", "rules", "sdlc-profile.json"), encoding="utf-8") as fh:
            return json.load(fh).get("jira", {}).get("token_env") or DEFAULT_JIRA_ENV
    except (OSError, ValueError):
        return DEFAULT_JIRA_ENV


def detect(env=None, system=None, root=ROOT):
    """{"runtime", "source", "confidence", "reason"}; env and system are injectable for tests."""
    env = os.environ if env is None else env
    system = system or platform.system()

    forced = (env.get("SDLC_RUNTIME") or "").strip().lower()
    if forced in (CLOUD, LOCAL):
        return _answer(forced, "SDLC_RUNTIME", "high", "set explicitly")
    if forced:
        return _answer(UNKNOWN, "SDLC_RUNTIME", "none", "ignored %r: use cloud or local" % forced)

    transport = (env.get("SDLC_DEVIN_TRANSPORT") or "").strip().lower()
    if transport == "bridge":
        return _answer(CLOUD, "SDLC_DEVIN_TRANSPORT", "high", "bridge = hosted in a Devin Cloud session")
    if transport == "api":
        return _answer(LOCAL, "SDLC_DEVIN_TRANSPORT", "high", "api = running on a PC with its own key")

    if system in ("Windows", "Darwin"):
        return _answer(LOCAL, "platform", "medium", "%s: Devin Cloud VMs are Linux" % system)

    if system == "Linux" and env.get(CLOUD_KEY_ENV) and env.get(jira_token_env(root)):
        return _answer(CLOUD, "org-secrets", "low", "Linux with %s and %s set, as org secrets provide on a Cloud VM"
                       % (CLOUD_KEY_ENV, jira_token_env(root)))

    return _answer(UNKNOWN, "none", "none", "no conclusive signal; handled as local. Set SDLC_RUNTIME to be sure")


def _answer(runtime, source, confidence, reason):
    return {"runtime": runtime, "source": source, "confidence": confidence, "reason": reason}


def is_cloud(**kw):
    """True only when detection says cloud. unknown is not cloud."""
    return detect(**kw)["runtime"] == CLOUD


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _merge(base, over):
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        elif not key.startswith("_"):
            out[key] = copy.deepcopy(val)
    return out


def effective_config(env=None, system=None, root=ROOT):
    """config.json, then the cloud overlay when the runtime is cloud, then config.local.json."""
    devin = os.path.join(root, ".devin")
    cfg = _read(os.path.join(devin, "config.json"))
    if detect(env=env, system=system, root=root)["runtime"] == CLOUD:
        cfg = _merge(cfg, _read(os.path.join(devin, "config.cloud.json")))
    return _merge(cfg, _read(os.path.join(devin, "config.local.json")))


def profile(runtime):
    """What the runtime changes, in one table. Each row is already stated in the repo's rules."""
    cloud = runtime == CLOUD
    return {
        "runtime": runtime,
        "session_state": "repository (a Cloud VM keeps no files between sessions)" if cloud
        else "local (~/.sdlc/sessions, outside the repo)",
        "auto_commit_push": cloud,
        "snowflake_login": "nonprod service account from a Devin org secret, never a personal ID" if cloud
        else "the person's own ID through Okta",
        "database_prompts": "skip when the service account is not provisioned; report 'not run'" if cloud
        else "run with the person's own login",
        "ask_the_user": "only at gates; a Cloud session may be unattended" if cloud
        else "may ask in the terminal",
    }


def probe(env=None, system=None):
    """A fingerprint with names and booleans only: never a value of any variable."""
    env = os.environ if env is None else env
    interesting = ("SDLC_RUNTIME", "SDLC_DEVIN_TRANSPORT", CLOUD_KEY_ENV, jira_token_env(), "DEVIN_PROJECT_DIR",
                   "CI", "CODESPACES", "WSL_DISTRO_NAME", "HOME", "USER", "USERNAME")
    return {
        "platform": system or platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "has_tty": sys.stdin.isatty() if sys.stdin else False,
        "home_is": os.path.expanduser("~"),
        "set": {name: bool(env.get(name)) for name in interesting},
        "devin_like_vars": sorted(k for k in env if k.upper().startswith("DEVIN")),
        "detected": detect(env=env, system=system),
    }


def hook_output(env=None, system=None):
    """SessionStart hook JSON: the agent starts the session knowing where it is."""
    found = detect(env=env, system=system)
    rows = profile(found["runtime"])
    text = ("Argus runtime: %s (%s, %s confidence: %s). Session state: %s. Auto commit and push: %s. "
            "Snowflake login: %s. Ask the user: %s." % (
                found["runtime"], found["source"], found["confidence"], found["reason"], rows["session_state"],
                "yes" if rows["auto_commit_push"] else "no", rows["snowflake_login"], rows["ask_the_user"]))
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("detect", "config", "probe", "hook"))
    args = ap.parse_args(argv)
    if args.cmd == "detect":
        out = dict(detect(), profile=profile(detect()["runtime"]))
    elif args.cmd == "config":
        out = effective_config()
    elif args.cmd == "probe":
        out = probe()
    else:
        try:
            sys.stdin.read()  # the hook event; unused
        except OSError:
            pass
        out = hook_output()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
