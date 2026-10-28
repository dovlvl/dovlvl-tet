import time
import unittest

import bootstrap  # noqa: F401 -- configure source imports
import numpy as np
from PIL import Image, ImageDraw

from detection import fit_grid
from helpers import C, scene
from recognition import Recognizer


def interior_grid(width=324, height=643):
    image = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(image)
    for count, size, vertical in ((10, width, True), (20, height, False)):
        for i in range(1, count):
            at = round(i * size / count)
            draw.line((at, 0, at, height - 1) if vertical else (0, at, width - 1, at), fill="#202020")
    return np.asarray(image)


class RoundRestartTests(unittest.TestCase):
    def test_already_cropped_interior_keeps_saved_coordinates(self):
        result = fit_grid(interior_grid(), [0, 0, 324, 643])
        self.assertIsNotNone(result)
        self.assertEqual(result[1], [0, 0, 324, 643])

    def test_missing_or_shifted_grid_is_rejected(self):
        rgb = interior_grid()
        for image in (np.zeros_like(rgb), np.roll(rgb, (16, 16), axis=(0, 1))):
            with self.subTest(blank=not image.any()):
                self.assertIsNone(fit_grid(image, [0, 0, 324, 643]))

    def initial_round(self):
        board = [[0] * 10 for _ in range(20)]
        board[-1][:3] = [1, 1, 1]
        recognizer = Recognizer()
        recognizer.process(scene(board), (0, 0, 340, 400), C, 1, time.monotonic())
        return recognizer, board

    def read(self, recognizer, image, seq, **kwargs):
        return recognizer.process(image, (0, 0, 340, 400), C, seq, time.monotonic(), **kwargs)

    def test_empty_then_spawn_starts_new_round_with_stable_pixel_evidence(self):
        recognizer, _ = self.initial_round()
        generation = recognizer.generation
        blank = [[0] * 10 for _ in range(20)]
        self.read(recognizer, scene(blank, kind=None), 2)
        first = self.read(recognizer, scene(blank, kind="I"), 3)
        self.assertFalse(first.valid)
        final = self.read(recognizer, scene(blank, kind="I"), 4)
        self.assertTrue(final.valid, final.reason)
        self.assertEqual(final.active.kind, "I")
        self.assertEqual(final.fixed, blank)
        self.assertGreater(final.generation, generation)

    def test_missing_stack_without_empty_frame_stays_uncertain(self):
        recognizer, board = self.initial_round()
        for seq in (2, 3):
            obs = self.read(recognizer, scene([[0] * 10 for _ in range(20)], kind="I"), seq)
            self.assertFalse(obs.valid)
            self.assertEqual(recognizer.last_fixed, board)

    def test_empty_frame_cannot_override_pending_drop_prediction(self):
        recognizer, board = self.initial_round()
        blank = [[0] * 10 for _ in range(20)]
        self.read(recognizer, scene(blank, kind=None), 2)
        obs = self.read(recognizer, scene(blank, kind="I"), 3, expected_fixed=board)
        self.assertFalse(obs.valid)
        self.assertEqual(recognizer.last_fixed, board)

    def test_neutral_popup_is_not_an_empty_frame(self):
        recognizer, board = self.initial_round()
        blank = [[0] * 10 for _ in range(20)]
        popup = scene(blank, kind=None)
        popup[:400, :200] = 150
        self.read(recognizer, popup, 2)
        obs = self.read(recognizer, scene(blank, kind="I"), 3)
        self.assertFalse(obs.valid)
        self.assertEqual(recognizer.last_fixed, board)

    def test_low_piece_after_empty_frame_is_not_spawn_evidence(self):
        recognizer, board = self.initial_round()
        blank = [[0] * 10 for _ in range(20)]
        self.read(recognizer, scene(blank, kind=None), 2)
        obs = self.read(recognizer, scene(blank, kind="I", state=(3, 12, 0)), 3)
        self.assertFalse(obs.valid)
        self.assertEqual(recognizer.last_fixed, board)


if __name__ == "__main__":
    unittest.main()
