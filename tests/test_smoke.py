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

    def test_not_ready_without_outcome(self):
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
        self.assertFalse(ok)
        self.assertIn("result", reason.lower())

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
        self.assertEqual(report.get("version"), 9)
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
