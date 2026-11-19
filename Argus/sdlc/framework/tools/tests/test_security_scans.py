"""security_scans.py tests: fake HTTP, no network, no secrets."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security_scans as ss  # noqa: E402

CFG = ss.load()
TOKEN = "tok-not-a-real-secret"


class FakeHttp:
    """Answers in order by (method, url fragment); records every call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers=None, data=None, cafile=None, timeout=60):
        self.calls.append((method, url, data))
        for i, (m, frag, code, body) in enumerate(self.routes):
            if m == method and frag in url:
                self.routes.pop(i)
                return code, body if isinstance(body, bytes) else json.dumps(body).encode()
        raise AssertionError("unexpected call %s %s" % (method, url))


def xlsx(rows):
    sheet = "".join('<row r="%d">%s</row>' % (i + 1, "".join(
        '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (col, i + 1, escape(val)) for col, val in row.items()))
        for i, row in enumerate(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/'
                   'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % sheet)
    return buf.getvalue()


WORKBOOK = [
    {"A": "Assessment Objective Working Tracker"},
    {"A": "GovRAMP Control ID", "D": "Control Name", "G": "Plain Language Requirement", "I": "Remediation Layer",
     "T": "Python Implementation Steps", "V": "JavaScript/Node.js Implementation Steps"},
    {"A": "AC-07", "D": "Unsuccessful Logon Attempts", "G": "Lock after failed logons", "I": "Application",
     "T": "Count failures", "V": "Show the lock message"},
    {"A": "CA-05b.", "D": "POA&M", "G": "Keep the POA&M current", "I": "Enterprise"},
    {"A": "SI-11", "D": "Error Handling", "G": "No internals in errors", "I": "Hybrid"},
]


class NotSetUpTests(unittest.TestCase):
    def test_each_tool_says_what_is_missing(self):
        self.assertEqual(ss.checkmarx(CFG, {}, "b", [])["status"], "not_set_up")
        self.assertIn("checkmarx_Access_Token", ss.checkmarx(CFG, {}, "b", [])["note"])
        self.assertIn("WIZ_CLIENT_ID", ss.wiz(CFG, {}, [])["note"])
        self.assertIn("ACME_CONFLUENCE_TOKEN", ss.govramp(CFG, {})["note"])
        pf = ss.preflight(CFG, {})
        self.assertTrue(all(v.startswith("not set up") for v in pf.values()))

    def test_dry_run_without_branch(self):
        r = ss.checkmarx(CFG, {"checkmarx_Access_Token": TOKEN}, None, [])
        self.assertEqual(r["status"], "not_set_up")
        self.assertIn("dry run", r["note"])

    def test_not_run_is_a_warning_not_a_pass(self):
        v = ss.verdict([ss.not_set_up("checkmarx", "x"), ss.not_set_up("wiz", "y")])
        self.assertEqual(v["overall"], "PASS_WITH_WARNINGS")
        self.assertEqual(len(v["warnings"]), 2)


class CheckmarxTests(unittest.TestCase):
    def results(self):
        return {"results": [
            {"id": "1", "type": "sast", "severity": "HIGH", "state": "TO_VERIFY",
             "data": {"queryName": "SQL_Injection", "nodes": [{"fileName": "/api/app/db.py", "line": 40}]}},
            {"id": "2", "type": "sast", "severity": "HIGH", "state": "TO_VERIFY",
             "data": {"queryName": "Reflected_XSS", "nodes": [{"fileName": "/web/src/old.js", "line": 9}]}},
            {"id": "3", "type": "sast", "severity": "CRITICAL", "state": "NOT_EXPLOITABLE",
             "data": {"queryName": "Hardcoded_Password", "nodes": [{"fileName": "/api/app/db.py", "line": 2}]}},
            {"id": "4", "type": "sca", "severity": "LOW", "state": "TO_VERIFY", "data": {"packageIdentifier": "x"}},
        ]}

    def test_scan_polls_and_blocks_only_findings_in_the_change(self):
        http = FakeHttp([
            ("GET", "/projects?name=claims-web", 200,
             {"projects": [{"id": "p1", "name": "claims-web"}]}),
            ("POST", "/scans", 201, {"id": "s1"}),
            ("GET", "/scans/s1", 200, {"status": "Running"}),
            ("GET", "/scans/s1", 200, {"status": "Completed"}),
            ("GET", "/results?scan-id=s1", 200, self.results()),
        ])
        with mock.patch.object(ss, "request", http):
            r = ss.checkmarx(CFG, {"checkmarx_Access_Token": TOKEN}, "devin/1-x", ["api/app/db.py"],
                             round_no=2, sleep=lambda s: None)
        self.assertEqual(r["status"], "findings")
        self.assertEqual([f["name"] for f in r["blocking"]], ["SQL_Injection"])
        self.assertEqual(r["counts"]["HIGH"], 2)
        self.assertEqual(r["counts"]["CRITICAL"], 0)
        self.assertEqual(r["round"], 2)
        scan = json.loads(http.calls[1][2])
        self.assertEqual(scan["handler"]["branch"], "devin/1-x")
        self.assertNotIn(TOKEN, json.dumps(r))
        v = ss.verdict([r])
        self.assertEqual(v["overall"], "FAIL")
        self.assertIn("SQL_Injection", ss.markdown(v))

    def test_pre_existing_blocks_when_configured(self):
        cfg = dict(CFG, block_pre_existing=True)
        findings = [ss.cx_finding(x) for x in self.results()["results"][:2]]
        for f in findings:
            f["in_change"] = False
        self.assertEqual(len(ss.graded("checkmarx", findings, cfg)["blocking"]), 2)
        self.assertEqual(len(ss.graded("checkmarx", findings, CFG)["blocking"]), 0)

    def test_refused_token_is_not_retried(self):
        http = FakeHttp([("GET", "/projects", 401, {})])
        with mock.patch.object(ss, "request", http):
            r = ss.checkmarx(CFG, {"checkmarx_Access_Token": TOKEN}, "b", [])
        self.assertEqual(r["status"], "error")
        self.assertEqual(len(http.calls), 1)

    def test_failed_scan(self):
        http = FakeHttp([
            ("GET", "/projects", 200, {"projects": [{"id": "p1", "name": "claims-web"}]}),
            ("POST", "/scans", 201, {"id": "s1"}),
            ("GET", "/scans/s1", 200, {"status": "Failed"}),
        ])
        with mock.patch.object(ss, "request", http):
            r = ss.checkmarx(CFG, {"checkmarx_Access_Token": TOKEN}, "b", [], sleep=lambda s: None)
        self.assertIn("Failed", r["note"])


class WizTests(unittest.TestCase):
    ENV = {"WIZ_CLIENT_ID": "id", "WIZ_CLIENT_SECRET": TOKEN}

    def node(self, **kw):
        n = {"id": kw.get("id", "f"), "name": "CVE-1", "detailedName": "urllib3", "version": "1.26.5",
             "fixedVersion": "1.26.18", "severity": "HIGH", "remediation": "",
             "layerMetadata": {"isBaseLayer": False},
             "vulnerableAsset": {"type": "CONTAINER_IMAGE",
                                 "name": "quay-nonprod.acme.example/claims/crln-shared-dev-img-api:1.0"}}
        n.update(kw)
        return n

    def test_unrecognised_client_id(self):
        with mock.patch.object(ss, "request", FakeHttp([("POST", "oauth/token", 401, b"")])):
            r = ss.wiz(CFG, self.ENV, [])
        self.assertEqual(r["status"], "error")
        self.assertIn("401", r["note"])

    def test_findings_are_scoped_tracked_and_graded(self):
        other = self.node(id="o", vulnerableAsset={"type": "CONTAINER_IMAGE", "name": "quay/x/someone-else:1"})
        nodes = [
            self.node(id="a"),
            self.node(id="b", layerMetadata={"isBaseLayer": True}),
            self.node(id="c", fixedVersion=None),
            self.node(id="d", version="2.1", fixedVersion="3.0"),
            other,
        ]
        http = FakeHttp([
            ("POST", "oauth/token", 200, {"access_token": "wiz-tok"}),
            ("POST", "graphql", 200, {"data": {"vulnerabilityFindings": {
                "nodes": nodes, "pageInfo": {"hasNextPage": False}}}}),
        ])
        with mock.patch.object(ss, "request", http):
            r = ss.wiz(CFG, self.ENV, ["api/requirements.txt"])
        sent = json.loads(http.calls[1][2])["variables"]["filterBy"]
        self.assertEqual(sent["assetTags"]["containsAny"][0]["value"], "apm0000000")
        self.assertIn("CONTAINER_IMAGE", sent["assetType"])
        self.assertEqual(r["unmatched"], 1)
        self.assertEqual(r["tracks"], {"code_fix": 1, "base_image": 1, "no_vendor_fix": 1, "needs_approval": 1})
        self.assertEqual([f["id"] for f in r["blocking"]], ["a"])
        self.assertNotIn(TOKEN, json.dumps(r))
        v = ss.verdict([r])
        self.assertEqual(v["overall"], "FAIL")
        self.assertTrue(any("code cannot fix" in w for w in v["warnings"]))

    def test_no_manifest_change_does_not_block(self):
        http = FakeHttp([
            ("POST", "oauth/token", 200, {"access_token": "wiz-tok"}),
            ("POST", "graphql", 200, {"data": {"vulnerabilityFindings": {
                "nodes": [self.node()], "pageInfo": {"hasNextPage": False}}}}),
        ])
        with mock.patch.object(ss, "request", http):
            r = ss.wiz(CFG, self.ENV, ["api/app/routes.py"])
        self.assertEqual(r["blocking"], [])
        self.assertEqual(r["counts"]["HIGH"], 1)


class GovrampTests(unittest.TestCase):
    def workbook(self):
        path = os.path.join(tempfile.mkdtemp(), "rules.xlsx")
        with open(path, "wb") as fh:
            fh.write(xlsx(WORKBOOK))
        return path

    def test_reads_application_and_hybrid_rules(self):
        r = ss.govramp(CFG, {}, self.workbook())
        self.assertEqual(r["status"], "checklist")
        self.assertEqual(r["rule_count"], 3)
        self.assertEqual([x["id"] for x in r["rules"]], ["AC-07", "SI-11"])
        self.assertEqual(r["rules"][0]["python"], "Count failures")
        self.assertEqual(len(r["sha256"]), 64)

    def test_review_gap_blocks_and_met_passes(self):
        r = ss.govramp(CFG, {}, self.workbook())
        self.assertEqual(ss.verdict([r])["overall"], "PASS_WITH_WARNINGS")
        ss.review(r, "AC-07", "gap", "api/app/auth.py:40 no lockout")
        v = ss.verdict([r])
        self.assertEqual(v["overall"], "FAIL")
        self.assertIn("AC-07", v["blocking"][0]["name"])
        ss.review(r, "AC-07", "met", "api/app/auth.py:44")
        ss.review(r, "SI-11", "not_affected", "")
        self.assertEqual(ss.verdict([r])["overall"], "PASS")
        with self.assertRaises(ValueError):
            ss.review(r, "XX-1", "met", "")

    def test_not_a_gap_rules_workbook(self):
        path = os.path.join(tempfile.mkdtemp(), "usage.xlsx")
        with open(path, "wb") as fh:
            fh.write(xlsx([{"A": "Session", "B": "ACUs"}]))
        self.assertEqual(ss.govramp(CFG, {}, path)["status"], "error")

    def test_cli_review_and_verdict(self):
        out = os.path.join(tempfile.mkdtemp(), "g.json")
        with mock.patch("sys.stdout", io.StringIO()):
            ss.main(["govramp", "--workbook", self.workbook(), "--out", out])
            ss.main(["review", out, "--id", "SI-11", "--result", "met", "--evidence", "api/errors.py:12"])
            with mock.patch("sys.stdout", io.StringIO()) as buf:
                code = ss.main(["verdict", out, "--markdown"])
        self.assertEqual(code, 0)
        self.assertIn("## Security scans: PASS", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
