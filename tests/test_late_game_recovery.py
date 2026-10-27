import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import bootstrap  # noqa: F401 -- configure source imports
from controller import AutoController
from detection import refine_next_region
from geometry import cellset, settle, orientations
from helpers import C, FakeBackend, Game, synthetic_emit, synthetic_tick
from input_win import KeyPulse
from model import Active, PendingAction, Reading
from recognition import PreviewCache, Recognizer
from runtime import Session
from timing import timing_profile


class NextRecoveryTests(unittest.TestCase):
    def test_session_retries_after_menu_and_publishes_only_one_verified_next(self):
        image = np.asarray(Image.open(Path(__file__).parent / "fixtures/saved_regions.png").convert("RGB"))
        c = copy.deepcopy(C)
        c.update(
            board=[319, 150, 681, 852],
            hold=[85, 234, 254, 351],
            next_default_count=1,
            next_slots=[[747, 242, 923, 524]],
        )
        backend = FakeBackend()
        ctl = AutoController(KeyPulse(backend), c)
        ctl.start(99, 100)
        session = Session(c, ctl, windows=Mock())
        session.telemetry = Mock()
        session.stop_event = Mock()
        clock = [100]
        iteration = [-1]

        def stopped():
            iteration[0] += 1
            clock[0] = 100 + iteration[0] * 0.6
            return iteration[0] >= 2

        def frame():
            pixels = np.zeros_like(image) if iteration[0] == 0 else image
            return iteration[0], clock[0], pixels, (85, 150, 923, 852), 0, 0, copy.deepcopy(c)

        session.stop_event.is_set.side_effect = stopped
        session.frames = Mock()
        session.frames.get.side_effect = frame
        timer = SimpleNamespace(monotonic=lambda: clock[0], perf_counter=time.perf_counter, strftime=time.strftime)
        with (
            patch("runtime.time", timer),
            patch("runtime.refine_saved_regions", return_value={}),
            patch("runtime.fit_grid", return_value=None),
        ):
            session.vision_loop()
        self.assertEqual(session.revision, 1)
        self.assertEqual(len(session.c["next_slots"]), 1)
        self.assertLess(session.c["next_slots"][0][3], 524)
        self.assertEqual(session.observations.get().queue, ("O",))
        self.assertFalse(session.c["preview_verified"])
        self.assertFalse(ctl.c["preview_verified"])
        self.assertEqual(ctl.c["next_slots"], session.c["next_slots"])
        self.assertFalse(backend.events)

    def test_merged_preview_recovers_first_piece_without_board_detection(self):
        image = np.asarray(Image.open(Path(__file__).parent / "fixtures/saved_regions.png").convert("RGB"))
        c = copy.deepcopy(C)
        c.update(board=None, next_default_count=1, next_slots=[[747, 242, 923, 524]])
        fixed = refine_next_region(image, (85, 150), c)
        self.assertEqual(len(fixed["next_slots"]), 1)
        x, y, r, b = fixed["next_slots"][0]
        self.assertLess(b, 524)
        reading = PreviewCache().read("next0", image[y - 150 : b - 150, x - 85 : r - 85], 1, c["min_s"], c["min_v"])
        self.assertTrue(reading.valid)
        self.assertEqual(reading.kind, "O")

    def test_blank_clipped_and_multiple_requested_previews_are_not_guessed(self):
        image = np.zeros((300, 300, 3), dtype=np.uint8)
        for slots, count in [([[10, 10, 100, 250]], 1), ([[10, 10, 400, 250]], 1), ([[10, 10, 100, 250]], 3)]:
            with self.subTest(slots=slots, count=count):
                c = dict(C, next_slots=slots, next_default_count=count)
                self.assertEqual(refine_next_region(image, (0, 0), c), {})


class LateGameRecoveryTests(unittest.TestCase):
    def setup_game(self):
        game = Game()
        backend = FakeBackend()
        ctl = AutoController(KeyPulse(backend), copy.deepcopy(C))
        ctl.start(99, 100)
        recognizer = Recognizer()
        recognizer.process(game.image(), (0, 0, 340, 400), C, 1, 100)
        obs = recognizer.process(game.image(), (0, 0, 340, 400), C, 2, 100)
        return game, backend, ctl, obs

    def active(self, kind, state, now):
        return Active(kind, state, cellset(kind, state), 1, now)

    def test_transition_animations_do_not_inflate_movement_ack_bound(self):
        _, _, ctl, before = self.setup_game()
        ctl.wait = PendingAction("left", 100, before.seq, before, expected=(2, 0, 0))
        moved = replace(before, seq=3, captured=100.06, active=self.active("T", (2, 0, 0), 100.06))
        ctl.verify(moved, 100.06)
        self.assertAlmostEqual(ctl.ack_bound_ms, 60)
        before = replace(before, hold=Reading("J", 1, 100))
        ctl.wait = PendingAction("hold", 100, before.seq, before)
        swapped = replace(
            before, seq=4, captured=100.45, active=self.active("J", (3, 0, 0), 100.45), hold=Reading("T", 1, 100.45)
        )
        ctl.verify(swapped, 100.45)
        self.assertIsNotNone(ctl.wait)  # Still requires two observed transition confirmations.
        ctl.verify(replace(swapped, seq=5, captured=100.48), 100.48)
        self.assertIsNone(ctl.wait)
        self.assertAlmostEqual(ctl.ack_bound_ms, 60)
        self.assertAlmostEqual(ctl.hold_ack_bound_ms, 480)
        self.assertAlmostEqual(timing_profile(swapped, ctl.c, ack_ms=ctl.ack_bound_ms)["step_ms"], 70)

    def test_drop_animation_is_separate_and_unacknowledged_moves_do_not_calibrate(self):
        _, _, ctl, before = self.setup_game()
        ctl.wait = PendingAction("left", 100, before.seq, before, expected=(2, 0, 0))
        ctl.verify(replace(before, seq=3, captured=100.06), 100.06)
        self.assertEqual(ctl.ack_bound_ms, 0)
        board = settle(before.fixed, orientations("T")[0], 3, 18)[0]
        ctl.wait = PendingAction("drop", 100, before.seq, before, expected_board=tuple(map(tuple, board)))
        after = replace(
            before,
            seq=4,
            captured=100.4,
            fixed=board,
            active=self.active("I", (3, 0, 0), 100.4),
            nexts=[Reading(k, 1, 100.4) for k in ("L", "O", "S")],
        )
        ctl.verify(after, 100.4)
        ctl.verify(replace(after, seq=5, captured=100.45), 100.45)
        self.assertIsNone(ctl.wait)
        self.assertEqual(ctl.blocks, 1)
        self.assertEqual(ctl.ack_bound_ms, 0)
        self.assertAlmostEqual(ctl.drop_ack_bound_ms, 450)

    def test_hold_still_requires_its_own_observed_confirmation_window(self):
        _, backend, ctl, obs = self.setup_game()
        ctl.hold_ack_bound_ms = 500
        ctl.plan = dict(hold=True)
        synthetic_tick(ctl, replace(obs, seq=3, captured=100.01, fall_ms=200), 100.02)
        self.assertTrue(ctl.running)
        self.assertTrue(ctl.urgent_requested)
        self.assertIsNone(ctl.wait)
        self.assertFalse(backend.events)

    def test_unsafe_route_releases_keys_and_replans_without_sending_another_key(self):
        _, backend, ctl, obs = self.setup_game()
        synthetic_emit(ctl, "left", obs, 100.01)
        ctl.wait = None
        target = sorted(cellset("T", (3, 18, 0)))
        ctl.plan = dict(kind="T", hold=False, cells=target, path=("drop",), _generation=obs.generation)
        before = len([event for event in backend.events if event[1]])
        with patch("controller.route_feasible", return_value=(False, "NATURAL_LOCK_BEFORE_ACTION")):
            synthetic_tick(ctl, replace(obs, seq=3, captured=100.02), 100.02)
        self.assertTrue(ctl.running)
        self.assertFalse(ctl.pulse.pressed)
        self.assertIsNone(ctl.plan)
        self.assertTrue(ctl.urgent_requested)
        self.assertEqual(ctl.execution_retry_seq, 3)
        self.assertEqual(len([event for event in backend.events if event[1]]), before)

    def test_retries_remain_bounded_and_f8_cannot_be_undone(self):
        _, backend, ctl, obs = self.setup_game()
        for seq in range(3, 8):
            ctl.execution_window_failed("unsafe", replace(obs, seq=seq))
        self.assertFalse(ctl.running)
        self.assertTrue(ctl.pulse.abort.is_set())
        self.assertIn("연속 5회", ctl.reason)
        ctl.stop("F8")
        ctl.execution_window_failed("unsafe", obs)
        self.assertEqual(ctl.reason, "F8")
        self.assertFalse(ctl.urgent_requested)
        self.assertFalse(backend.events)

    def test_diagnostic_and_opener_modes_still_stop_on_unsafe_execution(self):
        for mode in ("diagnostic", "opener"):
            _, _, ctl, obs = self.setup_game()
            ctl.diagnostic = mode == "diagnostic"
            ctl.c["opener_enabled"] = mode == "opener"
            ctl.execution_window_failed("unsafe", obs)
            self.assertFalse(ctl.running)
            self.assertFalse(ctl.urgent_requested)

    def test_recovery_uses_new_observation_for_bounded_urgent_search(self):
        _, backend, ctl, obs = self.setup_game()
        session = Session(ctl.c, ctl)
        session.telemetry = Mock()
        ctl.execution_window_failed("unsafe", obs)
        packet = dict(result=None, search_ms=1)
        with patch("runtime.urgent_plan", return_value=packet) as urgent:
            session.dispatch_search(replace(obs, seq=3, captured=100.03), ctl, 100.04)
        urgent.assert_called_once()
        self.assertEqual(ctl.execution_retry_seq, 3)
        self.assertEqual(ctl.failures, 2)
        self.assertTrue(ctl.running)
        self.assertFalse(backend.events)

    def test_control_loop_does_not_retry_the_failed_frame(self):
        _, backend, ctl, obs = self.setup_game()
        session = Session(ctl.c, ctl)
        session.telemetry = Mock()
        session.stop_event = Mock()
        session.stop_event.is_set.side_effect = [False, False, True]
        session.observations = Mock()
        session.observations.get.side_effect = [obs, replace(obs, seq=3)]
        ctl.execution_window_failed("unsafe", obs)
        ctl.tick = Mock()
        with (
            patch("runtime.time.monotonic", return_value=100.05),
            patch("runtime.urgent_plan", return_value=dict(result=None, search_ms=1)) as urgent,
        ):
            session.control_loop()
        urgent.assert_called_once()
        self.assertEqual(ctl.execution_retry_seq, 3)
        self.assertEqual(ctl.failures, 2)
        self.assertFalse(backend.events)

    def test_fresh_safe_plan_can_resume_after_releasing_an_unsafe_route(self):
        _, backend, ctl, obs = self.setup_game()
        session = Session(ctl.c, ctl)
        session.telemetry = Mock()
        ctl.execution_window_failed("unsafe", obs)
        fresh = replace(obs, seq=3, captured=100.03)
        session.observations.put(fresh)
        result = dict(kind="T", hold=False, cells=sorted(cellset("T", (3, 18, 0))), path=("drop",))
        with patch("runtime.urgent_plan", return_value=dict(result=result, search_ms=1)):
            session.dispatch_search(fresh, ctl, 100.04)
        self.assertIsNotNone(ctl.plan)
        synthetic_tick(ctl, fresh, 100.05)
        self.assertEqual(ctl.last_input, "drop")
        self.assertEqual(ctl.wait.action, "drop")
        self.assertEqual(len([event for event in backend.events if event[1]]), 1)
        ctl.stop("F8")
        self.assertFalse(ctl.pulse.pressed)


if __name__ == "__main__":
    unittest.main()
