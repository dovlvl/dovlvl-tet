"""Import visually labelled game screenshots as validated shape references."""

import argparse, json, sys, hashlib, shutil
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from detection import detect
from recognition import sample_board, components, cellset
from geometry import orientations


def normalized(cells):
    x0 = min(x for x, y in cells)
    y0 = min(y for x, y in cells)
    return sorted([x - x0, y - y0] for x, y in cells)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "pieces")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    entries = {}
    for kind in "IOTSZJL":
        source = args.source / (kind + "_active.jpg")
        im = Image.open(source).convert("RGB")
        rgb = np.asarray(im)
        detected = detect(rgb)
        box = detected["board"]
        if not box:
            raise ValueError(f"{kind}: board grid not detected")
        x, y, right, bottom = box
        grid, confidence, ghost, invalid = sample_board(rgb[y:bottom, x:right])
        # Labels may have a wrong hue boundary (real blue J was labelled I).
        # Validate the human-labelled capture by geometry before calibrating hue.
        expected = [normalized(p) for p in orientations(kind)]
        seen = set()
        matches = []
        for yy, xx in np.argwhere(grid > 0):
            if (int(xx), int(yy)) in seen:
                continue
            cells = set()
            stack = [(int(xx), int(yy))]
            color = grid[yy, xx]
            while stack:
                a, b = stack.pop()
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                cells.add((a, b))
                for nx, ny in ((a - 1, b), (a + 1, b), (a, b - 1), (a, b + 1)):
                    if 0 <= nx < 10 and 0 <= ny < 20 and grid[ny, nx] == color and (nx, ny) not in seen:
                        stack.append((nx, ny))
            if len(cells) == 4 and normalized(cells) in expected:
                rotation = expected.index(normalized(cells))
                p = orientations(kind)[rotation]
                state = (
                    min(a for a, b in cells) - min(a for a, b in p),
                    min(b for a, b in cells) - min(b for a, b in p),
                    rotation,
                )
                matches.append((kind, state))
        if invalid or not matches:
            raise ValueError(f"{kind}: no confirmed four-cell component")
        _, state = min(matches, key=lambda item: min(yy for xx, yy in cellset(*item)))
        cells = sorted(cellset(kind, state))
        shape = normalized(cells)
        if shape not in expected:
            raise ValueError(f"{kind}: shape does not match SRS geometry")
        minx = min(a for a, b in cells)
        maxx = max(a for a, b in cells) + 1
        miny = min(b for a, b in cells)
        maxy = max(b for a, b in cells) + 1
        cw = (right - x) / 10
        ch = (bottom - y) / 20
        samples = (
            np.array([rgb[round(y + (b + 0.5) * ch), round(x + (a + 0.5) * cw)] for a, b in cells], dtype=np.float32)
            / 255
        )
        hues = cv2.cvtColor(samples[None, :, :], cv2.COLOR_RGB2HSV)[0, :, 0]
        angle = np.deg2rad(hues)
        hue = float(np.rad2deg(np.arctan2(np.sin(angle).mean(), np.cos(angle).mean())) % 360)
        crop = [round(x + minx * cw), round(y + miny * ch), round(x + maxx * cw), round(y + maxy * ch)]
        shutil.copy2(source, args.output / source.name)
        im.crop(crop).save(args.output / (kind + "_piece.png"))
        entries[kind] = {
            "source_file": source.name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "crop_file": kind + "_piece.png",
            "board": box,
            "crop": crop,
            "cells": cells,
            "observed_shape": shape,
            "observed_rotation": state[2],
            "hue_degrees": hue,
            "sample_rgb": np.median(samples * 255, axis=0).astype(int).tolist(),
            "rotations": expected,
            "min_cell_confidence": float(min(confidence[b, a] for a, b in cells)),
            "verification": "real screenshot; grid, color and four-cell geometry checked",
            "rotations_verification": "derived from SRS geometry, not real captures of all rotations",
        }
        print(kind, box, cells, "confidence", entries[kind]["min_cell_confidence"])
    result = {
        "schema": "tetris-piece-references-v1",
        "source_url": "https://play.tetris.com/",
        "kinds": entries,
        "rotation_order": "0,90,180,270 degrees clockwise; equivalent appearances remain ambiguous",
    }
    (args.output / "templates.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Imported 7 real captures into", args.output)


if __name__ == "__main__":
    main()
