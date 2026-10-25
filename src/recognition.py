"""NumPy RGB sampling. No OCR/network; all ROIs share one captured frame."""

import time, zlib, colorsys, copy
from functools import lru_cache
from dataclasses import replace
import numpy as np
from model import Active, Reading, Observation
from geometry import SHAPES, orientations, fits, settle
from geometry import cellset as cellset
from piece_library import hue_centers, shape_rotations

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
NOMINAL_HUES = {
    k: colorsys.rgb_to_hsv(*(int(v[i : i + 2], 16) / 255 for i in (1, 3, 5)))[0] * 360 for k, v in PALETTE.items()
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
    centers = hue_centers()
    if centers:
        distance = np.stack(
            [
                np.minimum(
                    np.minimum(abs(h - centers[k]), 360 - abs(h - centers[k])),
                    np.minimum(abs(h - NOMINAL_HUES[k]), 360 - abs(h - NOMINAL_HUES[k])),
                )
                for k in KINDS[1:]
            ],
            axis=-1,
        )
        result = (distance.argmin(-1) + 1).astype(np.uint8)
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


def identify(cells, grid):
    if len(cells) != 4:
        return []
    values = {int(grid[y, x]) for x, y in cells}
    if len(values) != 1 or 0 in values:
        return []
    kind = KINDS[values.pop()]
    out = []
    if not shape_rotations(kind, cells):
        return []
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
    """Independent ROI geometry, bounded retries and inspectable masks."""

    def __init__(self):
        self.cache = {}
        self.debug = {}
        self.reclassifications = 0

    def invalidate(self):
        self.cache.clear()

    def read(self, name, rgb, now, min_s, min_v):
        if rgb is None or rgb.size == 0:
            self.debug[name] = {"reason": "미설정/잘린 영역", "raw_shape": None if rgb is None else list(rgb.shape)}
            return Reading(None, 0, now, False, "미설정/잘린 영역", now)
        fingerprint = (rgb.shape, zlib.adler32(np.ascontiguousarray(rgb)), min_s, min_v)
        old = self.cache.get(name)
        # Invalid reads are retried even when the image checksum does not change.
        if old and old[0] == fingerprint and now - old[1].updated < (1 if old[1].valid else 0.15):
            r = old[1]
            return Reading(r.kind, r.confidence, r.updated, r.valid, r.reason, now, r.state, r.available)
        r, debug = self.analyze(rgb, now, min_s, min_v)
        if name.startswith("next") and r.state in ("empty", "disabled"):
            r = Reading(None, r.confidence, now, False, "NEXT: 빈 슬롯/어두운 블록은 불확실", now, r.state, None)
        self.reclassifications += 1
        debug.update(
            fingerprint=fingerprint[1], raw_shape=list(rgb.shape), updated=now, reclassifications=self.reclassifications
        )
        self.debug[name] = debug
        self.cache[name] = (fingerprint, r)
        return r

    @staticmethod
    def classify(rgb, now, min_s, min_v):
        return PreviewCache.analyze(rgb, now, min_s, min_v)[0]

    @staticmethod
    def analyze(rgb, now, min_s, min_v):
        import cv2

        step = max(1, (max(rgb.shape[:2]) + 239) // 240)
        a = rgb[::step, ::step]
        # Preview thresholds differ from BOARD; dim HOLD must not become empty.
        lab, v, s = labels(a, min(0.22, min_s), min(0.10, min_v))
        hist = np.bincount(lab.ravel(), minlength=8)
        hist[0] = 0
        debug = {
            "mask": (lab > 0).astype(np.uint8) * 255,
            "normalized": np.zeros((96, 96, 3), np.uint8),
            "bbox": None,
            "scale_step": step,
        }
        h, w = lab.shape
        if min(h, w) < 8:
            return Reading(None, 0, now, False, "슬롯 영역이 너무 작음", now), debug
        count = int(hist.sum())
        color = int(hist.argmax())
        gray = False
        if count < max(8, h * w * 0.002):
            # A low-saturation piece is a disabled HOLD candidate, never empty.
            bg = float(np.median(v))
            mask = ((v > bg + 0.10) & (s < 0.22)).astype(np.uint8)
            if mask.sum() < max(8, h * w * 0.006):
                empty = bool((v < 0.32).mean() > 0.90 and float(v.max() - v.min()) < 0.045)
                return Reading(
                    None,
                    0.97 if empty else 0,
                    now,
                    empty,
                    "빈 HOLD 후보" if empty else "빈 칸/어두운 블록 구분 불가",
                    now,
                    "empty" if empty else "unknown",
                    True if empty else None,
                ), debug
            gray = True
        else:
            dominant = hist[color] / max(1, count)
            shade_pair = color in (2, 3) and (hist[2] + hist[3]) / count > 0.96
            if dominant < 0.85 and not shade_pair:
                return Reading(None, 0, now, False, "복수 색/슬롯 겹침/라벨 혼입", now), debug
            mask = ((lab > 0) if shade_pair else (lab == color)).astype(np.uint8)
        # Join mino seams; use each significant component, ignoring small text specks.
        kernel = max(2, round(min(h, w) * 0.045))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
        n, cc, stats, _ = cv2.connectedComponentsWithStats(closed)
        areas = [(int(stats[i, 4]), i) for i in range(1, n) if stats[i, 4] >= 8]
        if not areas:
            return Reading(None, 0, now, False, "블록 후보 없음", now), debug
        areas.sort(reverse=True)
        largest = areas[0][0]
        significant = [i for area, i in areas if area >= max(8, largest * 0.30)]
        selected = np.isin(cc, significant) & (mask > 0)
        ys, xs = np.where(selected)
        if not len(xs):
            return Reading(None, 0, now, False, "정규화 실패", now), debug
        x1, x2, y1, y2 = int(xs.min()), int(xs.max() + 1), int(ys.min()), int(ys.max() + 1)
        debug["bbox"] = [x1 * step, y1 * step, x2 * step, y2 * step]
        debug["mask"] = selected.astype(np.uint8) * 255
        scale = min(88 / (x2 - x1), 88 / (y2 - y1))
        nw = max(1, round((x2 - x1) * scale))
        nh = max(1, round((y2 - y1) * scale))
        thumb = cv2.resize(a[y1:y2, x1:x2], (nw, nh), interpolation=cv2.INTER_NEAREST)
        debug["normalized"][(96 - nh) // 2 : (96 - nh) // 2 + nh, (96 - nw) // 2 : (96 - nw) // 2 + nw] = thumb
        if x1 == 0 or y1 == 0 or x2 == w or y2 == h:
            return Reading(None, 0, now, False, "블록이 슬롯 경계에 닿음: 잘림/영역 여백 확인", now), debug
        bw, bh = x2 - x1, y2 - y1
        scores = []
        for kind in tuple(PALETTE) if gray else (KINDS[color],):
            best = 0
            for p in orientations(kind):
                px = min(x for x, y in p)
                py = min(y for x, y in p)
                shape = {(x - px, y - py) for x, y in p}
                cols = max(x for x, y in shape) + 1
                rows = max(y for x, y in shape) + 1
                square = min(bw / cols, bh / rows) / max(bw / cols, bh / rows)
                if square < 0.78:
                    continue
                agreement = []
                for yy in range(rows):
                    for xx in range(cols):
                        aa = int(x1 + (xx + 0.24) * bw / cols)
                        bb = max(aa + 1, int(x1 + (xx + 0.76) * bw / cols))
                        c = int(y1 + (yy + 0.24) * bh / rows)
                        d = max(c + 1, int(y1 + (yy + 0.76) * bh / rows))
                        density = float(selected[c:d, aa:bb].mean())
                        agreement.append(density if (xx, yy) in shape else 1 - density)
                score = min(agreement) * square  # every mino/empty cell must agree
                best = max(best, score)
            scores.append((best, kind))
        scores.sort(reverse=True)
        best, kind = scores[0]
        debug["scores"] = scores
        valid = best >= 0.82 and (not gray or len(scores) < 2 or best - scores[1][0] > 0.10)
        dim = gray or float(np.median(v[selected])) < 0.30
        state = "disabled" if dim and valid else "piece" if valid else "unknown"
        return Reading(
            kind if valid else None,
            float(best),
            now,
            bool(valid),
            "어두운 HOLD: 사용 불가 후보" if state == "disabled" else "" if valid else "색+4칸 도형 불일치",
            now,
            state,
            False if dim else None,
        ), debug


def lock_successors(board, kind, state=None):
    return _lock_successors(tuple(map(tuple, board)), kind, tuple(state) if state is not None else None)


@lru_cache(maxsize=256)
def _lock_successors(board, kind, state=None):
    """Pixel hypotheses for one observed piece locking, including line clears."""
    result = {}
    starts = [(x, 0, r) for r in range(4) for x in range(-3, 10)]
    if state is not None:
        starts.append(state)
    for x, y, r in starts:
        p = orientations(kind)[r]
        if not fits(board, p, x, y):
            continue
        while fits(board, p, x, y + 1):
            y += 1
        b, _ = settle([list(row) for row in board], p, x, y)
        key = tuple(map(tuple, b))
        result[key] = {(xx, yy) for yy, row in enumerate(b) for xx, v in enumerate(row) if v}
    return result


class Recognizer:
    def __init__(self):
        self.cache = PreviewCache()
        self.prev_grid = None
        self.last_active = None
        self.last_fixed = None
        self.stable = 0
        self.last_board = None
        self.fixed_time = 0
        self.last_seq = -1

    def reset(self):
        self.__init__()

    def process(self, rgb, bbox, config, seq, captured, capture_ms=0, expected_fixed=None):
        begin = time.perf_counter()
        now = time.monotonic()
        ox, oy, _, _ = bbox
        if seq <= self.last_seq:
            raise ValueError("Out-of-order recognition frame")
        self.last_seq = seq

        def roi(box):
            if box is None:
                return None
            x, y, r, b = box
            if x < ox or y < oy or r > ox + rgb.shape[1] or b > oy + rgb.shape[0] or r <= x or b <= y:
                return None
            return rgb[y - oy : b - oy, x - ox : r - ox]

        hold = self.cache.read("hold", roi(config["hold"]), now, config["min_s"], config["min_v"])
        nexts = [
            self.cache.read(f"next{i}", roi(box), now, config["min_s"], config["min_v"])
            for i, box in enumerate(config["next_slots"])
        ]
        # Normal Auto can confirm previews from repeated shape/color evidence;
        # opener execution retains its separate manual verification gate.
        hs = (hold.kind, hold.state) if hold.valid and hold.confidence >= config["confidence"] else None
        ns = (
            tuple((r.kind, r.valid) for r in nexts)
            if nexts and nexts[0].valid and nexts[0].confidence >= config["confidence"]
            else None
        )
        self.hold_stable = (
            (getattr(self, "hold_stable", 0) + 1 if hs == getattr(self, "hold_signature", None) else 1)
            if hs is not None
            else 0
        )
        self.next_stable = (
            (getattr(self, "next_stable", 0) + 1 if ns == getattr(self, "next_signature", None) else 1)
            if ns is not None
            else 0
        )
        self.hold_signature = hs
        self.next_signature = ns
        board_pixels = roi(config["board"])
        fingerprint = (
            board_pixels.shape,
            zlib.adler32(np.ascontiguousarray(board_pixels)),
            config["min_s"],
            config["min_v"],
            tuple(map(tuple, expected_fixed)) if expected_fixed is not None else None,
        )
        cached = getattr(self, "board_cache", None)
        if cached and cached[0] == fingerprint and cached[1].active and cached[1].confidence >= config["confidence"]:
            self.stable += 1
            active = replace(cached[1].active, updated=now)
            o = replace(
                cached[1],
                seq=seq,
                captured=captured,
                updated=now,
                active=active,
                stable=self.stable,
                hold=hold,
                nexts=nexts,
                hold_stable=self.hold_stable,
                next_stable=self.next_stable,
                capture_ms=capture_ms,
                vision_ms=(time.perf_counter() - begin) * 1000,
                fixed_updated=now,
            )
            self.last_active = active
            self.fixed_time = now
            return o
        grid, conf, ghost, invalid = sample_board(roi(config["board"]), config["min_s"], config["min_v"])
        occupied = {(int(x), int(y)) for y, x in np.argwhere(grid > 0)}
        candidates = []
        # Confirm a drop's predicted board against pixels; this is a hypothesis, never trusted blindly.
        if expected_fixed is not None:
            expected = {(x, y) for y, row in enumerate(expected_fixed) for x, v in enumerate(row) if v}
            if expected <= occupied:
                candidates = identify(occupied - expected, grid)
        # Persistent fixed board separates touching same-color active blocks.
        if not candidates and self.last_fixed is not None:
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
            options = []
            if self.last_fixed is not None and self.last_active is not None:
                # A new piece may already be far below spawn. Validate the
                # residual fixed board as a legal lock instead of using y<=2.
                for base in lock_successors(self.last_fixed, self.last_active.kind, self.last_active.state).values():
                    if base <= occupied:
                        options += identify(occupied - base, grid)
            if not options:
                options = [(k, s) for k, s in components(grid) if (s[1] <= 2 and 2 <= s[0] <= 5) or len(occupied) == 4]
                if self.last_fixed is not None and self.last_active is not None:
                    legal = lock_successors(self.last_fixed, self.last_active.kind, self.last_active.state)
                    options = [
                        (k, s)
                        for k, s in components(grid)
                        if tuple(tuple(int((x, y) in occupied - cellset(k, s)) for x in range(10)) for y in range(20))
                        in legal
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
            active = Active(kind, st, cells, ac, now, shape_rotations(kind, cells))
            reason = ""
            if (
                not getattr(self, "tracking_initialized", False)
                and st[1] > 3
                and not config.get("allow_stationary_bootstrap", False)
            ):
                previous = getattr(self, "bootstrap", None)
                current = (kind, tuple(map(tuple, fixed)), cells, st)
                moving = previous and previous[0] == kind and previous[1] == current[1] and previous[2] != cells
                self.bootstrap = current
                if not moving:
                    confidence = 0
                    reason = "BOOTSTRAP_MOTION_REQUIRED: low stationary shape may be fixed blocks"
                else:
                    self.tracking_initialized = True
            else:
                self.tracking_initialized = True
            # Dim filled ghosts require both shape and exact drop geometry. If the
            # skin is uncalibrated, reject rather than turn a shadow into a stack.
            board_rgb = roi(config["board"])
            hh, ww = board_rgb.shape[:2]
            brightness = np.max(
                board_rgb[
                    ((np.arange(20) + 0.5) * hh / 20).astype(int)[:, None],
                    ((np.arange(10) + 0.5) * ww / 10).astype(int)[None, :],
                ],
                axis=-1,
            )
            active_light = min(float(brightness[y, x]) for x, y in cells)
            rest = grid.copy()
            for x, y in cells:
                rest[y, x] = 0
            for gk, gs in components(rest):
                gc = cellset(gk, gs)
                if gk != kind or min(y for x, y in gc) <= max(y for x, y in cells):
                    continue
                if max(float(brightness[y, x]) for x, y in gc) > active_light * 0.55:
                    continue
                trial = [row[:] for row in fixed]
                for x, y in gc:
                    trial[y][x] = 0
                xx, yy, rr = st
                while fits(trial, orientations(kind)[rr], xx, yy + 1):
                    yy += 1
                if cellset(kind, (xx, yy, rr)) != gc:
                    continue
                if config.get("filled_ghost_verified", False):
                    fixed = trial
                    ghost += sorted(gc)
                else:
                    confidence = 0
                    reason = "AMBIGUOUS_FILLED_GHOST: calibrate skin before Auto"
            # During movement/rotation the fixed board cannot change. A lock or
            # hold has a spawn near the top; those transitions need stable frames.
            if self.last_fixed is not None and fixed != self.last_fixed and self.last_active:
                if tuple(map(tuple, fixed)) not in lock_successors(
                    self.last_fixed, self.last_active.kind, self.last_active.state
                ):
                    confidence = 0
                    reason = "UNEXPLAINED_FIXED_CHANGE: no observed-piece lock explains pixels"
            key = tuple(tuple(r) for r in fixed)
            self.stable = self.stable + 1 if key == self.last_board else 1
            self.last_board = key
            if self.last_active and (
                key != tuple(tuple(r) for r in (self.last_fixed or []))
                or (st[1] <= 2 and self.last_active.state[1] > 3)
                or kind != self.last_active.kind
            ):
                self.cache.invalidate()
            if confidence >= config.get("confidence", 0.8):
                changed = self.last_fixed is not None and fixed != self.last_fixed
                swapped = self.last_active is not None and kind != self.last_active.kind
                respawned = bool(
                    self.last_active and not changed and not swapped and st[1] <= 2 and self.last_active.state[1] >= 6
                )
                self.generation = getattr(self, "generation", 0) + int(changed or swapped or respawned)
                if changed or swapped or respawned:
                    self.transition = "lock" if changed else "piece_change"
                self.last_fixed = fixed
                self.last_active = active
                self.fixed_time = now
            else:
                self.stable = 0
        else:
            self.stable = 0
        if not occupied and not invalid:
            fixed = [[0] * 10 for _ in range(20)]
            self.fixed_time = now
        if invalid:
            reason = "팝업/줄 삭제/중앙 색상 불안정"
            confidence = 0
            active = None
        prediction_match = None
        if expected_fixed is not None and active:
            prediction_match = tuple(map(tuple, fixed)) == tuple(map(tuple, expected_fixed))
            if not prediction_match:
                reason = "DROP_BOARD_MISMATCH: observed pixels disagree with prediction"
        self.prev_grid = grid.copy()
        result = Observation(
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
            prediction_match=prediction_match,
            hold_stable=self.hold_stable,
            next_stable=self.next_stable,
            generation=getattr(self, "generation", 0),
            transition=getattr(self, "transition", "initial"),
        )
        self.board_cache = (fingerprint, copy.copy(result))
        return result
