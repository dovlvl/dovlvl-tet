"""Observed motion bounds and conservative execution checks; no score thresholds."""

from collections import deque
from copy import copy
from math import ceil
from geometry import orientations, fits, advance


def drop_distance(board, kind, state):
    x, y, r = state
    p = orientations(kind)[r]
    distance = 0
    while fits(board, p, x, y + distance + 1):
        distance += 1
    return distance


class MotionTracker:
    def __init__(self):
        self.previous = None
        self.samples = deque(maxlen=12)
        self.first_seen = {}
        self.last_generation = None
        self.interval_ms = 17
        self.movement_anchor = None
        self.grounded_since = None
        self.grounded_generation = None

    def update(self, o, controlled_action=None):
        o.motion_tracked = True
        if not o.active or o.confidence < 0.8:
            # Clear/spawn frames break motion continuity, not the capture loop.
            self.previous = None
            self.movement_anchor = None
            self.grounded_since = None
            self.grounded_generation = None
            return o
        o.controlled_motion = controlled_action in ("down", "up", "z", "hold", "drop")
        self.first_seen.setdefault(o.generation, o.captured)
        if len(self.first_seen) > 32:
            self.first_seen.pop(next(iter(self.first_seen)))
        previous = self.previous
        if previous and previous.active and o.captured > previous.captured:
            dt = o.captured - previous.captured
            self.interval_ms = dt * 1000
            if (
                previous.generation == o.generation
                and previous.active.state[2] == o.active.state[2]
                and not o.controlled_motion
                and not getattr(previous, "controlled_motion", False)
            ):
                dy = o.active.state[1] - previous.active.state[1]
                if dy > 0 and dt < 1:
                    anchor = self.movement_anchor
                    if dy >= 2:
                        self.samples.append((o.captured, (dy + 1) / dt))
                    elif (
                        anchor
                        and anchor.active
                        and anchor.generation == o.generation
                        and anchor.active.state[2] == o.active.state[2]
                    ):
                        elapsed = o.captured - anchor.captured
                        moved = o.active.state[1] - anchor.active.state[1]
                        if elapsed > 0 and moved > 0:
                            self.samples.append((o.captured, (moved + 1) / elapsed))
                    self.movement_anchor = copy(o)
            if o.controlled_motion:
                self.movement_anchor = None
        # Keep recent fast samples across generation changes. Never infer a
        # slower speed from a landed block or a spawn reset to the top.
        while self.samples and o.captured - self.samples[0][0] > 3:
            self.samples.popleft()
        o.gravity_cps = max((v for _, v in self.samples), default=0)
        o.motion_samples = len(self.samples)
        o.frame_interval_ms = self.interval_ms
        o.fall_cells = drop_distance(o.fixed, o.active.kind, o.active.state)
        if o.fall_cells:
            self.grounded_since = None
            self.grounded_generation = o.generation
        elif previous and previous.generation == o.generation:
            if previous.fall_cells > 0:
                self.grounded_since = previous.captured
                self.grounded_generation = o.generation
            if self.grounded_since is not None and self.grounded_generation == o.generation:
                o.grounded_known = True
                o.grounded_ms = max(0, (o.captured - self.grounded_since) * 1000)
        o.fall_ms = 1000 * o.fall_cells / o.gravity_cps if o.gravity_cps else None
        o.generation_first_seen = self.first_seen[o.generation]
        # The vision pipeline may subsequently mark the observation occluded.
        # Never let that mutation destroy the next frame's motion reference.
        self.previous = copy(o)
        return o


def timing_profile(o, c, age_ms=0, ack_ms=None):
    step = c["press_ms"] + c["gap_ms"]
    step = max(step, ack_ms or 0, 2 * o.frame_interval_ms)
    delay = c.get("lock_delay_ms", 0) if c.get("lock_delay_verified", False) else 0
    if o.motion_tracked and not o.fall_cells:
        delay = max(0, delay - o.grounded_ms) if o.grounded_known else 0
    return dict(
        gravity_cps=o.gravity_cps,
        step_ms=step,
        age_ms=max(0, age_ms),
        lock_delay_ms=delay,
        grounded_unusable=bool(o.motion_tracked and not o.fall_cells and (not o.grounded_known or delay <= age_ms)),
        calibrated=o.motion_samples > 0,
    )


def search_budget(o, c, age_ms=0, ack_ms=None):
    profile = timing_profile(o, c, age_ms, ack_ms)
    if o.fall_ms is None:
        return c.get("search_budget_ms", 160), profile
    remaining = o.fall_ms - age_ms - profile["step_ms"] - o.frame_interval_ms
    # Reserve at least one observed input/ack cycle. At the boundary only a
    # bounded baseline is attempted; unsafe paths are rejected independently.
    budget = max(1, min(c.get("search_budget_ms", 160), remaining * 0.25))
    return budget, profile


def route_feasible(board, kind, start, path, target, profile):
    """Replay keys with gravity at each action boundary, no lock resets assumed.

    Unknown gravity still forbids moving an already grounded piece unless a
    positive lock delay was explicitly verified. A hard drop is a calculated
    placement and must match the chosen target exactly.
    """
    from recognition import cellset

    if not path or path[-1] != "drop":
        return False, "PATH_WITHOUT_DROP"
    if profile.get("grounded_unusable", False):
        return False, "GROUNDED_TIME_UNKNOWN_OR_EXPIRED"
    speed = profile.get("gravity_cps", 0)
    step = profile.get("step_ms", 70) / 1000
    state = tuple(start)
    elapsed = profile.get("age_ms", 0) / 1000
    fallen = 0
    grounded = 0
    delay = profile.get("lock_delay_ms", 0) / 1000
    for index, action in enumerate(path):
        due = ceil(speed * elapsed) if speed and elapsed else 0
        for _ in range(max(0, due - fallen)):
            x, y, r = state
            if fits(board, orientations(kind)[r], x, y + 1):
                state = (x, y + 1, r)
                grounded = 0
                if not drop_distance(board, kind, state) and delay <= 0:
                    return False, "NATURAL_LOCK_BEFORE_ACTION"
            else:
                grounded += 1 / speed
                if grounded >= delay:
                    return False, "NATURAL_LOCK_BEFORE_ACTION"
        fallen = due
        if action == "drop":
            x, y, r = state
            y += drop_distance(board, kind, state)
            return (cellset(kind, (x, y, r)) == frozenset(map(tuple, target)), "TARGET_AFTER_GRAVITY")
        if not drop_distance(board, kind, state) and delay <= 0:
            return False, "GROUNDED_LOCK_DELAY_UNVERIFIED"
        state = advance(board, kind, state, action)
        if state is None:
            return False, "ACTION_BLOCKED_AFTER_GRAVITY"
        if not drop_distance(board, kind, state):
            grounded += step
            if grounded >= delay:
                return False, "LOCK_DURING_ACK"
        elapsed += step
    return False, "NO_TARGET"
