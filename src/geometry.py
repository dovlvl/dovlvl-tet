"""Pure board search. Coordinates: x right, y down; visible board 10x20."""

from collections import deque
from functools import lru_cache

SHAPES = {
    "I": ((0, 1), (1, 1), (2, 1), (3, 1)),
    "O": ((1, 0), (2, 0), (1, 1), (2, 1)),
    "T": ((1, 0), (0, 1), (1, 1), (2, 1)),
    "J": ((0, 0), (0, 1), (1, 1), (2, 1)),
    "L": ((2, 0), (0, 1), (1, 1), (2, 1)),
    "S": ((1, 0), (2, 0), (0, 1), (1, 1)),
    "Z": ((0, 0), (1, 0), (1, 1), (2, 1)),
}


@lru_cache(maxsize=7)
def orientations(kind):
    p = SHAPES[kind]
    out = []
    for _ in range(4):
        out.append(p)
        p = p if kind == "O" else tuple((3 - y, x) if kind == "I" else (2 - y, x) for x, y in p)
    return tuple(out)


def cellset(kind, state):
    x, y, r = state
    return frozenset((x + a, y + b) for a, b in orientations(kind)[r])


def fits(board, p, x, y):
    return all(0 <= x + a < 10 and 0 <= y + b < 20 and not board[y + b][x + a] for a, b in p)


def settle(board, p, x, y):
    b = [r[:] for r in board]
    for a, c in p:
        b[y + c][x + a] = 1
    remaining = [r for r in b if not all(r)]
    lines = 20 - len(remaining)
    return [[0] * 10 for _ in range(lines)] + remaining, lines


def evaluate(b, lines):
    heights = []
    holes = 0
    for x in range(10):
        first = next((y for y in range(20) if b[y][x]), 20)
        heights.append(20 - first)
        holes += sum(not b[y][x] for y in range(first, 20))
    return (
        3.0 * lines
        - 0.51 * sum(heights)
        - 0.9 * holes
        - 0.25 * sum(abs(a - c) for a, c in zip(heights, heights[1:]))
        - 0.35 * max(heights)
    )


# SRS kick offsets are stored with y positive upward, converted in rotate().
JLSTZ = {
    (0, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (1, 0): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (1, 2): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (2, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (2, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
    (3, 2): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (3, 0): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (0, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
}
IKICKS = {
    (0, 1): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (1, 0): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (1, 2): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
    (2, 1): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (2, 3): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (3, 2): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (3, 0): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (0, 3): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
}


def rotate(board, kind, state, direction=1):
    x, y, r = state
    nr = (r + direction) % 4
    offsets = ((0, 0),) if kind == "O" else (IKICKS if kind == "I" else JLSTZ)[r, nr]
    for index, (dx, dy) in enumerate(offsets):
        if fits(board, orientations(kind)[nr], x + dx, y - dy):
            return (x + dx, y - dy, nr), index
    return None


def advance(board, kind, state, key):
    if key in ("up", "z"):
        result = rotate(board, kind, state, 1 if key == "up" else -1)
        return result[0] if result else None
    x, y, r = state
    x += -1 if key == "left" else 1 if key == "right" else 0
    y += key == "down"
    return (x, y, r) if fits(board, orientations(kind)[r], x, y) else None
