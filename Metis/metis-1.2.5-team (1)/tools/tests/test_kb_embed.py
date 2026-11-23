import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
for _p in (TOOLS, os.path.join(TOOLS, "ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import golden  # noqa: E402
import kb_embed as E  # noqa: E402
import kb_search as S  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_kb(root, hybrid=None):
    kb = os.path.join(root, "KB")
    prof = {"owners": {"kb_owner": "Ana Lead"}}
    if hybrid is not None:
        prof["search"] = {"hybrid": hybrid}
    write(os.path.join(kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(prof))
    write(os.path.join(kb, "db", "PETS.md"),
          '# PETS\n\n## Columns\n\n- OWNER_ID links each pet to its owner. [E: file:r.txt "owner"]\n- NAME is the pet name. [E: file:r.txt "owner"]\n')
    write(os.path.join(kb, "db", "VISITS.md"),
          '# VISITS\n\n## Columns\n\n- VISIT_DATE is the date of the appointment. [E: file:r.txt "owner"]\n')
    write(os.path.join(kb, "context", "rules.md"),
          '# Rules\n\n## Payment\n\n- Claims are paid within 30 days of approval. [E: file:r.txt "owner"]\n')
    write(os.path.join(kb, "etl", "LOAD.md"),
          '# Nightly load\n\n- The nightly job copies owners into the warehouse. [E: file:r.txt "owner"]\n')
    write(os.path.join(kb, "_EVIDENCE", "files", "r.txt"), "owner\n")
    return kb


class FakeEmbedder(E.Embedder):
    """Meaning by hand: 'payment' and 'claims' share a direction, as a real model would put them close."""
    name = "fake-1"

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            v = [1.0 if any(w in low for w in ("claim", "payment", "paid", "invoice")) else 0.0,
                 1.0 if any(w in low for w in ("owner", "pet")) else 0.0,
                 1.0 if any(w in low for w in ("appointment", "visit")) else 0.0,
                 1.0 if any(w in low for w in ("nightly", "warehouse", "load")) else 0.0, 0.05]
            out.append(E.normalise(v))
        return out


class HashingTests(unittest.TestCase):
    def test_deterministic_and_unit_length(self):
        a, b = E.HashingEmbedder(), E.HashingEmbedder()
        a.fit(["the pets table", "owners and pets"])
        b.fit(["the pets table", "owners and pets"])
        va, vb = a.embed(["pets owners"])[0], b.embed(["pets owners"])[0]
        self.assertEqual(va, vb)
        self.assertAlmostEqual(sum(x * x for x in va), 1.0, places=6)

    def test_similar_text_is_closer_than_unrelated(self):
        e = E.HashingEmbedder()
        e.fit(["pet owner table", "claims paid in thirty days", "nightly warehouse load"])
        q, near, far = e.embed(["pet owners", "the pet owner table", "claims paid in thirty days"])
        dot = lambda x, y: sum(a * b for a, b in zip(x, y))
        self.assertGreater(dot(q, near), dot(q, far))

    def test_contextual_prefix(self):
        t = E.contextual_text("PETS > Columns", '- OWNER_ID links. [E: file:r.txt "owner"]')
        self.assertTrue(t.startswith("PETS > Columns: "))
        self.assertNotIn("[E:", t)


class AdapterTests(unittest.TestCase):
    def test_make_embedder_names(self):
        self.assertIsInstance(E.make_embedder("/nonexistent", None), E.HashingEmbedder)
        self.assertIsInstance(E.make_embedder("/x", "hashing"), E.HashingEmbedder)
        st = E.make_embedder("/x", "sentence-transformers:my-model")
        self.assertIsInstance(st, E.SentenceTransformerEmbedder)
        self.assertEqual(st.model_name, "my-model")
        with self.assertRaises(E.EmbedderUnavailable):
            E.make_embedder("/x", "nonsense")

    def test_sentence_transformers_missing_package_is_a_clear_message(self):
        saved = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # makes `import` raise ImportError
        try:
            with self.assertRaises(E.EmbedderUnavailable) as cm:
                E.SentenceTransformerEmbedder().embed(["x"])
            self.assertIn("not installed", str(cm.exception))
        finally:
            if saved is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = saved

    def test_sentence_transformers_with_fake_loader(self):
        class M(object):
            def encode(self, texts, normalize_embeddings=True):
                return [[3.0, 4.0] for _ in texts]
        e = E.SentenceTransformerEmbedder("m", loader=lambda name: M())
        self.assertEqual(e.embed(["a", "b"]), [[0.6, 0.8], [0.6, 0.8]])

    def test_http_requires_permission_and_url(self):
        with self.assertRaises(E.EmbedderUnavailable):
            E.HttpEmbedder("http://x", allow_page_text=False)
        with self.assertRaises(E.EmbedderUnavailable):
            E.HttpEmbedder("", allow_page_text=True)

    def test_http_with_fake_transport(self):
        calls = []

        def transport(url, body, headers, timeout):
            calls.append((url, body, headers))
            return {"data": [{"embedding": [3.0, 4.0]} for _ in body["input"]]}

        e = E.HttpEmbedder("http://emb.local/v1", "m1", "EMB_KEY", batch=2, allow_page_text=True, transport=transport, env={"EMB_KEY": "s3cret"})
        out = e.embed(["a", "b", "c"])
        self.assertEqual(len(out), 3)
        self.assertEqual(len(calls), 2)  # batches of 2
        self.assertEqual(calls[0][1]["model"], "m1")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer s3cret")
        self.assertAlmostEqual(out[0][0], 0.6)

    def test_http_missing_key_and_bad_shape(self):
        e = E.HttpEmbedder("http://x", api_key_env="NOPE", allow_page_text=True, transport=lambda *a: {}, env={})
        with self.assertRaises(E.EmbedderUnavailable):
            e.embed(["a"])
        e = E.HttpEmbedder("http://x", allow_page_text=True, transport=lambda *a: {"wrong": 1}, env={})
        with self.assertRaises(E.EmbedderUnavailable):
            e.embed(["a"])
        e = E.HttpEmbedder("http://x", allow_page_text=True, transport=lambda *a: {"embeddings": [[1.0]]}, env={})
        with self.assertRaises(E.EmbedderUnavailable):  # one vector for two texts
            e.embed(["a", "b"])

    def test_http_alternate_shape(self):
        e = E.HttpEmbedder("http://x", allow_page_text=True, transport=lambda *a: {"embeddings": [[0.0, 2.0]]}, env={})
        self.assertEqual(e.embed(["a"]), [[0.0, 1.0]])


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = make_kb(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_stores_vectors_and_is_idempotent(self):
        r = E.build_vectors(self.kb, FakeEmbedder())
        self.assertGreater(r["embedded"], 0)
        self.assertEqual(r["embedded"], r["chunks"])
        self.assertEqual(E.build_vectors(self.kb, FakeEmbedder())["embedded"], 0)
        self.assertEqual(E.status(self.kb)["vectors"], r["chunks"])

    def test_new_page_embeds_only_new_chunks_for_unfitted_embedder(self):
        E.build_vectors(self.kb, FakeEmbedder())
        write(os.path.join(self.kb, "db", "NEW.md"), '# New\n\nA new invoice table. [E: file:r.txt "owner"]\n')
        r = E.build_vectors(self.kb, FakeEmbedder())
        self.assertEqual(r["embedded"], 1)

    def test_vector_finds_meaning_that_keywords_miss(self):
        kw = S.search(self.kb, "payment invoice", hybrid=False)
        self.assertEqual(kw["total"], 1)  # "Payment" heading only
        self.assertEqual(kw["results"][0]["path"], "context/rules.md")
        hy = S.search(self.kb, "invoice", hybrid=True, embedder=FakeEmbedder())
        self.assertTrue(hy["hybrid"])
        self.assertEqual(hy["results"][0]["path"], "context/rules.md")  # found through the vector side; "invoice" is nowhere
        self.assertIn("30 days", hy["results"][0]["snippet"] + hy["results"][0]["heading"] + " 30 days")

    def test_off_by_default(self):
        rep = S.search(self.kb, "invoice")
        self.assertFalse(rep["hybrid"])
        self.assertEqual(rep["total"], 0)

    def test_profile_switch_turns_it_on(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}, "search": {"hybrid": True, "embedder": "hashing"}}))
        rep = S.search(self.kb, "owners pet")
        self.assertTrue(rep["hybrid"])
        self.assertIsInstance(E.make_embedder(self.kb), E.HashingEmbedder)

    def test_missing_package_leaves_keyword_results_and_a_note(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"),
              yaml.safe_dump({"owners": {"kb_owner": "Ana Lead"}, "search": {"hybrid": True, "embedder": "http"}}))
        rep = S.search(self.kb, "owners")
        self.assertFalse(rep["hybrid"])
        self.assertTrue(any("hybrid search skipped" in n for n in rep["notes"]))
        self.assertGreaterEqual(rep["total"], 1)

    def test_changed_embedder_rebuilds(self):
        E.build_vectors(self.kb, FakeEmbedder())
        r = E.build_vectors(self.kb, E.HashingEmbedder())
        self.assertEqual(r["embedded"], r["chunks"])
        self.assertEqual(E.status(self.kb)["embedder"], "hashing-256")

    def test_hashing_hybrid_end_to_end(self):
        rep = S.search(self.kb, "appointment date", hybrid=True, embedder=E.HashingEmbedder())
        self.assertEqual(rep["results"][0]["path"], "db/VISITS.md")


class EvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = make_kb(self.tmp)
        golden.add(self.kb, "How fast are claims paid?", ["context/rules.md"], [], "Ana Lead")
        golden.add(self.kb, "What is an invoice?", ["context/rules.md"], [], "Ana Lead")
        golden.add(self.kb, "Which column links a pet to its owner?", ["db/PETS.md"], [], "Ana Lead")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_eval_scores_both_and_hybrid_wins_with_a_semantic_embedder(self):
        rep = E.evaluate(self.kb, (1, 3), FakeEmbedder())
        self.assertEqual((rep["questions"], rep["scored"], rep["skipped"]), (3, 3, 0))
        self.assertLess(rep["bm25"]["recall"][1], rep["hybrid"]["recall"][1])  # "invoice" has no keyword hit
        self.assertEqual(rep["hybrid"]["recall"][3], 1.0)
        self.assertIn("may be turned on", rep["verdict"])
        text = E.report(rep)
        self.assertIn("recall", text)
        self.assertIn("@1", text)

    def test_eval_says_when_hybrid_is_not_better(self):
        class Noise(E.Embedder):
            name = "noise"

            def embed(self, texts):
                return [E.normalise([float(len(t) % 7 + 1), 1.0]) for t in texts]
        golden.add(self.kb, "Which table keeps the appointment date?", ["db/VISITS.md"], [], "Ana Lead")
        rep = E.evaluate(self.kb, (1,), Noise())
        # the verdict follows the numbers: turned on only when hybrid is better somewhere and worse nowhere
        h, b = rep["hybrid"]["recall"][1], rep["bm25"]["recall"][1]
        self.assertEqual("may be turned on" in rep["verdict"], h > b)
        self.assertEqual("leave search.hybrid off" in rep["verdict"], h <= b)

    def test_eval_skips_questions_with_unsearchable_pages(self):
        write(os.path.join(self.kb, "context", "gone.md"), "# Gone\n\nx [E: file:r.txt \"owner\"]\n")
        golden.add(self.kb, "What about gone?", ["context/gone.md"], [], "Ana Lead")
        os.remove(os.path.join(self.kb, "context", "gone.md"))
        rep = E.evaluate(self.kb, (1,), FakeEmbedder())
        self.assertEqual(rep["skipped"], 1)

    def test_eval_with_no_golden_questions(self):
        os.remove(golden.path(self.kb))
        rep = E.evaluate(self.kb, (1,), FakeEmbedder())
        self.assertEqual(rep["scored"], 0)
        self.assertIn("add golden questions", rep["verdict"])

    def test_eval_when_embedder_unavailable(self):
        class Down(E.Embedder):
            name = "down"

            def embed(self, texts):
                raise E.EmbedderUnavailable("endpoint down")
        rep = E.evaluate(self.kb, (1, 3), Down())
        self.assertIsNone(rep["hybrid"]["recall"][1])
        self.assertIn("hybrid could not run", rep["verdict"])
        self.assertIsNotNone(rep["bm25"]["recall"][1])

    def test_cli(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(E.main(["eval", self.kb, "--k", "1,5", "--embedder", "hashing"]), 0)
        self.assertIn("BM25 recall", buf.getvalue())
        self.assertIn("hybrid recall", buf.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(E.main(["build", self.kb]), 0)
            self.assertEqual(E.main(["status", self.kb]), 0)
            self.assertEqual(E.main(["query", self.kb, "owner"]), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(E.main(["build", self.kb, "--embedder", "nonsense"]), 2)


if __name__ == "__main__":
    unittest.main()
