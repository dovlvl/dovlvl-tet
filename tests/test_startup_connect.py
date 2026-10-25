import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gui import App


class StartupConnectTests(unittest.TestCase):
    def app(self):
        app = object.__new__(App)
        app.closed = False
        app.auto_connect = True
        app.startup_autoplay = True
        app.find_background = False
        app.future = None
        app.session = None
        app.ctl = None
        app.root = Mock()
        app.begin_find = Mock()
        app.start_auto = Mock()
        app.status = Mock()
        app.c = {"target": {"hwnd": 42}, "frame_age_ms": 200}
        app.backend = Mock()
        app.backend.foreground.return_value = 42
        return app

    def test_retries_after_loading_screen_and_waits_for_play(self):
        app = self.app()
        for _ in range(5):
            app.find_opened_game()
        self.assertEqual(app.begin_find.call_count, 5)
        self.assertEqual(app.root.after.call_count, 5)
        app.root.deiconify.assert_not_called()
        app.start_auto.assert_not_called()

    def test_does_not_submit_duplicate_capture(self):
        app = self.app()
        app.future = Mock()
        app.find_opened_game()
        app.begin_find.assert_not_called()
        app.root.after.assert_called_once()

    def test_f8_cancels_scan_and_pending_autoplay(self):
        app = self.app()
        app.stop()
        app.find_opened_game()
        self.assertFalse(app.startup_autoplay)
        app.begin_find.assert_not_called()
        app.root.after.assert_not_called()

    def observation(self, app):
        o = SimpleNamespace(
            valid=True,
            captured=time.monotonic(),
            hold=SimpleNamespace(valid=True),
            hold_stable=3,
            next_stable=3,
            nexts=[SimpleNamespace(valid=True, kind="T")],
        )
        app.session = SimpleNamespace(error="", visibility_error="", observations=Mock())
        app.session.observations.get.return_value = o
        return o

    def test_starts_once_after_live_preview_recognition(self):
        app = self.app()
        self.observation(app)
        app.start_when_recognized()
        app.start_when_recognized()
        app.start_auto.assert_called_once()

    def test_waits_for_fresh_stable_visible_focused_game(self):
        for blocked in ("stale", "unstable", "unknown_next", "hidden", "focus"):
            with self.subTest(blocked=blocked):
                app = self.app()
                o = self.observation(app)
                if blocked == "stale":
                    o.captured -= 1
                elif blocked == "unstable":
                    o.hold_stable = 1
                elif blocked == "unknown_next":
                    o.nexts[0].valid = False
                elif blocked == "hidden":
                    app.session.visibility_error = "covered"
                else:
                    app.backend.foreground.return_value = 99
                app.start_when_recognized()
                app.start_auto.assert_not_called()
                self.assertTrue(app.startup_autoplay)
