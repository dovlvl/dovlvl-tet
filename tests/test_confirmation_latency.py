import copy
import unittest
from unittest.mock import Mock, patch

import bootstrap  # noqa: F401 -- configure source imports
import numpy as np
from controller import AutoController
from detection import profile_fit
from helpers import C, FakeBackend, Game
from input_win import KeyPulse
from runtime import Session


def reference_profile(profile, count, ref_pad):
    """Original scalar bands retained solely for exact detection equivalence."""
    n = len(profile)
    best = None
    for pad in range(max(0, round(n * 0.005)), max(2, round(n * 0.05))):
        cell = (n - 2 * pad) / count
        if cell < 7:
            continue
        contrasts = []
        for i in range(1, count):
            p = round(pad + i * cell)
            c = round(pad + (i - 0.5) * cell)
            band = max(1, round(cell * 0.07))
            contrasts.append(
                float(
                    profile[max(0, p - band) : min(n, p + band + 1)].max()
                    - np.median(profile[max(0, c - band) : min(n, c + band + 1)])
                )
            )
        a = np.asarray(contrasts)
        fraction = float((a > 2).mean())
        score = fraction + 0.3 * min(1, float(np.maximum(a, 0).mean()) / 25) - abs(pad - ref_pad) * 0.001
        if best is None or score > best[0]:
            best = (score, pad, fraction)
    return best


class ConfirmationLatencyTests(unittest.TestCase):
    def test_batched_grid_bands_preserve_original_result_exactly(self):
        rng = np.random.default_rng(1981)
        for count in (10, 20):
            for n in (59, 70, 140, 200, 324, 647, 649, 1001):
                for dtype in (np.float32, np.float64):
                    for profile in (
                        rng.uniform(0, 255, n).astype(dtype),
                        np.zeros(n, dtype),
                        np.arange(n, dtype=dtype) % 11,
                    ):
                        with self.subTest(count=count, n=n, dtype=dtype):
                            self.assertEqual(
                                profile_fit(profile, count, n * 0.02), reference_profile(profile, count, n * 0.02)
                            )

    def replay(self, layout_ms, recognition_ms):
        c = copy.deepcopy(C)
        controller = AutoController(KeyPulse(FakeBackend()), c)
        session = Session(c, controller, windows=Mock())
        session.telemetry = Mock()
        clock = [100.01]
        rgb = Game().image()
        session.frames.put((1, 100, rgb, (0, 0, 340, 400), 0, session.revision, c))
        process = session.recognizer.process

        def layout(*_):
            clock[0] += layout_ms / 1000
            session.stop_event.set()  # Exactly one pass through the production loop.
            return (1, [0, 0, 200, 400])

        def recognize(*args, **kwargs):
            clock[0] += recognition_ms / 1000
            return process(*args, **kwargs)

        with (
            patch("runtime.Recognizer", return_value=session.recognizer),
            patch("runtime.time.monotonic", side_effect=lambda: clock[0]),
            patch("runtime.refine_saved_regions", return_value={}),
            patch("runtime.refine_next_region", return_value={}),
            patch("runtime.panel_occluded", return_value=False),
            patch("runtime.fit_grid", side_effect=layout),
            patch.object(session.recognizer, "process", side_effect=recognize) as reader,
        ):
            session.vision_loop()
        self.assertFalse(controller.pulse.pressed)
        return session, reader

    def test_slow_layout_discards_before_running_recognition(self):
        session, reader = self.replay(250, 0)
        reader.assert_not_called()
        self.assertIsNone(session.observations.get())
        session.telemetry.add.assert_any_call("discarded_after_layout", 1)

    def test_slow_recognition_does_not_publish_an_expired_confirmation_frame(self):
        session, reader = self.replay(1, 250)
        reader.assert_called_once()
        self.assertIsNone(session.observations.get())
        session.telemetry.add.assert_any_call("discarded_after_recognition", 1)

    def test_fresh_frame_still_reaches_the_existing_confirmation_pipeline(self):
        session, reader = self.replay(1, 1)
        reader.assert_called_once()
        self.assertIsNotNone(session.observations.get())
        self.assertEqual(session.observations.get().captured, 100)
        self.assertEqual(session.observations.get().seq, 1)
        self.assertFalse(session.controller.running)


if __name__ == "__main__":
    unittest.main()
