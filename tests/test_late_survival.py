import copy
import unittest
from unittest.mock import Mock, patch

import bootstrap  # noqa: F401 -- configure source imports
from controller import AutoController
from geometry import board_metrics
from helpers import C, FakeBackend, Game
from input_win import KeyPulse
from planner import execution_reserve, urgent_plan
from recognition import Recognizer
from strategy import auto_plan
from timing import route_feasible


def recorded_low_board():
    # Actual 20261027_115723 decision seq5154, before the central tower.
    return [[0] * 10 for _ in range(17)] + [
        list(map(int, r))
        for r in (
            "0100111100",
            "0110111110",
            "0111111110",
        )
    ]


class LateSurvivalTests(unittest.TestCase):
    def test_recorded_board_looks_ahead_and_avoids_original_five_high_drop(self):
        board = recorded_low_board()
        profile = dict(gravity_cps=11.62790697535904, step_ms=195.53444295143407, age_ms=94, lock_delay_ms=0)
        # Remove wall-clock noise; this verifies the policy, not its speed.
        with patch("planner.perf_counter", return_value=0), patch("planner.landings") as full_bfs:
            packet = auto_plan(
                board,
                "O",
                (3, 1, 0),
                "T",
                ["Z"],
                True,
                counterclockwise=True,
                goal="perfect_clear",
                timing=profile,
            )
        full_bfs.assert_not_called()
        self.assertEqual(packet["completed_depth"], 2)
        result = packet["result"]
        self.assertLessEqual(max(board_metrics(result["board"])[0]), 4)
        self.assertEqual(board_metrics(result["board"])[1], 0)
        start = (3, 0, 0) if result["hold"] else (3, 1, 0)
        replay_profile = dict(profile, age_ms=profile["step_ms"]) if result["hold"] else profile
        self.assertTrue(
            route_feasible(board, result["kind"], start, result["path"], result["cells"], replay_profile)[0]
        )

    def test_future_input_reserve_penalizes_center_tower_at_high_gravity(self):
        low = [[0] * 10 for _ in range(18)] + [[1] * 8 + [0, 0] for _ in range(2)]
        high = [[0] * 10 for _ in range(8)] + [[0, 0, 0, 1, 1, 1, 0, 0, 0, 0] for _ in range(12)]
        profile = dict(gravity_cps=14.29, step_ms=240, age_ms=94)
        self.assertEqual(execution_reserve(low, "T", profile), 0)
        self.assertLess(execution_reserve(high, "T", profile), execution_reserve(low, "T", profile))
        self.assertEqual(execution_reserve(high, "T", None), 0)
        self.assertEqual(execution_reserve(high, "T", dict(profile, gravity_cps=0)), 0)
        self.assertEqual(
            execution_reserve(high, None, profile), min(execution_reserve(high, kind, profile) for kind in "IJLOSTZ")
        )

    def test_measured_hold_confirmation_time_excludes_unfinishable_hold(self):
        profile = dict(gravity_cps=12, step_ms=180, hold_step_ms=2000, age_ms=90, lock_delay_ms=0)
        with patch("planner.perf_counter", return_value=0):
            result = auto_plan(
                recorded_low_board(),
                "O",
                (3, 1, 0),
                "T",
                ["Z"],
                True,
                goal="perfect_clear",
                timing=profile,
                counterclockwise=True,
            )["result"]
        self.assertIsNotNone(result)
        self.assertFalse(result["hold"])

    def test_no_safe_route_still_returns_none(self):
        profile = dict(gravity_cps=14, step_ms=240, age_ms=3000, lock_delay_ms=0)
        packet = urgent_plan(recorded_low_board(), "O", (3, 1, 0), budget_ms=100, timing=profile)
        self.assertIsNone(packet["result"])

    def test_execution_failure_keeps_limit_and_records_the_actual_reason(self):
        backend = FakeBackend()
        controller = AutoController(KeyPulse(backend), copy.deepcopy(C))
        controller.start(99, 100)
        controller.telemetry = Mock()
        recognizer = Recognizer()
        game = Game()
        recognizer.process(game.image(), (0, 0, 340, 400), C, 1, 100)
        obs = recognizer.process(game.image(), (0, 0, 340, 400), C, 2, 100)
        for _ in range(5):
            controller.execution_window_failed("EXECUTION_WINDOW_EXCEEDED: no safe path", obs)
        self.assertFalse(controller.running)
        self.assertEqual(controller.failures, 5)
        self.assertIn("연속 5회", controller.reason)
        calls = controller.telemetry.record.call_args_list
        self.assertEqual(sum(c.args[0] == "execution_window_failed" for c in calls), 5)
        stop = next(c for c in calls if c.args[0] == "controller_stop")
        self.assertEqual(stop.kwargs["previous_reason"], "EXECUTION_WINDOW_EXCEEDED: no safe path")
        self.assertFalse(backend.events)
        controller.stop("F8")
        controller.execution_window_failed("unsafe", obs)
        self.assertEqual(controller.reason, "F8")
        self.assertFalse(controller.pulse.pressed)

    def test_runtime_profile_includes_independent_hold_ack_bound(self):
        from runtime import Session

        controller = AutoController(KeyPulse(FakeBackend()), copy.deepcopy(C))
        controller.hold_ack_bound_ms = 450
        controller.ack_bound_ms = 150
        recognizer = Recognizer()
        game = Game()
        recognizer.process(game.image(), (0, 0, 340, 400), C, 1, 100)
        obs = recognizer.process(game.image(), (0, 0, 340, 400), C, 2, 100)
        session = Session(copy.deepcopy(C), controller)
        session.pool = Mock()
        session.telemetry = Mock()
        session.dispatch_search(obs, controller, 100.01)
        profile = session.pool.submit.call_args.kwargs["timing"]
        self.assertEqual(profile["hold_step_ms"], 450)
        self.assertEqual(profile["step_ms"], 150)


if __name__ == "__main__":
    unittest.main()
