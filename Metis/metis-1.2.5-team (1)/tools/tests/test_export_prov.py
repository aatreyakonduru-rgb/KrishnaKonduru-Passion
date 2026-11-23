import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import export_prov  # noqa: E402
import kb_gate  # noqa: E402


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


class ExportProvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "KB")
        os.makedirs(os.path.join(self.kb, ".metis"), exist_ok=True)
        os.makedirs(os.path.join(self.kb, "context"), exist_ok=True)

        write_file(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
                   yaml.safe_dump({"product": {"name": "ClaimsService"},
                                   "owners": {"kb_owner": "Ana Lead", "roles": {"lead": "Ana Lead"}},
                                   "otel": {"endpoint": "https://otel.example.test/v1/traces"}}))

        write_file(os.path.join(self.kb, "_EVIDENCE", "files", "rules.txt"), "pay in 30 days\n")
        write_file(os.path.join(self.kb, "context", "rules.md"),
                   "# Claims Rules\n\n- Claims are paid within 30 days [E: file:rules.txt]\n")

        # Create certification state and log
        kb_gate.lock(self.kb, "Ana Lead")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prov_turtle_export(self):
        ttl = export_prov.to_prov_turtle(self.kb)
        self.assertIn("@prefix prov: <http://www.w3.org/ns/prov#>", ttl)
        self.assertIn("prov:Activity", ttl)
        self.assertIn("prov:Person", ttl)
        self.assertIn("prov:Entity", ttl)
        self.assertIn("prov:wasGeneratedBy", ttl)
        self.assertIn("prov:wasAttributedTo", ttl)
        self.assertIn("Ana Lead", ttl)
        self.assertIn("rules.md", ttl)

    def test_prov_json_export(self):
        json_str = export_prov.to_prov_json(self.kb)
        doc = json.loads(json_str)
        self.assertIn("prefix", doc)
        self.assertIn("agent", doc)
        self.assertIn("activity", doc)
        self.assertIn("entity", doc)
        self.assertIn("wasGeneratedBy", doc)
        self.assertIn("wasAttributedTo", doc)

        # Check agent exists for Ana Lead
        has_lead = any("Ana Lead" in str(v) for v in doc["agent"].values())
        self.assertTrue(has_lead, "Ana Lead must be registered as a PROV agent")

    def test_otlp_json_export(self):
        otlp_str = export_prov.to_otlp_json(self.kb)
        doc = json.loads(otlp_str)
        self.assertIn("resourceSpans", doc)
        self.assertIn("resourceLogs", doc)

        spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertGreater(len(spans), 0)
        self.assertTrue(any("Lock" in s.get("name", "") or "Activity" in str(s) for s in spans))

        logs = doc["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        self.assertGreater(len(logs), 0)
        self.assertIn("Certification: lock", logs[0]["body"]["stringValue"])

    def test_export_all_prov(self):
        out_dir = os.path.join(self.kb, ".metis", "exports", "prov")
        written = export_prov.export_all_prov(self.kb, out_dir)
        self.assertTrue(any(w.endswith("prov-o.ttl") for w in written))
        self.assertTrue(any(w.endswith("prov.json") for w in written))
        self.assertTrue(any(w.endswith("otel-traces.json") for w in written))

        for p in written:
            self.assertTrue(os.path.isfile(p))
            self.assertGreater(os.path.getsize(p), 0)

    @patch("urllib.request.urlopen")
    def test_post_otlp_mock(self, mock_urlopen):
        class MockResp(object):
            def __init__(self):
                self.status = 200
            def read(self):
                return b'{"status":"success"}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        mock_urlopen.return_value = MockResp()
        code, resp = export_prov.post_otlp('{"resourceSpans":[]}', "https://otel.example.test/v1/traces")
        self.assertEqual(code, 200)
        self.assertIn("success", resp)


if __name__ == "__main__":
    unittest.main()
