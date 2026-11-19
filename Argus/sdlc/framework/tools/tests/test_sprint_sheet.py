"""The sprint planning sheet kept in the repo: formulas, the Capacity tab, edits, time off and new sprints."""
import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import sprint_sheet as S  # noqa: E402


def capacity(start="2026-10-07", days=7):
    """Two people over `days` calendar days from a Wednesday: hours = SUM(days) x B1 x share."""
    import datetime
    cells = {"A1": "Productive Hours =6", "B1": 6, "C1": "Sprint Days = 5", "C2": "Team  Member", "D2": "PTO Plan",
             "F2": "Office Location", "G2": "%age of time on Project"}
    cols = [S.col_name(8 + i) for i in range(days)]
    d0 = datetime.date.fromisoformat(start)
    for i, c in enumerate(cols):
        d = d0 + datetime.timedelta(days=i)
        cells["%s1" % c] = d.day
        cells["%s2" % c] = "MTWTFSS"[d.weekday()]
    hours = S.col_name(8 + days)
    cells["%s2" % hours] = "Available hours"
    for r, (name, share) in enumerate((("Ann Example", 1), ("Ben Example", 0.5)), start=3):
        cells["C%d" % r], cells["E%d" % r], cells["F%d" % r], cells["G%d" % r] = name, "Dev", "Offshore", share
        for i, c in enumerate(cols):
            cells["%s%d" % (c, r)] = 0 if (d0 + datetime.timedelta(days=i)).weekday() >= 5 else 1
        cells["%s%d" % (hours, r)] = '=IF(C%d="unassigned",0,(SUM(%s%d:%s%d)*$B$1)*G%d)' % (r, cols[0], r, cols[-1], r, r)
    cells["%s5" % hours] = "=SUM(%s3:%s4)" % (hours, hours)
    cells["%s6" % hours] = "=%s5/8" % hours
    cells["%s8" % hours] = "=%s6*1.3" % hours
    end = (d0 + datetime.timedelta(days=days - 1)).isoformat()
    return {"sprint": "26.4.2", "start": start, "end": end, "source": "test",
            "tabs": [{"name": "Capacity", "cells": cells},
                     {"name": "Carry forward", "cells": {"A1": "ACME-1", "D1": 13, "D2": 5, "D3": "=SUM(D1:D2)"}},
                     {"name": "Previous sprint AI savings", "cells": {"A1": "Key", "C1": "Story Points", "A2": "ACME-2",
                                                                       "C2": 8, "C3": "=SUM(C2:C2)"}}]}


class FormulaTest(unittest.TestCase):
    def ev(self, f, cells=None):
        tab = {"cells": dict(cells or {}, Z99=f)}
        return S.evaluate(tab)["Z99"]

    def test_arithmetic_and_functions(self):
        self.assertEqual(self.ev("=1+2*3"), 7)
        self.assertEqual(self.ev("=(1+2)*3"), 9)
        self.assertEqual(self.ev("=+A1+1", {"A1": 7}), 8)
        self.assertEqual(self.ev("=SUM(A1:C1)", {"A1": 1, "B1": "H", "C1": 0.5}), 1.5)
        self.assertEqual(self.ev("=COUNTIF(A1:C1,1)", {"A1": 1, "B1": 1, "C1": 0}), 2)
        self.assertEqual(self.ev('=IF(A1="unassigned",0,5)', {"A1": "Unassigned"}), 0)
        self.assertEqual(self.ev("=A1/0", {"A1": 1}), "#DIV/0!")
        self.assertEqual(self.ev("=A1+1", {"A1": "text"}), "#VALUE!")

    def test_shared_formula_moves_relative_references_only(self):
        self.assertEqual(S.shift_formula('IF(C5="x",0,(COUNTIF(I5:AC5,1)*$B$1)*G5)', 0, 3),
                         'IF(C8="x",0,(COUNTIF(I8:AC8,1)*$B$1)*G8)')
        self.assertEqual(S.shift_formula("+I1+1", 1, 0), "+J1+1")


class SheetTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sheet = capacity()

    def test_numbered_names_stay_apart(self):
        self.assertNotEqual(S.norm("Resource 10"), S.norm("Resource 28"))
        self.assertEqual(S.norm("Doe, Ann"), S.norm("doe ann"))

    def test_people_hours_and_totals(self):
        ppl = S.people(self.sheet)
        self.assertEqual([p["name"] for p in ppl], ["Ann Example", "Ben Example"])
        self.assertEqual(ppl[0]["hours"], 30)  # 5 weekdays x 6h
        self.assertEqual(ppl[1]["allocation"], 50)
        self.assertEqual(S.totals(self.sheet), {"hours": 45, "points": 5.625, "points_with_ai": 7.3125})

    def test_half_day_off_day_and_holiday(self):
        S.set_days(self.sheet, "Ann Example", {"2026-10-08"}, "0.5")
        S.set_days(self.sheet, "Ann Example", {"2026-10-09"}, 0)
        S.set_days(self.sheet, "Ben Example", {"2026-10-12"}, "H")
        ppl = S.people(self.sheet)
        self.assertEqual((ppl[0]["half"], ppl[0]["off"]), (["2026-10-08"], ["2026-10-09"]))
        self.assertEqual(ppl[0]["hours"], 21)
        self.assertEqual(ppl[1]["holiday"], ["2026-10-12"])
        self.assertEqual(ppl[1]["hours"], 12)
        with self.assertRaises(S.SheetError):
            S.set_days(self.sheet, "Ann Example", {"2026-10-08"}, "2")

    def test_weekends_are_never_changed(self):
        self.assertEqual(S.set_days(self.sheet, "Ann Example", {"2026-10-10", "2026-10-11"}, 0), [])

    def test_edits_and_who_may_make_them(self):
        changes = S.edit(self.sheet, {"Capacity": {"B1": "7"}, "Carry forward": {"D2": "8"}})
        self.assertEqual(len(changes), 2)
        self.assertEqual(S.totals(self.sheet)["hours"], 52.5)
        self.assertEqual(S.evaluate(S.tab_of(self.sheet, "Carry forward"))["D3"], 21)
        self.assertTrue(S.only_own_days(self.sheet, {"Capacity": {"I3": "0"}}, "Ann Example"))
        self.assertFalse(S.only_own_days(self.sheet, {"Capacity": {"I4": "0"}}, "Ann Example"))
        self.assertFalse(S.only_own_days(self.sheet, {"Capacity": {"B1": "7"}}, "Ann Example"))

    def test_planner_change_reaches_every_sheet_it_covers(self):
        S.set_days(self.sheet, "Ann Example", {"2026-10-08", "2026-10-09"}, 0)
        S.save(self.sheet, self.dir)
        before = [{"name": "Ann Example", "from": "2026-10-08", "to": "2026-10-09"}]
        after = [{"name": "Ann Example", "from": "2026-10-09", "to": "2026-10-12"}]
        touched = S.apply_time_off(before, after, self.dir)
        sheet, changes = touched["26.4.2"]
        self.assertEqual(sorted((c[1], c[3]) for c in changes), [("2026-10-08", 1), ("2026-10-12", 0)])
        self.assertEqual(S.people(sheet)[0]["off"], ["2026-10-09", "2026-10-12"])

    def test_leave_section_for_the_sprint_leave_page(self):
        S.set_days(self.sheet, "Ann Example", {"2026-10-09"}, 0)
        S.set_days(self.sheet, "Ann Example", {"2026-10-08"}, "0.5")
        sec = S.leave_section(self.sheet, {"people": [{"name": "Ben Example", "jira_user": "BB2", "no_leave": True,
                                                       "note": "back-up for Ann"}]})
        ann, ben = sec["people"]
        self.assertEqual((ann["off"], ann["note"]), (["2026-10-09"], "half day 2026-10-08"))
        self.assertEqual((ben["jira_user"], ben["no_leave"], ben["note"], ben["allocation"]), ("BB2", True, "back-up for Ann", 50))
        self.assertEqual(sec["productive_hours"], 6)

    def test_new_sprint_copies_people_and_clears_last_sprints_values(self):
        S.set_days(self.sheet, "Ann Example", {"2026-10-09"}, 0)
        new = S.new_sheet("26.4.3", "2026-10-28", self.sheet)
        self.assertEqual((new["start"], new["end"]), ("2026-10-28", "2026-11-03"))
        self.assertEqual(S.people(new)[0]["off"], [])
        self.assertEqual(S.tab_of(new, "Capacity")["cells"]["H1"], 28)
        self.assertEqual(S.tab_of(new, "Capacity")["cells"]["C1"], "Sprint Days = 5")
        self.assertEqual(S.tab_of(new, "Carry forward")["cells"], {"D3": "=SUM(D1:D2)"})
        self.assertEqual(S.tab_of(new, "Previous sprint AI savings")["cells"],
                         {"A1": "Key", "C1": "Story Points", "C3": "=SUM(C2:C2)"})

    def test_edits_block_and_pages(self):
        block = S.parse_block('%s\nsprint: 26.4.2\nby: Ann Example\nedits: {"Capacity": {"I3": "0"}}' % S.EDITS_MARK)
        self.assertEqual(block["edits"], {"Capacity": {"I3": "0"}})
        with self.assertRaises(S.SheetError):
            S.parse_block("nothing here")
        jp, hp = S.save(self.sheet, self.dir)
        page = open(hp, encoding="utf-8").read()
        self.assertIn('data-ref="B1"', page)
        self.assertIn("SDLC-SPRINT-SHEET-EDITS", page)
        frag = S.render_fragment(self.sheet)
        self.assertNotIn("<input", frag)
        self.assertIn('data-total="O5">45<', frag)
        self.assertEqual(S.load("26.4.2", self.dir)["sprint"], "26.4.2")
        self.assertEqual(S.current(None, self.dir), "26.4.2")


class ImportTest(unittest.TestCase):
    def test_workbook_with_shared_formulas_and_half_day_hours(self):
        sheet_xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                     '<row r="1"><c r="B1"><v>6</v></c><c r="I1"><v>7</v></c><c r="J1"><f>+I1+1</f><v>8</v></c></row>'
                     '<row r="2"><c r="C2" t="s"><v>0</v></c><c r="G2" t="s"><v>1</v></c><c r="I2" t="s"><v>2</v></c>'
                     '<c r="J2" t="s"><v>3</v></c><c r="K2" t="s"><v>4</v></c></row>'
                     '<row r="3"><c r="C3" t="s"><v>5</v></c><c r="G3"><v>1</v></c><c r="I3"><v>1</v></c><c r="J3"><v>0</v></c>'
                     '<c r="K3"><f t="shared" ref="K3:K4" si="0">IF(C3="unassigned",0,(COUNTIF(I3:J3,1)*$B$1)*G3)</f><v>6</v></c></row>'
                     '<row r="4"><c r="C4" t="s"><v>6</v></c><c r="G4"><v>0.5</v></c><c r="I4"><v>1</v></c><c r="J4"><v>1</v></c>'
                     '<c r="K4"><f t="shared" si="0"/><v>6</v></c></row></sheetData></worksheet>')
        strings = ["Team  Member", "%age of time on Project", "W", "T", "Available hours", "Ann Example", "Ben Example"]
        sst = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">%s</sst>' % "".join(
            "<si><t>%s</t></si>" % s for s in strings)
        wb = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
              '<sheet name="Capacity " sheetId="1" r:id="rId1"/><sheet name="Sheet1" sheetId="2" r:id="rId2"/></sheets></workbook>')
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Target="worksheets/sheet1.xml"/>'
                '</Relationships>')
        path = os.path.join(tempfile.mkdtemp(), "plan.xlsx")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/_rels/workbook.xml.rels", rels)
            z.writestr("xl/sharedStrings.xml", sst)
            z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        sheet = S.import_xlsx(path, "26.4.2", "2026-10-07", drop={"Sheet1"})
        self.assertEqual([t["name"] for t in sheet["tabs"]], ["Capacity"])
        cells = sheet["tabs"][0]["cells"]
        self.assertEqual(cells["K4"], '=IF(C4="unassigned",0,(SUM(I4:J4)*$B$1)*G4)')
        self.assertEqual(sheet["end"], "2026-10-08")
        self.assertEqual([p["hours"] for p in S.people(sheet)], [6, 6])
        json.dumps(sheet)


if __name__ == "__main__":
    unittest.main()
