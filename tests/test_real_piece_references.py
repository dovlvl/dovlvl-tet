import sys, time, copy, unittest
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from config import DEFAULT
from geometry import orientations
from recognition import sample_board, identify, Recognizer, PreviewCache
from piece_library import library, shape_rotations


class RealPieceReferenceTests(unittest.TestCase):
    def test_all_seven_original_screenshots_with_annotated_fixed_board(self):
        for kind, entry in library()["kinds"].items():
            with self.subTest(kind=kind):
                rgb = np.asarray(Image.open(ROOT / "data/pieces" / entry["source_file"]).convert("RGB"))
                x, y, r, b = entry["board"]
                grid, _, _, invalid = sample_board(rgb[y:b, x:r])
                self.assertFalse(invalid)
                cells = set(map(tuple, entry["cells"]))
                identified = identify(cells, grid)
                self.assertTrue(identified, kind)
                self.assertEqual(identified[0][0], kind)
                fixed = (grid > 0).astype(int)
                for xx, yy in cells:
                    fixed[yy, xx] = 0
                # This is an annotated still-image classification test, not
                # authorization to press keys from a stationary live shape.
                c = copy.deepcopy(DEFAULT)
                c.update(board=entry["board"], hold=None, next_slots=[None], allow_stationary_bootstrap=True)
                detector = Recognizer()
                now = time.monotonic()
                for seq in (1, 2):
                    obs = detector.process(
                        rgb, (0, 0, rgb.shape[1], rgb.shape[0]), c, seq, now, expected_fixed=fixed.tolist()
                    )
                self.assertTrue(obs.valid, (kind, obs.reason, obs.confidence))
                self.assertEqual(obs.active.kind, kind)
                self.assertEqual(obs.active.cells, frozenset(cells))

    def test_four_derived_rotations_with_real_photographed_cell_pixels(self):
        for kind, entry in library()["kinds"].items():
            im = Image.open(ROOT / "data/pieces" / entry["source_file"]).convert("RGB")
            x, y, right, bottom = entry["board"]
            cw = (right - x) / 10
            ch = (bottom - y) / 20
            a, b = entry["cells"][0]
            tile = im.crop(
                (
                    round(x + (a + 0.15) * cw),
                    round(y + (b + 0.15) * ch),
                    round(x + (a + 0.85) * cw),
                    round(y + (b + 0.85) * ch),
                )
            ).resize((18, 18))
            for rotation, shape in enumerate(orientations(kind)):
                with self.subTest(kind=kind, rotation=rotation):
                    image = Image.new("RGB", (200, 400), (10, 10, 10))
                    cells = {(3 + xx, 4 + yy) for xx, yy in shape}
                    for xx, yy in cells:
                        image.paste(tile, (xx * 20 + 1, yy * 20 + 1))
                    grid, *_ = sample_board(np.asarray(image))
                    self.assertEqual(identify(cells, grid)[0][0], kind)
                    candidates = shape_rotations(kind, cells)
                    self.assertIn(rotation, candidates)
                    self.assertEqual(len(candidates), 4 if kind == "O" else 2 if kind in "ISZ" else 1)

    def test_cropped_references_classify_as_preview_with_padding(self):
        for kind in library()["kinds"]:
            with self.subTest(kind=kind):
                crop = np.asarray(Image.open(ROOT / "data/pieces" / (kind + "_piece.png")).convert("RGB"))
                padded = np.pad(crop, ((10, 10), (10, 10), (0, 0)), constant_values=16)
                result = PreviewCache.classify(padded, time.monotonic(), 0.28, 0.28)
                self.assertTrue(result.valid, (kind, result))
                self.assertEqual(result.kind, kind)
