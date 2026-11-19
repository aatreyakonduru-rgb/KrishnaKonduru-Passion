"""gen_api_kb.py describes auth from what the scan found, not a fixed claim."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

import yaml

GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kbgen", "gen_api_kb.py")


def endpoint(path, handler, auth=None, decorators=()):
    return {"path": path, "method": "GET", "handler": handler, "line": 1, "params": [],
            "auth": auth, "decorators": list(decorators)}


class AuthFromScanTest(unittest.TestCase):
    def registry(self, endpoints):
        src = {"routers": [{"module": "apps.demo.api", "prefix": "/demo", "file": "apps/demo/api.py", "tags": [],
                            "endpoints": endpoints}], "commented_out_mounts": [], "schemas": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "api.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(src, fh)
            subprocess.run([sys.executable, GEN, path], cwd=tmp, check=True, capture_output=True,
                           env=dict(os.environ, SDLC_KB_OUT=os.path.join(tmp, "kb")))
            out = glob.glob(os.path.join(tmp, "kb", "**", "10_ENDPOINT_REGISTRY.yaml"), recursive=True)[0]
            with open(out, encoding="utf-8") as fh:
                return yaml.safe_load(fh)["metadata"]

    def test_mixed_endpoints_name_what_was_found(self):
        meta = self.registry([endpoint("/a", "a_api", "HttpAuthorizationAuth()", ["authenticate_request"]),
                              endpoint("/b", "b_api")])
        self.assertEqual(meta["auth_mechanism"], "HttpAuthorizationAuth() + @authenticate_request()")
        self.assertEqual(meta["endpoints_without_auth"], 1)
        self.assertNotIn("JWT", meta["auth_mechanism"])

    def test_no_auth_anywhere_says_so(self):
        meta = self.registry([endpoint("/b", "b_api")])
        self.assertEqual(meta["auth_mechanism"], "none found by the scan")
        self.assertEqual(meta["endpoints_without_auth"], 1)


if __name__ == "__main__":
    unittest.main()
