"""Which Metis features are experimental, and why.

A feature is experimental when it was built and tested only against fakes or local validators, or when no real consumer has
used it yet. Experimental features are not part of the default build and are hidden from the screen navigation until a team turns
them on, so the product a new team sees is the part that has been proven. The list lives here, in one place; the manual, the
Release Record and the UI read it through this module.

    python3 features.py list                 every feature and its state
    python3 features.py check                exit 1 if a feature names a file that does not exist

Turn a feature on for one KB in .metis/kb-profile.yaml:

    experimental:
      enable: [notify, bitbucket, oidc]      # feature ids from the list below, or "all"

A feature leaves this list when `evidence` says what real system it was verified against (and when).
"""
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))

# id: (what, files, screens, evidence needed to leave the list)
EXPERIMENTAL = {
    "notify": ("Slack, Teams, webhook and email alerts", ["notify.py", "refresh_trigger.py"], ["/notify"],
               "one real Slack or Teams message and one real SMTP mail received"),
    "bitbucket": ("Bitbucket pull request impact comments", ["bb_pr.py"], [],
                  "one comment posted to a real Bitbucket pull request (the comment route is unconfirmed)"),
    "oidc": ("Single sign-on with OpenID Connect", ["auth_oidc.py"], [],
             "one sign-in against the company identity provider"),
    "hybrid_search": ("Vector and hybrid search", ["kb_embed.py"], [],
                      "pack_eval.py --compare-names-only shows recall at least BM25's with a real embedder"),
    "llm_judge": ("Model-judged citations and golden answers", ["llm_judge.py"], [],
                  "agreement rate with human reviewers on 50 sampled lines, recorded"),
    "okf": ("OKF v0.2 bundle", ["okf_bundle.py"], [], "the official OKF validator passes a bundle"),
    "rdf": ("RDF, OWL and SPARQL export", ["export_rdf.py"], [], "one external graph tool loads the export"),
    "prov_otel": ("W3C PROV and OpenTelemetry export", ["export_prov.py"], [], "one collector ingests the export"),
    "federation": ("Shared cross-team index and impact walks", ["shared_index.py", "cross_impact.py"], ["/federation"],
                   "two real team KBs registered and walked"),
    "recipes": ("Runbook and CI recipe ingest", ["recipes_ingest.py"], [], "one real runbook ingested and reviewed by its owner"),
    "adr": ("ADR and incident ingest", ["adr_ingest.py"], [], "one real ADR folder ingested and reviewed by its owner"),
    "facts_time": ("Time-aware facts", ["facts_time.py"], [], "one real question answered from a past date"),
}


def profile(kb):
    p = os.path.join(kb, ".metis", "kb-profile.yaml")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def enabled(kb, feature):
    """True when `feature` is not experimental, or the profile lists it (or "all") under experimental.enable."""
    if feature not in EXPERIMENTAL:
        return True
    on = (profile(kb).get("experimental") or {}).get("enable") or []
    on = [on] if isinstance(on, str) else on
    return "all" in on or feature in on


def hidden_screens(kb):
    """Screen paths of experimental features this KB has not turned on."""
    return {s for f, (_, _, screens, _) in EXPERIMENTAL.items() if not enabled(kb, f) for s in screens}


def check():
    """Problems: a feature that names a file that is not in tools/."""
    out = []
    for f, (_, files, _, evidence) in EXPERIMENTAL.items():
        for name in files:
            if not os.path.isfile(os.path.join(HERE, name)):
                out.append("%s: %s is not in tools/" % (f, name))
        if not evidence:
            out.append("%s: says nothing about the evidence that ends its experimental state" % f)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("list", "check"):
        print(__doc__)
        return 2
    if argv[0] == "check":
        problems = check()
        for p in problems:
            print(p)
        print("%d features, %d problems" % (len(EXPERIMENTAL), len(problems)))
        return 1 if problems else 0
    for f, (what, files, screens, evidence) in sorted(EXPERIMENTAL.items()):
        print("%-14s %s\n               files: %s%s\n               leaves the list when: %s" % (
            f, what, ", ".join(files), "; screens: " + ", ".join(screens) if screens else "", evidence))
    return 0


if __name__ == "__main__":
    sys.exit(main())
