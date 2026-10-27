import copy
import unittest
from unittest.mock import Mock, patch

import bootstrap  # noqa: F401 -- configure source imports
from geometry import advance, cellset, hard_drop, orientations, settle
from helpers import C, FakeBackend, Game
from controller import AutoController
from input_win import KeyPulse
from planner import basic_candidates, plan, urgent_plan
from recognition import Recognizer
from runtime import Session
from strategy import auto_plan, builtin_book, pc_position_score
from timing import route_feasible


class PerfectClearGoalTests(unittest.TestCase):
    def test_pc_beats_an_artificially_higher_utility_move(self):
        board = [[0] * 10 for _ in range(16)] + [[1] * 9 + [0] for _ in range(4)]
        with patch("planner.perf_counter", return_value=0):
            packet = plan(
                board,
                "I",
                (3, 0, 0),
                None,
                [],
                False,
                scorer=lambda b, n: 100000 if any(map(any, b)) else -100000,
                use_points=True,
                prioritize_pc=True,
            )
        self.assertEqual(packet["pc_status"], "found_confirmed_queue")
        self.assertEqual(packet["result"]["cells"], packet["pc_path"][0]["cells"])
        self.assertFalse(any(map(any, packet["result"]["board"])))
        self.assertFalse(packet["pc_deferred_for_survival"])

    def test_two_piece_pc_with_single_next_and_filled_hold_replays(self):
        board = [[0] * 10 for _ in range(18)] + [[1] * 6 + [0] * 4 for _ in range(2)]
        with patch("planner.perf_counter", return_value=0):
            packet = auto_plan(
                board,
                "T",
                (3, 0, 0),
                "O",
                ["O"],
                True,
                goal="perfect_clear",
            )
        self.assertEqual(packet["visible_next"], ["O"])
        self.assertEqual(packet["pc_remaining"], 2)
        self.assertTrue(packet["result"]["hold"])
        self.assertTrue(packet["result"]["strategy"].startswith("PC path"))
        from planner import route_to

        current, held, queue = "T", "O", ["O"]
        for placement in packet["pc_path"]:
            if placement["hold"]:
                current, held = held or queue.pop(0), current
            self.assertEqual(current, placement["kind"])
            path = route_to(board, current, (3, 0, 0), placement["cells"])
            self.assertIsNotNone(path)
            state = (3, 0, 0)
            for action in path[:-1]:
                state = advance(board, current, state, action)
                self.assertIsNotNone(state)
            x, y, r = state
            y = hard_drop(board, orientations(current)[r], x, y)
            self.assertEqual(cellset(current, (x, y, r)), frozenset(map(tuple, placement["cells"])))
            board, lines = settle(board, orientations(current)[r], x, y)
            self.assertEqual(lines, placement["lines"])
            if queue:
                current = queue.pop(0)
        self.assertFalse(any(map(any, board)))

    def test_pc_goal_bypasses_score_opener_even_when_verified(self):
        step = builtin_book()["variants"][0]["steps"][0]
        with patch("openers.opener_plan") as unused:
            packet = auto_plan(
                [list(row) for row in step["expected_before"]],
                step["kind"],
                (3, 0, 0),
                None,
                list("LJOSZT"),
                False,
                previews=True,
                basic_verified=True,
                goal="perfect_clear",
                budget_ms=60,
            )
        unused.assert_not_called()
        self.assertNotIn("TKI", packet["result"]["strategy"])
        self.assertEqual(packet["result"]["evaluation"]["goal"], "perfect_clear")

    def test_scorer_prefers_low_surface_and_clearing_over_a_tower(self):
        low = [[0] * 10 for _ in range(19)] + [[1] * 8 + [0] * 2]
        tower = [[0] * 10 for _ in range(16)] + [[1, 1] + [0] * 8 for _ in range(4)]
        self.assertGreater(pc_position_score(low, 0), pc_position_score(tower, 0))
        empty = [[0] * 10 for _ in range(20)]
        self.assertGreater(pc_position_score(empty, 2), pc_position_score(low, 0))

    def test_urgent_search_can_rotate_and_clear_under_observed_gravity(self):
        board = [[0] * 10 for _ in range(16)] + [[int(x != 5) for x in range(10)] for _ in range(4)]
        profile = dict(gravity_cps=40, step_ms=20, age_ms=10, lock_delay_ms=0)
        packet = urgent_plan(board, "I", (3, 0, 0), scorer=pc_position_score, budget_ms=100, timing=profile)
        result = packet["result"]
        self.assertIsNotNone(result)
        self.assertFalse(any(map(any, result["board"])))
        self.assertTrue(route_feasible(board, "I", (3, 0, 0), result["path"], result["cells"], profile)[0])

    def test_shortest_first_gives_rotation_a_turn_before_distant_translations(self):
        values = basic_candidates([[0] * 10 for _ in range(20)], "I", (3, 0, 0), shortest_first=True)
        paths = [value["path"] for value in values]
        self.assertLess(paths.index(("up", "drop")), paths.index(("left", "left", "drop")))

    def test_unknown_next_does_not_become_a_pc_promise(self):
        packet = auto_plan(
            [[0] * 10 for _ in range(20)],
            "T",
            (3, 0, 0),
            None,
            ["?", "O"],
            False,
            goal="perfect_clear",
            budget_ms=60,
        )
        self.assertEqual(packet["visible_next"], [])
        self.assertNotEqual(packet["pc_status"], "found_confirmed_queue")
        self.assertEqual(packet["pc_future"], "unknown_beyond_observed_queue")

    def test_runtime_requests_pc_goal_and_uses_same_scorer_for_urgent_play(self):
        config = copy.deepcopy(C)
        config["next_slots"] = config["next_slots"][:1]
        game = Game()
        recognizer = Recognizer()
        recognizer.process(game.image(), (0, 0, 340, 400), config, 1, 100)
        obs = recognizer.process(game.image(), (0, 0, 340, 400), config, 2, 100.01)
        controller = AutoController(KeyPulse(FakeBackend()), config)
        session = Session(config, controller)
        session.telemetry = Mock()
        session.pool = Mock()
        session.dispatch_search(obs, controller, 100.02)
        self.assertEqual(session.pool.submit.call_args.kwargs["goal"], "perfect_clear")
        self.assertEqual(len(session.pool.submit.call_args.kwargs["nexts"]), 1)
        controller.urgent_requested = True
        with patch("runtime.urgent_plan", return_value=dict(result=None, search_ms=1)) as urgent:
            session.dispatch_search(obs, controller, 100.02)
        self.assertIs(urgent.call_args.args[5], pc_position_score)


if __name__ == "__main__":
    unittest.main()
