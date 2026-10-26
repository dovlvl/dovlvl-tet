import copy
import numpy as np
from PIL import Image, ImageDraw
from config import DEFAULT
from recognition import PALETTE
from geometry import orientations, advance, settle, fits, cellset

C = copy.deepcopy(DEFAULT)
C.update(
    preview_verified=True,
    auto_mode="continuous",
    rotation_confirmed=True,
    board=[0, 0, 200, 400],
    hold=[220, 0, 320, 80],
    next_slots=[[220, 100, 320, 180], [220, 190, 320, 270], [220, 280, 320, 360]],
)
C["keys"]["z"] = "Z"
C["keys"]["hold"] = "C"
# The legacy geometric mock explicitly permits a 5 s lock window. Timed
# gravity/unknown-lock-delay tests use a separate profile and simulator.
C.update(lock_delay_verified=True, lock_delay_ms=5000)
C["allow_stationary_bootstrap"] = True  # Static screenshot fixtures; live default requires motion below spawn.


def scene(board, kind="T", state=(3, 0, 0), held=None, nexts=("I", "L", "O"), ghost=False):
    im = Image.new("RGB", (340, 400), "#101010")
    d = ImageDraw.Draw(im)
    for y, row in enumerate(board):
        for x, v in enumerate(row):
            if v:
                d.rectangle((x * 20 + 1, y * 20 + 1, x * 20 + 18, y * 20 + 18), fill=PALETTE["J"])
    if kind:
        if ghost:
            x, y, r = state
            p = orientations(kind)[r]
            while fits(board, p, x, y + 1):
                y += 1
            for a, b in p:
                d.rectangle(
                    ((x + a) * 20 + 1, (y + b) * 20 + 1, (x + a) * 20 + 18, (y + b) * 20 + 18),
                    outline="#007878",
                    width=1,
                )
        for x, y in cellset(kind, state):
            if 0 <= x < 10 and 0 <= y < 20:
                d.rectangle((x * 20 + 1, y * 20 + 1, x * 20 + 18, y * 20 + 18), fill=PALETTE[kind])

    def preview(kind, box):
        if not kind:
            return
        p = orientations(kind)[0]
        x0 = min(x for x, y in p)
        y0 = min(y for x, y in p)
        for x, y in p:
            a = box[0] + 10 + (x - x0) * 18
            b = box[1] + 12 + (y - y0) * 18
            d.rectangle((a, b, a + 16, b + 16), fill=PALETTE[kind])

    preview(held, C["hold"])
    for k, b in zip(nexts, C["next_slots"]):
        preview(k, b)
    return np.array(im)


class FakeBackend:
    def __init__(self, callback=None):
        self.focus = 99
        self.events = []
        self.callback = callback

    def foreground(self):
        return self.focus

    def own_window(self, target):
        return target == 1

    def key(self, vk, down):
        self.events.append((vk, down))
        if down and self.callback:
            self.callback(vk)


class Game:
    def __init__(self):
        self.board = [[0] * 10 for _ in range(20)]
        self.kind = "T"
        self.state = (3, 0, 0)
        self.hold = None
        self.queue = ["I", "L", "O", "S", "Z", "J", "T", "I", "O"] * 8
        self.drops = 0
        self.hold_allowed = True

    def image(self):
        return scene(self.board, self.kind, self.state, self.hold, self.queue[:3], True)

    def input(self, vk):
        from input_win import VK

        reverse = {VK[v]: k for k, v in C["keys"].items()}
        action = reverse[vk]
        if action == "drop":
            x, y, r = self.state
            p = orientations(self.kind)[r]
            while fits(self.board, p, x, y + 1):
                y += 1
            self.board = settle(self.board, p, x, y)[0]
            self.kind = self.queue.pop(0)
            self.state = (3, 0, 0)
            self.drops += 1
            self.hold_allowed = True
        elif action == "hold":
            if self.hold_allowed:
                self.kind, self.hold = self.hold or self.queue.pop(0), self.kind
                self.state = (3, 0, 0)
                self.hold_allowed = False
        else:
            state = advance(self.board, self.kind, self.state, action)
            if state:
                self.state = state


# Synthetic capture timestamps must use the same clock at input freshness checks.
def synthetic_tick(ctl, obs, now):
    from unittest.mock import patch

    with patch("controller.time.monotonic", return_value=now):
        ctl.tick(obs, now)


def synthetic_emit(ctl, action, obs, now):
    from unittest.mock import patch

    with patch("controller.time.monotonic", return_value=now):
        ctl.emit(action, obs, now)


class Source:
    game = None

    def grab(self, box):
        rgb = self.game.image()[: box["height"], : box["width"]]
        a = np.zeros((rgb.shape[0], rgb.shape[1], 4), np.uint8)
        a[:, :, :3] = rgb[:, :, ::-1]
        return a

    def close(self):
        pass
