import copy, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from strategy import auto_plan, builtin_book, position_score
from config import DEFAULT, load
from tempfile import TemporaryDirectory


class AdaptiveAutoTests(unittest.TestCase):
    def test_tki_sequence_and_transition_to_regular_play(self):
        steps = builtin_book()["variants"][0]["steps"]
        for index, step in enumerate(steps):
            board = [list(row) for row in step["expected_before"]]
            queue = [s["kind"] for s in steps[index + 1 :]] + list("ILOSZJT")
            p = auto_plan(board, step["kind"], (3, 0, 0), None, queue, False, previews=True, basic_verified=True)
            self.assertTrue(p["result"]["strategy"].startswith("TKI"), (index, p))
            self.assertEqual(set(map(tuple, p["result"]["cells"])), set(map(tuple, step["cells"])))
        board = [list(row) for row in steps[-1]["expected_after"]]
        result = auto_plan(board, "I", (3, 0, 0), None, ["L", "O"], False, opening=False)["result"]
        self.assertIsNotNone(result)
        self.assertNotIn("TKI", result["strategy"])

    def test_wrong_queue_falls_back_instead_of_stopping(self):
        b = [[0] * 10 for _ in range(20)]
        p = auto_plan(b, "O", (3, 0, 0), None, ["S", "Z"], False, previews=True, basic_verified=True)
        self.assertIsNotNone(p["result"])
        self.assertNotIn("TKI", p["result"]["strategy"])

    def test_preview_gate_prevents_unverified_opener(self):
        p = auto_plan([[0] * 10 for _ in range(20)], "I", (3, 0, 0), None, list("LJOSZT"), False)
        self.assertNotIn("TKI", p["result"]["strategy"])

    def test_tetris_and_perfect_clear_take_priority(self):
        b = [[0] * 10 for _ in range(16)] + [[1] * 9 + [0] for _ in range(4)]
        a = auto_plan(b, "O", (3, 0, 0), "I", ["L", "T"], True)["result"]
        self.assertTrue(a["hold"])
        self.assertEqual(a["lines"], 4)
        self.assertEqual(a["strategy"], "Perfect Clear")

    def test_buried_holes_cost_more_than_open_well(self):
        clean = [[0] * 10 for _ in range(18)] + [[1] * 9 + [0] for _ in range(2)]
        dirty = copy.deepcopy(clean)
        dirty[19][4] = 0
        dirty[19][9] = 1
        self.assertGreater(position_score(clean, 0), position_score(dirty, 0))

    def test_existing_install_migrates_to_continuous_auto(self):
        import json

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(dict(DEFAULT, auto_mode="one")))
            c = load(path)
            self.assertEqual(c["auto_mode"], "continuous")
            self.assertEqual(c["keys"]["hold"], "C")

    def test_auto_runtime_finishes_opener_and_keeps_playing(self):
        import time
        from helpers import C, Game, FakeBackend
        from test_session import Source
        from input_win import KeyPulse
        from controller import AutoController
        from runtime import Session

        steps = builtin_book()["variants"][0]["steps"]
        c = copy.deepcopy(C)
        c.update(opener_enabled=False, basic_auto_verified=True, preview_verified=True)
        game = Game()
        game.kind = steps[0]["kind"]
        game.queue = [s["kind"] for s in steps[1:]] + list("ILOSZJT") * 10
        Source.game = game
        ctl = AutoController(KeyPulse(FakeBackend(game.input)), c)
        session = Session(c, ctl, None, Source)
        try:
            session.start()
            session.request_toggle(99)
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline and not session.error and ctl.blocks < 8:
                if not ctl.running and ctl.blocks:
                    break
                time.sleep(0.02)
            self.assertFalse(session.error, session.error)
            self.assertGreaterEqual(ctl.blocks, 8, ctl.reason)
            self.assertTrue(ctl.running, ctl.reason)
            self.assertNotIn("TKI", session.last_packet["result"]["strategy"])
        finally:
            session.stop()
