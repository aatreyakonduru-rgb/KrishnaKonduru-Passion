import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kb_gate  # noqa: E402
import kb_manifest  # noqa: E402


class GateLock(unittest.TestCase):
    def setUp(self):
        self.kb = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.kb)

    def test_lock_is_taken_and_released(self):
        path = os.path.join(self.kb, kb_gate.LOCK)
        with kb_gate.gate_lock(self.kb):
            self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path))

    def test_same_thread_can_nest(self):
        with kb_gate.gate_lock(self.kb):
            with kb_gate.gate_lock(self.kb, wait=0.2):
                pass
            self.assertTrue(os.path.exists(os.path.join(self.kb, kb_gate.LOCK)))
        self.assertFalse(os.path.exists(os.path.join(self.kb, kb_gate.LOCK)))

    def test_another_writer_waits_then_is_refused_with_a_plain_message(self):
        os.makedirs(os.path.join(self.kb, ".metis"))
        with open(os.path.join(self.kb, kb_gate.LOCK), "w") as fh:  # a lock another process holds
            fh.write("pid 1\n")
        t0 = time.monotonic()
        with self.assertRaises(kb_gate.GateError) as cm:
            with kb_gate.gate_lock(self.kb, wait=0.3):
                pass
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)
        self.assertIn("another certification is in progress", str(cm.exception))
        self.assertTrue(os.path.exists(os.path.join(self.kb, kb_gate.LOCK)))  # not ours: left alone

    def test_a_lock_left_by_a_dead_process_is_taken_over(self):
        os.makedirs(os.path.join(self.kb, ".metis"))
        p = os.path.join(self.kb, kb_gate.LOCK)
        with open(p, "w") as fh:
            fh.write("pid 1\n")
        old = time.time() - 1000
        os.utime(p, (old, old))
        with kb_gate.gate_lock(self.kb, wait=1, stale=300):
            pass
        self.assertFalse(os.path.exists(p))

    def test_the_lock_is_released_when_the_work_fails(self):
        with self.assertRaises(RuntimeError):
            with kb_gate.gate_lock(self.kb):
                raise RuntimeError("boom")
        self.assertFalse(os.path.exists(os.path.join(self.kb, kb_gate.LOCK)))

    def test_two_threads_never_lose_an_update(self):
        kb_gate.save_state(self.kb, {"locked": True, "files": {}})
        errors = []

        def add(n):
            try:
                for i in range(15):
                    with kb_gate.gate_lock(self.kb, wait=20):
                        st = kb_gate.load_state(self.kb)
                        st["files"]["t%d-%d.md" % (n, i)] = {"sha256": "x"}
                        time.sleep(0.001)
                        kb_gate.save_state(self.kb, st)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=add, args=(n,)) for n in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(kb_gate.load_state(self.kb)["files"]), 60)

    def test_state_is_written_whole_and_leaves_no_temp_file(self):
        kb_gate.save_state(self.kb, {"locked": True, "files": {"a.md": {"sha256": "1"}}})
        self.assertEqual(sorted(os.listdir(os.path.join(self.kb, ".metis"))), ["certified.yaml"])
        with open(os.path.join(self.kb, kb_gate.STATE), encoding="utf-8") as fh:
            self.assertEqual(yaml.safe_load(fh)["files"]["a.md"]["sha256"], "1")

    def test_the_lock_file_is_not_kb_content(self):
        self.assertTrue(".metis/gate.lock".startswith(kb_manifest.LOCAL))
        self.assertIn(".metis", kb_gate.EXEMPT_DIRS)


if __name__ == "__main__":
    unittest.main()
