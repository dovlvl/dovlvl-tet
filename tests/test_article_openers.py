import copy
import json
from pathlib import Path
import unittest
import time

import bootstrap  # noqa: F401 -- configure source imports
from geometry import advance, cellset, hard_drop, orientations, settle
from openers import board_key, book_for_save, compile_book, load_book, opener_plan
from controller import AutoController
from input_win import KeyPulse
from recognition import Recognizer
from helpers import C, FakeBackend, Game, synthetic_tick

ROOT = Path(__file__).resolve().parents[1]


class ArticleOpenerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.books = [load_book(ROOT / "data/openers" / (name + ".json")) for name in ("Stickspin", "SDPC")]

    def plan(self, book, board, index, kind, held=None, queue=(), used=False, chosen=None):
        return opener_plan(book, index, chosen, board, kind, (3, 0, 0), held, list(queue), used, True, True)

    def test_every_compiled_edge_replays_and_has_a_completion(self):
        for book in self.books:
            for variant in book["variants"]:
                levels = variant["compiled_levels"]
                for index, level in enumerate(levels):
                    for node in level:
                        for step in node["choices"]:
                            with self.subTest(
                                book=book["name"], variant=variant["name"], index=index, kind=step["kind"]
                            ):
                                board = [list(row) for row in node["board"]]
                                result = self.plan(book, board, index, step["kind"], chosen=variant["name"])["result"]
                                self.assertIsNotNone(result)
                                state = (3, 0, 0)
                                for action in result["path"]:
                                    if action == "drop":
                                        x, y, r = state
                                        state = (x, hard_drop(board, orientations(step["kind"])[r], x, y), r)
                                    else:
                                        state = advance(board, step["kind"], state, action)
                                        self.assertIsNotNone(state)
                                self.assertEqual(cellset(step["kind"], state), frozenset(map(tuple, step["cells"])))
                                x, y, r = state
                                after, lines = settle(board, orientations(step["kind"])[r], x, y)
                                self.assertEqual(board_key(after), step["expected_after"])
                                self.assertEqual(lines, step["lines"])
                                if index % 7 == 6:
                                    self.assertEqual((result["spin"], lines), ("full", 1 if index == 6 else 2))
                                if index < 13:
                                    self.assertIn(board_key(after), [n["board"] for n in levels[index + 1]])

    def test_first_bag_matches_source_second_bag_base(self):
        expected = [
            ["........#.", "#......###", "###....###", "###...####"],
            [".#........", "##.......#", "####...###", "####...###"],
        ]
        for book, rows in zip(self.books, expected):
            before_second = book["variants"][0]["compiled_levels"][7][0]["board"]
            self.assertEqual(["".join("#" if v else "." for v in row) for row in before_second[-4:]], rows)

    def test_fourteen_placements_complete_for_both_mirrors(self):
        for book in self.books:
            for variant in book["variants"]:
                board = [[0] * 10 for _ in range(20)]
                lines = 0
                for index, level in enumerate(variant["compiled_levels"]):
                    node = next(n for n in level if n["board"] == board_key(board))
                    # Select the last available choice to exercise a different legal order.
                    kind = node["choices"][-1]["kind"]
                    result = self.plan(book, board, index, kind, chosen=variant["name"])["result"]
                    self.assertIsNotNone(result)
                    board = result["board"]
                    lines += result["lines"]
                self.assertEqual(lines, 3)
                self.assertIn("OPENER_COMPLETE", self.plan(book, board, 14, "I", chosen=variant["name"])["reason"])

    def test_unseen_queue_wrong_board_and_repeated_hold_stop(self):
        for book in self.books:
            variant = book["variants"][0]
            board = [[0] * 10 for _ in range(20)]
            desired = variant["compiled_levels"][0][0]["choices"][0]["kind"]
            # T is deliberately last in each bag; an unseen piece never authorizes a swap.
            self.assertIsNone(self.plan(book, board, 0, "T", queue=["?", desired])["result"])
            self.assertTrue(self.plan(book, board, 0, "T", held=desired)["result"]["hold"])
            self.assertIsNone(self.plan(book, board, 0, "T", held=desired, used=True)["result"])
            board[0][0] = 1
            self.assertIsNone(self.plan(book, board, 0, desired)["result"])

    def test_save_reload_and_invalid_targets(self):
        for book in self.books:
            saved = book_for_save(book)
            self.assertLess(len(json.dumps(saved).encode()), 2_000_000)
            self.assertNotIn("compiled_levels", saved["variants"][0])
            self.assertEqual(compile_book(saved), book)
            saved["variants"][0]["compiled_levels"] = [[{"board": [], "choices": []}]]
            saved["variants"][0]["step_count"] = 1
            self.assertEqual(compile_book(saved), book)
            broken = copy.deepcopy(saved)
            broken["variants"][0]["stages"][0]["targets"][0]["cells"] = [[-1, 19]] * 4
            with self.assertRaises(ValueError):
                compile_book(broken)

    def test_controller_confirms_fourteen_simulated_blocks_with_one_next(self):
        for book in self.books:
            variant = book["variants"][0]
            board = [[0] * 10 for _ in range(20)]
            order = []
            for level in variant["compiled_levels"]:
                step = next(n for n in level if n["board"] == board_key(board))["choices"][0]
                order.append(step["kind"])
                board = [list(row) for row in step["expected_after"]]
            game = Game()
            game.kind = order[0]
            game.queue = order[1:] + list("IJLOSTZ") * 10
            config = copy.deepcopy(C)
            config["next_slots"] = config["next_slots"][:1]
            controller = AutoController(KeyPulse(FakeBackend(game.input)), config)
            recognizer = Recognizer()
            base = time.monotonic()
            controller.start(99, base)
            for i in range(5000):
                now = base + i * 0.025
                obs = recognizer.process(game.image(), (0, 0, 340, 400), config, i, now)
                if controller.running and obs.valid and not controller.plan and not controller.wait:
                    packet = opener_plan(
                        book,
                        controller.blocks,
                        controller.opener_variant,
                        obs.fixed,
                        obs.active.kind,
                        obs.active.state,
                        obs.hold.kind,
                        list(obs.queue),
                        controller.hold_used,
                        True,
                        True,
                    )
                    packet["key"] = (obs.board_key, obs.active.kind, controller.hold_used)
                    controller.accept_plan(packet, obs)
                synthetic_tick(controller, obs, now)
                if not controller.running:
                    break
            self.assertEqual(controller.blocks, 14, controller.reason)
            self.assertIn("OPENER_COMPLETE", controller.reason)
            self.assertFalse(controller.pulse.pressed)


if __name__ == "__main__":
    unittest.main()
