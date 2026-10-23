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

    def test_bare_is_bear(self):
        self.assertEqual(normalize_play_call("bare"), "Bear")
        self.assertEqual(normalize_play_call("Army bare"), "Army Bear")
        self.assertEqual(phrase_token_aliases().get("bare"), "bear")

    def test_compound(self):
        self.assertEqual(normalize_play_call("AXLE BRONCO"), "Axle BRONCO")
        self.assertEqual(normalize_play_call("BUMP AXEL"), "BUMP Axle")

    def test_config_loaded(self):
        cfg = load_team_config()
        self.assertIn("play_word_aliases", cfg)
        self.assertIn("axel", phrase_token_aliases())


class TestTurnoverScoring(unittest.TestCase):
    def test_pick_six_is_their_score(self):
        import pandas as pd

        from step2_clean import result_flags
        from step3_epa import TD_POINTS, after_play_state

        flags = result_flags("Interception, Def TD")
        self.assertFalse(flags["is_touchdown"])
        self.assertTrue(flags["is_turnover"])
        self.assertTrue(flags["is_def_td"])
        self.assertEqual(flags["points_scored"], 0)
        row = pd.Series({
            "field_position": 40, "down": 1, "distance": 10, "yards_gained": 52,
            "result": "Interception, Def TD", "distance_bucket": "long", **flags,
        })
        after, points, turnover = after_play_state(row)
        self.assertIsNone(after)
        self.assertEqual(points, -TD_POINTS)
        self.assertTrue(turnover)
        self.assertTrue(result_flags("Complete, TD")["is_touchdown"])


class TestBlitzLanes(unittest.TestCase):
    def test_normalize_and_lanes(self):
        from tag_normalize import blitz_is_pressure, blitz_lane, blitz_tagged, normalize_blitz

        self.assertEqual(normalize_blitz("outside"), "Outside")
        self.assertEqual(normalize_blitz(" no "), "No")
        self.assertEqual(normalize_blitz("nan"), "")
        self.assertTrue(blitz_tagged("No"))
        self.assertFalse(blitz_tagged(""))
        self.assertFalse(blitz_is_pressure("No"))
        self.assertTrue(blitz_is_pressure("Cross"))
        self.assertEqual(blitz_lane("Inside"), "inside")
        self.assertEqual(blitz_lane("BANDIT STAB"), "outside")
        self.assertEqual(blitz_lane("WILL BLAST"), "inside")
        self.assertEqual(blitz_lane("MIKE CROSS"), "cross")
        self.assertEqual(blitz_lane("Yes"), "")

    def test_phrase_and_film_checks_accept_lanes(self):
        import step4_dashboard as d

        p = d.parse_film_phrase("odd front inside blitz cover 4")
        self.assertEqual(p["def_front"], "Odd")
        self.assertEqual(p["blitz"], "Inside")
        self.assertEqual(p["coverage"], "Cover 4")
        self.assertEqual(d.parse_film_phrase("cross blitz")["blitz"], "Cross")
        self.assertEqual(d.parse_film_phrase("no blitz")["blitz"], "No")
        row = {"def_front": "Odd", "coverage": "Cover 4", "blitz": "Outside"}
        self.assertEqual(d.play_missing_film_fields(row), set())
        self.assertTrue(d._tagger_pack_complete(
            {"drive_id": 1, "play_n": 1, "def_front": "Odd", "blitz": "Cross"}, ["front", "blitz"]
        ))
        self.assertFalse(d._tagger_pack_complete(
            {"drive_id": 1, "play_n": 1, "def_front": "Odd"}, ["front", "blitz"]
        ))

    def test_live_blitz_lane_split(self):
        import pandas as pd

        from mesh_engine import analyze_live_blitz

        logs = pd.DataFrame({
            "unit": ["Offense"] * 5,
            "blitz": ["No", "Inside", "Outside", "Outside", ""],
            "result": ["Gain"] * 5,
            "yards_gained": [3, 1, 0, 6, 2],
        })
        out = analyze_live_blitz(logs, "Offense")
        self.assertEqual(out["plays"], 4)  # blank is untagged
        self.assertEqual(out["blitz_plays"], 3)
        self.assertEqual(out["lanes"]["outside"]["plays"], 2)
        self.assertAlmostEqual(out["lanes"]["inside"]["pct"], 33.3)


class TestBoothInvites(unittest.TestCase):
    URL = "http://192.168.1.20:8501/?station=tag&focus=front,blitz"

    def test_local_qr_png_needs_no_packages(self):
        import struct

        from qr_local import encode, qr_png

        qr = encode(self.URL)
        self.assertEqual(qr.size, qr.version * 4 + 17)
        # Three finder patterns: dark 7x7 ring corners
        for x, y in ((0, 0), (qr.size - 7, 0), (0, qr.size - 7)):
            self.assertTrue(qr.modules[y][x] and qr.modules[y + 6][x + 6])
            self.assertFalse(qr.modules[y + 1][x + 1])
        png = qr_png(self.URL, scale=4, border=4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = struct.unpack(">II", png[16:24])
        self.assertEqual(w, (qr.size + 8) * 4)
        self.assertEqual(w, h)

    def test_inline_svg_qr_matches_matrix(self):
        import re

        from qr_local import encode, qr_svg

        qr = encode(self.URL)
        svg = qr_svg(self.URL, size_px=220, border=4)
        self.assertTrue(svg.startswith("<svg") and f'viewBox="0 0 {qr.size + 8} {qr.size + 8}"' in svg)
        dark = sum(int(w) for w in re.findall(r"h(\d+)v1", svg))
        self.assertEqual(dark, sum(sum(1 for v in row if v) for row in qr.modules))

    def test_local_qr_matches_reference_library(self):
        try:
            import qrcode
            from qrcode.util import MODE_8BIT_BYTE, QRData
        except Exception:
            self.skipTest("qrcode not installed")
        from qr_local import encode

        for mask in range(8):
            mine = encode(self.URL, ecl="M", mask=mask)
            ref = qrcode.QRCode(
                version=mine.version,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                border=0,
                mask_pattern=mask,
            )
            ref.add_data(QRData(self.URL.encode(), mode=MODE_8BIT_BYTE))
            ref.make(fit=False)
            self.assertEqual([list(map(bool, r)) for r in ref.modules], mine.modules)

    def test_invite_address_detection(self):
        import step4_dashboard as d

        class _Ctx:
            def __init__(self, url, headers):
                self.url = url
                self.headers = headers

        class _St:
            def __init__(self, url=None, headers=None):
                self.context = _Ctx(url, headers or {})

            @staticmethod
            def get_option(_name):
                return 8501

        real_st, real_ip, real_hosted = d.st, d._lan_ip, d._is_hosted_runtime
        try:
            d._lan_ip = lambda: "192.168.1.5"
            d._is_hosted_runtime = lambda: False
            d.st = _St(url="https://livetrack.streamlit.app/")
            self.assertEqual(d._detected_booth_base_url()[0], "https://livetrack.streamlit.app")
            d.st = _St(url="http://localhost:8501/")
            self.assertEqual(d._detected_booth_base_url(), ("http://192.168.1.5:8501", "laptop Wi-Fi"))
            # Hosted behind a proxy that only shows localhost → never a container LAN IP
            d._is_hosted_runtime = lambda: True
            d.st = _St(url=None, headers={"Host": "localhost:8501"})
            self.assertEqual(d._detected_booth_base_url(), ("", ""))
            d.st = _St(url=None, headers={"Host": "localhost:8501",
                                          "X-Forwarded-Host": "booth.onrender.com"})
            self.assertEqual(d._detected_booth_base_url()[0], "https://booth.onrender.com")
        finally:
            d.st, d._lan_ip, d._is_hosted_runtime = real_st, real_ip, real_hosted

    def test_two_tagger_packs(self):
        from booth_stations import (
            TAGGER_PACKS,
            default_focuses_for_station,
            normalize_focuses,
            tagger_invite_url,
        )

        self.assertEqual([list(p["focuses"]) for p in TAGGER_PACKS],
                         [["front", "blitz"], ["coverage", "ball"]])
        # No focus in the link → tagger picks a job on the phone
        self.assertEqual(default_focuses_for_station("tag"), [])
        self.assertEqual(normalize_focuses("coverage_ball"), ["coverage", "ball"])
        self.assertTrue(
            tagger_invite_url("192.168.1.20:8501", ["front", "blitz"]).endswith(
                "/?station=tag&focus=front,blitz"
            )
        )

    def test_parallel_taggers_keep_both_tags(self):
        from booth_snaps import upsert_live_snap

        rows = [{"opponent": "Leonard", "half": 1, "drive_id": 3, "play_n": 2,
                 "unit": "Offense", "def_front": "", "coverage": "", "blitz": ""}]

        def load():
            import pandas as pd

            return pd.DataFrame(rows)

        stale = load()  # both taggers read before either saves

        def update_at(i, patch):
            rows[i].update(patch)
            return True

        upsert_live_snap(drive_id=3, play_n=2, updates={"def_front": "Odd", "blitz": "Yes"},
                         opponent="Leonard", append_fn=rows.append, update_at_fn=update_at,
                         load_fn=lambda: stale)
        upsert_live_snap(drive_id=3, play_n=2, updates={"coverage": "4"},
                         opponent="Leonard", append_fn=rows.append, update_at_fn=update_at,
                         load_fn=lambda: stale)
        self.assertEqual(rows[0]["def_front"], "Odd")
        self.assertEqual(rows[0]["blitz"], "Yes")
        self.assertEqual(rows[0]["coverage"], "4")


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
        first = ((report.get("scenarios") or {}).get("by_down") or {}).get("1") or {}
        self.assertIn("overall", first)
        self.assertIn("by_distance", first)
        self.assertIn("Overall", md)


class TestRpoSplit(unittest.TestCase):
    def test_army_bear_splits(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        s = d._split_play_tags("Army Bear", "pass", favs)
        self.assertEqual(s["run_tag"], "Army")
        self.assertEqual(s["pass_tag"], "Bear")
        self.assertEqual(s["play_type"], "rpo")

    def test_pass_only_and_run_only(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        self.assertEqual(d._split_play_tags("Bear", "pass", favs)["pass_tag"], "Bear")
        self.assertEqual(d._split_play_tags("Army", "run", favs)["run_tag"], "Army")
        self.assertFalse(d._split_play_tags("Army", "run", favs)["pass_tag"])

    def test_compose_two_tokens(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        c = d._compose_play_parts([("Army", "run"), ("Bear", "pass")], favs)
        self.assertEqual(c["run_tag"], "Army")
        self.assertEqual(c["pass_tag"], "Bear")
        self.assertEqual(c["play_type"], "rpo")


class TestPhrasePlayTags(unittest.TestCase):
    def test_pass_only_does_not_keep_sticky_run(self):
        import step4_dashboard as d

        run, pas = d._ql_phrase_play_tags(
            {"run_tag": "", "pass_tag": "Spot", "play_call": "Spot"},
            sticky_run="Mary",
            sticky_pass="Wave",
        )
        self.assertEqual(run, "")
        self.assertEqual(pas, "Spot")

    def test_run_only_does_not_keep_sticky_pass(self):
        import step4_dashboard as d

        run, pas = d._ql_phrase_play_tags(
            {"run_tag": "Mary", "pass_tag": "", "play_call": "Mary"},
            sticky_run="Illinois",
            sticky_pass="Spot",
        )
        self.assertEqual(run, "Mary")
        self.assertEqual(pas, "")

    def test_unnamed_gain_keeps_sticky(self):
        import step4_dashboard as d

        run, pas = d._ql_phrase_play_tags(
            {"run_tag": "", "pass_tag": "", "play_call": "", "outcome_lane": ""},
            sticky_run="Mary",
            sticky_pass="",
        )
        self.assertEqual(run, "Mary")
        self.assertEqual(pas, "")

    def test_unnamed_pass_outcome_drops_sticky_run(self):
        import step4_dashboard as d

        run, pas = d._ql_phrase_play_tags(
            {
                "run_tag": "",
                "pass_tag": "",
                "play_call": "",
                "outcome_lane": "pass",
            },
            sticky_run="Mary",
            sticky_pass="",
        )
        self.assertEqual(run, "")
        self.assertEqual(pas, "")

    def test_pass_phrase_parse_has_no_run_tag(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Spot incomplete", favs)
        self.assertEqual(p.get("pass_tag"), "Spot")
        self.assertFalse(p.get("run_tag"))
        self.assertEqual(p.get("play_type"), "pass")

    def test_current_season_tags_enter_phrase_map(self):
        import pandas as pd

        import step4_dashboard as d

        rows = pd.DataFrame(
            {
                "formation": ["RAIDER", "TEXAS NASTY", "SLOT DIP BASH"],
                "motion": ["1 FLY", "", ""],
                "season": ["26-27", "26-27", "26-27"],
                "form_tagged": [1, 1, 1],
            }
        )
        ctx = d._season_phrase_context(rows)
        self.assertIn("Raider", ctx["formations"])
        self.assertIn("Texas Nasty", ctx["formations"])
        self.assertIn("Slot Dip", ctx["formations"])
        self.assertIn("Bash", ctx["variants"])
        self.assertIn("1 Fly", ctx["motions"])
        favs = {"formations": [], "variants": [], "motions": [], "plays": {}, "inbox_plays": []}
        parsed = d.parse_live_phrase(
            "Raider Army Trap gain of 4",
            favs,
            extra_plays=[("Army Trap", "run")],
            extra_formations=["Raider"],
        )
        self.assertEqual(parsed.get("formation"), "Raider")
        self.assertEqual(parsed.get("play_call"), "Army Trap")
        self.assertEqual(parsed.get("play_type"), "run")

    def test_odd_scheme_tagger_front_is_odd(self):
        import pandas as pd

        from mesh_engine import (
            _booth_front_for_opponent,
            scout_favorite_looks,
            scout_situation_expect,
        )

        self.assertEqual(_booth_front_for_opponent("54", "Leonard"), "Odd")
        self.assertEqual(_booth_front_for_opponent("44", "Bells"), "Odd")
        scout = pd.DataFrame(
            {
                "down": [1, 1, 1, 1],
                "distance_bucket": ["long"] * 4,
                "field_zone": ["own_territory"] * 4,
                "def_front": ["54", "54", "44", "45"],
                "coverage": ["4", "4", "4", "0"],
                "blitz": ["BANDIT STAB", "", "WILL BLAST", ""],
            }
        )
        expect = scout_situation_expect(
            "Leonard",
            1,
            "long",
            "own_territory",
            scout_df=scout,
        )
        self.assertEqual(expect["film_front"], "54")
        self.assertEqual(expect["booth_front"], "Odd")
        self.assertEqual(expect["coverage"], "4")
        self.assertEqual(expect["front_pct"], 50)  # 2 of 4
        self.assertEqual(expect["coverage_pct"], 75)  # 3 of 4
        self.assertEqual(expect["blitz_pct"], 50)
        self.assertEqual(expect["blitz_type"], "BANDIT STAB")
        # Lane / package rates are among blitz snaps only (2 blitzes here)
        self.assertEqual(expect["blitz_type_pct"], 50)  # 1 of 2 blitzes
        self.assertEqual(expect["blitz_lane"], "outside")
        self.assertEqual(expect["outside_pct"], 50)
        self.assertEqual(expect["inside_pct"], 50)
        self.assertFalse(expect["cross_flag"])
        self.assertIn("tag Odd", expect["summary"])
        # Blitz leads the sentence; front/coverage follow
        self.assertTrue(expect["sentence"].startswith("Blitz 50%"))
        self.assertIn("BANDIT STAB", expect["sentence"])
        self.assertIn("outside", expect["sentence"])
        self.assertIn("54 (tag Odd) front 50%", expect["sentence"])
        self.assertIn("Cover 4 75%", expect["sentence"])
        # CROSS as top package → protection-change flag
        cross_scout = scout.copy()
        cross_scout["blitz"] = ["MIKE CROSS", "MIKE CROSS", "WILL BLAST", ""]
        cross_expect = scout_situation_expect(
            "Leonard", 1, "long", "own_territory", scout_df=cross_scout
        )
        self.assertTrue(cross_expect["cross_flag"])
        self.assertEqual(cross_expect["blitz_lane"], "cross")
        self.assertIn("protection change", cross_expect["sentence"])
        self.assertTrue(cross_expect["sentence"].startswith("Blitz"))
        # Favorites path (tagger chips) collapses numbers to Odd
        import mesh_engine as me

        orig = me.load_scout

        def _fake_load(role, opponent=None, season=None):
            return scout

        me.load_scout = _fake_load
        try:
            looks = scout_favorite_looks("Leonard", n=4)
        finally:
            me.load_scout = orig
        self.assertEqual(looks["fronts"], ["Odd"])
        self.assertEqual(looks["coverages"][0], "4")

    def test_film_tags_on_live_phrase(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Spot incomplete even no blitz cover 3", favs)
        self.assertEqual(p.get("def_front"), "Even")
        self.assertEqual(p.get("coverage"), "Cover 3")
        self.assertEqual(p.get("blitz"), "No")

    def test_bare_maps_to_bear_pass(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("bare incomplete", favs)
        self.assertEqual(p.get("pass_tag"), "Bear")
        self.assertFalse(p.get("run_tag"))

    def test_bare_front_is_bear_front(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Spot incomplete bare front cover 3", favs)
        self.assertEqual(p.get("def_front"), "Bear")
        self.assertEqual(p.get("coverage"), "Cover 3")
        self.assertEqual(p.get("pass_tag"), "Spot")
        self.assertNotEqual(p.get("pass_tag"), "")
        # "bare front" is the front, not a second pass tag
        self.assertEqual(p.get("run_tag") or "", "")


class TestFastLogReady(unittest.TestCase):
    def test_ready_with_call_and_outcome(self):
        import step4_dashboard as d

        ok, reason = d._ql_draft_ready_for_fast_log(
            {
                "formation": "Slot",
                "run_tag": "Mary",
                "pass_tag": "",
                "play_call": "Mary",
                "result": "Gain",
                "has_outcome": True,
                "play_is_new": False,
            }
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_ready_with_default_outcome(self):
        import step4_dashboard as d

        ok, reason = d._ql_draft_ready_for_fast_log(
            {
                "formation": "Slot",
                "run_tag": "Mary",
                "pass_tag": "",
                "play_call": "Mary",
                "result": "Gain",
                "has_outcome": False,
                "play_is_new": False,
            }
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_not_ready_for_new_play(self):
        import step4_dashboard as d

        ok, _ = d._ql_draft_ready_for_fast_log(
            {
                "formation": "",
                "run_tag": "",
                "pass_tag": "",
                "play_call": "Zombie",
                "result": "Gain",
                "has_outcome": True,
                "play_is_new": True,
            }
        )
        self.assertFalse(ok)


class TestRpoOutcomeType(unittest.TestCase):
    def test_completion_is_pass(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Army Bear completion to Cheatham", favs)
        self.assertEqual(p.get("run_tag"), "Army")
        self.assertEqual(p.get("pass_tag"), "Bear")
        self.assertEqual(p.get("play_type"), "pass")
        self.assertEqual(p.get("outcome_lane"), "pass")
        self.assertEqual(p.get("touch_role"), "target")
        self.assertIn("Cheatham", str(p.get("ball_player")))

    def test_carry_is_run(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Army Bear carry for Walker", favs)
        self.assertEqual(p.get("run_tag"), "Army")
        self.assertEqual(p.get("pass_tag"), "Bear")
        self.assertEqual(p.get("play_type"), "run")
        self.assertEqual(p.get("outcome_lane"), "run")
        self.assertEqual(p.get("touch_role"), "carry")
        self.assertTrue(p.get("ball_player"))
    def test_incomplete_is_pass(self):
        import step4_dashboard as d

        self.assertEqual(
            d.resolve_logged_play_type(
                run_tag="Army", pass_tag="Bear", result="Incomplete"
            ),
            "pass",
        )

    def test_name_first_carry_yards(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("luke carry for 10", favs)
        self.assertTrue(p.get("ball_player"))
        self.assertIn("Luke", str(p.get("ball_player")))
        self.assertEqual(p.get("touch_role"), "carry")
        self.assertEqual(p.get("outcome_lane"), "run")
        self.assertEqual(p.get("result"), "Gain")
        self.assertEqual(p.get("yards_gained"), 10)

    def test_name_first_catch_yards(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("luke catch for 12", favs)
        self.assertTrue(p.get("ball_player"))
        self.assertIn("Luke", str(p.get("ball_player")))
        self.assertEqual(p.get("touch_role"), "target")
        self.assertEqual(p.get("yards_gained"), 12)
        self.assertEqual(p.get("result"), "Gain")

    def test_complete_to_name_yards(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("complete to luke for 10", favs)
        self.assertTrue(p.get("ball_player"))
        self.assertIn("Luke", str(p.get("ball_player")))
        self.assertEqual(p.get("touch_role"), "target")
        self.assertEqual(p.get("outcome_lane"), "pass")
        self.assertEqual(p.get("result"), "Gain")
        self.assertEqual(p.get("yards_gained"), 10)

    def test_completed_to_opp_spot_yards(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        # Own 20 → Opp 45 = ball 20 → 55 → +35
        p = d.parse_live_phrase(
            "Slot Dip Bash completed to the opp 45",
            favs,
            start_ball_yard=20,
        )
        self.assertEqual(p.get("end_ball_yard"), 55)
        self.assertEqual(p.get("yards_gained"), 35)
        self.assertEqual(p.get("result"), "Gain")
        self.assertTrue(p.get("has_outcome"))
        # Pre-snap LOS unchanged when only end spot given
        self.assertIsNone(p.get("ball_yard"))

    def test_own_start_and_opp_end_spot(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase(
            "1st and 10 own 25 Army Bear completed to the opp 40",
            favs,
        )
        self.assertEqual(p.get("ball_yard"), 25)
        self.assertEqual(p.get("end_ball_yard"), 60)
        self.assertEqual(p.get("yards_gained"), 35)
        self.assertEqual(p.get("down"), 1)
        self.assertEqual(p.get("distance_yards"), 10)

    def test_completion_to_name_yards(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("completion to Cheatham for 15", favs)
        self.assertIn("Cheatham", str(p.get("ball_player")))
        self.assertEqual(p.get("touch_role"), "target")
        self.assertEqual(p.get("result"), "Gain")
        self.assertEqual(p.get("yards_gained"), 15)

    def test_rushes_for_and_handoff(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Luke rushes for 8", favs)
        self.assertEqual(p.get("touch_role"), "carry")
        self.assertEqual(p.get("yards_gained"), 8)
        p2 = d.parse_live_phrase("handoff to luke for 5", favs)
        self.assertEqual(p2.get("touch_role"), "carry")
        self.assertEqual(p2.get("yards_gained"), 5)

    def test_touch_stats_board(self):
        import pandas as pd
        import step4_dashboard as d

        logs = pd.DataFrame(
            [
                {
                    "opponent": "Test",
                    "unit": "Offense",
                    "ball_player": "Luke Harris",
                    "touch_role": "carry",
                    "result": "Gain",
                    "yards_gained": 10,
                    "play_type": "run",
                },
                {
                    "opponent": "Test",
                    "unit": "Offense",
                    "ball_player": "Luke Harris",
                    "pass_player": "Nate Harris",
                    "touch_role": "target",
                    "result": "Gain",
                    "yards_gained": 12,
                    "play_type": "pass",
                },
                {
                    "opponent": "Test",
                    "unit": "Offense",
                    "ball_player": "Luke Harris",
                    "pass_player": "Nate Harris",
                    "touch_role": "target",
                    "result": "Incomplete",
                    "yards_gained": 0,
                    "play_type": "pass",
                },
                {
                    "opponent": "Test",
                    "unit": "Offense",
                    "pass_player": "Nate Harris",
                    "touch_role": "target",
                    "result": "Turnover",
                    "yards_gained": 0,
                    "play_type": "pass",
                },
                {
                    "opponent": "Test",
                    "unit": "Offense",
                    "ball_player": "Luke Harris",
                    "pass_player": "Nate Harris",
                    "touch_role": "target",
                    "result": "TD",
                    "yards_gained": 25,
                    "play_type": "pass",
                },
            ]
        )
        board = d.player_skill_stats_table(logs, "Test")
        by_name = {r["player"]: r for _, r in board.iterrows()}
        luke = by_name["Luke Harris"]
        self.assertEqual(int(luke["carries"]), 1)
        self.assertEqual(int(luke["rush_yds"]), 10)
        self.assertEqual(int(luke["targets"]), 3)
        self.assertEqual(int(luke["receptions"]), 2)
        self.assertEqual(int(luke["rec_yds"]), 37)
        self.assertEqual(int(luke["rec_td"]), 1)
        nate = by_name["Nate Harris"]
        self.assertEqual(int(nate["att"]), 4)
        self.assertEqual(int(nate["cmp"]), 2)
        self.assertEqual(int(nate["pass_yds"]), 37)
        self.assertEqual(int(nate["pass_td"]), 1)
        self.assertEqual(int(nate["ints"]), 1)

    def test_passer_to_target_phrase(self):
        import step4_dashboard as d

        favs = d.load_live_favorites()
        p = d.parse_live_phrase("Nate to Luke for 10", favs)
        self.assertIn("Nate", str(p.get("pass_player")))
        self.assertIn("Luke", str(p.get("ball_player")))
        self.assertEqual(p.get("touch_role"), "target")
        self.assertEqual(p.get("yards_gained"), 10)
        self.assertEqual(p.get("outcome_lane"), "pass")

    def test_resolve_pass_player_from_lineup(self):
        import step4_dashboard as d

        self.assertEqual(
            d.resolve_pass_player(
                touch_role="target",
                slots={"QB": "Nate Harris"},
            ),
            "Nate Harris",
        )
        self.assertEqual(
            d.resolve_pass_player(
                touch_role="carry",
                play_type="run",
                slots={"QB": "Nate Harris"},
            ),
            "",
        )
        self.assertEqual(
            d.resolve_pass_player(
                pass_player="Custom QB",
                touch_role="target",
                slots={"QB": "Nate Harris"},
            ),
            "Custom QB",
        )


class TestStartNewGame(unittest.TestCase):
    def test_archive_and_clear_live_log(self):
        import pandas as pd
        import step4_dashboard as d
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log = tmp_path / "live_log.csv"
            arch = tmp_path / "archive"
            pd.DataFrame(
                [{"opponent": "Scrimmage", "result": "Gain", "yards_gained": 5}]
            ).to_csv(log, index=False)
            old_log, old_arch = d.LIVE_LOG_FILE, d.LIVE_LOG_ARCHIVE_DIR
            d.LIVE_LOG_FILE = log
            d.LIVE_LOG_ARCHIVE_DIR = arch
            try:
                path = d.archive_and_clear_live_log(opponent="Scrimmage")
                self.assertTrue(path and path.exists())
                cleared = pd.read_csv(log)
                self.assertEqual(len(cleared), 0)
            finally:
                d.LIVE_LOG_FILE = old_log
                d.LIVE_LOG_ARCHIVE_DIR = old_arch

    def test_ht_generation_stores_live_snapshot(self):
        """HT generate (not Start new) is the durable store for 1st-half tags."""
        import tempfile
        from pathlib import Path

        import pandas as pd

        import mesh_engine as m

        logs = pd.DataFrame(
            [
                {
                    "opponent": "HSAA",
                    "half": 1,
                    "unit": "Offense",
                    "down": 1,
                    "distance": "long",
                    "field_zone": "midfield",
                    "ball_yard": 45,
                    "formation": "SLOT TRIG",
                    "play_call": "ARMY",
                    "result": "Gain",
                    "yards_gained": 4,
                    "def_front": "Even",
                    "coverage": "Cover 3",
                    "blitz": "No",
                    "ball_player": "Luke Harris",
                    "tagged_by": "Tagger",
                },
                {
                    "opponent": "HSAA",
                    "half": 1,
                    "unit": "Offense",
                    "down": 2,
                    "distance": "medium",
                    "field_zone": "midfield",
                    "ball_yard": 49,
                    "formation": "SLOT TRIG",
                    "play_call": "MOLLY",
                    "result": "Gain",
                    "yards_gained": 8,
                    "def_front": "Even",
                    "coverage": "Cover 4",
                    "blitz": "Yes",
                    "ball_player": "Tyse Lennon",
                    "tagged_by": "Tagger",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old_ht = m.HALFTIME_REPORTS_DIR
            old_arch = m.LIVE_LOG_ARCHIVE_DIR
            old_state = m.GAME_STATE_FILE
            m.HALFTIME_REPORTS_DIR = tmp_path / "ht"
            m.LIVE_LOG_ARCHIVE_DIR = tmp_path / "archive"
            m.GAME_STATE_FILE = tmp_path / "game_state.json"
            import live_games as lg

            old_lg = lg.LIVE_GAMES_DIR
            old_db = lg.DB_FILE
            lg.LIVE_GAMES_DIR = tmp_path / "live_games"
            lg.DB_FILE = tmp_path / "football.db"
            try:
                result = m.end_first_half("HSAA", logs, plan={}, player_board=None)
                snap = result.get("live_log_snapshot") or {}
                self.assertEqual(int(snap.get("plays") or 0), 2)
                candidates = list((tmp_path / "ht").glob("*_live.csv"))
                self.assertTrue(candidates, "expected *_live.csv next to HT report")
                saved = pd.read_csv(candidates[0])
                self.assertEqual(len(saved), 2)
                self.assertEqual(int((saved["coverage"].astype(str).str.len() > 0).sum()), 2)
                self.assertEqual(int((saved["ball_player"].astype(str).str.len() > 0).sum()), 2)
                arch = list((tmp_path / "archive").glob("*_halftime.csv"))
                self.assertTrue(arch, "expected live_log_archive/*_halftime.csv")
                self.assertEqual(snap.get("tag_fill", {}).get("coverage"), 2)
                self.assertTrue((result.get("state") or {}).get("live_log_snapshot"))
                # Same durable store as Main End Game
                self.assertTrue(snap.get("live_games_saved"), snap)
                lg_files = list((tmp_path / "live_games").glob("*.csv"))
                self.assertTrue(lg_files, "expected data/live_games checkpoint on HT")
                lg_df = pd.read_csv(lg_files[0])
                self.assertEqual(len(lg_df), 2)
                self.assertIn("Even", set(lg_df["def_front"].astype(str)))
            finally:
                m.HALFTIME_REPORTS_DIR = old_ht
                m.LIVE_LOG_ARCHIVE_DIR = old_arch
                m.GAME_STATE_FILE = old_state
                lg.LIVE_GAMES_DIR = old_lg
                lg.DB_FILE = old_db

    def test_overlay_live_film_onto_blank_hudl(self):
        """Hudl game with blank film should pick up live_games film tags."""
        import tempfile
        from pathlib import Path

        import pandas as pd

        import live_games as lg

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db = tmp_path / "football.db"
            old_db = lg.DB_FILE
            lg.DB_FILE = db
            try:
                import sqlite3

                hudl = pd.DataFrame(
                    [
                        {
                            "play_num": 1,
                            "odk": "O",
                            "formation": "SLOT TRIG",
                            "play_call": "ARMY",
                            "play_type": "Run",
                            "down": 1,
                            "distance": 10,
                            "def_front": "",
                            "coverage": "",
                            "blitz": "",
                            "yard_line": -45,
                            "yards_gained": 4,
                            "result": "Rush",
                            "game_id": 6,
                            "season": "26-27",
                            "source_file": "season.xlsx",
                            "opponent": "Commerce",
                            "field_position": 45,
                        },
                        {
                            "play_num": 2,
                            "odk": "O",
                            "formation": "DOT",
                            "play_call": "MOLLY",
                            "play_type": "Pass",
                            "down": 2,
                            "distance": 6,
                            "def_front": "",
                            "coverage": "",
                            "blitz": "",
                            "yard_line": -49,
                            "yards_gained": 8,
                            "result": "Complete",
                            "game_id": 6,
                            "season": "26-27",
                            "source_file": "season.xlsx",
                            "opponent": "Commerce",
                            "field_position": 49,
                        },
                    ]
                )
                with sqlite3.connect(db) as conn:
                    hudl.to_sql("offense_plays", conn, if_exists="replace", index=False)
                    hudl.to_sql("offense_plays_epa", conn, if_exists="replace", index=False)

                live = pd.DataFrame(
                    [
                        {
                            "play_num": 1,
                            "def_front": "3-3 Stack",
                            "coverage": "Cover 3",
                            "blitz": "No",
                            "game_id": 6,
                            "season": "26-27",
                            "opponent": "Commerce",
                            "source_file": "live:Commerce.csv",
                        },
                        {
                            "play_num": 2,
                            "def_front": "Even",
                            "coverage": "Cover 1",
                            "blitz": "Yes",
                            "game_id": 6,
                            "season": "26-27",
                            "opponent": "Commerce",
                            "source_file": "live:Commerce.csv",
                        },
                    ]
                )
                result = lg.overlay_live_film_onto_hudl(live)
                self.assertTrue(result.get("overlaid"), result)
                with sqlite3.connect(db) as conn:
                    out = pd.read_sql("SELECT def_front, coverage, blitz FROM offense_plays ORDER BY play_num", conn)
                self.assertEqual(list(out["def_front"]), ["3-3 Stack", "Even"])
                self.assertEqual(list(out["coverage"]), ["Cover 3", "Cover 1"])
                self.assertEqual(list(out["blitz"]), ["No", "Yes"])
            finally:
                lg.DB_FILE = old_db

    def test_ht_tendency_helpers(self):
        import step4_dashboard as d

        bdf = d._ht_tendency_dim_table(
            [{"formation": "Slot", "blitz_pct": 50, "blitz_plays": 2, "plays": 4}],
            dim_key="formation",
            dim_label="Formation",
        )
        self.assertIsNotNone(bdf)
        self.assertIn("Blitz %", bdf.columns)


class TestPlayCallBoards(unittest.TestCase):
    def test_overall_and_mode_keys(self):
        import pandas as pd
        from mesh_engine import annotate_play_call_keys

        df = pd.DataFrame(
            [
                {
                    "play_call": "Army Bear",
                    "run_tag": "Army",
                    "pass_tag": "Bear",
                    "play_type": "run",
                    "call": "Army Bear",
                },
                {
                    "play_call": "Army Bear",
                    "run_tag": "Army",
                    "pass_tag": "Bear",
                    "play_type": "pass",
                    "call": "Army Bear",
                },
                {
                    "play_call": "Power",
                    "run_tag": "Power",
                    "pass_tag": "",
                    "play_type": "run",
                    "call": "Power",
                },
            ]
        )
        out = annotate_play_call_keys(df)
        self.assertEqual(list(out["play_call_overall"]), ["Army Bear", "Army Bear", "Power"])
        self.assertEqual(
            list(out["play_call_mode"]),
            ["Army Bear · run", "Army Bear · pass", ""],
        )

    def test_report_includes_play_calls(self):
        import pandas as pd
        from mesh_engine import build_halftime_report

        fixture = ROOT / "tests" / "fixtures" / "live_log_half.csv"
        log = pd.read_csv(fixture)
        # Inject dual-tag snaps so by_mode has something to score
        extra = pd.DataFrame(
            [
                {
                    "timestamp": "2026-08-01T12:00:00",
                    "opponent": "Farmersville",
                    "half": 1,
                    "unit": "Offense",
                    "down": 1,
                    "distance": "long",
                    "field_zone": "midfield",
                    "formation": "Trips",
                    "play_call": "Army Bear",
                    "run_tag": "Army",
                    "pass_tag": "Bear",
                    "play_type": "run",
                    "call": "Army Bear",
                    "result": "Gain",
                    "yards_gained": 5,
                },
                {
                    "timestamp": "2026-08-01T12:01:00",
                    "opponent": "Farmersville",
                    "half": 1,
                    "unit": "Offense",
                    "down": 2,
                    "distance": "medium",
                    "field_zone": "midfield",
                    "formation": "Trips",
                    "play_call": "Army Bear",
                    "run_tag": "Army",
                    "pass_tag": "Bear",
                    "play_type": "pass",
                    "call": "Army Bear",
                    "result": "Incomplete",
                    "yards_gained": 0,
                },
            ]
        )
        log = pd.concat([log, extra], ignore_index=True)
        report = build_halftime_report(
            "Farmersville", log, {"offense_pins": [], "defense_pins": []}
        )
        self.assertGreaterEqual(report.get("version"), 9)
        self.assertIn("play_calls", report)
        overall = (report["play_calls"].get("overall") or {}).get("offense") or []
        modes = (report["play_calls"].get("by_mode") or {}).get("offense") or []
        self.assertTrue(any("Army Bear" == r.get("label") for r in overall))
        self.assertTrue(any("·" in str(r.get("label") or "") for r in modes))
        first = ((report.get("scenarios") or {}).get("by_down") or {}).get("1") or {}
        ton = ((first.get("overall") or {}).get("tonight") or {})
        self.assertIsNotNone(ton.get("avg_epa"))
        self.assertGreaterEqual(int(ton.get("plays") or 0), 1)
        self.assertIn("long", first.get("by_distance") or {})


class TestSeasonScope(unittest.TestCase):
    def test_season_helpers(self):
        from team_config import (
            current_season_aliases,
            current_season_id,
            is_current_season_value,
        )

        self.assertTrue(current_season_id())
        self.assertIn("current", current_season_aliases())
        self.assertTrue(is_current_season_value("current"))
        self.assertTrue(is_current_season_value(current_season_id()))
        self.assertTrue(is_current_season_value(""))
        self.assertFalse(is_current_season_value("24-25"))
        # Prior season id is not "current" once you've rolled forward
        prior = "25-26" if current_season_id() != "25-26" else "24-25"
        if prior != current_season_id():
            self.assertFalse(is_current_season_value(prior))
        # Aliases must never list another YY-YY year
        yearish = [a for a in current_season_aliases() if a.count("-") == 1 and a[0].isdigit()]
        self.assertEqual(yearish, [current_season_id().lower()])

    def test_game_review_excludes_prior_season(self):
        """26-27 Game Review must not include 25-26 games even with polluted aliases."""
        import pandas as pd
        from unittest.mock import patch

        import team_config as tc
        from step4_dashboard import game_review_table, plays_for_season

        df = pd.DataFrame(
            {
                "season": ["26-27"] * 3 + ["25-26"] * 5 + ["24-25"] * 2,
                "game_id": [1, 2, 3, 17, 18, 19, 20, 21, 5, 6],
                "opponent": [
                    "Bonham Scrimmage",
                    "Cooper Scrimmage",
                    "HSAA",
                    "Farmersville",
                    "Commerce",
                    "Bonham",
                    "Honey Grove",
                    "Leonard",
                    "Unknown",
                    "Unknown",
                ],
                "epa": [0.1] * 10,
                "points_scored": [0] * 10,
                "is_touchdown": [0] * 10,
                "game_notes": [""] * 10,
            }
        )
        # Even if aliases wrongly include 25-26, concrete 26-27 pick stays clean
        polluted = {"", "current", "26-27", "25-26"}
        with patch.object(tc, "current_season_aliases", return_value=polluted):
            with patch.object(
                tc,
                "is_current_season_value",
                side_effect=lambda v: str(v).strip().lower() in polluted,
            ):
                rev = plays_for_season(df, "26-27")
        self.assertEqual(set(rev["season"].unique()), {"26-27"})
        games = game_review_table(rev)
        self.assertEqual(set(games["opponent"]), {"Bonham Scrimmage", "Cooper Scrimmage", "HSAA"})
        # Archived year still reachable via picker
        prior = plays_for_season(df, "25-26")
        self.assertEqual(set(prior["season"].unique()), {"25-26"})
        self.assertIn("Commerce", set(game_review_table(prior)["opponent"]))

    def test_roster_season_roundtrip(self):
        import step4_dashboard as d

        with tempfile.TemporaryDirectory() as td:
            roster_path = Path(td) / "roster.json"
            starters_path = Path(td) / "starters.json"
            old_roster = d.ROSTER_FILE
            old_starters = d.STARTERS_FILE
            d.ROSTER_FILE = roster_path
            d.STARTERS_FILE = starters_path
            try:
                # Legacy flat file still loads
                roster_path.write_text(
                    json.dumps({"players": [{"name": "Test QB", "positions": ["QB"]}]}),
                    encoding="utf-8",
                )
                players = d.load_roster()
                self.assertEqual(players[0]["name"], "Test QB")
                d.save_roster(players)
                saved = json.loads(roster_path.read_text(encoding="utf-8"))
                self.assertIn("seasons", saved)
                self.assertIn("active_season", saved)
                self.assertTrue(saved["players"])

                d.save_starters({"offense": {"QB": "Test QB"}})
                starters = d.load_starters()
                self.assertEqual(starters["offense"]["QB"], "Test QB")
                s_saved = json.loads(starters_path.read_text(encoding="utf-8"))
                self.assertIn("seasons", s_saved)
            finally:
                d.ROSTER_FILE = old_roster
                d.STARTERS_FILE = old_starters

    def test_create_roster_carry_over(self):
        import step4_dashboard as d
        import team_config as tc

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            roster_path = td_path / "roster.json"
            starters_path = td_path / "starters.json"
            cfg_path = td_path / "team_config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "season": {
                            "id": "25-26",
                            "label": "2025-26",
                            "current_aliases": ["current", "25-26", ""],
                        }
                    }
                ),
                encoding="utf-8",
            )
            old_roster, old_starters = d.ROSTER_FILE, d.STARTERS_FILE
            old_cfg = tc.CONFIG_FILE
            d.ROSTER_FILE = roster_path
            d.STARTERS_FILE = starters_path
            tc.CONFIG_FILE = cfg_path
            tc.load_team_config.cache_clear()
            try:
                d.save_roster(
                    [
                        {"name": "Keeper", "positions": ["WR"], "starter": True},
                        {"name": "Grad", "positions": ["RB"], "starter": False},
                    ]
                )
                d.save_starters({"offense": {"WR1": "Keeper", "RB": "Grad"}})
                result = d.create_season_roster(
                    new_season_id="26-27",
                    new_season_label="2026-27",
                    carry_names=["Keeper"],
                    source_season_id="25-26",
                )
                self.assertEqual(result["carried"], 1)
                self.assertEqual(result["left_behind"], 1)
                self.assertEqual(tc.current_season_id(), "26-27")
                active = d.load_roster()
                self.assertEqual([p["name"] for p in active], ["Keeper"])
                archived = d.load_roster_for_season("25-26")
                names = {p["name"] for p in archived}
                self.assertEqual(names, {"Keeper", "Grad"})
                starters = d.load_starters().get("offense") or {}
                self.assertEqual(starters.get("WR1"), "Keeper")
                self.assertNotIn("RB", starters)
            finally:
                d.ROSTER_FILE = old_roster
                d.STARTERS_FILE = old_starters
                tc.CONFIG_FILE = old_cfg
                tc.load_team_config.cache_clear()


class TestSchedule(unittest.TestCase):
    def test_add_and_save_roundtrip(self):
        import schedule as sch

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            old_data = sch.DATA_DIR
            old_opp = sch.OPPONENTS_FILE
            sch.DATA_DIR = data
            sch.OPPONENTS_FILE = data / "opponents.csv"
            try:
                df = sch.add_schedule_game(sch.empty_schedule(), "Farmersville")
                df = sch.add_schedule_game(df, "Commerce", notes="Home")
                df = sch.add_schedule_game(df, "Someone", playoff=True)
                path = sch.save_schedule(df, None)
                self.assertTrue(path.exists())
                loaded = sch.load_schedule(None)
                self.assertEqual(list(loaded["opponent"]), ["Farmersville", "Commerce", "Someone"])
                self.assertIn("Playoff", loaded.iloc[-1]["notes"])
            finally:
                sch.DATA_DIR = old_data
                sch.OPPONENTS_FILE = old_opp


class TestFormationBook(unittest.TestCase):
    def test_compass_and_h_tags(self):
        from formation_logic import formation_breakdown

        east = formation_breakdown("East")
        self.assertEqual(east["layout"], "TripsRight")
        self.assertIn("Trips right", east["note"])

        west = formation_breakdown("West")
        self.assertEqual(west["layout"], "TripsLeft")

        dip = formation_breakdown("Slot Dip")
        self.assertIn("1-WR", dip["note"])
        self.assertTrue(dip["layout"].startswith("SlotDip"))

        trig = formation_breakdown("Slot Trig")
        self.assertIn("2-WR", trig["note"])

        fox = formation_breakdown("Fox RT")
        self.assertEqual(fox["layout"], "FoxRight")
        self.assertIn("3-WR", fox["note"])

        fever = formation_breakdown("Fever LT")
        self.assertEqual(fever["layout"], "FeverLeft")
        self.assertIn("attached TE", fever["note"])

    def test_personnel_tags(self):
        from formation_logic import formation_breakdown

        self.assertIn("Doubles", formation_breakdown("Dot")["note"])
        self.assertIn("Bunch", formation_breakdown("Pack RT")["note"])
        self.assertIn("Empty Bunch", formation_breakdown("Cowboy")["note"])
        self.assertIn("12", formation_breakdown("Texas")["note"])
        self.assertIn("6 OL", formation_breakdown("Nasty")["note"])
        self.assertIn("boundary", formation_breakdown("Trix")["note"].lower())


class TestBoothStations(unittest.TestCase):
    def test_normalize_and_query(self):
        from booth_stations import normalize_station, station_from_query

        self.assertEqual(normalize_station("defense"), "defense")
        self.assertEqual(normalize_station("Film"), "defense")
        self.assertEqual(normalize_station("call"), "call")
        self.assertEqual(normalize_station(""), "full")
        self.assertEqual(station_from_query({"station": "defense"}), "defense")
        self.assertEqual(station_from_query({"station": ["call"]}), "call")
        self.assertIsNone(station_from_query({}))


if __name__ == "__main__":
    unittest.main()
