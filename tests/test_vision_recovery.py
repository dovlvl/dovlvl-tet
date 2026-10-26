import time, copy, unittest

import bootstrap  # noqa: F401 -- configure source imports
from helpers import Game, FakeBackend, C, synthetic_tick, synthetic_emit
from controller import AutoController
from input_win import KeyPulse
from recognition import Recognizer
from runtime import Session
from unittest.mock import Mock


class VisionRecoveryTests(unittest.TestCase):
    def setup_game(self):
        game = Game()
        backend = FakeBackend()
        ctl = AutoController(KeyPulse(backend), copy.deepcopy(C))
        now = time.monotonic()
        ctl.start(99, now)
        recognizer = Recognizer()
        recognizer.process(game.image(), (0, 0, 340, 400), C, 1, now)
        obs = recognizer.process(game.image(), (0, 0, 340, 400), C, 2, now + 0.01)
        return game, backend, ctl, recognizer, obs, now

    def test_long_gap_releases_keys_then_replans_without_stale_action(self):
        game, backend, ctl, r, obs, t = self.setup_game()
        synthetic_emit(ctl, "left", obs, t + 0.02)
        self.assertTrue(ctl.pulse.pressed)
        epoch = ctl.vision_epoch
        synthetic_tick(ctl, None, t + 0.03)
        self.assertTrue(ctl.running)
        self.assertFalse(ctl.pulse.pressed)
        self.assertGreater(ctl.vision_epoch, epoch)
        synthetic_tick(ctl, None, t + 10)
        self.assertTrue(ctl.running)
        count = len(backend.events)
        obs = r.process(game.image(), (0, 0, 340, 400), C, 3, t + 10.01)
        synthetic_tick(ctl, obs, t + 10.01)
        self.assertTrue(ctl.running)
        self.assertIsNone(ctl.wait)
        self.assertIsNone(ctl.plan)
        self.assertEqual(len(backend.events), count)
        self.assertFalse(ctl.vision_paused)

    def test_gap_during_drop_does_not_trigger_transition_timeout(self):
        game, backend, ctl, r, obs, t = self.setup_game()
        synthetic_emit(ctl, "drop", obs, t + 0.02)
        synthetic_tick(ctl, None, t + 4)
        self.assertTrue(ctl.running)
        self.assertEqual(ctl.phase, "VISION_WAIT")
        ctl.stop("F8")
        synthetic_tick(ctl, None, t + 8)
        self.assertFalse(ctl.running)

    def test_focus_loss_still_stops(self):
        game, backend, ctl, r, obs, t = self.setup_game()
        synthetic_tick(ctl, None, t + 0.02)
        backend.focus = 123
        synthetic_tick(ctl, None, t + 0.03)
        self.assertFalse(ctl.running)

    def test_pre_gap_search_signature_is_invalidated(self):
        game, backend, ctl, r, obs, t = self.setup_game()
        session = Session(C, ctl)
        before = session.signature(obs, False)
        synthetic_tick(ctl, None, t + 0.02)
        self.assertNotEqual(before, session.signature(obs, False))

    def test_resize_preserves_resume_intent_but_f8_cancels_it(self):
        game, backend, ctl, r, obs, t = self.setup_game()
        c = copy.deepcopy(C)
        c.update(target={"hwnd": 99, "pid": 5}, client=[0, 0, 800, 600])
        windows = Mock()
        windows.info.return_value = {"pid": 5, "client": [0, 0, 900, 700]}
        session = Session(c, ctl, windows)
        session.monitor(None, t + 0.02)
        self.assertTrue(session.need_detection)
        self.assertTrue(session.auto_resume_requested)
        self.assertFalse(ctl.running)
        session.emergency()
        self.assertFalse(session.auto_resume_requested)
