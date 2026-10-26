"""NumPy RGB sampling. No OCR/network; all ROIs share one captured frame."""

import time, zlib
import numpy as np
from model import Active, Reading, Observation
from geometry import orientations

KINDS = ("", "Z", "L", "O", "S", "I", "J", "T")
PALETTE = {
    "I": "#38d5e8",
    "O": "#f4d447",
    "T": "#ae62dc",
    "J": "#5078e6",
    "L": "#ef9b38",
    "S": "#68c766",
    "Z": "#e65864",
}


def labels(rgb, min_s=0.28, min_v=0.28):
    a = np.asarray(rgb, dtype=np.float32) / 255
    mx = a.max(-1)
    mn = a.min(-1)
    delta = mx - mn
    sat = delta / np.maximum(mx, 1e-6)
    r, g, b = np.moveaxis(a, -1, 0)
    h = np.zeros_like(mx)
    nz = delta > 1e-6
    den = np.maximum(delta, 1e-6)
    mr = nz & (mx == r)
    mg = nz & ~mr & (mx == g)
    mb = nz & ~mr & ~mg
    h[mr] = ((g - b) / den)[mr] % 6
    h[mg] = ((b - r) / den + 2)[mg]
    h[mb] = ((r - g) / den + 4)[mb]
    h *= 60
    result = np.select(
        [h < 15, h < 43, h < 75, h < 165, h < 205, h < 260, h < 345], [1, 2, 3, 4, 5, 6, 7], default=1
    ).astype(np.uint8)
    result[(sat < min_s) | (mx < min_v)] = 0
    return result, mx, sat


def sample_board(rgb, min_s=0.28, min_v=0.28):
    h, w = rgb.shape[:2]
    if w < 30 or h < 60:
        raise ValueError("게임판 영역 크기 오류")
    offsets = np.array([0.3, 0.4, 0.5, 0.6, 0.7])
    ys = ((np.arange(20)[:, None] + offsets) * h / 20).astype(int)
    xs = ((np.arange(10)[:, None] + offsets) * w / 10).astype(int)
    samples = rgb[ys[:, None, :, None], xs[None, :, None, :]]  # 20,10,5,5,3
    lab, light, sat = labels(samples, min_s, min_v)
    counts = np.stack([(lab == i).sum(axis=(-1, -2)) for i in range(8)], axis=-1)
    grid = counts.argmax(-1).astype(np.uint8)
    conf = counts.max(-1) / 25
    # Outline ghost: colored edge but dark center. Do not include it in occupancy.
    ey = ((np.arange(20)[:, None] + np.array([0.05, 0.95])) * h / 20).astype(int).clip(0, h - 1)
    ex = ((np.arange(10)[:, None] + np.array([0.05, 0.95])) * w / 10).astype(int).clip(0, w - 1)
    edges = rgb[ey[:, None, :, None], ex[None, :, None, :]]
    el, _, _ = labels(edges, 0.18, 0.12)
    ghost = np.argwhere((grid == 0) & (el > 0).any(axis=(-1, -2)))[:, ::-1].tolist()
    neutral = ((sat < 0.15) & (light > 0.3)).mean(axis=(-1, -2)) > 0.45
    invalid = bool(neutral.sum() > 12 or (conf < 0.6).sum() > 15)
    return grid, conf, ghost, invalid


def cellset(kind, state):
    x, y, r = state
    return frozenset((x + a, y + b) for a, b in orientations(kind)[r])


def identify(cells, grid):
    if len(cells) != 4:
        return []
    values = {int(grid[y, x]) for x, y in cells}
    if len(values) != 1 or 0 in values:
        return []
    kind = KINDS[values.pop()]
    out = []
    for r, p in enumerate(orientations(kind)):
        st = (min(x for x, y in cells) - min(x for x, y in p), min(y for x, y in cells) - min(y for x, y in p), r)
        if cellset(kind, st) == frozenset(cells):
            out.append((kind, st))
    return out[:1]


def components(grid):
    seen = set()
    found = []
    for y, x in np.argwhere(grid > 0):
        x = int(x)
        y = int(y)
        if (x, y) in seen:
            continue
        seen.add((x, y))
        stack = [(x, y)]
        cells = set()
        color = grid[y, x]
        while stack:
            a, b = stack.pop()
            cells.add((a, b))
            for c, d in ((a - 1, b), (a + 1, b), (a, b - 1), (a, b + 1)):
                if 0 <= c < 10 and 0 <= d < 20 and (c, d) not in seen and grid[d, c] == color:
                    seen.add((c, d))
                    stack.append((c, d))
        found += identify(cells, grid)
    return found


class PreviewCache:
    def __init__(self):
        self.cache = {}

    def read(self, name, rgb, now, min_s, min_v):
        if rgb is None:
            return Reading(None, 0, now, False, "미설정", now)
        fingerprint = (rgb.shape, zlib.adler32(rgb.tobytes()), min_s, min_v)
        old = self.cache.get(name)
        if old and old[0] == fingerprint:
            r = old[1]
            return Reading(r.kind, r.confidence, r.updated, r.valid, r.reason, now)
        r = self.classify(rgb, now, min_s, min_v)
        self.cache[name] = (fingerprint, r)
        return r

    @staticmethod
    def classify(rgb, now, min_s, min_v):
        # Subsample to <=100x100, enough for four-mino previews.
        step = max(1, (max(rgb.shape[:2]) + 119) // 120)
        a = rgb[::step, ::step]
        lab, v, s = labels(a, min_s, min_v)
        colors = lab[lab > 0]
        if len(colors) < 8:
            dark = (v < 0.32).mean() if len(colors) == 0 else 0
            return Reading(
                None,
                0.97 if dark > 0.88 else 0,
                now,
                bool(dark > 0.88),
                "빈 칸" if dark > 0.88 else "색/글자/테두리 혼입",
                now,
            )
        hist = np.bincount(colors, minlength=8)
        color = int(hist.argmax())
        dominant = hist[color] / len(colors)
        ys, xs = np.where(lab == color)
        x1, x2 = xs.min(), xs.max() + 1
        y1, y2 = ys.min(), ys.max() + 1
        w = x2 - x1
        h = y2 - y1
        shade_pair = color in (2, 3) and set(np.unique(colors)) <= {2, 3} and dominant >= 0.7
        if dominant < 0.88 and not shade_pair:
            return Reading(None, 0, now, False, "여러 블록/색이 한 슬롯에 있음", now)
        if shade_pair:
            lab = np.where(lab > 0, color, 0)
            dominant = min(0.99, dominant + 0.23)
            ys, xs = np.where(lab == color)
            x1, x2 = xs.min(), xs.max() + 1
            y1, y2 = ys.min(), ys.max() + 1
            w = x2 - x1
            h = y2 - y1
        kind = KINDS[color]
        best = 0
        for p in orientations(kind):
            px = min(x for x, y in p)
            py = min(y for x, y in p)
            shape = {(x - px, y - py) for x, y in p}
            cols = max(x for x, y in shape) + 1
            rows = max(y for x, y in shape) + 1
            square = min(w / cols, h / rows) / max(w / cols, h / rows)
            if square < 0.7:
                continue
            fits = []
            for yy in range(rows):
                for xx in range(cols):
                    aa = int(x1 + (xx + 0.25) * w / cols)
                    bb = max(aa + 1, int(x1 + (xx + 0.75) * w / cols))
                    cc = int(y1 + (yy + 0.25) * h / rows)
                    dd = max(cc + 1, int(y1 + (yy + 0.75) * h / rows))
                    density = (lab[cc:dd, aa:bb] == color).mean()
                    fits.append(density if (xx, yy) in shape else 1 - density)
            best = max(best, float(np.mean(fits)) * square * dominant)
        valid = best >= 0.8
        return Reading(
            kind if valid else None, float(best), now, bool(valid), "" if valid else "4칸 도형 검증 실패", now
        )


class Recognizer:
    def __init__(self):
        self.cache = PreviewCache()
        self.prev_grid = None
        self.last_active = None
        self.last_fixed = None
        self.stable = 0
        self.last_board = None
        self.fixed_time = 0

    def reset(self):
        self.__init__()

    def process(self, rgb, bbox, config, seq, captured, capture_ms=0):
        begin = time.perf_counter()
        now = time.monotonic()
        ox, oy, _, _ = bbox

        def roi(box):
            if box is None:
                return None
            x, y, r, b = box
            return rgb[y - oy : b - oy, x - ox : r - ox]

        hold = self.cache.read("hold", roi(config["hold"]), now, config["min_s"], config["min_v"])
        nexts = [
            self.cache.read(f"next{i}", roi(box), now, config["min_s"], config["min_v"])
            for i, box in enumerate(config["next_slots"])
        ]
        grid, conf, ghost, invalid = sample_board(roi(config["board"]), config["min_s"], config["min_v"])
        occupied = {(int(x), int(y)) for y, x in np.argwhere(grid > 0)}
        candidates = []
        # Persistent fixed board separates touching same-color active blocks.
        if self.last_fixed is not None:
            base = {(x, y) for y, row in enumerate(self.last_fixed) for x, v in enumerate(row) if v}
            if base <= occupied:
                candidates = identify(occupied - base, grid)
        if not candidates and self.prev_grid is not None:
            old = self.prev_grid
            removed = {(int(x), int(y)) for y, x in np.argwhere((old > 0) & (old != grid))}
            added = {(int(x), int(y)) for y, x in np.argwhere((grid > 0) & (old != grid))}
            if 0 < len(removed) <= 4 and 0 < len(added) <= 4:
                for color in set(int(grid[y, x]) for x, y in added):
                    kind = KINDS[color]
                    for r, p in enumerate(orientations(kind)):
                        for ax, ay in added:
                            for px, py in p:
                                st = (ax - px, ay - py, r)
                                cells = cellset(kind, st)
                                if (
                                    added <= cells
                                    and all(0 <= x < 10 and 0 <= y < 20 and grid[y, x] == color for x, y in cells)
                                    and identify((cells - added) | removed, old)
                                ):
                                    candidates.append((kind, st))
        unique = {cellset(k, s): (k, s) for k, s in candidates}
        if len(unique) != 1:
            # At startup or after lock/hold, only a spawn-area component is accepted.
            options = [
                (k, s)
                for k, s in components(grid)
                if (s[1] <= 2 and 2 <= s[0] <= 5) or (len(occupied) == 4 and s[1] < 14)
            ]
            unique = {cellset(k, s): (k, s) for k, s in options}
        active = None
        fixed = self.last_fixed or [[0] * 10 for _ in range(20)]
        confidence = 0
        reason = "현재 블록 대기 (시작/전환/판별 불가)"
        if len(unique) == 1 and not invalid:
            cells, (kind, st) = next(iter(unique.items()))
            ac = float(min(conf[y, x] for x, y in cells))
            fixed = (grid > 0).astype(int)
            for x, y in cells:
                fixed[y, x] = 0
            fixed = fixed.tolist()
            confidence = min(ac, float(np.quantile(conf, 0.05)))
            active = Active(kind, st, cells, ac, now)
            reason = ""
            key = tuple(tuple(r) for r in fixed)
            self.stable = self.stable + 1 if key == self.last_board else 1
            self.last_board = key
            self.last_fixed = fixed
            self.last_active = active
            self.fixed_time = now
        else:
            self.stable = 0
        if not occupied and not invalid:
            fixed = [[0] * 10 for _ in range(20)]
            self.fixed_time = now
        if invalid:
            reason = "팝업/줄 삭제/중앙 색상 불안정"
            confidence = 0
            active = None
        self.prev_grid = grid.copy()
        return Observation(
            seq,
            captured,
            now,
            fixed,
            active,
            ghost,
            hold,
            nexts,
            confidence,
            self.stable,
            reason,
            capture_ms,
            (time.perf_counter() - begin) * 1000,
            raw=grid.tolist(),
            fixed_updated=self.fixed_time,
            fixed_confidence=confidence if active else (0.97 if not occupied and not invalid else 0),
            ghost_confidence=0.8 if ghost and not invalid else 0,
            ghost_updated=now,
        )
