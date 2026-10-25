import sys, time, copy, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from PIL import Image, ImageDraw
from detection import detect, panel_occluded
from config import DEFAULT, validate
from recognition import Recognizer, PALETTE
from geometry import orientations
from windows import shifted, same_size
from helpers import Game, FakeBackend, C, synthetic_tick, synthetic_emit
from controller import AutoController
from input_win import KeyPulse
from model import Reading


class DetectorTests(unittest.TestCase):
    def image(self, colors=True):
        im = Image.new("RGB", (800, 500), "#eeeeee")
        d = ImageDraw.Draw(im)
        d.rectangle((294, 24, 506, 436), fill="#111111")
        d.rectangle((300, 30, 500, 430), fill="black")
        for x in range(300, 501, 20):
            d.line((x, 30, x, 430), fill="#202020")
        for y in range(30, 431, 20):
            d.line((300, y, 500, y), fill="#202020")
        d.rectangle((160, 75, 260, 155), fill="#222222")
        d.rectangle((550, 75, 650, 345), fill="#222222")
        d.rectangle((150, 310, 260, 355), fill="#222222")
        # An ad with roughly board aspect ratio but without a cell grid.
        d.rectangle((10, 20, 140, 280), fill="#111111")
        if colors:
            for kind, top in zip("LTO", (85, 175, 265)):
                for x, y in orientations(kind)[0]:
                    d.rectangle((560 + x * 18, top + y * 18, 576 + x * 18, top + y * 18 + 16), fill=PALETTE[kind])
        return np.asarray(im)

    def test_grid_and_hold_next_independent(self):
        z = detect(self.image(), default_count=3)
        self.assertIsNotNone(z["board"])
        self.assertIsNotNone(z["hold"])
        self.assertEqual(len(z["next_slots"]), 3)
        self.assertLess(abs(z["board"][0] - 300), 4)
        self.assertGreater(z["next_slots"][0][0], 500)
        self.assertLess(z["hold"][3], 200)

    def test_empty_board_hold_and_next_geometry(self):
        z = detect(self.image(False), default_count=3)
        self.assertIsNotNone(z["board"])
        self.assertIsNotNone(z["hold"])
        self.assertEqual(len(z["next_slots"]), 3)
        self.assertTrue(z["next_count_inferred"])

    def test_ad_without_grid_rejected(self):
        im = np.full((500, 800, 3), 238, np.uint8)
        im[20:420, 300:500] = 16
        self.assertIsNone(detect(im)["board"])

    def test_menu_hidden_grid_keeps_independently_anchored_regions(self):
        im = self.image(False).copy()
        im[24:437, 294:507] = 17
        z = detect(im)
        self.assertIsNotNone(z["board"])
        self.assertTrue(z["geometry_only"])
        self.assertIsNotNone(z["hold"])
        self.assertEqual(len(z["next_slots"]), 1)
        c = copy.deepcopy(DEFAULT)
        c.update({k: z[k] for k in ("board", "hold", "next_slots")})
        o = Recognizer().process(im, (0, 0, 800, 500), c, 1, time.monotonic())
        self.assertFalse(o.valid)

    def test_negative_monitor_coordinates(self):
        z = detect(self.image(), (-1920, -120))
        self.assertLess(z["board"][0], 0)
        self.assertLess(z["board"][1], 0)
        c = copy.deepcopy(DEFAULT)
        c.update({k: z[k] for k in ("board", "hold", "next_slots")})
        validate(c, True)

    def test_popup_panel_rejected(self):
        board = np.zeros((400, 200, 3), np.uint8)
        board[90:300, 20:180] = 55
        self.assertTrue(panel_occluded(board))
        self.assertFalse(panel_occluded(np.zeros_like(board)))

    def test_partial_detection_not_full_success(self):
        im = self.image().copy()
        im[50:350, 520:700] = 238
        z = detect(im)
        self.assertIsNotNone(z["board"])
        self.assertFalse(z["next_slots"])
        self.assertIn("next", z["reasons"])

    def test_same_frame_auto_detection_and_recognition(self):
        im = self.image()
        z = detect(im, default_count=3)
        c = copy.deepcopy(DEFAULT)
        c.update({k: z[k] for k in ("board", "hold", "next_slots")})
        o = Recognizer().process(im, (0, 0, 800, 500), c, 1, time.monotonic())
        self.assertTrue(o.hold.valid)
        self.assertIsNone(o.hold.kind)
        self.assertEqual(o.queue, ("L", "T", "O"))


class DesktopStateTests(unittest.TestCase):
    def test_release_failure_stops_and_reports_error(self):
        from runtime import Session

        class Broken(FakeBackend):
            def key(self, vk, down):
                super().key(vk, down)
                if not down:
                    raise OSError("injected keyup failure")

        b = Broken()
        ctl = AutoController(KeyPulse(b), C)
        ctl.start(99, time.monotonic())
        ctl.pulse.press("LEFT", time.monotonic(), 35, 35)
        s = Session(C, ctl)
        with self.assertLogs(level="ERROR"):
            s.emergency()
        self.assertFalse(ctl.running)
        self.assertTrue(ctl.pulse.abort.is_set())
        self.assertIn("KEY_RELEASE_ERROR", ctl.reason)

    def test_window_move_translation(self):
        c = copy.deepcopy(C)
        z = shifted(c, [0, 0, 1000, 800], [-1920, 50, -920, 850])
        self.assertEqual(z["board"], [-1920, 50, -1720, 450])
        self.assertTrue(same_size([0, 0, 1000, 800], [-1920, 50, -920, 850]))
        self.assertFalse(same_size([0, 0, 1000, 800], [0, 0, 900, 800]))

    def test_board_only_config_valid(self):
        c = copy.deepcopy(DEFAULT)
        c["board"] = [0, 0, 200, 400]
        validate(c, True)

    def test_optional_unknowns_allow_current_only_auto(self):
        g = Game()
        r = Recognizer()
        t = time.monotonic()
        b = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(b), C)
        ctl.start(99, t)
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.01)
        o.hold = Reading(None, 0, t, False)
        o.nexts = [Reading(None, 0, t, False)]
        self.assertFalse(ctl.hold_clear(o))
        from planner import plan

        packet = plan(o.fixed, o.active.kind, o.active.state, None, [], False)
        packet["key"] = (o.board_key, o.active.kind, False)
        ctl.accept_plan(packet, o)
        from unittest.mock import patch

        with patch("controller.time.monotonic", return_value=t + 0.03):
            synthetic_tick(ctl, o, t + 0.03)
        self.assertTrue(ctl.running, ctl.reason)
        self.assertTrue(b.events)

    def test_diagnostic_left_waits_for_screen_ack(self):
        g = Game()
        r = Recognizer()
        t = time.monotonic()
        b = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(b), C)
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.01)
        ctl.begin_diagnostic(99, o, "left", t + 0.02)
        self.assertTrue(ctl.running)
        for i in range(2, 5):
            now = t + i * 0.03
            o = r.process(g.image(), (0, 0, 340, 400), C, i, now)
            synthetic_tick(ctl, o, now)
        self.assertFalse(ctl.running)
        self.assertIn("진단 성공", ctl.reason)

    def test_diagnostic_api_success_without_change_fails(self):
        g = Game()
        r = Recognizer()
        t = time.monotonic()
        b = FakeBackend()
        ctl = AutoController(KeyPulse(b), C)
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.01)
        ctl.begin_diagnostic(99, o, "left", t + 0.02)
        o = r.process(g.image(), (0, 0, 340, 400), C, 3, t + 0.5)
        synthetic_tick(ctl, o, t + 0.5)
        self.assertFalse(ctl.running)
        self.assertIn("INPUT_CONFIRMATION_ERROR", ctl.reason)

    def test_uncertain_board_diagnostic_never_sends(self):
        g = Game()
        r = Recognizer()
        t = time.monotonic()
        b = FakeBackend()
        ctl = AutoController(KeyPulse(b), C)
        o = r.process(g.image(), (0, 0, 340, 400), C, 1, t)
        ctl.begin_diagnostic(99, o, "left", t)
        self.assertTrue(b.events)
        synthetic_tick(ctl, None, t + 1)
        self.assertFalse(ctl.running)
        self.assertIn("확인 불가", ctl.last_ack)

    def test_six_diagnostic_actions_confirmed_by_simulated_frames(self):
        for action in ("left", "right", "up", "z", "hold", "drop"):
            g = Game()
            g.hold = "I"
            r = Recognizer()
            t = time.monotonic()
            b = FakeBackend(g.input)
            ctl = AutoController(KeyPulse(b), C)
            for i in range(2):
                o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.01)
            ctl.begin_diagnostic(99, o, action, t + 0.02)
            for i in range(2, 7):
                now = t + i * 0.03
                o = r.process(g.image(), (0, 0, 340, 400), C, i, now)
                synthetic_tick(ctl, o, now)
            self.assertFalse(ctl.running, action)
            self.assertIn("진단 성공", ctl.reason, action)

    def test_line_clear_then_new_spawn(self):
        g = Game()
        g.board = [[0] * 10 for _ in range(18)] + [[1] * 8 + [0, 0] for _ in range(2)]
        g.kind = "O"
        g.state = (3, 0, 0)
        r = Recognizer()
        t = time.monotonic()
        b = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(b), C)
        ctl.start(99, t)
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.01)
        g.state = (7, 0, 0)
        o = r.process(g.image(), (0, 0, 340, 400), C, 2, t + 0.015)
        synthetic_emit(ctl, "drop", o, t + 0.02)
        for i in range(3, 7):
            now = t + i * 0.03
            o = r.process(g.image(), (0, 0, 340, 400), C, i, now)
            synthetic_tick(ctl, o, now)
        self.assertFalse(any(map(any, g.board)))
        self.assertIsNone(ctl.wait)
        self.assertTrue(ctl.running)


if __name__ == "__main__":
    unittest.main()
