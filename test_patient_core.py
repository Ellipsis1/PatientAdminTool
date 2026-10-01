"""Unit tests for patient_core. Run with:  python -m unittest -v"""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import patient_core as core


def case(**overrides):
    d = dict(name_id="R. Yel B658-CGAF", center="Chicago", arch_type="LAO4",
             split_file="No", cutback="No", stl_only="No", tooth_shade="A2",
             due_date="6/11/2026", surgery_date="", rx_date="6/3/2026",
             scan_date="6/2/2026", ios_box="IOS", designer="Josh")
    d.update(overrides)
    return d


class DateTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(core.fmt_date("06/03/2026"), "6/03/2026")
        self.assertEqual(core.fmt_date("6/3/26", "."), "6.3.2026")
        self.assertEqual(core.fmt_date(""), "")

    def test_invalid(self):
        self.assertIsNone(core.parse_date("13/45/2026"))
        self.assertIsNone(core.parse_date("next tuesday"))

    def test_month_grid_for_date_picker(self):
        weeks = core.month_weeks(2026, 10)                # Oct 1, 2026 is a Thursday
        self.assertEqual(weeks[0], [0, 0, 0, 0, 1, 2, 3])  # Sunday first
        self.assertEqual(weeks[-1], [25, 26, 27, 28, 29, 30, 31])
        self.assertEqual(core.shift_month(2026, 12, 1), (2027, 1))
        self.assertEqual(core.shift_month(2026, 1, -1), (2025, 12))


class NamingTests(unittest.TestCase):
    def test_patient_split(self):
        p = core.patient_from("T. Hug (K445-P3AC)", "Milwaukee")
        self.assertEqual((p.init2, p.name3, p.uid, p.first1), ("T.", "HUG", "K445-P3AC", "T"))

    def test_folder_name(self):
        self.assertEqual(core.folder_name(case()), "6.3.2026 R. YEL B658-CGAF Chicago")
        self.assertTrue(core.folder_name(case(arch_type="MODEL ONLY")).endswith(" MODEL ONLY"))

    def test_casenotes_uses_given_today(self):
        notes = core.build_casenotes(case(), today=date(2026, 9, 29))
        self.assertIn("Awaiting Approval Date: 9/29/2026", notes)
        self.assertIn("MAND STL NAME\nB658-CGAF_MD_R_YEL_Chicago", notes)
        self.assertNotIn("MAX STL NAME", notes)


class ArchFromTreatmentTests(unittest.TestCase):
    def test_sides(self):
        self.assertEqual(core.arch_from_treatment("Lower Zirconia Arch Replacement"), "LAO4")
        self.assertEqual(core.arch_from_treatment("Upper Zirconia Arch Replacement"), "UAO4")
        self.assertEqual(core.arch_from_treatment("Upper and Lower Zirconia"), "DAO4")
        self.assertIsNone(core.arch_from_treatment(""))


class GuessRoleTests(unittest.TestCase):
    def test_by_extension(self):
        self.assertEqual(core.guess_role("shot 1.PNG"), "SCREENSHOT")

    def test_by_name(self):
        self.assertEqual(core.guess_role("upper_jaw.stl"), "MX")
        self.assertEqual(core.guess_role("Mandibular.stl"), "MD")
        self.assertEqual(core.guess_role("bite scan.stl"), "BITE")
        self.assertEqual(core.guess_role("lower cutback.stl"), "MD_CUTBACK")
        self.assertEqual(core.guess_role("upper base.stl"), "MX_BASE")
        self.assertEqual(core.guess_role("lower teeth.stl"), "MD_TEETH")
        self.assertEqual(core.guess_role("upper model.stl"), "MDL_MX")
        self.assertEqual(core.guess_role("lower working.stl"), "WRK_MD")
        self.assertEqual(core.guess_role("upper.dcm"), "MX_DCM")

    def test_falls_back_on_arch(self):
        self.assertEqual(core.guess_role("scan.stl", "LAO4"), "MD")
        self.assertEqual(core.guess_role("scan.stl", "UAO4"), "MX")
        self.assertIsNone(core.guess_role("scan.stl", "DAO4"))   # both arches: ask
        self.assertIsNone(core.guess_role("scan.stl"))

    def test_md_inside_word_is_not_lower(self):
        # "cmd" contains "md" but is not a lower-arch token
        self.assertIsNone(core.guess_role("cmd_export.stl"))


class PlanAndCopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        self.src.mkdir()
        self.main = self.root / "Desktop" / core.folder_name(case())

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, text="x"):
        p = self.src / name
        p.write_text(text)
        return p

    def test_names_and_routing(self):
        items = [(self.make("a.stl"), "MD"), (self.make("b.png"), "SCREENSHOT"),
                 (self.make("m.stl"), "MDL_MX"), (self.make("notes.pdf"), "KEEP"),
                 (self.make("d.stl"), None)]
        plan = core.plan_file_copies(items, case(), self.main)
        rel = [[p.relative_to(self.main).as_posix() for p in dests] if dests else None
               for dests in plan]
        self.assertEqual(rel, [
            ["B658-CGAF STL/B658-CGAF_MD_R_YEL_Chicago.stl"],
            ["Design Screenshots/B658-CGAF_R_YEL_Screenshot_01.png"],
            ["B658-CGAF STL/B658-CGAF_MDL_MX_R_YEL_Chicago.stl",       # models go to both
             "3D Viewer/B658-CGAF_MDL_MX_R_YEL_Chicago.stl"],
            ["notes.pdf"],
            None,
        ])

    def test_collisions_in_batch_and_on_disk(self):
        existing = self.main / "B658-CGAF STL" / "B658-CGAF_MD_R_YEL_Chicago.stl"
        existing.parent.mkdir(parents=True)
        existing.write_text("old")
        shots = self.main / "Design Screenshots"
        shots.mkdir()
        (shots / "B658-CGAF_R_YEL_Screenshot_01.png").write_text("old")

        items = [(self.make("a.stl"), "MD"), (self.make("b.stl"), "MD"),
                 (self.make("s1.png"), "SCREENSHOT"), (self.make("s2.png"), "SCREENSHOT")]
        names = [dests[0].name for dests in core.plan_file_copies(items, case(), self.main)]
        self.assertEqual(names, [
            "B658-CGAF_MD_R_YEL_Chicago_02.stl",
            "B658-CGAF_MD_R_YEL_Chicago_03.stl",
            "B658-CGAF_R_YEL_Screenshot_02.png",
            "B658-CGAF_R_YEL_Screenshot_03.png",
        ])

    def test_copy_keeps_originals(self):
        src = self.make("upper.stl", "mesh")
        core.create_folder_structure(self.main, "B658-CGAF", notes="hello")
        plan = core.plan_file_copies([(src, "MX")], case(), self.main)
        core.copy_files(zip([src], plan))
        self.assertTrue(src.exists())
        self.assertEqual(plan[0][0].read_text(), "mesh")
        self.assertEqual((self.main / "CaseNotes.txt").read_text(), "hello")
        for sub in ("3D Viewer", "Design Screenshots", "B658-CGAF STL"):
            self.assertTrue((self.main / sub).is_dir())

    def test_rx_pdf_goes_beside_casenotes(self):
        rx = self.make("Lab Rx.pdf", "rx")
        core.create_folder_structure(self.main, "B658-CGAF", notes="hello")
        plan = core.plan_rx_copy(rx, self.main)
        self.assertEqual(plan, [self.main / "Lab Rx.pdf"])
        core.copy_files([(rx, plan)])
        self.assertTrue(rx.exists())                              # copied, not moved
        self.assertEqual(core.plan_rx_copy(rx, self.main), [])    # same file again: nothing to do
        rx.write_text("revised rx")
        self.assertEqual(core.plan_rx_copy(rx, self.main), [self.main / "Lab Rx_02.pdf"])

    def test_safe_name_strips_windows_chars(self):
        self.assertEqual(core.safe_name('a<b>:c"d?e*'), "abcde")


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "settings.json"
            self.assertEqual(core.load_settings(path), {})          # missing file
            core.save_settings({"designer": "Josh"}, path)
            self.assertEqual(core.load_settings(path), {"designer": "Josh"})
            path.write_text("{not json")
            self.assertEqual(core.load_settings(path), {})          # corrupt file


class ListsTests(unittest.TestCase):
    """apply_lists mutates module lists, so snapshot and restore them around each test."""

    def setUp(self):
        self.saved = {k: list(v) for k, v in core._EDITABLE.items()}
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / core.LISTS_FILE

    def tearDown(self):
        for k, v in self.saved.items():
            core._EDITABLE[k][:] = v
        self.tmp.cleanup()

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return self.path

    def test_apply_updates_in_place_and_ignores_bad_keys(self):
        ref = core.DESIGNERS
        p = self.write(json.dumps({"version": "v2", "designers": ["Zed"], "centers": "nope"}))
        self.assertEqual(core.apply_lists([p]), (p, "v2"))
        self.assertIs(core.DESIGNERS, ref)              # same object, new contents
        self.assertEqual(core.DESIGNERS, ["Zed"])
        self.assertEqual(core.CENTERS, self.saved["centers"])  # invalid value ignored

    def test_load_uses_file_beside_app(self):
        p = self.write(json.dumps({"version": "b1", "designers": ["Bo"]}))
        with mock.patch.object(core, "default_lists_path", return_value=p):
            self.assertEqual(core.load_lists(), (p, "b1"))
        self.assertEqual(core.DESIGNERS, ["Bo"])

    def test_missing_or_broken_file_uses_built_in(self):
        with mock.patch.object(core, "default_lists_path", return_value=self.path):
            self.assertEqual(core.load_lists(), (None, None))    # no file
            self.write("{broken json")
            self.assertEqual(core.load_lists(), (None, None))
        self.assertEqual(core.DESIGNERS, self.saved["designers"])


if __name__ == "__main__":
    unittest.main()
