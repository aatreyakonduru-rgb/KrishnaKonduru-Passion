import os
import sys
import tempfile
import unittest
import zipfile

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import read_docs  # noqa: E402
import verify_kb  # noqa: E402

WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SNS = ('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
ANS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_zip(path, parts):
    with zipfile.ZipFile(path, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)


class Docs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scratch = os.path.join(self.tmp, "scratch")
        self.kb = os.path.join(self.tmp, "repo", "kb")
        write(os.path.join(self.kb, ".metis", "kb-profile.yaml"), yaml.safe_dump({"product": {"name": "S"}}))
        self.docx = os.path.join(self.tmp, "Claims Rules.docx")
        make_zip(self.docx, {"word/document.xml":
            '<w:document %s><w:body><w:p><w:r><w:t>Claims are paid within 30 days.</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Status</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Closed</w:t>'
            '</w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>' % WNS})
        self.xlsx = os.path.join(self.tmp, "fields.xlsx")
        make_zip(self.xlsx, {
            "xl/workbook.xml": '<workbook %s><sheets><sheet name="Field Map" sheetId="1" r:id="rId1"/></sheets></workbook>' % SNS,
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                          '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/sharedStrings.xml": '<sst %s><si><t>MEMBER_ID</t></si></sst>' % SNS,
            "xl/worksheets/sheet1.xml": '<worksheet %s><sheetData><row r="2"><c r="B2" t="s"><v>0</v></c>'
                                        '<c r="C2"><v>12</v></c></row></sheetData></worksheet>' % SNS})
        self.pptx = os.path.join(self.tmp, "deck.pptx")
        make_zip(self.pptx, {"ppt/presentation.xml": "<p/>", "ppt/slides/slide2.xml":
            '<p:sld xmlns:p="x" %s><a:p><a:r><a:t>Go live in March</a:t></a:r></a:p></p:sld>' % ANS})
        self.bad = os.path.join(self.tmp, "scan.png")
        with open(self.bad, "wb") as fh:
            fh.write(b"\x89PNG....")
        self.assertEqual(read_docs.cmd_extract(self.scratch, [self.docx, self.xlsx, self.pptx, self.bad], "Pat Lee"), 0)
        self.man = read_docs.load_manifest(self.scratch)["documents"]

    def places(self, did):
        return read_docs.text_at(self.scratch, did)

    def test_extract_places(self):
        self.assertEqual(self.places("Claims-Rules.docx")["para1"], ["Claims are paid within 30 days."])
        self.assertEqual(self.places("Claims-Rules.docx")["para2"], ["Status | Closed"])
        self.assertEqual(self.places("fields.xlsx")["Field_Map!B2"], ["MEMBER_ID"])
        self.assertEqual(self.places("deck.pptx")["slide2"], ["Go live in March"])
        self.assertEqual(self.man["scan.png"]["status"], "not read")
        self.assertEqual(len(self.man["fields.xlsx"]["sha256"]), 64)

    def test_same_file_read_once(self):
        read_docs.cmd_extract(self.scratch, [self.docx], "Pat Lee")
        self.assertEqual(len(read_docs.load_manifest(self.scratch)["documents"]), 4)

    def check(self, text):
        return [p for _, p in read_docs.check_tags(self.scratch, text)]

    def test_check_quotes(self):
        self.assertEqual(self.check('- Paid in 30 days [E: doc:Claims-Rules.docx#para1 "paid within 30 days"]'), [None])
        self.assertIn("not found", self.check('- x [E: doc:Claims-Rules.docx#para1 "paid within 60 days"]')[0])
        self.assertIn("no place", self.check('- x [E: doc:Claims-Rules.docx#para9 "paid"]')[0])
        self.assertIn("could not be read", self.check('- x [E: doc:scan.png#line1 "x"]')[0])
        self.assertIn("must be", self.check("- x [E: doc:Claims-Rules.docx#para1]")[0])

    def test_record_then_verify(self):
        write(os.path.join(self.kb, "rules.md"),
              '# Claims\n\n- Paid in 30 days [E: doc:Claims-Rules.docx#para1 "paid within 30 days"]\n'
              '- Member id column [E: doc:fields.xlsx#Field_Map!B2 "MEMBER_ID"]\n')
        self.assertEqual(read_docs.cmd_record(self.kb, self.scratch, kept_at="SharePoint link"), 0)
        reg = read_docs.load_register(self.kb)
        self.assertEqual(set(reg), {"Claims-Rules.docx", "fields.xlsx"})
        self.assertEqual(reg["fields.xlsx"]["given_by"], "Pat Lee")
        self.assertEqual(verify_kb.Checker(self.kb).run()["problems"], [])
        write(os.path.join(self.kb, "more.md"), '# More\n\n- x [E: doc:Claims-Rules.docx#para1 "Claims are paid"]\n')
        probs = verify_kb.Checker(self.kb).run()["problems"]
        self.assertIn("was not checked", probs[0]["problem"])

    def test_record_refuses_bad_quote(self):
        write(os.path.join(self.kb, "rules.md"), '# C\n\n- x [E: doc:deck.pptx#slide2 "Go live in May"]\n')
        self.assertEqual(read_docs.cmd_record(self.kb, self.scratch), 1)
        self.assertFalse(os.path.exists(read_docs.register_path(self.kb)))

    def test_unrecorded_doc_fails_verify(self):
        write(os.path.join(self.kb, "rules.md"), '# C\n\n- x [E: doc:deck.pptx#slide2 "Go live"]\n')
        self.assertIn("not in _EVIDENCE/documents", verify_kb.Checker(self.kb).run()["problems"][0]["problem"])


if __name__ == "__main__":
    unittest.main()
