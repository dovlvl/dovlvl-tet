import copy
import unittest

import bootstrap  # noqa: F401 -- configure source imports
from controller import AutoController
from helpers import C, FakeBackend, Game
from input_win import KeyPulse
from recognition import Recognizer


TIMING_REASON = "EXECUTION_WINDOW_EXCEEDED: no observed-state path can finish safely"


class StopReasonMessageTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.controller = AutoController(KeyPulse(self.backend), copy.deepcopy(C))
        self.controller.start(99, 100)
        reader = Recognizer()
        game = Game()
        self.observation = reader.process(game.image(), (0, 0, 340, 400), C, 1, 100)

    def test_timing_limit_explains_safe_time_and_path_and_still_releases_keys(self):
        self.controller.pulse.press("LEFT", 100, 35, 35)
        self.assertTrue(self.controller.pulse.pressed)
        for _ in range(5):
            self.controller.execution_window_failed(TIMING_REASON, self.observation)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.failures, 5)
        self.assertEqual(self.controller.block_failures, 5)
        self.assertIn("시간", self.controller.reason)
        self.assertIn("경로", self.controller.reason)
        self.assertNotIn("조작 키", self.controller.reason)
        self.assertIn("연속 5회 / 블록당 8회", self.controller.reason)
        self.assertTrue(self.controller.pulse.abort.is_set())
        self.assertFalse(self.controller.pulse.pressed)
        self.assertEqual(sum(down for _, down in self.backend.events), 1)

    def test_per_block_limit_remains_eight(self):
        self.controller.block_failures = 7
        self.controller.execution_window_failed(TIMING_REASON, self.observation)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.block_failures, 8)
        self.assertEqual(self.controller.failures, 1)
        self.assertIn("시간", self.controller.reason)

    def test_confirmation_failure_retains_key_configuration_guidance(self):
        for _ in range(5):
            self.controller.replan("이동/회전 실패 또는 상태 불일치: 최신 화면 재탐색")
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.failures, 5)
        self.assertIn("입력 확인 반복 실패", self.controller.reason)
        self.assertIn("조작 키", self.controller.reason)

    def test_noncounting_replan_does_not_consume_or_trigger_limits(self):
        self.controller.failures = 4
        self.controller.block_failures = 7
        self.controller.replan("STALE_PLAN", count_failure=False)
        self.assertTrue(self.controller.running)
        self.assertEqual(self.controller.failures, 4)
        self.assertEqual(self.controller.block_failures, 7)

    def test_late_execution_failure_cannot_replace_f8_stop(self):
        self.controller.stop("F8 긴급 중지")
        self.controller.execution_window_failed(TIMING_REASON, self.observation)
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.reason, "F8 긴급 중지")
        self.assertFalse(self.backend.events)


if __name__ == "__main__":
    unittest.main()
