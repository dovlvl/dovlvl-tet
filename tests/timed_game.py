"""Real-clock mock with gravity, non-resetting lock delay, entry/clear gaps."""

import time
from helpers import Game, scene, C
from geometry import advance, fits, orientations, settle
from input_win import VK
from recognition import cellset


class TimedGame(Game):
    def __init__(self, cps=30, lock_ms=250, entry_ms=40, clear_ms=80):
        super().__init__()
        self.queue = list("IIOOTTLLSSZZJJ") * 20
        self.cps = cps
        self.lock_s = lock_ms / 1000
        self.entry_s = entry_ms / 1000
        self.clear_s = clear_ms / 1000
        self.generation = 0
        self.now = time.monotonic()
        self.next_fall = self.now + 1 / cps
        self.ground_since = None
        self.spawn_due = None
        self.visible = True
        self.held_keys = {}
        self.locks = []
        self.spawns = [(self.generation, self.now)]
        self.inputs = []
        self.carryover = 0
        self.held_overlap = 0
        self.topout = False

    def lock(self, now, hard=False):
        cells = sorted(cellset(self.kind, self.state))
        self.board, lines = settle(self.board, orientations(self.kind)[self.state[2]], *self.state[:2])
        self.locks.append(
            dict(
                time=now,
                generation=self.generation,
                kind=self.kind,
                cells=cells,
                hard=hard,
                lines=lines,
                board=[r[:] for r in self.board],
            )
        )
        self.drops += 1
        self.visible = False
        self.ground_since = None
        self.spawn_due = now + self.entry_s + (self.clear_s if lines else 0)

    def update(self, now):
        if self.topout:
            return
        while True:
            if not self.visible:
                if self.spawn_due > now:
                    break
                at = self.spawn_due
                self.kind = self.queue.pop(0)
                self.state = (3, 0, 0)
                self.generation += 1
                self.visible = True
                self.hold_allowed = True
                self.spawns.append((self.generation, at))
                self.next_fall = at + 1 / self.cps
                if not fits(self.board, orientations(self.kind)[0], 3, 0):
                    self.topout = True
                    break
                # Movement keys repeat on spawn in this worst-case DAS model.
                # Rotation/HOLD/drop are edge-triggered and never auto-repeat.
                for key, gen in self.held_keys.items():
                    if gen != self.generation:
                        self.held_overlap += 1
                        if key in ("left", "right", "down"):
                            self.carryover += 1
                            new = advance(self.board, self.kind, self.state, key)
                            if new is not None:
                                self.state = new
            if self.ground_since is not None and self.ground_since + self.lock_s <= min(now, self.next_fall):
                self.lock(self.ground_since + self.lock_s)
                continue
            if self.next_fall > now:
                break
            at = self.next_fall
            self.next_fall += 1 / self.cps
            new = advance(self.board, self.kind, self.state, "down")
            if new is not None:
                self.state = new
                if advance(self.board, self.kind, self.state, "down") is None:
                    self.ground_since = at
            elif self.ground_since is None:
                self.ground_since = at
        self.now = now

    def image(self):
        return scene(self.board, self.kind if self.visible else None, self.state, self.hold, self.queue[:3], True)

    def key(self, vk, down, expected_generation):
        now = time.monotonic()
        self.update(now)
        reverse = {VK[v]: k for k, v in C["keys"].items()}
        action = reverse[vk]
        if not down:
            self.held_keys.pop(action, None)
            return
        self.held_keys[action] = self.generation
        self.inputs.append(
            dict(
                time=now,
                action=action,
                expected_generation=expected_generation,
                generation=self.generation,
                visible=self.visible,
                state=self.state,
            )
        )
        if not self.visible or self.topout:
            return
        if action == "drop":
            x, y, r = self.state
            p = orientations(self.kind)[r]
            while fits(self.board, p, x, y + 1):
                y += 1
            self.state = (x, y, r)
            self.lock(now, True)
        elif action == "hold" and self.hold_allowed:
            self.kind, self.hold = self.hold or self.queue.pop(0), self.kind
            self.state = (3, 0, 0)
            self.generation += 1
            self.hold_allowed = False
            self.ground_since = None
            self.next_fall = now + 1 / self.cps
            self.spawns.append((self.generation, now))
        elif action != "hold":
            new = advance(self.board, self.kind, self.state, action)
            if new is not None:
                self.state = new
