import copy
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
from controller import AutoController
from geometry import cellset
from helpers import C, FakeBackend, Game, scene
from input_win import KeyPulse
from model import PendingAction
from recognition import Recognizer, components
from telemetry import Telemetry, has_recognition_failure, record_landing_mismatch


class DropReportingTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = Recognizer()
        game = Game()
        now = time.monotonic()
        for seq in (1, 2):
            self.before = self.recognizer.process(game.image(), (0, 0, 340, 400), C, seq, now)
        self.pending = PendingAction(
            action="drop",
            sent=now + 0.01,
            seq=2,
            before=self.before,
            expected_board=tuple(tuple([1] * 10) for _ in range(20)),
        )
        self.unchanged = replace(self.before, seq=3, captured=now + 0.02, prediction_match=False)
        self.telemetry = Telemetry()

    def test_unchanged_drop_frame_is_waiting_and_does_not_consume_error_slot(self):
        self.assertFalse(has_recognition_failure(self.unchanged, self.pending))
        record_landing_mismatch(self.telemetry, self.pending, self.unchanged)
        self.assertTrue(self.telemetry.events.empty())
        self.assertFalse(self.pending.mismatch_logged)

    def test_old_capture_is_not_a_failed_landing(self):
        old = replace(self.unchanged, captured=self.pending.sent - 0.01)
        self.assertFalse(has_recognition_failure(old, self.pending))
        record_landing_mismatch(self.telemetry, self.pending, old)
        self.assertTrue(self.telemetry.events.empty())

    def test_natural_fall_without_fixed_board_change_is_still_waiting(self):
        active = replace(self.before.active, state=(3, 1, 0), cells=cellset("T", (3, 1, 0)))
        falling = replace(self.unchanged, active=active)
        self.assertFalse(has_recognition_failure(falling, self.pending))

    def test_changed_board_or_piece_or_queue_still_reports_mismatch_once(self):
        board = copy.deepcopy(self.unchanged.fixed)
        board[-1][0] = 1
        for obs in (
            replace(self.unchanged, fixed=board),
            replace(self.unchanged, generation=self.before.generation + 1),
            replace(self.unchanged, active=replace(self.before.active, kind="I")),
            replace(self.unchanged, nexts=self.before.nexts[1:]),
        ):
            with self.subTest(observation=obs):
                pending = replace(self.pending)
                telemetry = Telemetry()
                self.assertTrue(has_recognition_failure(obs, pending))
                record_landing_mismatch(telemetry, pending, obs)
                record_landing_mismatch(telemetry, pending, obs)
                self.assertEqual(telemetry.events.qsize(), 1)
                self.assertEqual(telemetry.events.get_nowait()["event"], "landing_mismatch")

    def test_uncertain_frames_and_mismatch_without_drop_are_still_errors(self):
        self.assertTrue(has_recognition_failure(replace(self.unchanged, confidence=0), self.pending))
        self.assertTrue(has_recognition_failure(replace(self.unchanged, active=None), self.pending))
        self.assertTrue(has_recognition_failure(self.unchanged, None))
        self.assertTrue(has_recognition_failure(self.unchanged, replace(self.pending, action="hold")))

    def test_waiting_frame_does_not_confirm_input_or_send_another_key(self):
        backend = FakeBackend()
        controller = AutoController(KeyPulse(backend), copy.deepcopy(C))
        controller.wait = self.pending
        controller.telemetry = self.telemetry
        controller.verify(self.unchanged, self.unchanged.captured)
        self.assertIs(controller.wait, self.pending)
        self.assertEqual(controller.blocks, 0)
        self.assertFalse(backend.events)
        self.assertTrue(self.telemetry.events.empty())

    def test_candidate_components_are_calculated_once_for_uncertain_board(self):
        recognizer = Recognizer()
        board = [[0] * 10 for _ in range(20)]
        board[-1][:3] = [1, 1, 1]
        recognizer.process(scene(board), (0, 0, 340, 400), C, 1, time.monotonic())
        with patch("recognition.components", wraps=components) as calculate:
            obs = recognizer.process(
                scene([[0] * 10 for _ in range(20)], kind="I"), (0, 0, 340, 400), C, 2, time.monotonic()
            )
        self.assertFalse(obs.valid)
        self.assertEqual(calculate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
