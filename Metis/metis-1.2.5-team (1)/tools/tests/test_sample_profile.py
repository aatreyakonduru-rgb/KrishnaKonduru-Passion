"""The sample profile in examples/acme must fill in every shareable prompt."""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

import prompts  # noqa: E402

SAMPLE = os.path.join(DIST, "examples", "acme")


class SampleProfileTests(unittest.TestCase):
    def test_every_prompt_renders_with_sample(self):
        profile = prompts.load_yaml(os.path.join(SAMPLE, "kb-profile.yaml"))
        reg = prompts.registry()
        files = sorted(glob.glob(os.path.join(DIST, "kb-prompts", "*.md")))
        rendered = 0
        for path in files:
            meta, _ = prompts.split(prompts.read(path))
            if not meta or not meta.get("shareable"):
                continue
            with self.subTest(prompt=os.path.basename(path)):
                out = prompts.render(prompts.read(path), profile, reg, env="test", base=SAMPLE,
                                     args={"MODULE_NAME": "orders-api", "MODULE_SOURCE": "orders-api"})
                self.assertNotIn("{{", out)
                rendered += 1
        self.assertGreater(rendered, 0)


if __name__ == "__main__":
    unittest.main()
