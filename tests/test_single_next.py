import copy, time, unittest
from pathlib import Path
import numpy as np
from PIL import Image

import bootstrap  # noqa: F401 -- configure source imports
from config import DEFAULT
from detection import detect, refine_saved_regions
from recognition import Recognizer


class SingleNextTests(unittest.TestCase):
    def image(self):
        return np.asarray(Image.open(Path(__file__).parent / "fixtures/saved_regions.png").convert("RGB"))

    def test_one_requested_preview_stays_one_with_three_visible(self):
        for count in (1, 2, 3):
            z = detect(self.image(), default_count=count)
            self.assertEqual(len(z["next_slots"]), count)
            c = copy.deepcopy(DEFAULT)
            c.update({k: z[k] for k in ("board", "hold", "next_slots")})
            o = Recognizer().process(self.image(), (0, 0, 838, 702), c, 1, time.monotonic())
            self.assertEqual(o.queue, tuple("OTI"[:count]))

    def test_saved_border_and_merged_next_recovered_from_failure_capture(self):
        c = copy.deepcopy(DEFAULT)
        c.update(board=[319, 150, 681, 852], hold=[85, 234, 254, 351], next_slots=[[747, 242, 923, 524]])
        fixed = refine_saved_regions(self.image(), (85, 150), c)
        self.assertTrue(fixed)
        c.update(fixed)
        r = Recognizer()
        previous = np.asarray(Image.open(Path(__file__).parent / "fixtures/saved_regions_previous.png").convert("RGB"))
        for seq, im in enumerate((previous, self.image(), self.image()), 1):
            o = r.process(im, (85, 150, 923, 852), c, seq, time.monotonic())
        self.assertTrue(o.valid, (o.reason, o.confidence))
        self.assertEqual(o.active.kind, "L")
        self.assertEqual(o.queue, ("O",))
        self.assertTrue(o.hold.valid)
        self.assertIsNone(o.hold.kind)

    def test_default_uses_one_next(self):
        self.assertEqual(DEFAULT["next_default_count"], 1)
        self.assertEqual(len(DEFAULT["next_slots"]), 1)
