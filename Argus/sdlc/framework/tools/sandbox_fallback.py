#!/usr/bin/env python3
"""Start the sandbox when Argus has nothing real to talk to.

On a first run there is often no Jira token, no Devin key and no reachable Jira. Rather than a console that
shows errors everywhere, Argus can use the made-up company in tools/sandbox/ (sample Jira, Confluence,
database, repo). This module only decides and prepares; server.py applies the result.

    decide(...)  -> {"use": bool, "why": str}      pure; env, runtime and keys are passed in
    ensure(...)  -> {"url", "folder", "env", ...}  makes the sandbox if its folder is empty, starts its server

When it does NOT fall back (on purpose):
  - a Jira token or a Devin key is set, even a wrong one: a bad credential must show its error, not fake data
  - SDLC_JIRA_BASE or SDLC_SANDBOX_URL is set: someone pointed Argus somewhere already
  - SDLC_SANDBOX_FALLBACK=off
  - the runtime is not "local": Devin Cloud must not quietly work on made-up data, and "unknown" (a Linux
    machine nothing identifies) could be a Cloud VM. Set SDLC_RUNTIME=local or SDLC_DEVIN_TRANSPORT=api to allow it.
Everything in the sandbox is made up; the console shows a banner while it is on.
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX_TOOLS = os.path.join(HERE, "sandbox")
OFF_VALUES = ("off", "0", "false", "no")
SANDBOX_USER = "resource2"  # the sandbox Jira user a token of this name signs in as
FIRST_PORT = 8799


def decide(env, runtime, token_env, devin_key):
    """Whether to start the sandbox. `runtime` is runtime_env.detect()["runtime"]; keys are names-only truthiness."""
    if (env.get("SDLC_SANDBOX_FALLBACK") or "on").strip().lower() in OFF_VALUES:
        return {"use": False, "why": "turned off by SDLC_SANDBOX_FALLBACK"}
    for var in ("SDLC_SANDBOX_URL", "SDLC_JIRA_BASE"):
        if env.get(var):
            return {"use": False, "why": "%s is already set" % var}
    if runtime != "local":
        return {"use": False, "why": "runtime is %s, not local; set SDLC_RUNTIME=local to allow the sandbox" % runtime}
    if env.get(token_env):
        return {"use": False, "why": "%s is set, so the real Jira is used" % token_env}
    if devin_key:
        return {"use": False, "why": "a Devin key is set, so Jira is read through Devin Cloud"}
    return {"use": True, "why": "no Jira token and no Devin key: nothing real to read Jira with"}


def default_folder(state_dir):
    return os.path.join(os.path.expanduser(state_dir), "sandbox")


def _tools():
    if SANDBOX_TOOLS not in sys.path:
        sys.path.insert(0, SANDBOX_TOOLS)
    import make_sandbox
    import sandbox_server
    import switch
    return make_sandbox, sandbox_server, switch


def ensure(folder, root, profile, ports=None):
    """Make the sandbox in `folder` when it has none, start its server on the first free port.

    Returns {"url", "folder", "port", "made", "env", "server"}. `env` holds what the framework reads
    (SDLC_SANDBOX, SDLC_SANDBOX_URL and the token variables); the caller applies it. Raises RuntimeError
    with a plain message when it cannot.
    """
    make_sandbox, sandbox_server, switch = _tools()
    folder = os.path.abspath(os.path.expanduser(folder))
    made = False
    if not os.path.isfile(os.path.join(folder, "jira.yaml")):
        try:
            try:
                make_sandbox.like(root)  # the sample's Jira project and team match this repo's profile
            except (OSError, ValueError, KeyError):
                pass  # no installed profile to copy from: the sample keeps its own names
            make_sandbox.make(folder)
        except SystemExit as exc:  # make() refuses a folder that already holds other files
            raise RuntimeError(str(exc)) from None
        except OSError as exc:
            raise RuntimeError("could not make the sandbox in %s: %s" % (folder, exc)) from None
        made = True
    last = None
    for port in (ports if ports is not None else range(FIRST_PORT, FIRST_PORT + 10)):
        try:
            srv = sandbox_server.serve(folder, port=port)
        except OSError as exc:
            last = exc
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        real_port = srv.server_address[1]
        return {"url": "http://127.0.0.1:%d" % real_port, "folder": folder, "port": real_port, "made": made,
                "env": switch.env(folder, real_port, SANDBOX_USER, profile=profile), "server": srv}
    raise RuntimeError("no free port for the sandbox server (%s)" % last)


def public(info, why):
    """What /api/config shows: no server object, no environment."""
    return {"on": True, "url": info["url"], "folder": info["folder"], "made": info["made"], "why": why}
