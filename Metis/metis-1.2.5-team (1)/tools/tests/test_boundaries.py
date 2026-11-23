import ast
import os
import unittest

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BANNED = {"cvbc", "team"}


class Boundaries(unittest.TestCase):
    def test_tools_never_import_team_folders(self):
        bad = []
        for root, _dirs, files in os.walk(TOOLS):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    try:
                        tree = ast.parse(fh.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mods = [node.module]
                    for m in mods:
                        if m.split(".")[0] in BANNED:
                            bad.append(f"{os.path.relpath(path, TOOLS)}: {m}")
        self.assertEqual(bad, [], "tools/ must not import cvbc or team")


if __name__ == "__main__":
    unittest.main()
