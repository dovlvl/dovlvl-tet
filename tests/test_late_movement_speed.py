import copy
import threading
import unittest
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
from controller import AutoController
from geometry import board_metrics
from helpers import C, FakeBackend, Game, synthetic_tick
from input_win import KeyPulse
from planner import basic_candidates, urgent_plan
from recognition import Recognizer
from runtime import Latest
from strategy import pc_position_score
from timing import route_feasible


class MovementSpeedTests(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.config = copy.deepcopy(C)
        self.backend = FakeBackend(self.game.input)
        self.controller = AutoController(KeyPulse(self.backend), self.config)
        self.recognizer = Recognizer()
        self.observe(1, 100)
        self.obs = self.observe(2, 100.02)
        self.controller.start(99, 100)

    def observe(self, seq, captured):
        return self.recognizer.process(self.game.image(), (0, 0, 340, 400), self.config, seq, captured)

    def accept(self):
        result = next(
            a
            for a in basic_candidates(self.obs.fixed, "T", (3, 0, 0), rotation=False)
            if a["path"] == ("right", "right", "right", "drop")
        )
        self.controller.accept_plan(dict(result=result, key=(self.obs.board_key, "T", False)), self.obs)

    def downs(self):
        return sum(down for _, down in self.backend.events)

    def prepare_gap(self):
        self.accept()
        synthetic_tick(self.controller, self.obs, 100.04)
        obs = self.observe(3, 100.09)
        synthetic_tick(self.controller, obs, 100.10)
        self.assertIsNone(self.controller.wait)
        self.assertEqual(self.downs(), 1)
        return obs

    def test_confirmed_frame_can_resume_after_configured_gap_without_new_capture(self):
        obs = self.prepare_gap()
        synthetic_tick(self.controller, obs, 100.105)
        self.assertEqual(self.downs(), 1)
        synthetic_tick(self.controller, obs, 100.115)
        self.assertEqual(self.downs(), 2)
        self.assertEqual(self.controller.wait.seq, obs.seq)
        synthetic_tick(self.controller, obs, 100.19)
        self.assertEqual(self.downs(), 2)  # No third key without the second key's ACK.
        self.controller.stop()

    def test_next_key_uses_the_ack_frame_after_rechecking_its_route(self):
        obs = self.prepare_gap()
        synthetic_tick(self.controller, obs, 100.115)
        fresh = self.observe(4, 100.17)
        synthetic_tick(self.controller, fresh, 100.20)
        self.assertEqual(self.downs(), 3)
        self.assertEqual(self.controller.wait.seq, fresh.seq)
        self.assertEqual(self.game.state[0], 6)
        self.controller.stop()

    def test_search_result_can_use_still_fresh_frame_without_idle_capture(self):
        synthetic_tick(self.controller, self.obs, 100.04)
        self.accept()
        synthetic_tick(self.controller, self.obs, 100.05)
        self.assertEqual(self.downs(), 1)
        self.controller.stop()

    def test_same_frame_retry_keeps_freshness_focus_stop_and_backend_guards(self):
        for failure in ("stale", "uncertain", "focus", "F8", "guard", "board"):
            with self.subTest(failure=failure):
                self.setUp()
                obs = self.prepare_gap()
                now = 100.115
                if failure == "stale":
                    now = 100.5
                elif failure == "uncertain":
                    obs.confidence = 0
                elif failure == "focus":
                    self.backend.focus = 1
                elif failure == "F8":
                    self.controller.stop("F8")
                elif failure == "guard":
                    self.controller.pulse.observation_guard = lambda *_: False
                else:
                    obs.fixed[19][0] = 1
                synthetic_tick(self.controller, obs, now)
                self.assertEqual(self.downs(), 1)
                self.assertFalse(self.controller.pulse.pressed)
                self.controller.stop()

    def test_latest_notification_does_not_lose_an_already_published_frame(self):
        latest = Latest()
        old, new = object(), object()
        latest.put(old)
        ready, done = threading.Event(), threading.Event()

        def consume():
            ready.set()
            latest.wait_for_change(old, 1)
            done.set()

        worker = threading.Thread(target=consume)
        worker.start()
        self.assertTrue(ready.wait(1))
        latest.put(new)
        self.assertTrue(done.wait(1))
        worker.join()
        self.assertIs(latest.get(), new)

    def test_recorded_level_eight_board_preserves_more_next_piece_room(self):
        # Actual 20261027_143409 generation 247, 46,000-point endgame.
        board = [[0] * 10 for _ in range(9)] + [
            list(map(int, row))
            for row in (
                "0001000000",
                "0001110000",
                "0000100000",
                "0000110000",
                "0000110000",
                "0001110000",
                "0000110000",
                "0011110000",
                "0111111010",
                "1111111010",
                "1111111011",
            )
        ]
        profile = dict(gravity_cps=21.4285714264, step_ms=206.5608213211, age_ms=94, lock_delay_ms=0)
        with patch("planner.perf_counter", return_value=0):
            result = urgent_plan(board, "L", (3, 0, 0), True, True, pc_position_score, 6, profile, next_kind="O")[
                "result"
            ]
        self.assertEqual(max(board_metrics(result["board"])[0]), 12)  # Recorded center drop reached 13.
        self.assertEqual(result["path"], ("right", "drop"))
        self.assertTrue(route_feasible(board, "L", (3, 0, 0), result["path"], result["cells"], profile)[0])


if __name__ == "__main__":
    unittest.main()
