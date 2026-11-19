#!/usr/bin/env python3
"""Turn the sandbox on for a shell: the environment the framework reads to use the sandbox.

    python3 switch.py --folder ~/Documents/sdlc-sandbox [--user resource2] [--shell bash|powershell|cmd]

Prints the lines to paste (or eval) in a shell: SDLC_SANDBOX (the folder), SDLC_SANDBOX_URL (the
sandbox server, where every Jira and Confluence call goes) and the Jira and Confluence token
variables named in the team settings, set to a sandbox user, who is then "you" in the sandbox Jira.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
PORT = 8799


def env(folder, port=PORT, user="resource2", profile=None):
    if profile is None:
        import team_links
        profile = team_links.load()
    out = {"SDLC_SANDBOX": os.path.abspath(os.path.expanduser(folder)),
           "SDLC_SANDBOX_URL": "http://127.0.0.1:%d" % port}
    for section in ("jira", "confluence"):
        name = (profile.get(section) or {}).get("token_env")
        if name:
            out[name] = user
    return out


def lines(values, shell="bash"):
    if shell == "powershell":
        return ["$env:%s = '%s'" % (k, v) for k, v in values.items()]
    if shell == "cmd":
        return ["set %s=%s" % (k, v) for k, v in values.items()]
    return ["export %s='%s'" % (k, v) for k, v in values.items()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", default=os.environ.get("SDLC_SANDBOX") or "~/Documents/sdlc-sandbox")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--user", default="resource2")
    ap.add_argument("--shell", choices=("bash", "powershell", "cmd"),
                    default="powershell" if os.name == "nt" else "bash")
    args = ap.parse_args(argv)
    print("\n".join(lines(env(args.folder, args.port, args.user), args.shell)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
