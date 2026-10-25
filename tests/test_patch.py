import unittest, time, copy, threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from unittest.mock import patch
from helpers import C, Game, FakeBackend
from input_win import KeyPulse
from controller import AutoController
from recognition import Recognizer
from planner import plan
from runtime import Session


class PatchTests(unittest.TestCase):
    def test_one_block_stops_after_confirmed_spawn(self):
        c = copy.deepcopy(C)
        c["auto_mode"] = "one"
        g = Game()
        r = Recognizer()
        b = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(b), c)
        base = time.monotonic()
        ctl.start(99, base)
        for i in range(500):
            now = base + i * 0.03
            o = r.process(g.image(), (0, 0, 340, 400), c, i, now)
            with patch("controller.time.monotonic", return_value=now):
                if ctl.running and o.valid and not ctl.plan and not ctl.wait:
                    p = plan(o.fixed, o.active.kind, o.active.state, None, [], False)
                    p["key"] = (o.board_key, o.active.kind, False)
                    ctl.accept_plan(p, o)
                ctl.tick(o, now)
            if not ctl.running:
                break
        self.assertEqual(ctl.blocks, 1)
        self.assertEqual(g.drops, 1)
        self.assertFalse(ctl.pulse.pressed)

    def test_stale_frame_cannot_emit(self):
        c = copy.deepcopy(C)
        g = Game()
        r = Recognizer()
        b = FakeBackend()
        ctl = AutoController(KeyPulse(b), c)
        now = time.monotonic()
        ctl.start(99, now)
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), c, i, now - 1)
        ctl.emit("left", o, now)
        self.assertFalse(b.events)

    def test_emergency_invalidates_pending_start(self):
        ctl = AutoController(KeyPulse(FakeBackend()), C)
        s = Session(C, ctl)
        s.request_toggle(99)
        s.emergency()
        generation, _ = s.commands.get_nowait()
        self.assertNotEqual(generation, s.generation)
        self.assertTrue(ctl.pulse.abort.is_set())

    def test_watchdog_stops_capture_stall(self):
        ctl = AutoController(KeyPulse(FakeBackend()), C)
        s = Session(C, ctl)
        ctl.start(99, time.monotonic())
        s.health["capture"]["last"] -= 3
        t = threading.Thread(target=s.watchdog_loop)
        t.start()
        try:
            deadline = time.monotonic() + 1
            while ctl.running and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(ctl.running)
            self.assertIn("capture", ctl.reason)
        finally:
            s.stop_event.set()
            t.join(1)

    def test_diagnostic_without_board_can_be_cancelled_during_countdown(self):
        from config import DEFAULT

        c = copy.deepcopy(DEFAULT)
        c["input_countdown"] = 1
        b = FakeBackend()
        ctl = AutoController(KeyPulse(b), c)
        s = Session(c, ctl)
        try:
            s.start(diagnostic_only=True)
            s.schedule_diagnostic("left", 99, time.monotonic())
            s.emergency()
            time.sleep(1.1)
            self.assertFalse(b.events)
            self.assertFalse(ctl.running)
            self.assertFalse(s.error)
        finally:
            s.stop()

    def test_space_scan_down_up_has_no_extended_flag(self):
        from input_win import keyboard_event, VK

        down = keyboard_event(VK["SPACE"], True, 0x39)
        up = keyboard_event(VK["SPACE"], False, 0x39)
        self.assertEqual(down.ki.wScan, 0x39)
        self.assertEqual(down.ki.dwFlags, 8)
        self.assertEqual(up.ki.dwFlags, 10)
