import unittest

import bootstrap  # noqa: F401 -- configure source imports
from scoring import award, tspin, ScoreState
from strategy import auto_plan, builtin_book
from planner import landings
from geometry import advance, orientations, settle


class SiteScoreTests(unittest.TestCase):
    def test_published_regular_and_full_spin_table(self):
        self.assertEqual([award(n)["lock_points"] for n in range(5)], [0, 100, 300, 500, 800])
        self.assertEqual([award(n, "full")["lock_points"] for n in range(4)], [400, 800, 1200, 1600])

    def test_b2b_is_stateful_and_regular_clear_breaks_it(self):
        first = award(4, state=ScoreState(back_to_back=False, combo=-1))
        blank = award(0, state=first["score_state"])
        second = award(2, "full", state=blank["score_state"])
        self.assertEqual(second["lock_points"], 1800)
        single = award(1, state=second["score_state"])
        self.assertEqual(award(4, state=single["score_state"])["lock_points"], 800)

    def test_unknown_chain_and_unpublished_bonuses_are_not_invented(self):
        event = award(2, perfect_clear=True, state=ScoreState())
        self.assertEqual(event["lock_points"], 300)
        self.assertEqual(event["combo_bonus"], 0)
        self.assertEqual(event["perfect_clear_bonus"], 0)
        self.assertFalse(event["pc_bonus_verified"])
        self.assertFalse(event["combo_bonus_verified"])
        self.assertEqual(award(4, state=ScoreState(back_to_back=None))["back_to_back_bonus"], 0)

    def test_spin_requires_actual_last_rotation_and_three_corners(self):
        step = builtin_book()["variants"][0]["steps"][-1]
        b = [list(row) for row in step["expected_before"]]
        spin_candidates = [
            a for a in landings(b, "T", counterclockwise=True) if a["spin"] == "full" and a["lines"] == 2
        ]
        self.assertTrue(spin_candidates)
        a = spin_candidates[0]
        state = (a["x"], a["y"], a["r"])
        self.assertEqual(tspin(b, "T", state, True), "full")
        self.assertEqual(tspin(b, "T", state, False), "none")
        self.assertEqual(tspin(b, "T", state, True, drop_distance=1), "none")
        self.assertEqual(tspin([[0] * 10 for _ in range(20)], "T", (3, 18, 0), True), "none")

    def test_score_policy_selects_reachable_tspin_double(self):
        step = builtin_book()["variants"][0]["steps"][-1]
        b = [list(row) for row in step["expected_before"]]
        packet = auto_plan(
            board=b,
            kind="T",
            start=(3, 0, 0),
            held=None,
            nexts=[],
            use_hold=False,
            opening=False,
            budget_ms=600,
            max_depth=1,
            counterclockwise=True,
        )
        a = packet["result"]
        self.assertEqual(a["spin"], "full", packet)
        self.assertEqual(a["lines"], 2)
        self.assertGreaterEqual(a["expected_points"], 1200)
        state = (3, 0, 0)
        for action in a["path"][:-1]:
            state = advance(b, "T", state, action)
            self.assertIsNotNone(state)
        self.assertEqual(state, (a["x"], a["y"], a["r"]))
        self.assertEqual(settle(b, orientations("T")[state[2]], *state[:2])[1], 2)
        self.assertEqual(a["spin_judgment"], "model_only")

    def test_rotation_and_hold_find_immediate_tetris_pc(self):
        b = [[0] * 10 for _ in range(16)] + [[1] * 9 + [0] for _ in range(4)]
        a = auto_plan(
            board=b,
            kind="O",
            start=(3, 0, 0),
            held="I",
            nexts=["L", "T"],
            use_hold=True,
            opening=False,
            counterclockwise=True,
        )["result"]
        self.assertTrue(a["hold"])
        self.assertEqual(a["lines"], 4)
        self.assertTrue(a["perfect_clear"])
        self.assertEqual(a["perfect_clear_bonus"], 0)
        self.assertTrue(any(k in a["path"] for k in ("up", "z")))

    def test_insufficient_known_queue_does_not_claim_opener(self):
        a = auto_plan(
            board=[[0] * 10 for _ in range(20)],
            kind="I",
            start=(3, 0, 0),
            held=None,
            nexts=["L"],
            use_hold=False,
            previews=True,
            basic_verified=True,
            budget_ms=100,
        )["result"]
        self.assertFalse(a["strategy"].startswith("TKI"))

    def test_same_kind_hold_respawn_can_escape_low_obstruction(self):
        b = [[0] * 10 for _ in range(20)]
        for y in range(8, 20):
            b[y][5] = 1
        b[19] = [1] * 8 + [0, 0]
        a = auto_plan(
            board=b,
            kind="O",
            start=(0, 16, 0),
            held="O",
            nexts=[],
            use_hold=True,
            opening=False,
            budget_ms=300,
            max_depth=1,
        )["result"]
        self.assertTrue(a["hold"])
        self.assertEqual(a["lines"], 1)
