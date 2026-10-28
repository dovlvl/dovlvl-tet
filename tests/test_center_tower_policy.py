import unittest
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
from geometry import advance, board_metrics, cellset, hard_drop, orientations
from strategy import auto_plan
from timing import route_feasible


def recorded_board():
    # decision seq3860 from the user's 20261028_150047 game.
    rows = ["0000000000"] * 13 + [
        "0000000100",
        "1111111110",
        "1111111110",
        "1101111110",
        "1111111110",
        "1111111110",
        "1011111111",
    ]
    return [[int(value) for value in row] for row in rows]


class CenterTowerPolicyTests(unittest.TestCase):
    def assert_reachable(self, board, kind, result):
        state = (3, 0, 0)
        for action in result["path"][:-1]:
            state = advance(board, kind, state, action)
            self.assertIsNotNone(state)
        x, y, rotation = state
        y = hard_drop(board, orientations(kind)[rotation], x, y)
        self.assertEqual(cellset(kind, (x, y, rotation)), frozenset(map(tuple, result["cells"])))

    def test_recorded_position_keeps_spawn_columns_low_without_adding_holes(self):
        board = recorded_board()
        profile = dict(gravity_cps=7.117437722444255, step_ms=127.2525, age_ms=62, lock_delay_ms=0)
        for timing in (None, profile):
            with self.subTest(timing=timing), patch("planner.perf_counter", return_value=0):
                result = auto_plan(
                    board,
                    "J",
                    (3, 0, 0),
                    None,
                    [],
                    False,
                    goal="perfect_clear",
                    max_depth=1,
                    timing=timing,
                    counterclockwise=True,
                )["result"]
            self.assertIsNotNone(result)
            heights, holes, _ = board_metrics(result["board"])
            self.assertLessEqual(max(heights[3:7]), 6)
            self.assertLessEqual(holes, board_metrics(board)[1])
            self.assertLessEqual(max(heights), 8)
            self.assert_reachable(board, "J", result)
            if timing:
                self.assertTrue(route_feasible(board, "J", (3, 0, 0), result["path"], result["cells"], timing)[0])

    def test_avoids_a_new_hole_when_a_reachable_compact_alternative_exists(self):
        # Synthetic uneven board: old policy creates a second covered hole.
        rows = ["0000000000"] * 13 + [
            "0100010010",
            "0100110010",
            "1101110010",
            "1101110110",
            "1101110110",
            "1111111110",
            "1111011111",
        ]
        board = [[int(value) for value in row] for row in rows]
        with patch("planner.perf_counter", return_value=0):
            result = auto_plan(
                board, "Z", (3, 0, 0), None, [], False, goal="perfect_clear", max_depth=1, counterclockwise=True
            )["result"]
        self.assertIsNotNone(result)
        heights, holes, _ = board_metrics(result["board"])
        self.assertLessEqual(holes, board_metrics(board)[1])
        self.assertLessEqual(max(heights), 8)
        self.assert_reachable(board, "Z", result)


if __name__ == "__main__":
    unittest.main()
