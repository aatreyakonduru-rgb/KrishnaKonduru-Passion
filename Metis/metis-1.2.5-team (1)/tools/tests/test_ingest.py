import io
import os
import sys
import tempfile
import unittest
import zipfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import doc_images  # noqa: E402
import doc_intake  # noqa: E402
import doc_kb  # noqa: E402
import read_docs  # noqa: E402
import verify_kb  # noqa: E402

WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        fh.write(text)


def docx_bytes(*paras):
    buf = io.BytesIO()
    body = "".join("<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % p for p in paras)
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document %s><w:body>%s</w:body></w:document>" % (WNS, body))
    return buf.getvalue()


class FakeHttp:
    """Answers GETs from a dict of url -> json or bytes."""

    def __init__(self, routes, deny=False):
        self.routes, self.deny, self.asked = routes, deny, []

    def json(self, url):
        self.asked.append(url)
        if self.deny:
            raise doc_intake.Denied("HTTP 401: the token is invalid or has no access")
        if url not in self.routes:
            raise doc_intake.Missing("HTTP 404")
        return self.routes[url]

    def bytes(self, url, auth=True, limit=0):
        self.asked.append(url)
        if url not in self.routes:
            raise doc_intake.Missing("HTTP 404")
        return self.routes[url]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb = os.path.join(self.tmp, "repo", "kb")
        self.scratch = os.path.join(self.tmp, "scratch")
        self.profile = {"product": {"name": "S"}, "sources": {
            "confluence": {"base_url": "https://wiki.example.test", "secret": "CONF"},
            "sharepoint": {"secret": "SP"}}}
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(self.profile))

    def intake(self, sources, http=None, by="Pat Lee", **kw):
        it = doc_intake.Intake(self.kb, self.scratch, by, profile=self.profile,
                               http_factory=(lambda kind: http) if http else None, **kw)
        it.run(sources)
        return it

    def manifest(self):
        return read_docs.load_manifest(self.scratch)["documents"]


class Local(Base):
    def test_folder_zip_text_and_unreadable(self):
        src = os.path.join(self.tmp, "handover")
        write(os.path.join(src, "rules.docx"), docx_bytes("Claims are paid within 30 days."), "wb")
        write(os.path.join(src, "notes", "standup.md"), "Decided to move go-live to March.\n")
        write(os.path.join(src, "pic.png"), b"\x89PNG....", "wb")
        write(os.path.join(src, ".hidden"), "x")
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("deep/spec.txt", "The interface runs nightly.\n")
            z.writestr("../evil.txt", "no")
        write(os.path.join(src, "bundle.zip"), inner.getvalue(), "wb")
        self.intake([src])
        names = {d["name"]: d for d in self.manifest().values()}
        self.assertEqual(names["rules.docx"]["status"], "read")
        self.assertEqual(names["notes__standup.md"]["status"], "read")
        self.assertEqual(names["spec.txt"]["status"], "read")
        self.assertIn("bundle.zip!deep/spec.txt", names["spec.txt"]["origin"])
        self.assertEqual(names["pic.png"]["status"], "not read")
        self.assertNotIn(".hidden", names)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.scratch, "INTAKE.yaml")))

    def test_missing_source_and_unknown_link_are_listed_not_fatal(self):
        self.intake([os.path.join(self.tmp, "nope"), "https://example.org/x"])
        res = yaml.safe_load(open(os.path.join(self.scratch, "INTAKE.yaml")))["files"]
        self.assertEqual([r["status"] for r in res], ["not read", "not read"])

    def test_file_limit(self):
        src = os.path.join(self.tmp, "many")
        for i in range(5):
            write(os.path.join(src, "f%d.txt" % i), "line %d\n" % i)
        self.intake([src], max_files=3)
        self.assertEqual(len(self.manifest()), 3)
        res = yaml.safe_load(open(os.path.join(self.scratch, "INTAKE.yaml")))["files"]
        self.assertEqual(len([r for r in res if "limit" in r.get("reason", "")]), 2)

    def test_scratch_inside_kb_refused(self):
        with self.assertRaises(SystemExit):
            doc_intake.main([self.kb, os.path.join(self.kb, "tmp"), "--by", "x", self.tmp])

    def test_same_file_keeps_its_id_and_a_changed_file_gets_a_new_one(self):
        f = os.path.join(self.tmp, "a", "Rules.txt")
        write(f, "Paid in 30 days.\n")
        self.intake([f])
        write(os.path.join(self.kb, "context", "x.md"), '- Paid [E: doc:Rules.txt#line1 "Paid in 30 days"]\n')
        self.assertEqual(read_docs.cmd_record(self.kb, self.scratch), 0)
        # a second run, new scratch: identical file keeps id Rules.txt; changed content becomes Rules.txt-2
        self.scratch = os.path.join(self.tmp, "scratch2")
        self.intake([f])
        self.assertIn("Rules.txt", self.manifest())
        write(f, "Paid in 45 days.\n")
        self.scratch = os.path.join(self.tmp, "scratch3")
        self.intake([f])
        self.assertEqual(list(self.manifest()), ["Rules.txt-2"])


class Links(Base):
    def test_confluence_page_children_and_attachment(self):
        b = "https://wiki.example.test"
        page = lambda i, t, body, anc=(): {  # noqa: E731
            "id": i, "title": t, "version": {"number": 3, "when": "2026-01-05"}, "space": {"key": "TEAM"},
            "ancestors": [{"title": a} for a in anc], "_links": {"webui": "/display/TEAM/%s" % t.replace(" ", "+")},
            "body": {"storage": {"value": body}}}
        routes = {
            b + "/rest/api/content/100?expand=" + doc_intake.CONF_EXPAND: page("100", "Claims Home", "<p>Claims are paid within 30 days.</p>"),
            b + "/rest/api/content/100/child/attachment?limit=50&start=0": {"results": [
                {"title": "rules.docx", "_links": {"download": "/download/rules.docx"}, "extensions": {"fileSize": 10}}]},
            b + "/download/rules.docx": docx_bytes("Appeals take 60 days."),
            b + "/rest/api/content/100/child/page?limit=50&start=0&expand=" + doc_intake.CONF_EXPAND: {"results": [
                page("101", "Child Page", "<p>Child fact.</p>", ("Claims Home",))]},
            b + "/rest/api/content/101/child/attachment?limit=50&start=0": {"results": []},
            b + "/rest/api/content/101/child/page?limit=50&start=0&expand=" + doc_intake.CONF_EXPAND: {"results": []},
        }
        self.intake([b + "/pages/viewpage.action?pageId=100"], FakeHttp(routes))
        docs = self.manifest()
        self.assertEqual(len(docs), 3)
        page_doc = [d for d in docs.values() if d["name"].startswith("Claims Home")][0]
        self.assertTrue(page_doc["origin"].startswith(b + "/display/TEAM"))
        text = read_docs.text_at(self.scratch, [k for k, d in docs.items() if d["name"].startswith("Child")][0])
        self.assertIn("Child fact.", " ".join(" ".join(v) for v in text.values()))
        self.assertTrue(any(d["name"] == "rules.docx" and d["status"] == "read" for d in docs.values()))

    def test_confluence_denied_is_reported_and_not_retried(self):
        http = FakeHttp({}, deny=True)
        self.intake(["https://wiki.example.test/pages/viewpage.action?pageId=9"], http)
        res = yaml.safe_load(open(os.path.join(self.scratch, "INTAKE.yaml")))["files"]
        self.assertEqual(res[0]["status"], "not read")
        self.assertIn("token", res[0]["reason"])
        self.assertEqual(len(http.asked), 1)

    def test_missing_token_is_reported(self):
        os.environ.pop("CONF", None)
        self.intake(["https://wiki.example.test/pages/viewpage.action?pageId=9"])
        res = yaml.safe_load(open(os.path.join(self.scratch, "INTAKE.yaml")))["files"]
        self.assertIn("CONF", res[0]["reason"])

    def test_confluence_link_forms(self):
        ref = doc_intake.Intake.conf_ref
        self.assertEqual(ref("https://w/x/pages/viewpage.action?pageId=55"), ("id", "55"))
        self.assertEqual(ref("https://w/wiki/spaces/ENG/pages/123/Title"), ("id", "123"))
        self.assertEqual(ref("https://w/display/ENG/My+Page"), ("title", "ENG", "My Page"))
        self.assertIsNone(ref("https://w/display/ENG"))

    def test_sharepoint_folder_recursive(self):
        url = "https://contoso.sharepoint.com/:f:/s/team/abc"
        sid = "u!" + doc_intake.base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        g = doc_intake.GRAPH
        par = {"driveId": "D1"}
        routes = {
            "%s/shares/%s/driveItem" % (g, sid): {"id": "F", "name": "Handover", "folder": {}, "parentReference": par},
            "%s/drives/D1/items/F/children?$top=200" % g: {"value": [
                {"id": "S", "name": "Sub", "folder": {}, "parentReference": par},
                {"id": "I1", "name": "design.docx", "size": 10, "parentReference": par, "webUrl": "https://contoso.sharepoint.com/design.docx",
                 "lastModifiedDateTime": "2026-02-01T10:00:00Z", "lastModifiedBy": {"user": {"displayName": "Sam Roy"}},
                 "@microsoft.graph.downloadUrl": "https://dl.example.test/design"},
                {"id": "I3", "name": "Home.aspx", "size": 10, "parentReference": par}]},
            "%s/drives/D1/items/S/children?$top=200" % g: {"value": [
                {"id": "I2", "name": "notes.txt", "size": 5, "parentReference": par, "webUrl": "https://contoso.sharepoint.com/notes.txt"}]},
            "https://dl.example.test/design": docx_bytes("The interface runs nightly."),
            "%s/drives/D1/items/I2/content" % g: b"Retry three times.\n",
        }
        self.intake([url], FakeHttp(routes))
        names = {d["name"]: d for d in self.manifest().values()}
        self.assertEqual(names["design.docx"]["origin"], "https://contoso.sharepoint.com/design.docx")
        self.assertEqual(names["notes.txt"]["status"], "read")
        res = yaml.safe_load(open(os.path.join(self.scratch, "INTAKE.yaml")))["files"]
        self.assertTrue(any(r["item"].endswith("Home.aspx") and r["status"] == "not read" for r in res))


class Restricted(Base):
    B = "https://wiki.example.test"
    URL = "https://wiki.example.test/pages/viewpage.action?pageId=100"

    def routes(self, ver=3, restricted=True, body="<p>Claims are paid within 30 days.</p>"):
        r = {"read": {"restrictions": {"user": {"results": [{"displayName": "Dee Data"}]}, "group": {"results": [{"name": "claims-team"}]}}}} if restricted else {}
        page = {"id": "100", "title": "Claims Home", "version": {"number": ver, "when": "2026-01-05"}, "space": {"key": "T"},
                "ancestors": [], "_links": {"webui": "/display/T/Claims+Home"}, "body": {"storage": {"value": body}}, "restrictions": r}
        return {self.B + "/rest/api/content/100?expand=" + doc_intake.CONF_EXPAND: page,
                self.B + "/rest/api/content/100/child/attachment?limit=50&start=0": {"results": []},
                self.B + "/rest/api/content/100/child/page?limit=50&start=0&expand=" + doc_intake.CONF_EXPAND: {"results": []}}

    def page(self, did, scratch=None):
        place = list(read_docs.text_at(scratch or self.scratch, did))[-1]
        write(os.path.join(scratch or self.scratch, "pages", "p.md"), "---\n%s---\n- Paid [E: doc:%s#%s \"Claims are paid within 30 days\"]\n" % (
            yaml.safe_dump({"title": "Claims", "category": "requirements"}), did, place))

    def test_restriction_is_captured_and_blocks_publishing_until_a_lead_approves(self):
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump(dict(self.profile, owners={"kb_owner": "Ana Lead"})))
        self.intake([self.URL], FakeHttp(self.routes()))
        did, d = list(self.manifest().items())[0]
        self.assertEqual(d["access"], "restricted")
        self.assertEqual(d["restricted_to"], ["Dee Data", "group claims-team"])
        self.page(did)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 1)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))
        self.assertEqual(doc_kb.main(["approve-restricted", self.scratch, did, "--kb", self.kb, "--by", "Pat Lee", "--note", "ok"]), 2)
        self.assertEqual(doc_kb.main(["approve-restricted", self.scratch, did, "--kb", self.kb, "--by", "Ana Lead", "--note", "claims team agreed to share"]), 0)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        with open(os.path.join(self.kb, "context", "requirements", "claims.md"), encoding="utf-8") as fh:
            self.assertIn("restricted at its source to Dee Data, group claims-team, use approved by Ana Lead", fh.read())
        self.assertEqual(read_docs.load_register(self.kb)[did]["access"], "restricted")

    def test_unrestricted_page_is_not_flagged(self):
        self.intake([self.URL], FakeHttp(self.routes(restricted=False)))
        self.assertNotIn("access", list(self.manifest().values())[0])

    def test_resync_skips_unchanged_versions_and_flags_changed_ones(self):
        self.intake([self.URL], FakeHttp(self.routes(restricted=False)))
        did = list(self.manifest())[0]
        self.page(did)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.assertEqual(read_docs.load_register(self.kb)[did]["version"], 3)
        s2 = os.path.join(self.tmp, "scratch2")
        doc_intake.Intake(self.kb, s2, "Pat Lee", profile=self.profile, http_factory=lambda k: FakeHttp(self.routes(restricted=False))).run([self.URL])
        self.assertEqual(read_docs.load_manifest(s2).get("documents") if os.path.isfile(read_docs.manifest_path(s2)) else {}, {})
        s3 = os.path.join(self.tmp, "scratch3")
        doc_intake.Intake(self.kb, s3, "Pat Lee", profile=self.profile, http_factory=lambda k: FakeHttp(
            self.routes(ver=4, restricted=False, body="<p>Claims are paid within 45 days.</p>"))).run([self.URL])
        new = list(read_docs.load_manifest(s3)["documents"].values())[0]
        self.assertEqual((new["version"], new["changed_from"]), (4, did))

class Publish(Base):
    def setUp(self):
        super().setUp()
        src = os.path.join(self.tmp, "in")
        write(os.path.join(src, "Claims Rules.docx"), docx_bytes("Claims are paid within 30 days.", "Appeals take 60 days."), "wb")
        write(os.path.join(src, "standup.txt"), "Meeting minutes. Decision: go live in March. Action item: Sam.\n")
        self.intake([src], by="Pat Lee")
        self.docs = self.manifest()
        self.rules = [k for k, d in self.docs.items() if d["name"].endswith("Claims Rules.docx")][0]
        self.stand = [k for k, d in self.docs.items() if d["name"].endswith("standup.txt")][0]
        self.page_dir = os.path.join(self.scratch, "pages")

    def page(self, name, front, body):
        write(os.path.join(self.page_dir, name), "---\n%s---\n%s" % (yaml.safe_dump(front), body))

    def good_pages(self):
        self.page("rules.md", {"title": "Claims payment rules", "category": "requirements"},
                  '- Paid within 30 days [E: doc:%s#para1 "paid within 30 days"]\n'
                  '- Appeals take 60 days [E: doc:%s#para2 "Appeals take 60 days"]\n' % (self.rules, self.rules))
        self.page("meet.md", {"title": "Go-live decision", "category": "meetings"},
                  '- Go live in March [E: doc:%s#line1 "go live in March"]\n' % self.stand)

    def test_classify_suggests_categories(self):
        self.assertEqual(doc_kb.classify(self.kb, self.scratch), 0)
        plan = {d["id"]: d for d in yaml.safe_load(open(os.path.join(self.scratch, "PLAN.yaml")))["documents"]}
        self.assertEqual(plan[self.stand]["suggested_category"], "meetings")

    def test_publish_writes_pages_with_provenance_and_passes_verify(self):
        self.good_pages()
        self.assertEqual(doc_kb.publish(self.kb, self.scratch, kept_at="SharePoint /Handover"), 0)
        text = open(os.path.join(self.kb, "context", "requirements", "claims-payment-rules.md"), encoding="utf-8").read()
        self.assertIn("generated_by: doc_kb.py", text)
        self.assertIn("given by Pat Lee", text)
        self.assertIn("## Sources", text)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "meetings", "go-live-decision.md")))
        index = open(os.path.join(self.kb, "context", "DOC_INDEX.md"), encoding="utf-8").read()
        self.assertIn("Claims Rules.docx", index)
        self.assertIn("Pat Lee", index)
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])
        self.assertEqual(read_docs.load_register(self.kb)[self.rules]["given_by"], "Pat Lee")

    def test_bad_batch_writes_nothing(self):
        self.good_pages()
        self.page("bad.md", {"title": "Wrong", "category": "nope"},
                  '- x [E: doc:%s#para1 "paid within 60 days"]\n- password: hunter22x\n' % self.rules)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 1)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))
        self.assertFalse(os.path.exists(read_docs.register_path(self.kb)))

    def test_untagged_fact_line_and_no_tags_are_refused(self):
        self.page("a.md", {"title": "A", "category": "other"}, "- a claim with no source\n")
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 1)
        self.page("a.md", {"title": "A", "category": "other"},
                  '- ok [E: doc:%s#para1 "paid within 30 days"]\n- loose line\n' % self.rules)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 1)

    def test_existing_hand_written_page_is_not_replaced(self):
        write(os.path.join(self.kb, "context", "meetings", "go-live-decision.md"), "# Mine\n")
        self.good_pages()
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.assertEqual(open(os.path.join(self.kb, "context", "meetings", "go-live-decision.md")).read(), "# Mine\n")
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "meetings", "go-live-decision.NEW.md")))

    def test_republish_updates_own_page_and_dry_run_writes_nothing(self):
        self.good_pages()
        self.assertEqual(doc_kb.publish(self.kb, self.scratch, dry=True), 0)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context")))
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "requirements", "claims-payment-rules.NEW.md")))

    def test_semicolon_in_quote_is_refused(self):
        self.page("a.md", {"title": "A", "category": "other"}, '- x [E: doc:%s#line1 "Decision: go live in March. Action item: Sam."]\n' % self.stand)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.page("a.md", {"title": "A", "category": "other"}, '- x [E: doc:%s#para1 "Claims are paid; within"]\n' % self.rules)
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 1)

    def test_after_the_gate_closes_pages_wait_for_a_lead(self):
        import kb_gate
        prof = os.path.join(self.kb, ".metis", "kb-profile.yaml")
        write(prof, yaml.safe_dump(dict(self.profile, owners={"kb_owner": "Ana Lead"})))
        kb_gate.lock(self.kb, "Ana Lead")
        self.good_pages()
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        self.assertFalse(os.path.exists(os.path.join(self.kb, "context", "requirements", "claims-payment-rules.md")))
        batch = kb_gate.batches(self.kb)[0]
        digest = open(os.path.join(self.kb, "_PENDING", batch, "DIGEST.md"), encoding="utf-8").read()
        self.assertIn("Pat Lee", digest)
        self.assertIn("Claims Rules.docx", digest)
        kb_gate.certify(self.kb, batch, "Ana Lead")
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "context", "requirements", "claims-payment-rules.md")))
        self.assertEqual(kb_gate.check(self.kb)[0], [])
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])


RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
ANS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20
PNG2 = b"\x89PNG\r\n\x1a\n" + bytes(range(255, -1, -1)) * 20


def pptx_with_pictures(path):
    rel = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId1" Target="../media/image1.png"/><Relationship Id="rId2" Target="../media/image2.png"/>'
           '<Relationship Id="rId3" Target="../media/tiny.png"/></Relationships>')
    blip = lambda i: '<a:blip r:embed="rId%d"/>' % i  # noqa: E731
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
        z.writestr("ppt/slides/slide4.xml", '<p:sld xmlns:p="x" %s %s><a:p><a:r><a:t>Flow</a:t></a:r></a:p>%s%s%s</p:sld>'
                   % (ANS, RNS, blip(1), blip(2), blip(3)))
        z.writestr("ppt/slides/_rels/slide4.xml.rels", rel)
        z.writestr("ppt/media/image1.png", PNG)
        z.writestr("ppt/media/image2.png", PNG2)
        z.writestr("ppt/media/tiny.png", b"\x89PNG\r\n\x1a\nxx")


class Pictures(Base):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.tmp, "in")
        os.makedirs(self.src)
        pptx_with_pictures(os.path.join(self.src, "deck.pptx"))
        write(os.path.join(self.src, "screen.png"), PNG, "wb")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", '<w:document %s %s %s><w:body><w:p><w:r><w:t>Intro</w:t></w:r></w:p>'
                       '<w:p><w:r><a:blip r:embed="rId9"/></w:r></w:p></w:body></w:document>' % (WNS, ANS, RNS))
            z.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId9" Target="media/image7.png"/></Relationships>')
            z.writestr("word/media/image7.png", PNG2 + b"z")
        write(os.path.join(self.src, "spec.docx"), buf.getvalue(), "wb")
        self.intake([self.src])
        doc_images.cmd_extract(self.scratch)
        self.items = yaml.safe_load(open(os.path.join(self.scratch, "IMAGES.yaml")))["images"]

    def by(self, doc, place):
        return [i for i in self.items if i["doc"] == doc and i["place"] == place][0]

    def test_extract_finds_pictures_in_order_and_skips_the_useless(self):
        self.assertEqual(self.by("deck.pptx", "slide4/image1")["status"], "pending")
        self.assertEqual(self.by("deck.pptx", "slide4/image2")["status"], "pending")
        self.assertIn("smaller", self.by("deck.pptx", "slide4/image3")["reason"])
        self.assertEqual(self.by("spec.docx", "image1")["status"], "pending")
        first = self.by("deck.pptx", "slide4/image1")
        self.assertTrue(os.path.isfile(first["file"]))
        # screen.png has the same bytes as deck image1: the model looks once, the copy gets the same text
        shot = self.by("screen.png", "image1")
        self.assertEqual((shot["status"], shot["duplicate_of"]), ("skipped", first["id"]))

    def test_picture_only_file_is_not_read_until_merge(self):
        self.assertEqual(self.manifest()["screen.png"]["status"], "not read")

    def write_text(self, entries):
        write(os.path.join(self.scratch, "IMAGE_TEXT.yaml"), yaml.safe_dump({"images": entries}))

    def pending_ids(self):
        return [i["id"] for i in self.items if i["status"] == "pending"]

    def test_merge_makes_picture_text_quotable_and_publishable(self):
        ids = {(i["doc"], i["place"]): i["id"] for i in self.items if i["status"] == "pending"}
        entries = [{"id": ids[("deck.pptx", "slide4/image1")], "kind": "text", "lines": ["Claim status | Days", "Open | 30"]},
                   {"id": ids[("deck.pptx", "slide4/image2")], "kind": "description", "lines": ["Box Intake points to box Adjudication"]},
                   {"id": ids[("spec.docx", "image1")], "kind": "decorative"}]
        self.write_text(entries)
        self.assertEqual(doc_images.cmd_merge(self.scratch), 0)
        man = self.manifest()
        self.assertEqual(man["screen.png"]["status"], "read")
        places = read_docs.text_at(self.scratch, "deck.pptx")
        self.assertEqual(places["slide4"], ["Flow"])  # real text is kept
        self.assertEqual(places["slide4/image1"], ["Claim status | Days", "Open | 30"])
        self.assertTrue(places["slide4/image2"][0].startswith("(model description)"))
        tags = lambda t: [p for _, p in read_docs.check_tags(self.scratch, t)]  # noqa: E731
        self.assertEqual(tags('- x [E: doc:deck.pptx#slide4/image1 "Open | 30"]'), [None])
        self.assertEqual(tags('- x [E: doc:screen.png#image1 "Open | 30"]'), [None])
        self.assertIn("not found", tags('- x [E: doc:deck.pptx#slide4/image1 "Open | 60"]')[0])
        # merge twice: nothing doubles
        self.assertEqual(doc_images.cmd_merge(self.scratch), 0)
        self.assertEqual(len(read_docs.text_at(self.scratch, "deck.pptx")["slide4/image1"]), 2)
        # a page quoting a picture publishes, the register marks it, the page says a model read it
        write(os.path.join(self.scratch, "pages", "p.md"), "---\ntitle: Claim days\ncategory: process\n---\n"
              '- Open claims take 30 days [E: doc:deck.pptx#slide4/image1 "Open | 30"]\n'
              '- Same table in the screenshot [E: doc:screen.png#image1 "Claim status | Days"]\n')
        self.assertEqual(doc_kb.publish(self.kb, self.scratch), 0)
        page = open(os.path.join(self.kb, "context", "processes", "claim-days.md"), encoding="utf-8").read()
        self.assertIn("read from pictures inside the documents by a model", page)
        reg = read_docs.load_register(self.kb)
        self.assertEqual(reg["deck.pptx"]["checked"][0]["read_from_picture_by_model"], "text")
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])

    def test_merge_reports_pictures_not_looked_at_and_bad_entries(self):
        first = self.pending_ids()[0]
        self.write_text([{"id": first, "kind": "text", "lines": []}, {"id": "img-999", "kind": "text", "lines": ["x"]}])
        self.assertEqual(doc_images.cmd_merge(self.scratch), 1)

    def test_image_with_no_viewable_format_is_skipped_with_a_reason(self):
        data = b"RIFF\x00\x00\x00\x00WAVE" + b"x" * 5000
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook/>")
            z.writestr("xl/media/image1.emf", data)
        f = os.path.join(self.tmp, "in2", "book.xlsx")
        write(f, buf.getvalue(), "wb")
        self.scratch = os.path.join(self.tmp, "s2")
        self.intake([f])
        doc_images.cmd_extract(self.scratch)
        items = yaml.safe_load(open(os.path.join(self.scratch, "IMAGES.yaml")))["images"]
        self.assertIn("cannot be shown", items[0]["reason"])

    def test_scanned_pdf(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("pymupdf not installed")
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        png = os.path.join(self.tmp, "scan.png")
        Image.effect_noise((200, 200), 80).save(png)
        pdf = os.path.join(self.tmp, "in3", "scan.pdf")
        os.makedirs(os.path.dirname(pdf))
        d = fitz.open()
        d.new_page().insert_image(fitz.Rect(0, 0, 300, 300), filename=png)
        d.save(pdf)
        self.scratch = os.path.join(self.tmp, "s3")
        self.intake([pdf])
        self.assertEqual(self.manifest()["scan.pdf"]["status"], "not read")
        doc_images.cmd_extract(self.scratch)
        items = yaml.safe_load(open(os.path.join(self.scratch, "IMAGES.yaml")))["images"]
        self.assertEqual((items[0]["place"], items[0]["status"]), ("p1/image1", "pending"))
        write(os.path.join(self.scratch, "IMAGE_TEXT.yaml"), yaml.safe_dump({"images": [
            {"id": items[0]["id"], "kind": "text", "lines": ["Appeal form 7"]}]}))
        self.assertEqual(doc_images.cmd_merge(self.scratch), 0)
        self.assertEqual(self.manifest()["scan.pdf"]["status"], "read")


if __name__ == "__main__":
    unittest.main()
