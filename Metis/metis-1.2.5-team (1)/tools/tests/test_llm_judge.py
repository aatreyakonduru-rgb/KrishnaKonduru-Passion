import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import golden  # noqa: E402
import llm_judge as J  # noqa: E402

PROFILE = {"owners": {"kb_owner": "Ana Lead"}}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class FakeJudge(J.Judge):
    """Says `supported` when every word of the claim's first number-or-word is in the window; records what it saw."""
    name = "fake"

    def __init__(self, verdict="supported"):
        self.verdict, self.seen = verdict, []

    def judge(self, request):
        self.seen.append(request)
        return {"id": request["id"], "verdict": self.verdict, "reason": "fake reason", "judged_by": "fake"}


class Base(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(PROFILE))
        write(os.path.join(self.kb, "_EVIDENCE", "files", "r.txt"), "Claims are paid within 30 days of approval.\nOther line.\n")
        write(os.path.join(self.kb, "context", "rules.md"), "# Rules\n\n- Claims are paid within 30 days. [E: file:r.txt \"paid within 30 days\"]\n")
        self.ans = os.path.join(self.kb, "ans")
        write(os.path.join(self.ans, "G-0001.md"), "# A\n\n- Claims are paid within 30 days. [E: kb:context/rules.md \"paid within 30 days\"]\n")
        golden.add(self.kb, "How fast are claims paid?", ["context/rules.md"], ["30 days"], "Ana Lead")

    def tearDown(self):
        shutil.rmtree(self.kb, ignore_errors=True)


class Citations(Base):
    def test_request_has_claim_quote_and_window(self):
        reqs = J.citation_requests(self.kb, slurp(os.path.join(self.kb, "context", "rules.md")), "context/rules.md")
        self.assertEqual(len(reqs), 1)
        req, lexical = reqs[0]
        self.assertIsNone(lexical)
        self.assertEqual(req["claim"], "Claims are paid within 30 days.")
        self.assertEqual(req["quote"], "paid within 30 days")
        self.assertIn("Claims are paid within 30 days of approval.", req["source_window"])
        self.assertEqual(req["where"], "context/rules.md:3")
        self.assertRegex(req["id"], r"^J-[0-9a-f]{10}$")

    def test_fake_judge_verdicts_sit_beside_lexical_result(self):
        j = FakeJudge("partial")
        rows = J.judge_citations(self.kb, slurp(os.path.join(self.kb, "context", "rules.md")), j, "rules")
        self.assertEqual(rows[0]["judged"]["verdict"], "partial")
        self.assertEqual(rows[0]["judged"]["says"], "partly supported by the quoted source text")
        self.assertEqual(rows[0]["lexical"], "quote and lines check out")

    def test_lexical_failure_is_kept_when_judged(self):
        write(os.path.join(self.kb, "x.md"), "- Claims are paid within 45 days. [E: file:r.txt \"within 45 days\"]\n")
        rows = J.judge_citations(self.kb, slurp(os.path.join(self.kb, "x.md")), FakeJudge("supported"), "x")
        self.assertIn("quoted text not found", rows[0]["lexical"])

    def test_missing_source_is_unavailable_not_judged(self):
        j = FakeJudge()
        rows = J.judge_citations(self.kb, "- Claim. [E: file:nope.txt]\n", j, "x")
        self.assertEqual(rows[0]["judged"]["status"], "unavailable")
        self.assertEqual(j.seen, [])

    def test_headings_and_code_are_not_claims(self):
        self.assertEqual(J.citation_requests(self.kb, "# Title [E: file:r.txt]\n```\n- x [E: file:r.txt]\n```\n"), [])


class FileJudgeTests(Base):
    def test_writes_request_then_reads_verdict(self):
        fj = J.FileJudge(self.kb)
        req = J.citation_requests(self.kb, slurp(os.path.join(self.kb, "context", "rules.md")), "r")[0][0]
        self.assertIsNone(fj.judge(req))
        rp = os.path.join(self.kb, ".metis", "judge", "requests", req["id"] + ".json")
        self.assertTrue(os.path.isfile(rp))
        self.assertEqual(json.loads(slurp(rp))["claim"], req["claim"])
        self.assertEqual(slurp(os.path.join(self.kb, ".metis", "judge", ".gitignore")).strip(), "*")
        write(os.path.join(self.kb, ".metis", "judge", "verdicts", req["id"] + ".json"),
              json.dumps({"id": req["id"], "verdict": "supported", "reason": "the source says 30 days", "judged_by": "Devin"}))
        v = fj.judge(req)
        self.assertEqual((v["verdict"], v["judged_by"]), ("supported", "Devin"))
        row = J.run_judge(fj, req)
        self.assertEqual(row["says"], "supported by the quoted source text")

    def test_pending_status_and_listing(self):
        J.judge_citations(self.kb, slurp(os.path.join(self.kb, "context", "rules.md")), J.FileJudge(self.kb), "r")
        rows = J.list_requests(self.kb)
        self.assertEqual([r["status"] for r in rows], ["pending"])
        self.assertEqual(J.main(["status", self.kb]), 0)

    def test_bad_verdict_files_are_errors_not_verdicts(self):
        fj = J.FileJudge(self.kb)
        req = J.citation_requests(self.kb, slurp(os.path.join(self.kb, "context", "rules.md")), "r")[0][0]
        for bad in ({"id": req["id"], "verdict": "correct", "reason": "x"}, {"id": req["id"], "verdict": "supported", "reason": ""},
                    {"id": "J-other", "verdict": "supported", "reason": "x"}):
            write(os.path.join(self.kb, ".metis", "judge", "verdicts", req["id"] + ".json"), json.dumps(bad))
            self.assertEqual(J.run_judge(fj, req)["status"], "error")
        write(os.path.join(self.kb, ".metis", "judge", "verdicts", req["id"] + ".json"), "{not json")
        self.assertEqual(J.run_judge(fj, req)["status"], "error")

    def test_a_changed_line_gets_a_new_request_id(self):
        a = J.citation_requests(self.kb, "- Paid in 30 days. [E: file:r.txt]\n")[0][0]["id"]
        b = J.citation_requests(self.kb, "- Paid in 31 days. [E: file:r.txt]\n")[0][0]["id"]
        self.assertNotEqual(a, b)


class GoldenJudge(Base):
    def test_lexical_result_is_unchanged_and_judged_is_beside_it(self):
        lex_before = golden.score(self.kb, self.ans)
        rows = J.golden_judge(self.kb, self.ans, FakeJudge("supported"))
        self.assertEqual(golden.score(self.kb, self.ans), lex_before)
        r = rows[0]
        self.assertEqual(r["lexical"], {"result": lex_before[0]["result"], "why": lex_before[0]["why"]})
        self.assertEqual(r["judged"]["verdict"], "supported")
        self.assertEqual(r["flag"], "")
        self.assertEqual(r["citations"][0]["judged"]["verdict"], "supported")

    def test_golden_request_names_expected_pages_and_question(self):
        j = FakeJudge()
        J.golden_judge(self.kb, self.ans, j)
        req = [r for r in j.seen if r["kind"] == "golden"][0]
        self.assertEqual(req["expected_pages"], ["context/rules.md"])
        self.assertEqual(req["question"], "How fast are claims paid?")
        self.assertIn("paid within 30 days", req["source_window"])

    def test_disagreement_is_flagged_not_resolved(self):
        rows = J.golden_judge(self.kb, self.ans, FakeJudge("unsupported"))
        self.assertEqual(rows[0]["lexical"]["result"], "pass")
        self.assertEqual(rows[0]["flag"], "lexical pass, judged unsupported")

    def test_missing_answer(self):
        rows = J.golden_judge(self.kb, os.path.join(self.kb, "none"), FakeJudge())
        self.assertEqual((rows[0]["lexical"]["result"], rows[0]["judged"]["status"]), ("missing", "no answer"))

    def test_pending_with_file_judge_and_cli(self):
        rows = J.golden_judge(self.kb, self.ans, J.FileJudge(self.kb))
        self.assertEqual(rows[0]["judged"]["status"], "pending")
        self.assertEqual(J.main(["golden_judge", self.kb, self.ans, "--judge", "file"]), 0)
        self.assertTrue(os.listdir(os.path.join(self.kb, ".metis", "judge", "requests")))

    def test_summary(self):
        rows = J.golden_judge(self.kb, self.ans, FakeJudge("partial"))
        self.assertEqual(J.summary(rows)["partial"], 1)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HttpJudgeTests(unittest.TestCase):
    REQ = {"id": "J-1", "kind": "citation", "claim": "c", "quote": "q", "source_window": "w"}

    def judge(self, reply, env=None, endpoint="https://llm.example.com/v1/chat/completions"):
        calls = []

        def opener(req, timeout=None):
            calls.append(req)
            if isinstance(reply, Exception):
                raise reply
            return Resp(json.dumps({"choices": [{"message": {"content": reply}}]}).encode())
        j = J.HttpJudge(endpoint, "m1", "MY_KEY", 5, opener, env if env is not None else {"MY_KEY": "sk-secret"})
        return j, calls

    def test_parses_verdict_and_sends_key_only_in_header(self):
        j, calls = self.judge('Here: {"verdict": "Supported", "reason": "it says so"}')
        v = j.judge(self.REQ)
        self.assertEqual((v["verdict"], v["reason"], v["judged_by"]), ("supported", "it says so", "http:m1"))
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer sk-secret")
        self.assertNotIn(b"sk-secret", calls[0].data)
        self.assertIn(b'"model": "m1"', calls[0].data)

    def test_missing_key_env_is_a_clear_error_and_no_call(self):
        j, calls = self.judge("{}", env={})
        with self.assertRaises(J.JudgeError) as e:
            j.judge(self.REQ)
        self.assertIn("MY_KEY", str(e.exception))
        self.assertEqual(calls, [])

    def test_bad_replies_and_network_errors(self):
        for reply in ("no json here", '{"verdict": "great", "reason": "x"}', '{"verdict": "supported"}'):
            with self.assertRaises(J.JudgeError):
                self.judge(reply)[0].judge(self.REQ)
        with self.assertRaises(J.JudgeError):
            self.judge(urllib.error.URLError("down"))[0].judge(self.REQ)
        err = urllib.error.HTTPError("u", 401, "no", {}, None)
        with self.assertRaises(J.JudgeError) as e:
            self.judge(err)[0].judge(self.REQ)
        self.assertIn("401", str(e.exception))

    def test_endpoint_rules(self):
        with self.assertRaises(J.JudgeError):
            J.HttpJudge("http://llm.example.com/v1", "m", "K")
        with self.assertRaises(J.JudgeError):
            J.HttpJudge("ftp://x/y", "m", "K")
        with self.assertRaises(J.JudgeError):
            J.HttpJudge("https://x/y", "", "K")
        J.HttpJudge("http://127.0.0.1:8080/v1/chat/completions", "m", "K")

    def test_profile_builds_the_judge_and_never_stores_a_key(self):
        kb = tempfile.mkdtemp()
        try:
            self.assertIsInstance(J.judge_from_profile(kb), J.FileJudge)
            write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(
                {"judge": {"endpoint": "https://llm.example.com/v1/chat/completions", "model": "m1", "api_key_env": "MY_KEY"}}))
            j = J.judge_from_profile(kb, environ={})
            self.assertIsInstance(j, J.HttpJudge)
            self.assertEqual(j.api_key_env, "MY_KEY")
            self.assertFalse(hasattr(j, "api_key"))
            with self.assertRaises(J.JudgeError):
                J.judge_from_profile(tempfile.mkdtemp(), "http")
        finally:
            shutil.rmtree(kb, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
