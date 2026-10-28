import unittest
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
from geometry import advance, cellset, hard_drop, orientations
from planner import basic_candidates
from strategy import auto_plan
from timing import route_feasible


def late_board():
    # Fixed occupancy from the observed frame before the 2026-10-28 stop.
    rows = ["0000000000"] * 12 + [
        "0001111100",
        "0001111100",
        "0000111000",
        "0111111000",
        "0111111100",
        "0011111100",
        "1111111000",
        "1111111110",
    ]
    return [[int(value) for value in row] for row in rows]


PROFILE = dict(
    gravity_cps=9.803921568640739, step_ms=562, age_ms=140, lock_delay_ms=0, grounded_unusable=False, calibrated=True
)


class LateSearchSeedTests(unittest.TestCase):
    def test_expired_budget_preserves_pixel_checked_direct_drop_only(self):
        board = late_board()
        with patch("planner.perf_counter", return_value=2):
            choices = basic_candidates(board, "I", (3, 3, 0), deadline=1, timing=PROFILE)
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0]["path"], ("drop",))
        self.assertTrue(route_feasible(board, "I", (3, 3, 0), choices[0]["path"], choices[0]["cells"], PROFILE)[0])

    def test_root_plan_keeps_safe_seed_when_initial_slice_expires_before_first_candidate(self):
        # Setup overhead consumed the 1 ms budget before the first proposal.
        times = iter([100])
        with patch("planner.perf_counter", side_effect=lambda: next(times, 100.002)):
            packet = auto_plan(
                late_board(), "I", (3, 3, 0), "Z", ["T"], False, budget_ms=1, goal="perfect_clear", timing=PROFILE
            )
        self.assertIsNotNone(packet["result"])
        self.assertTrue(packet["timed_out"])
        self.assertEqual(packet["result"]["path"], ("drop",))

    def test_expired_budget_does_not_bypass_grounded_or_natural_lock_checks(self):
        for profile in (dict(PROFILE, grounded_unusable=True), dict(PROFILE, age_ms=1200)):
            with self.subTest(profile=profile), patch("planner.perf_counter", return_value=2):
                self.assertEqual(basic_candidates(late_board(), "I", (3, 3, 0), deadline=1, timing=profile), [])

    def test_blocked_spawn_has_no_seed_even_after_budget_expiry(self):
        board = [[1] * 10 for _ in range(20)]
        with patch("planner.perf_counter", return_value=2):
            self.assertEqual(basic_candidates(board, "I", (3, 0, 0), deadline=1, timing=PROFILE), [])

    def test_seed_target_is_reachable_from_observed_state(self):
        board = late_board()
        choices = basic_candidates(board, "I", (3, 3, 0), timing=PROFILE)
        self.assertEqual(len(choices), 1)
        candidate = choices[0]
        state = (3, 3, 0)
        for action in candidate["path"][:-1]:
            state = advance(board, "I", state, action)
            self.assertIsNotNone(state)
        x, y, rotation = state
        y = hard_drop(board, orientations("I")[rotation], x, y)
        self.assertEqual(frozenset(map(tuple, candidate["cells"])), cellset("I", (x, y, rotation)))


if __name__ == "__main__":
    unittest.main()
