"""CP5 smoke tests — phrase normalize, lock, HT report on fixture log."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from file_lock import file_lock  # noqa: E402
from tag_normalize import normalize_play_call  # noqa: E402
from team_config import load_team_config, phrase_token_aliases  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_axel_variants(self):
        for raw in ("AXEL", "Axel", "axel", "AXLE", "Axle", "axle"):
            self.assertEqual(normalize_play_call(raw), "Axle")

    def test_compound(self):
        self.assertEqual(normalize_play_call("AXLE BRONCO"), "Axle BRONCO")
        self.assertEqual(normalize_play_call("BUMP AXEL"), "BUMP Axle")

    def test_config_loaded(self):
        cfg = load_team_config()
        self.assertIn("play_word_aliases", cfg)
        self.assertIn("axel", phrase_token_aliases())


class TestFileLock(unittest.TestCase):
    def test_lock_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "live_log.csv"
            target.write_text("a\n", encoding="utf-8")
            with file_lock(target, timeout=2):
                target.write_text("a\nb\n", encoding="utf-8")
            self.assertEqual(target.read_text(encoding="utf-8"), "a\nb\n")
            self.assertFalse(target.with_suffix(".csv.lock").exists())


class TestHalftimeFixture(unittest.TestCase):
    def test_build_halftime_on_fixture(self):
        import pandas as pd
        from mesh_engine import build_halftime_report, format_halftime_report_markdown

        fixture = ROOT / "tests" / "fixtures" / "live_log_half.csv"
        self.assertTrue(fixture.exists(), "missing fixture live_log_half.csv")
        log = pd.read_csv(fixture)
        plan = {"opponent": "Farmersville", "offense_pins": [], "defense_pins": []}
        report = build_halftime_report("Farmersville", log, plan)
        self.assertIsInstance(report, dict)
        self.assertIn("version", report)
        md = format_halftime_report_markdown(report)
        self.assertTrue(len(md) > 50)


if __name__ == "__main__":
    unittest.main()
