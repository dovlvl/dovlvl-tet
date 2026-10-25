import sys, unittest, time, copy
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import DEFAULT
from model import Reading
from ui_status import summary


class StatusTests(unittest.TestCase):
    def test_only_short_statuses_and_known_previews(self):
        t = time.monotonic()
        s = SimpleNamespace(error="", visibility_error="")
        o = SimpleNamespace(
            captured=t,
            valid=True,
            reason="",
            hold=Reading("T", 0.99, t),
            nexts=[Reading("L", 0.99, t), Reading(None, 0, t, False), Reading("O", 0.99, t)],
        )
        self.assertEqual(summary(DEFAULT, s, o, now=t), "보드: 정상   홀드: T   넥스트: L → ? → O")
        s.error = "vision_loop: full internal details"
        text = summary(DEFAULT, s, o, now=t)
        self.assertIn("보드: 오류", text)
        self.assertNotIn("vision_loop", text)
        self.assertEqual(summary(DEFAULT, s, o, now=t + 39), "보드: 오류   홀드: 불확실   넥스트: ?")

    def test_search_and_occlusion_are_distinct(self):
        s = SimpleNamespace(error="", visibility_error="covered by settings")
        self.assertIn("가려짐", summary(DEFAULT, s, None))
        s.visibility_error = ""
        self.assertIn("찾는 중", summary(DEFAULT, s, None, searching=True))
