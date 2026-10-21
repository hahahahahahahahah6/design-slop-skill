#!/usr/bin/env python3
"""Tests for design-slop-skill: each slop fixture must trigger its rule,
clean.html must stay silent, and fix.py must lower the slop score."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(ROOT.parent / "scripts"))

import detect  # noqa: E402
import fix  # noqa: E402


def rules_for(name):
    findings, _score, seen = detect.detect_paths([FIXTURES / name])
    return findings, seen


class TestDetect(unittest.TestCase):
    def test_001_giant_radius(self):
        findings, seen = rules_for("slop-001.html")
        self.assertIn("SLOP-001", seen)
        self.assertTrue(any("32px" in f.snippet for f in findings if f.rule_id == "SLOP-001"))

    def test_002_glassmorphism(self):
        _f, seen = rules_for("slop-002.html")
        self.assertIn("SLOP-002", seen)

    def test_003_glow(self):
        _f, seen = rules_for("slop-003.html")
        self.assertIn("SLOP-003", seen)

    def test_004_redpurple_gradient(self):
        _f, seen = rules_for("slop-004.html")
        self.assertIn("SLOP-004", seen)

    def test_005_dark_only(self):
        findings, seen = rules_for("slop-005.html")
        self.assertIn("SLOP-005", seen)
        self.assertTrue(any(f.line == 4 for f in findings if f.rule_id == "SLOP-005"))

    def test_006_hero(self):
        _f, seen = rules_for("slop-006.html")
        self.assertIn("SLOP-006", seen)

    def test_007_single_column(self):
        _f, seen = rules_for("slop-007.html")
        self.assertIn("SLOP-007", seen)

    def test_clean_is_silent(self):
        findings, seen = rules_for("clean.html")
        self.assertEqual(findings, [], f"false positives: {[f.rule_id for f in findings]}")
        self.assertEqual(seen, [])

    def test_mixed_triggers_many(self):
        _f, seen = rules_for("mixed.html")
        self.assertGreaterEqual(len(seen), 5)
        for rid in ("SLOP-001", "SLOP-002", "SLOP-003", "SLOP-004", "SLOP-005", "SLOP-006", "SLOP-007"):
            self.assertIn(rid, seen)

    def test_score_range_and_weighting(self):
        _f, score, _s = detect.detect_paths([FIXTURES / "mixed.html"])
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)
        _f2, score2, _s2 = detect.detect_paths([FIXTURES / "slop-004.html"])  # high-weight rule only
        _f3, score3, _s3 = detect.detect_paths([FIXTURES / "slop-001.html"])  # medium-weight only
        self.assertGreater(score2, score3)

    def test_findings_have_file_and_line(self):
        findings, _seen = rules_for("slop-001.html")
        self.assertTrue(findings)
        for f in findings:
            self.assertTrue(f.filename.endswith("slop-001.html"))
            self.assertGreaterEqual(f.line, 1)
            d = f.to_dict()
            self.assertIn("suggestion_en", d)
            self.assertIn("suggestion_zh", d)

    def test_json_output_parseable(self):
        import io
        import json
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = detect.main([str(FIXTURES / "slop-004.html"), "--json"])
        self.assertEqual(rc, 1)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["score"], 20)
        self.assertIn("SLOP-004", data["rules"])

    def test_dark_with_light_path_is_not_slop(self):
        # prefers-color-scheme present -> SLOP-005 must not fire
        findings, seen = rules_for("clean.html")
        self.assertNotIn("SLOP-005", seen)


class TestFix(unittest.TestCase):
    def _fixed(self, name):
        src = (FIXTURES / name).read_text()
        return fix.fix_text(src)

    def test_radius_clamped(self):
        out = self._fixed("slop-001.html")
        self.assertNotIn("32px", out)
        self.assertIn("10px", out)

    def test_glass_removed(self):
        out = self._fixed("slop-002.html")
        self.assertNotIn("backdrop-filter", out)
        self.assertNotIn("rgba(255, 255, 255, 0.12)", out)

    def test_glow_neutralized(self):
        out = self._fixed("slop-003.html")
        self.assertNotIn("168, 85, 247", out)
        self.assertIn(fix.NEUTRAL_SHADOW, out)

    def test_gradient_solidified(self):
        out = self._fixed("slop-004.html")
        self.assertNotIn("linear-gradient", out)

    def test_dark_gets_light_block(self):
        out = self._fixed("slop-005.html")
        self.assertIn("prefers-color-scheme: light", out)

    def test_hero_tamed(self):
        out = self._fixed("slop-006.html")
        self.assertNotIn("4rem", out)
        self.assertIn("2.25rem", out)
        self.assertIn("text-align: left", out)

    def test_container_widened(self):
        out = self._fixed("slop-007.html")
        self.assertNotIn("640px", out)
        self.assertIn("72rem", out)

    def test_fix_lowers_score(self):
        for name in ("slop-001.html", "slop-003.html", "slop-004.html",
                     "slop-005.html", "slop-006.html"):
            _f, before, _s = detect.detect_paths([FIXTURES / name])
            out = self._fixed(name)
            tmp = FIXTURES / f"_tmp_{name}"
            try:
                tmp.write_text(out)
                _f2, after, _s2 = detect.detect_paths([tmp])
            finally:
                tmp.unlink(missing_ok=True)
            self.assertLess(after, before, f"score did not drop for {name}: {before} -> {after}")

    def test_fix_widens_container_but_keeps_grid_todo(self):
        # fix.py widens the narrow container; adding a grid layout is a human
        # design decision, so SLOP-007 (no-grid) may legitimately remain.
        name = "slop-007.html"
        _f, before, _s = detect.detect_paths([FIXTURES / name])
        out = self._fixed(name)
        tmp = FIXTURES / f"_tmp_{name}"
        try:
            tmp.write_text(out)
            findings2, after, _s2 = detect.detect_paths([tmp])
        finally:
            tmp.unlink(missing_ok=True)
        self.assertLessEqual(after, before)
        self.assertFalse(any("single narrow column" in f.snippet for f in findings2))

    def test_clean_untouched(self):
        src = (FIXTURES / "clean.html").read_text()
        out = fix.fix_text(src)
        self.assertEqual(out, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
