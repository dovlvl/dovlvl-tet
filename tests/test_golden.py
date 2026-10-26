"""Offline regression snapshots. Generate missing files only with GOLDEN_UPDATE=1.

Existing snapshots are never overwritten, even in generation mode. Lists retain
semantic order; only unordered sets, dictionary keys and placement collections
are sorted. No deadline-limited searches or native keyboard input are used.
"""

import copy
import json
import os
import tempfile
import unittest
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import bootstrap  # noqa: E402, F401 -- configure source imports

import config  # noqa: E402
import geometry  # noqa: E402
import openers  # noqa: E402
import planner  # noqa: E402
import scoring  # noqa: E402
import strategy  # noqa: E402
import timing  # noqa: E402
import ui_status  # noqa: E402
from detection import detect  # noqa: E402
from helpers import C, scene  # noqa: E402
from recognition import PreviewCache, Recognizer, sample_board  # noqa: E402

KINDS = "IJLOSTZ"
GOLDEN = Path(__file__).parent / "golden"
TIME_FIELDS = {
    "updated",
    "seen",
    "captured",
    "capture_ms",
    "vision_ms",
    "fps",
    "fixed_updated",
    "ghost_updated",
    "generation_first_seen",
    "frame_interval_ms",
    "fall_ms",
    "grounded_ms",
}


def canonical(value):
    if is_dataclass(value) and not isinstance(value, dict):
        value = asdict(value)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, float):
        return round(value, 9)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported snapshot type: {type(value)}")


def without_times(value):
    if is_dataclass(value) and not isinstance(value, dict):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: without_times(item) for key, item in value.items() if key not in TIME_FIELDS}
    if isinstance(value, (list, tuple)):
        return [without_times(item) for item in value]
    return value


def placements(values):
    return sorted(
        (canonical(value) for value in values),
        key=lambda value: (value["cells"], value["spin"], value["lines"], value["path"], value["score"]),
    )


def reference_book():
    return openers.compile_book(json.loads((ROOT / "data/openers/TKI_Fonzie.json").read_text(encoding="utf-8")))


def boards():
    uneven = [[0] * 10 for _ in range(20)]
    for x, height in enumerate((2, 4, 1, 3, 0, 5, 2, 1, 3, 2)):
        for y in range(20 - height, 20):
            uneven[y][x] = 1
    uneven[18][1] = 0  # Include a buried hole.
    return {
        "empty": [[0] * 10 for _ in range(20)],
        "uneven": uneven,
        "tspin": [list(row) for row in reference_book()["variants"][0]["steps"][-1]["expected_before"]],
    }


class GoldenTests(unittest.TestCase):
    def test_snapshot_generation_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(__name__ + ".GOLDEN", Path(directory)), patch.dict(os.environ, {"GOLDEN_UPDATE": "0"}):
                with self.assertRaisesRegex(AssertionError, "Missing snapshot"):
                    self.snapshot("guard", {"value": 1})
                self.assertFalse((Path(directory) / "guard.json").exists())
                with patch.dict(os.environ, {"GOLDEN_UPDATE": "1"}):
                    self.snapshot("guard", {"value": 1})
                    original = (Path(directory) / "guard.json").read_bytes()
                    with self.assertRaisesRegex(AssertionError, "Snapshot differs"):
                        self.snapshot("guard", {"value": 2})
                    self.assertEqual((Path(directory) / "guard.json").read_bytes(), original)

    def snapshot(self, name, value):
        actual = json.dumps(canonical(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        path = GOLDEN / f"{name}.json"
        if not path.exists():
            self.assertEqual(os.environ.get("GOLDEN_UPDATE"), "1", f"Missing snapshot: {path}; use GOLDEN_UPDATE=1")
            GOLDEN.mkdir(exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(actual)
        self.assertEqual(path.read_text(encoding="utf-8"), actual, f"Snapshot differs: {name}")

    def test_geometry(self):
        results = {"orientations": {kind: geometry.orientations(kind) for kind in KINDS}, "boards": {}}
        for name, board in boards().items():
            cases = []
            for kind in KINDS:
                for r in range(4):
                    for x, y in ((3, 0), (-1, 5), (7, 5), (3, 17), (3, 18)):
                        state = (x, y, r)
                        p = geometry.orientations(kind)[r]
                        case = dict(kind=kind, state=state, fits=geometry.fits(board, p, x, y))
                        case["rotate"] = [geometry.rotate(board, kind, state, d) for d in (1, -1)]
                        case["advance"] = {
                            a: geometry.advance(board, kind, state, a) for a in ("left", "right", "up", "z", "down")
                        }
                        if case["fits"]:
                            while geometry.fits(board, p, x, y + 1):
                                y += 1
                            after, lines = geometry.settle(board, p, x, y)
                            case.update(settle=(after, lines), evaluate=geometry.evaluate(after, lines))
                        cases.append(case)
            results["boards"][name] = dict(board=board, cases=cases)
        self.snapshot("geometry", results)

    def test_planner(self):
        results = {}
        for name, board in boards().items():
            for kind in KINDS:
                landings = placements(planner.landings(board, kind, deadline=None, counterclockwise=True))
                routes = [
                    dict(
                        cells=a["cells"],
                        spin=a["spin"],
                        path=planner.route_to(
                            board, kind, (3, 0, 0), a["cells"], counterclockwise=True, spin=a["spin"]
                        ),
                    )
                    for a in landings
                ]
                results[f"{name}/{kind}"] = dict(
                    landings=landings,
                    routes=routes,
                    unreachable=planner.route_to(board, kind, (3, 0, 0), [(0, 0)]),
                    basic=placements(
                        planner.basic_candidates(board, kind, (3, 0, 0), counterclockwise=True, deadline=None)
                    ),
                )
        self.snapshot("planner", results)

    def test_scoring_strategy(self):
        awards = []
        for spin in ("none", "mini", "full"):
            for lines in range(5):
                for b2b in (None, False, True):
                    for level, combo in ((1, None), (3, -1), (10, 2)):
                        args = dict(
                            lines=lines,
                            spin=spin,
                            perfect_clear=True,
                            hard_distance=4,
                            soft_distance=2,
                            state=scoring.ScoreState(level=level, back_to_back=b2b, combo=combo, lines=8),
                        )
                        awards.append(dict(input=args, output=scoring.award(**args)))
        spins = []
        for name, board in boards().items():
            for a in planner.landings(board, "T", deadline=None, counterclockwise=True):
                state = (a["x"], a["y"], a["r"])
                for kind, rotated, kick, distance in (
                    ("T", True, 0, 0),
                    ("T", False, 0, 0),
                    ("T", True, 4, 0),
                    ("T", True, 0, 1),
                    ("I", True, 0, 0),
                ):
                    spins.append(
                        dict(
                            board=name,
                            state=state,
                            kind=kind,
                            rotated=rotated,
                            kick=kick,
                            distance=distance,
                            result=scoring.tspin(board, kind, state, rotated, kick, distance),
                        )
                    )
        self.snapshot(
            "scoring_strategy",
            dict(
                awards=awards,
                spins=spins,
                strategy={
                    name: dict(
                        metrics=strategy.metrics(board), scores=[strategy.position_score(board, n) for n in range(5)]
                    )
                    for name, board in boards().items()
                },
            ),
        )

    def test_timing(self):
        profiles = []
        routes = []
        for tracked, cells, known, grounded, speed, samples in (
            (False, 18, False, 0, 0, 0),
            (True, 12, False, 0, 5, 3),
            (True, 0, False, 0, 20, 4),
            (True, 0, True, 480, 20, 4),
        ):
            obs = SimpleNamespace(
                motion_tracked=tracked,
                fall_cells=cells,
                grounded_known=known,
                grounded_ms=grounded,
                gravity_cps=speed,
                motion_samples=samples,
                frame_interval_ms=17,
            )
            for verified in (False, True):
                for age in (0, 40, 500):
                    c = dict(C, lock_delay_verified=verified, lock_delay_ms=500)
                    profile = timing.timing_profile(obs, c, age_ms=age, ack_ms=90)
                    profiles.append(dict(observation=vars(obs), verified=verified, age=age, profile=profile))
                    for name, board in boards().items():
                        for kind in ("I", "T", "O"):
                            choices = placements(planner.basic_candidates(board, kind, (3, 0, 0), deadline=None))
                            for a in choices[:: max(1, len(choices) // 3)]:
                                routes.append(
                                    dict(
                                        board=name,
                                        kind=kind,
                                        profile=profile,
                                        path=a["path"],
                                        target=a["cells"],
                                        result=timing.route_feasible(
                                            board, kind, (3, 0, 0), a["path"], a["cells"], profile
                                        ),
                                    )
                                )
        empty = boards()["empty"]
        self.snapshot(
            "timing",
            dict(
                profiles=profiles,
                routes=routes,
                missing_drop=timing.route_feasible(empty, "T", (3, 0, 0), ["left"], [], {}),
            ),
        )

    def test_openers(self):
        book = reference_book()
        mirrors = [openers.mirrored_variant(v) for v in book["variants"]]
        mirrored_book = copy.deepcopy(book)
        mirrored_book["variants"] = mirrors
        self.snapshot(
            "openers", dict(compiled=book, mirrored=mirrors, compiled_mirror=openers.compile_book(mirrored_book))
        )

    def test_recognition(self):
        images = {}
        for kind in KINDS:
            images[f"scene_{kind}"] = (
                scene(boards()["uneven"], kind=kind, state=(3, 3, 0), held=kind, nexts=(kind,) * 3, ghost=True),
                copy.deepcopy(C),
            )
        images["scene_empty"] = (scene(boards()["empty"], kind=None, held=None, nexts=()), copy.deepcopy(C))
        for path in sorted((Path(__file__).parent / "fixtures").glob("*.png")):
            with Image.open(path) as image:
                rgb = np.asarray(image.convert("RGB"))
            regions = detect(rgb, default_count=1)
            self.assertIsNotNone(regions, path.name)
            c = copy.deepcopy(config.DEFAULT)
            c.update({key: regions[key] for key in ("board", "hold", "next_slots")})
            images[path.name] = (rgb, c)
        results = {}
        for name, (rgb, c) in images.items():
            x, y, right, bottom = c["board"]
            samples = sample_board(rgb[y:bottom, x:right])
            previews = []
            for box in (c["hold"], *c["next_slots"]):
                if box is not None:
                    x, y, right, bottom = box
                    previews.append(
                        without_times(PreviewCache.classify(rgb[y:bottom, x:right], 100, c["min_s"], c["min_v"]))
                    )
            recognizer = Recognizer()
            observations = []
            for seq in (1, 2, 3):
                now = 100 + seq * 0.02
                with patch("recognition.time.monotonic", return_value=now):
                    obs = recognizer.process(rgb, (0, 0, rgb.shape[1], rgb.shape[0]), c, seq, now)
                observations.append(dict(fields=without_times(obs), valid=obs.valid, queue=obs.queue))
            results[name] = dict(sample_board=samples, previews=previews, observations=observations)
        self.snapshot("recognition", results)

    def test_config_status(self):
        cases = {"default": (copy.deepcopy(config.DEFAULT), False), "complete": (copy.deepcopy(C), True)}
        for key, value in (
            ("score_level", 0),
            ("press_ms", 14),
            ("gap_ms", 301),
            ("frame_age_ms", 49),
            ("plan_age_ms", 2001),
            ("search_depth", 8),
            ("opener_enabled", True),
            ("hotkey_stop", "F6"),
            ("hotkey_toggle", "A"),
            ("board", None),
            ("hold", C["board"]),
            ("next_slots", []),
            ("confidence", 0.1),
        ):
            c = copy.deepcopy(C)
            c[key] = value
            cases[key] = (c, True)
        validation = {}
        for name, (c, complete) in cases.items():
            try:
                output = config.validate(c, complete)
                result = dict(accepted=True, result=output)
            except ValueError as exc:
                result = dict(accepted=False, message=str(exc))
            validation[name] = dict(config=c, complete=complete, output=result)
        statuses = []
        recognizer = Recognizer()
        for seq in (1, 2):
            obs = recognizer.process(scene(boards()["empty"]), (0, 0, 340, 400), C, seq, 100)
        for age in (-0.01, 0, 0.599, 0.6, 10):
            for error, visibility, searching in (
                (False, "", False),
                (True, "", False),
                (False, "covered", False),
                (False, "", True),
            ):
                session = SimpleNamespace(error="failure" if error else "", visibility_error=visibility)
                statuses.append(
                    dict(
                        age=age,
                        error=error,
                        visibility=visibility,
                        searching=searching,
                        result=ui_status.summary(C, session, obs, searching=searching, now=100 + age),
                    )
                )
        self.snapshot(
            "config_status",
            dict(validation=validation, statuses=statuses, absent=ui_status.summary(C, None, None, now=100)),
        )


if __name__ == "__main__":
    unittest.main()
