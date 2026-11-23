import os
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import code_links  # noqa: E402
import gen_graph  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class CodeLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({
            "product": {"name": "TestApp"},
            "sources": {"workspace_root": self.tmp, "repos": {"app": "app-repo"}}
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def file(self, name, text):
        write(os.path.join(self.tmp, "app-repo", name), text)

    def links(self):
        res = code_links.build(self.kb)
        return {(l["from"]["name"], l["rel"], l["to"]["name"]) for l in res["links"]}, res

    def test_python_imports_and_classes(self):
        self.file("services/user.py",
                  "import math\n"
                  "from app.models import BaseModel\n\n"
                  "class UserService(BaseModel):\n"
                  "    def get_user(self, uid):\n"
                  "        return math.sqrt(uid)\n")
        got, res = self.links()
        self.assertIn(("user", "imports", "math"), got)
        self.assertIn(("user", "imports", "app.models.BaseModel"), got)
        self.assertIn(("UserService", "references", "BaseModel"), got)
        self.assertEqual(res["dropped"], [])

    def test_python_flask_and_fastapi_endpoints(self):
        self.file("api/routes.py",
                  "from flask import Flask\n"
                  "app = Flask(__name__)\n\n"
                  "@app.route('/api/v1/orders', methods=['GET'])\n"
                  "def list_orders():\n"
                  "    return []\n\n"
                  "@app.post('/api/v1/orders')\n"
                  "def create_order():\n"
                  "    return {}\n")
        got, res = self.links()
        self.assertIn(("list_orders", "exposes_endpoint", "GET /api/v1/orders"), got)
        self.assertIn(("GET /api/v1/orders", "handled_by", "list_orders"), got)
        self.assertIn(("create_order", "exposes_endpoint", "POST /api/v1/orders"), got)
        self.assertIn(("POST /api/v1/orders", "handled_by", "create_order"), got)

    def test_python_table_references(self):
        self.file("models/order.py",
                  "class Order:\n"
                  "    __tablename__ = 'orders'\n"
                  "    def find(self, cursor):\n"
                  "        cursor.execute('SELECT id, amt FROM orders WHERE id = 1')\n")
        got, res = self.links()
        self.assertIn(("Order", "reads_table", "orders"), got)

    def test_java_spring_controller_and_jpa(self):
        self.file("src/main/java/org/example/OwnerController.java",
                  "package org.example;\n"
                  "import org.springframework.stereotype.Controller;\n"
                  "import org.springframework.web.bind.annotation.GetMapping;\n"
                  "import org.springframework.web.bind.annotation.PostMapping;\n\n"
                  "@Controller\n"
                  "public class OwnerController {\n"
                  "    @GetMapping(\"/owners/new\")\n"
                  "    public String initForm() {\n"
                  "        return \"form\";\n"
                  "    }\n"
                  "    @PostMapping(\"/owners/new\")\n"
                  "    public String processForm() {\n"
                  "        return \"redirect\";\n"
                  "    }\n"
                  "}\n")
        self.file("src/main/java/org/example/Owner.java",
                  "package org.example;\n"
                  "import jakarta.persistence.Entity;\n"
                  "import jakarta.persistence.Table;\n\n"
                  "@Entity\n"
                  "@Table(name = \"owners\")\n"
                  "public class Owner extends Person {\n"
                  "}\n")
        got, res = self.links()
        self.assertIn(("OwnerController", "exposes_endpoint", "GET /owners/new"), got)
        self.assertIn(("GET /owners/new", "handled_by", "OwnerController"), got)
        self.assertIn(("OwnerController", "exposes_endpoint", "POST /owners/new"), got)
        self.assertIn(("Owner", "reads_table", "owners"), got)
        self.assertIn(("Owner", "references", "Person"), got)
        self.assertEqual(res["dropped"], [])

    def test_java_repository_and_query(self):
        self.file("src/main/java/org/example/VetRepository.java",
                  "package org.example;\n"
                  "import org.springframework.data.jpa.repository.JpaRepository;\n"
                  "import org.springframework.data.jpa.repository.Query;\n\n"
                  "public interface VetRepository extends JpaRepository<Vet, Integer> {\n"
                  "    @Query(\"SELECT v FROM vets v ORDER BY v.lastName\")\n"
                  "    List<Vet> findAllVets();\n"
                  "}\n")
        got, res = self.links()
        self.assertIn(("VetRepository", "references", "Vet"), got)
        self.assertIn(("VetRepository", "reads_table", "vets"), got)

    JAVA_SAMPLE = (
        "package org.example;\n"
        "import org.springframework.data.repository.CrudRepository;\n"
        "// import fake.Commented;\n"
        "/* @GetMapping(\"/fake\") */\n"
        "@RequestMapping(\"/api\")\n"
        "public class Foo<T> extends Bar<T, U> implements Baz {\n"
        "    @GetMapping(\"/a\")\n"
        "    int m() { return 1; }\n"
        "    @RequestMapping(value = \"/v\", method = RequestMethod.POST)\n"
        "    void n() {}\n"
        "}\n")
    JAVA_REPO_SAMPLE = (
        "package org.example;\n"
        "public interface R extends CrudRepository<Owner, Integer> {}\n")

    def check_java_sample(self, got):
        self.assertIn(("Foo", "exposes_endpoint", "GET /api/a"), got)
        self.assertIn(("Foo", "exposes_endpoint", "POST /api/v"), got)
        self.assertNotIn(("Foo", "exposes_endpoint", "GET /api/api"), got)   # class-level mapping is a prefix only
        self.assertFalse([g for g in got if g[2] in ("Commented", "GET /fake/fake", "GET /fake")])
        self.assertIn(("Foo", "references", "Bar"), got)
        self.assertNotIn(("Foo", "references", "U>"), got)                    # generic args are not types
        self.assertIn(("Foo", "references", "Baz"), got)
        self.assertIn(("R", "references", "Owner"), got)
        self.assertNotIn(("R", "references", "Integer>"), got)

    def test_java_regex_fallback_generics_comments_class_prefix(self):
        self.file("src/Foo.java", self.JAVA_SAMPLE)
        self.file("src/R.java", self.JAVA_REPO_SAMPLE)
        orig = code_links.load_tree_sitter
        code_links.load_tree_sitter = lambda: {}          # force the regex fallback even if tree-sitter is installed
        try:
            got, res = self.links()
        finally:
            code_links.load_tree_sitter = orig
        self.assertEqual(res["tree_sitter"], "none")
        self.check_java_sample(got)

    @unittest.skipUnless(code_links.load_tree_sitter().get("java"), "tree-sitter + tree-sitter-java not importable")
    def test_java_tree_sitter_matches_fallback_on_sample(self):
        self.file("src/Foo.java", self.JAVA_SAMPLE)
        self.file("src/R.java", self.JAVA_REPO_SAMPLE)
        got, res = self.links()
        self.assertIn("java", res["tree_sitter"])
        self.check_java_sample(got)
        key = lambda ls: {(l["from"]["name"], l["rel"], l["to"]["name"], l["line"]) for l in ls}
        parser = code_links.load_tree_sitter()["java"]
        for name, text in (("Foo.java", self.JAVA_SAMPLE), ("R.java", self.JAVA_REPO_SAMPLE)):
            ts = code_links.parse_java_ts(parser, text, name)[0]
            rx = code_links.parse_java(text, name)[0]
            self.assertEqual(key(ts), key(rx), name)

    @unittest.skipUnless(code_links.load_tree_sitter().get("java"), "tree-sitter + tree-sitter-java not importable")
    def test_java_tree_sitter_handles_what_regex_cannot(self):
        text = ("package a;\n"
                "@RequestMapping(path = \"/api\")\n"
                "public class Foo extends q.Base implements q.Qux<String> {\n"
                "    String s = \"class Evil extends Nope {\";\n"
                "    @GetMapping({\"/p\", \"/q\"})\n"
                "    void o() {}\n"
                "}\n")
        ts, _, _ = code_links.parse_java_ts(code_links.load_tree_sitter()["java"], text, "Foo.java")
        got = {(l["from"]["name"], l["rel"], l["to"]["name"]) for l in ts}
        self.assertIn(("Foo", "exposes_endpoint", "GET /api/p"), got)
        self.assertIn(("Foo", "exposes_endpoint", "GET /api/q"), got)
        self.assertIn(("Foo", "references", "Qux"), got)
        self.assertFalse([g for g in got if g[0] == "Evil"])               # text inside a string literal is not code

    def test_typescript_nestjs_and_express(self):
        self.file("src/controllers/pet.controller.ts",
                  "import { Controller, Get, Post } from '@nestjs/common';\n"
                  "import { PetService } from '../services/pet.service';\n\n"
                  "@Controller('pets')\n"
                  "export class PetController {\n"
                  "    @Get(':id')\n"
                  "    findOne() { return {}; }\n"
                  "}\n")
        got, res = self.links()
        self.assertIn(("pet.controller", "imports", "PetService"), got)
        self.assertIn(("PetController", "exposes_endpoint", "GET /pets/:id"), got)
        self.assertIn(("GET /pets/:id", "handled_by", "PetController"), got)

    def test_typescript_fetch_client_and_typeorm(self):
        self.file("src/client.ts",
                  "export async function loadPets() {\n"
                  "    const res = await fetch('/api/pets');\n"
                  "    return res.json();\n"
                  "}\n")
        self.file("src/models/pet.ts",
                  "import { Entity } from 'typeorm';\n\n"
                  "@Entity('pets')\n"
                  "export class Pet {}\n")
        got, res = self.links()
        self.assertIn(("client", "calls", "GET /api/pets"), got)
        self.assertIn(("Pet", "reads_table", "pets"), got)

    def test_symbols_for_helper(self):
        path = os.path.join(self.tmp, "app-repo", "math_utils.py")
        self.file("math_utils.py",
                  "class Calculator:\n"
                  "    def add(self, a, b):\n"
                  "        return a + b\n")
        syms = code_links.symbols_for(path)
        names = {s["name"]: s["kind"] for s in syms}
        self.assertEqual(names, {"Calculator": "class", "Calculator.add": "function"})

    def test_reflection_and_dynamic_dispatch_reported_as_unparsed(self):
        self.file("dyn.py",
                  "import importlib\n"
                  "def load(name):\n"
                  "    return getattr(importlib, name)\n")
        _, res = self.links()
        self.assertTrue(any("dynamic dispatch" in u["reason"] or "getattr" in u["reason"] for u in res["unparsed"]))

    def test_cli_and_origin_derivation(self):
        self.file("api.py", "def my_func(): pass\n")
        self.assertEqual(code_links.main([self.kb]), 0)
        out_file = os.path.join(self.kb, "CROSS-LAYER", "parsed.code.links.yaml")
        self.assertTrue(os.path.isfile(out_file))
        # gen_graph recognizes parsed.code.links.yaml as parsed origin
        self.assertEqual(gen_graph.origin_of("CROSS-LAYER/parsed.code.links.yaml"), "parsed")

    def test_merge_into_parsed_option(self):
        parsed_links_file = os.path.join(self.kb, "CROSS-LAYER", "parsed.links.yaml")
        write(parsed_links_file, yaml.safe_dump({
            "links": [{"from": {"type": "table", "name": "a"}, "rel": "reads", "to": {"type": "table", "name": "b"}, "source": '[E: app/x.sql:1 "x"]'}]
        }))
        self.file("app.py",
                  "import os\n"
                  "def hello(): pass\n")
        self.assertEqual(code_links.main([self.kb, "--merge-into-parsed"]), 0)
        with open(parsed_links_file, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        self.assertTrue(len(data.get("links", [])) >= 2)


if __name__ == "__main__":
    unittest.main()
