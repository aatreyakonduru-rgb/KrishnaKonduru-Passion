"""Team settings for Argus.

Every value that names the team's product, Jira project, repo or Devin org comes from one settings file, so the
Argus code holds none of them: .devin/rules/sdlc-profile.json in the repo (or sdlc-profile.yaml, used when
PyYAML is installed), or the file SDLC_PROFILE points to. sdlc/kb/examples/acme/sdlc-profile.json shows every key with made-up values. Stdlib only.
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_DIR = os.path.dirname(HERE)


def find_root(start=FRAMEWORK_DIR):
    """The repo root: the nearest folder above the framework that has a .devin folder."""
    d = start
    while True:
        if os.path.isdir(os.path.join(d, ".devin")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.abspath(os.path.join(start, "..", ".."))
        d = up


ROOT = find_root()
FRAMEWORK = os.path.relpath(FRAMEWORK_DIR, ROOT).replace(os.sep, "/")
QUERY_SCOPES = ("sprint", "open", "mine", "mine_sprint", "qa", "uat", "waiting")
OPTIONAL_QUERY_SCOPES = ("automation", "automation_open")


class ProfileError(Exception):
    pass


def _yaml():
    try:
        import yaml
    except ImportError:
        return None
    return yaml


def profile_path():
    """SDLC_PROFILE, else .devin/rules/sdlc-profile.yaml when PyYAML is installed, else sdlc-profile.json."""
    if os.environ.get("SDLC_PROFILE"):
        return os.environ["SDLC_PROFILE"]
    base = os.path.join(ROOT, ".devin", "rules", "sdlc-profile")
    if os.path.exists(base + ".yaml") and (_yaml() or not os.path.exists(base + ".json")):
        return base + ".yaml"
    return base + ".json"


def load(path=None):
    path = path or profile_path()
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        raise ProfileError("no team settings at %s: copy sdlc/kb/examples/acme/sdlc-profile.json there and "
                           "fill in your values (or set SDLC_PROFILE)" % path) from None
    if path.endswith((".yaml", ".yml")):
        yaml = _yaml()
        if yaml is None:
            raise ProfileError("%s is YAML but PyYAML is not installed: pip install pyyaml, or use "
                               "sdlc-profile.json instead" % path)
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ProfileError("%s is not valid YAML: %s" % (path, exc))
    else:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProfileError("%s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ProfileError("%s must hold a mapping of settings" % path)
    return data


def get(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node or node[part] in ("", None):
            raise ProfileError("%s has no %s" % (PATH, dotted))
        node = node[part]
    return node


def and_join(items):
    items = [str(i) for i in items]
    return " and ".join([", ".join(items[:-1]), items[-1]]) if len(items) > 1 else "".join(items)


STATUS_SLOT = re.compile(r"\{statuses\.(\w+)\}")


def fill_statuses(jql, data):
    """Turn each {statuses.<queue>} into the quoted Jira statuses listed under jira.statuses.<queue>."""
    statuses = (data.get("jira") or {}).get("statuses") or {}

    def one(m):
        names = statuses.get(m.group(1))
        if not names:
            raise ProfileError("%s has no jira.statuses.%s" % (PATH, m.group(1)))
        return ", ".join('"%s"' % str(n).replace('"', '\\"') for n in names)
    return STATUS_SLOT.sub(one, jql)


def queries(data):
    """The ticket-list JQL, with {statuses.*} filled in and {user} turned into the %s Argus fills in."""
    q = get(data, "jira.queries")
    missing = [s for s in QUERY_SCOPES if not q.get(s)]
    if missing:
        raise ProfileError("%s has no jira.queries.%s" % (PATH, missing[0]))
    scopes = QUERY_SCOPES + tuple(s for s in OPTIONAL_QUERY_SCOPES if q.get(s))
    return {s: fill_statuses(q[s], data).replace("%", "%%").replace("{user}", "%s") for s in scopes}


try:
    PATH = profile_path()
    PROFILE = load(PATH)
    PRODUCT = get(PROFILE, "product.name")
    BRAND = get(PROFILE, "product.brand")
    WORKBENCH_TITLE = PROFILE.get("product", {}).get("framework_name") or BRAND + " Argus"
    WORKBENCH_SHORT = WORKBENCH_TITLE
    WORKBENCH_BRAND = WORKBENCH_TITLE[:-len(" Argus")] if WORKBENCH_TITLE.endswith(" Argus") else BRAND
    LEGACY_SYSTEMS = list(PROFILE.get("product", {}).get("legacy_systems") or [])
    ACT_AS = [str(u).upper() for u in (PROFILE.get("act_as") or {}).get("allowed") or []]
    JIRA_HOST = get(PROFILE, "jira.host").rstrip("/")
    PROJECT = get(PROFILE, "jira.project")
    IT_TEAM = get(PROFILE, "jira.it_team")
    JIRA_TOKEN_ENV = get(PROFILE, "jira.token_env")
    FIELDS = {k: get(PROFILE, "jira.fields." + k) for k in ("story_points", "sprint", "acceptance", "it_team")}
    FIELDS["epic_link"] = (PROFILE.get("jira", {}).get("fields") or {}).get("epic_link") or ""
    JQL = queries(PROFILE)
    PHASES = [str(x).upper() for x in get(PROFILE, "jira.phases")]
    REPO_HOST = get(PROFILE, "repo.host")
    REPO_SLUG = get(PROFILE, "repo.slug")
    KB_BRANCH = get(PROFILE, "repo.kb_branch")
    DEVIN_APP = get(PROFILE, "devin.app").rstrip("/")
    DEVIN_ORG = get(PROFILE, "devin.org_id")
    KB = get(PROFILE, "paths.kb").strip("/")
    DOCS = {k: v for k, v in (PROFILE.get("docs") or {}).items() if not k.startswith("_")}
    AUTOMATION = {k: v for k, v in (PROFILE.get("automation") or {}).items() if not k.startswith("_")}

    if not re.match(r"^[A-Z][A-Z0-9_]*$", PROJECT):
        raise ProfileError("jira.project must be a Jira project key such as ABC, not %r" % PROJECT)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", JIRA_TOKEN_ENV):
        raise ProfileError("jira.token_env must be the name of an environment variable, not %r" % JIRA_TOKEN_ENV)
    if REPO_SLUG.count("/") != 1:
        raise ProfileError("repo.slug must look like PROJECT/repo, not %r" % REPO_SLUG)

    TICKET = re.escape(PROJECT) + r"-\d+"
except ProfileError as exc:
    # A wrong settings file is the team's to fix, not a crash: one line, no traceback.
    raise SystemExit("Argus settings: %s" % exc) from None


def fill_page(data, values):
    """A static page with its {{KEY}} markers replaced by the team's values, HTML-escaped."""
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, html.escape(str(value)))
    return text.encode("utf-8")


CLI_VALUES = {"product": PRODUCT, "brand": BRAND, "workbench_title": WORKBENCH_TITLE,
              "workbench_short": WORKBENCH_SHORT, "project": PROJECT, "jira_token_env": JIRA_TOKEN_ENV}

if __name__ == "__main__":
    # For the launch scripts: python3 sdlc_profile.py workbench_short
    if len(sys.argv) != 2 or sys.argv[1] not in CLI_VALUES:
        sys.exit("usage: sdlc_profile.py %s" % "|".join(CLI_VALUES))
    print(CLI_VALUES[sys.argv[1]])
