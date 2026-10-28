import copy
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import bootstrap  # noqa: F401 -- configure source imports
import numpy as np
from PIL import Image

from controller import AutoController
from detection import panel_occluded
from helpers import C, FakeBackend, Game, synthetic_emit, synthetic_tick
from input_win import KeyPulse
from recognition import Recognizer
from runtime import Session


FIXTURES = Path(__file__).parent / "fixtures/drop_trail_popup"


def grid_with_trail():
    board = np.zeros((400, 200, 3), np.uint8)
    board[::20, :] = 40
    board[:, ::20] = 40
    board[40:360, 20:100] = 65
    return board


class DropTrailPopupTests(unittest.TestCase):
    def test_thin_grid_does_not_join_narrow_drop_trail_into_a_panel(self):
        self.assertFalse(panel_occluded(grid_with_trail()))

    def test_saved_drop_effects_are_not_popups_at_multiple_scales(self):
        for name in ("trail_left", "trail_stack", "trail_center"):
            with Image.open(FIXTURES / f"{name}.png") as image:
                for scale in (0.5, 1, 1.75, 2):
                    with self.subTest(name=name, scale=scale):
                        size = (round(image.width * scale), round(image.height * scale))
                        board = np.asarray(image.resize(size, Image.Resampling.NEAREST).convert("RGB"))
                        self.assertFalse(panel_occluded(board))

    def test_real_menu_and_game_over_still_block_the_board(self):
        for name in ("menu", "game_over"):
            with Image.open(FIXTURES / f"{name}.png") as image:
                for scale in (0.5, 1, 1.75, 2):
                    with self.subTest(name=name, scale=scale):
                        size = (round(image.width * scale), round(image.height * scale))
                        board = np.asarray(image.resize(size, Image.Resampling.NEAREST).convert("RGB"))
                        self.assertTrue(panel_occluded(board))

    def test_panel_over_a_trail_is_still_an_occlusion(self):
        board = grid_with_trail()
        board[90:300, 20:180] = 55
        # Small text-shaped holes cannot turn a broad panel into a drop trail.
        board[120:130, 50:90] = 230
        self.assertTrue(panel_occluded(board))

    def test_popup_invalidates_an_otherwise_valid_observation_and_releases_keys(self):
        config = copy.deepcopy(C)
        game = Game()
        now = time.monotonic()
        reader = Recognizer()
        for seq in (1, 2):
            before = reader.process(game.image(), (0, 0, 340, 400), config, seq, now)
        backend = FakeBackend()
        controller = AutoController(KeyPulse(backend), config)
        controller.start(99, now)
        synthetic_emit(controller, "left", before, now + 0.01)
        self.assertTrue(controller.pulse.pressed)
        sent_count = sum(down for _, down in backend.events)
        popup = game.image()
        popup[90:300, 20:180] = 55
        session = Session(config, controller)
        session.frames.put((1, now + 0.02, popup, (0, 0, 340, 400), 0, 0, config))
        session.stop_event = Mock()
        session.stop_event.is_set.side_effect = [False, True]
        reader.process = Mock(return_value=replace(before, seq=3, captured=now + 0.02))
        with patch("runtime.Recognizer", return_value=reader), patch("runtime.time.monotonic", return_value=now + 0.03):
            session.vision_loop()
        observed = session.observations.get()
        self.assertIsNone(observed.active)
        self.assertFalse(observed.valid)
        self.assertEqual(observed.fixed_confidence, 0)
        synthetic_tick(controller, observed, now + 0.04)
        self.assertFalse(controller.pulse.pressed)
        self.assertEqual(sum(down for _, down in backend.events), sent_count)


if __name__ == "__main__":
    unittest.main()
