import copy, time, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401 -- configure source imports
from helpers import C, Game, FakeBackend, scene, synthetic_tick, synthetic_emit
from recognition import Recognizer
from timing import MotionTracker
from controller import AutoController
from input_win import KeyPulse, VK
from runtime import Session
from helpers import Source


class TransitionGame(Game):
    def __init__(self):
        super().__init__()
        self.blank_until = 0
        self.blank_frames = 0
        self.clears = 0
        self.board = [[0] * 10 for _ in range(18)] + [[1] * 8 + [0, 0] for _ in range(2)]
        self.kind = "O"

    def input(self, vk):
        before = sum(map(sum, self.board))
        super().input(vk)
        if vk == VK["SPACE"]:
            self.clears += (before + 4 - sum(map(sum, self.board))) // 10
            self.blank_until = time.monotonic() + 0.12

    def image(self):
        if time.monotonic() < self.blank_until:
            self.blank_frames += 1
            return scene(self.board, kind=None, nexts=self.queue[:3])
        return super().image()


class DropTransitionTests(unittest.TestCase):
    def test_motion_reference_survives_later_popup_mutation(self):
        r = Recognizer()
        m = MotionTracker()
        g = Game()
        now = time.monotonic()
        previous = r.process(g.image(), (0, 0, 340, 400), C, 1, now)
        m.update(previous)
        self.assertIsNotNone(m.previous.active)
        previous.active = None
        previous.confidence = 0
        current = r.process(g.image(), (0, 0, 340, 400), C, 2, now + 0.02)
        m.update(current)  # Original timing.py:27 raised previous.active.state.
        self.assertIsNotNone(m.previous.active)
        current.active = None
        m.update(current)
        self.assertIsNone(m.previous)
        self.assertIsNone(m.movement_anchor)

    def test_drop_without_spawn_expires_pending_confirmation(self):
        r = Recognizer()
        g = Game()
        t = time.monotonic()
        ctl = AutoController(KeyPulse(FakeBackend()), copy.deepcopy(C))
        ctl.start(99, t)
        r.process(g.image(), (0, 0, 340, 400), C, 1, t)
        o = r.process(g.image(), (0, 0, 340, 400), C, 2, t + 0.01)
        synthetic_emit(ctl, "drop", o, t + 0.02)
        synthetic_tick(ctl, None, t + 0.03)
        self.assertIsNotNone(ctl.wait)
        synthetic_tick(ctl, None, t + 4)
        self.assertTrue(ctl.running)
        self.assertIsNone(ctl.wait)
        self.assertIsNone(ctl.plan)
        self.assertFalse(ctl.pulse.pressed)
        self.assertIn("전환 확인 시간 초과", ctl.last_ack)

    def test_worker_failure_persists_traceback_and_clears_live_metrics(self):
        ctl = AutoController(KeyPulse(FakeBackend()), copy.deepcopy(C))
        s = Session(C, ctl)
        with tempfile.TemporaryDirectory() as folder:
            s.telemetry.folder = Path(folder)
            s.beat("capture", time.monotonic())
            s.beat("vision", time.monotonic())

            def vision_loop():
                raise RuntimeError("injected vision failure")

            with self.assertLogs(level="ERROR"):
                s.guard(vision_loop)
            saved = Path(s.failure_path).read_text(encoding="utf-8")
            self.assertIn("Traceback (most recent call last)", saved)
            self.assertIn("injected vision failure", saved)
            self.assertEqual(s.health_snapshot()["vision"]["state"], "failed")
            self.assertIsNone(s.health_snapshot()["vision"]["current_ms"])
            text = s.performance_text(None)
            self.assertIn("작업 중단", text)
            self.assertIn("마지막 성공:", text)
            self.assertNotIn("FPS | 캡처", text)

    def test_stale_observation_hides_historical_fps_and_timings(self):
        ctl = AutoController(KeyPulse(FakeBackend()), copy.deepcopy(C))
        s = Session(C, ctl)
        g = Game()
        o = Recognizer().process(g.image(), (0, 0, 340, 400), C, 1, time.monotonic() - 39)
        o.fps = 59.7
        o.capture_ms = 12.34
        text = s.performance_text(o)
        self.assertIn("최신 프레임 대기", text)
        self.assertNotIn("59.7", text)
        self.assertNotIn("12.34", text)

    def test_capture_vision_and_continuous_auto_survive_empty_drop_frames(self):
        g = TransitionGame()
        Source.game = g
        c = copy.deepcopy(C)
        c.update(hold=None, next_slots=[None], search_budget_ms=100)
        backend = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(backend), c)
        s = Session(c, ctl, None, Source)
        empty = []
        track = s.motion.update

        def observe(o, controlled_action=None):
            if o.active is None and g.drops:
                empty.append((o.seq, o.captured))
            return track(o, controlled_action)

        try:
            with patch.object(s.motion, "update", side_effect=observe):
                s.start()
                ctl.start(99, time.monotonic())
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and not s.error and ctl.running and ctl.blocks < 4:
                    time.sleep(0.01)
                self.assertFalse(s.error, s.failure_traceback or s.error)
                self.assertTrue(empty, "No active=None transition reached vision")
                self.assertGreater(g.blank_frames, 0)
                self.assertGreater(g.clears, 0)
                self.assertGreaterEqual(ctl.blocks, 4, ctl.reason)
                self.assertTrue(ctl.running)
                self.assertLess(time.monotonic() - s.observations.get().captured, 0.5)
                self.assertTrue(all(t.is_alive() for t in s.threads))
                self.assertGreater(s.health["capture"]["count"], len(empty))
                print(
                    f"DROP_TRANSITION_PIPELINE drops={g.drops} confirmed={ctl.blocks} empty_observations={len(empty)} clears={g.clears}"
                )
        finally:
            s.stop()
