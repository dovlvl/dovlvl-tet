"""Validated references from real game screenshots; no runtime image guessing."""

from functools import lru_cache
from pathlib import Path
import json, sys
from geometry import orientations


def normalize(cells):
    xx = min(x for x, y in cells)
    yy = min(y for x, y in cells)
    return tuple(sorted((x - xx, y - yy) for x, y in cells))


@lru_cache(maxsize=1)
def library():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    path = root / "data" / "pieces" / "templates.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "tetris-piece-references-v1" or set(data.get("kinds", {})) != set("IOTSZJL"):
        raise ValueError("도형 기준 데이터 형식/7종 누락")
    for kind, entry in data["kinds"].items():
        expected = [normalize(p) for p in orientations(kind)]
        if [normalize(p) for p in entry["rotations"]] != expected or normalize(entry["observed_shape"]) not in expected:
            raise ValueError("도형 기준 데이터와 SRS 불일치: " + kind)
        if not 0 <= entry["hue_degrees"] < 360:
            raise ValueError("도형 색상 기준 오류: " + kind)
    return data


def shape_rotations(kind, cells):
    observed = normalize(cells)
    data = library()
    patterns = data["kinds"][kind]["rotations"] if data else orientations(kind)
    return tuple(r for r, p in enumerate(patterns) if normalize(p) == observed)


def hue_centers():
    data = library()
    return {kind: entry["hue_degrees"] for kind, entry in data["kinds"].items()} if data else None
