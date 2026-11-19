"""tools/roadmap_epics.py — a PO roadmap sheet becomes epic drafts plus the questions the PO still owes."""
import io
import os
import sys
import unittest
import urllib.error
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roadmap_epics as re_  # noqa: E402

HEADER = ["Feature", "Programme", "Needed by", "Confluence link", "Notes", "Outcomes", "Owner", "Colour"]
FULL = ["Threshold override screen", "EOC", "Q2 2027",
        "https://wiki.acme.example/pages/viewpage.action?pageId=123",
        "PCMH coordinators need to override thresholds. Today they email the analyst.",
        "1. Override saved\n2. Audit row written", "Jane", "orange"]
THIN = ["CHF work-UI 2026", "CHF", "", "", "", "", "", ""]


def xlsx(rows):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    body = "".join('<row r="%d">' % (r + 1) + "".join(
        '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>'
        % (chr(65 + c), r + 1, v.replace("&", "&amp;").replace("<", "&lt;"))
        for c, v in enumerate(row)) + "</row>" for r, row in enumerate(rows))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        xml = '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (ns, body)
        zf.writestr("xl/worksheets/sheet1.xml", xml)
    return buf.getvalue()


def page(title="Override BRD", version=4, when="2026-09-01T10:00:00.000Z"):
    return {"title": title, "version": {"number": version, "when": when}, "space": {"key": "ACMEWIKI"}}


class SheetTests(unittest.TestCase):
    def test_xlsx_and_csv_read_the_same_rows(self):
        rows = [HEADER, FULL, THIN]
        self.assertEqual(re_.read_xlsx(xlsx(rows)), rows)
        csv_rows = re_.read_csv(("\n".join(",".join('"%s"' % c.replace("\n", " ") for c in r) for r in rows)).encode())
        self.assertEqual(csv_rows[0], HEADER)
        self.assertEqual(csv_rows[2], THIN)

    def test_columns_are_matched_loosely_and_leftovers_reported(self):
        mapping, unmapped = re_.map_columns(HEADER)
        self.assertEqual({k: HEADER[v] for k, v in mapping.items()},
                         {"title": "Feature", "programme": "Programme", "target": "Needed by",
                          "source": "Confluence link", "description": "Notes", "outcomes": "Outcomes",
                          "owner": "Owner"})
        self.assertEqual(unmapped, ["Colour"])
        with self.assertRaises(ValueError):
            re_.plan([["Colour", "Comment"], ["x", "y"]])


class DraftTests(unittest.TestCase):
    def reader(self, **kw):
        return re_.ConfluenceReader(token="t", opener=lambda p: page(**kw))

    def test_full_row_only_owes_the_fix_version(self):
        res = re_.plan([HEADER, FULL], confluence=self.reader())
        d = res["epics"][0]
        self.assertEqual(d["acceptance"], "1. Override saved\n2. Audit row written")
        self.assertEqual(d["notes"], ["orange"])
        self.assertEqual([q["field"] for q in res["questions"]], ["fix_version"])
        self.assertTrue(res["sources"][0]["readable"])
        self.assertEqual(res["sources"][0]["version"], 4)

    def test_thin_row_gets_every_contract_question(self):
        res = re_.plan([HEADER, THIN])
        fields = {q["field"] for q in res["questions"]}
        self.assertEqual(fields, {"summary", "description", "source", "acceptance", "target", "owner"})
        self.assertNotIn("specialty", fields)  # CHF named in the programme column
        self.assertTrue(any("phase, sprint, quarter or year" in q["question"] for q in res["questions"]))
        self.assertEqual(res["ready"], [])

    def test_specialty_comes_from_programme_or_title_else_asked(self):
        row = list(FULL)
        self.assertEqual(re_.plan([HEADER, row])["epics"][0]["specialty"], "EOC")
        row[1] = "Core"
        self.assertEqual(re_.plan([HEADER, row])["epics"][0]["specialty"], "Foundational")
        row[1] = "Analytics team"
        res = re_.plan([HEADER, row])
        self.assertEqual(res["epics"][0]["specialty"], "")
        self.assertIn("Foundational", [q for q in res["questions"] if q["field"] == "specialty"][0]["question"])
        self.assertNotIn("Analytics team", res["epics"][0]["labels"])

    def test_long_title_is_questioned_and_too_many_outcomes(self):
        row = list(FULL)
        row[0] = "A very long epic title that runs past the eight word rule"
        row[5] = "\n".join("%d. o%d" % (i, i) for i in range(1, 8))
        qs = dict((q["field"], q["question"]) for q in re_.plan([HEADER, row], confluence=self.reader())["questions"])
        self.assertIn("at most 8", qs["summary"])
        self.assertIn("at most six", qs["acceptance"])


class ConfluenceTests(unittest.TestCase):
    def test_unreadable_page_becomes_an_upload_request(self):
        def forbidden(path):
            if path.endswith("/user/current"):
                return {"username": "svc"}
            raise urllib.error.HTTPError(path, 404, "nf", {}, None)
        res = re_.plan([HEADER, FULL], confluence=re_.ConfluenceReader(token="t", opener=forbidden))
        src = [q for q in res["questions"] if q["field"] == "source"][0]["question"]
        self.assertIn("upload it as a document", src)
        self.assertIn("whenever that page changes", src)
        self.assertFalse(res["sources"][0]["readable"])

    def test_locked_account_is_not_retried(self):
        calls = []

        def locked(path):
            calls.append(path)
            raise urllib.error.HTTPError(path, 403, "locked", {}, None)
        r = re_.ConfluenceReader(token="t", opener=locked)
        r.check("https://wiki.acme.example/pages/viewpage.action?pageId=1")
        r.check("https://wiki.acme.example/pages/viewpage.action?pageId=2")
        self.assertEqual(len(calls), 1)
        self.assertIn("403", r.locked)

    def test_no_token_and_no_page_id(self):
        r = re_.ConfluenceReader(token="")
        why = r.check("https://wiki.acme.example/pages/viewpage.action?pageId=9")["why"]
        self.assertIn("no Confluence service-account token", why)
        why = re_.ConfluenceReader(token="t").check("https://wiki.acme.example/x/abc")["why"]
        self.assertIn("no page id", why)

    def test_source_stamp_and_staleness(self):
        src = {"readable": True, "title": "BRD", "version": 4, "updated": "2026-09-01"}
        stamp = re_.source_stamp(src, "2026-10-09")
        self.assertEqual(stamp, 'Source: Confluence page "BRD" (v4, updated 2026-09-01), read 2026-10-09.')
        self.assertFalse(re_.source_is_stale(stamp, "2026-10-09"))
        self.assertTrue(re_.source_is_stale(stamp, "2027-02-01"))
        up = re_.source_stamp({"readable": False, "name": "brd.docx"}, "2026-10-09")
        self.assertIn("fresh upload", up)
        self.assertTrue(re_.source_is_stale(up, "2027-01-20"))
        self.assertFalse(re_.source_is_stale("no stamp here"))


class OutputTests(unittest.TestCase):
    def test_markdown_and_year_plan(self):
        res = re_.plan([HEADER, FULL, THIN])
        md = re_.to_markdown(res)
        self.assertIn("Nothing is written to Jira", md)
        self.assertIn("## Threshold override screen", md)
        self.assertIn("[owner]", md)
        yp = re_.to_year_plan(res, 2026, "roadmap.xlsx")
        self.assertIn('name: "Threshold override screen"\n    status: next_year', yp)
        self.assertIn('note: "EOC · needed by Q2 2027"', yp)
        self.assertIn('note: "CHF"\n    target_confirmed: false', yp)
        self.assertNotIn("points", yp)


if __name__ == "__main__":
    unittest.main()
