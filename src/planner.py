"""Bounded visible-queue SRS search. Utility is never game points."""

from collections import deque
from functools import lru_cache
from time import perf_counter
from geometry import orientations, advance, fits, settle, evaluate, IKICKS, JLSTZ, cellset, hard_drop
from scoring import tspin, award, ScoreState, SITE_RULES
from dataclasses import asdict


class BudgetExpired(Exception):
    pass


def check(deadline):
    if deadline is not None and perf_counter() >= deadline:
        raise BudgetExpired()


def pc_row_bound(board, left):
    """Necessary condition only; deliberately not a height-based proof."""
    cells_left = sum(map(sum, board)) + 4 * left
    return cells_left >= 10 and sum(bool(any(row)) for row in board) <= cells_left // 10


def landings(
    board,
    kind,
    start=(3, 0, 0),
    rotation=True,
    scorer=evaluate,
    deadline=None,
    counterclockwise=False,
    initial_rotation=None,
):
    shapes = orientations(kind)
    if not fits(board, shapes[start[2]], *start[:2]):
        return []
    masks = tuple(sum(1 << x for x, v in enumerate(row) if v) for row in board)

    @lru_cache(maxsize=None)
    def valid(x, y, r):
        return all(0 <= x + a < 10 and 0 <= y + b < 20 and not masks[y + b] & (1 << (x + a)) for a, b in shapes[r])

    spin_sensitive = kind == "T"
    initial_rotation = initial_rotation or (False, 0)
    q = deque([(start, (), initial_rotation)])
    seen = {(start, initial_rotation) if spin_sensitive else start}
    result = {}
    count = 0
    drops = {}
    actions = (
        ("left", "right")
        + (("up",) if rotation and kind != "O" else ())
        + (("z",) if rotation and counterclockwise else ())
        + ("down",)
    )
    while q:
        count += 1
        if count % 32 == 0:
            check(deadline)
        (x, y, r), path, rotation_meta = q.popleft()
        dy = drops.get((x, y, r))
        if dy is None:
            dy = y
            while valid(x, dy + 1, r):
                dy += 1
            for yy in range(y, dy + 1):
                drops[x, yy, r] = dy
        cells = cellset(kind, (x, dy, r))
        spin = tspin(board, kind, (x, dy, r), *rotation_meta, drop_distance=dy - y) if spin_sensitive else "none"
        result_key = (cells, spin)
        if result_key not in result:
            b, lines = settle(board, shapes[r], x, dy)
            result[result_key] = dict(
                kind=kind,
                x=x,
                y=dy,
                r=r,
                cells=sorted(cells),
                board=b,
                lines=lines,
                path=path + ("drop",),
                score=scorer(b, lines),
                spin=spin,
                hard_distance=dy - y,
                soft_distance=path.count("down"),
                rotation_meta=rotation_meta,
            )
        for action in actions:
            if action in ("up", "z"):
                nr = (r + (1 if action == "up" else -1)) % 4
                offsets = ((0, 0),) if kind == "O" else (IKICKS if kind == "I" else JLSTZ)[r, nr]
                hit = next(
                    (((x + dx, y - dy, nr), i) for i, (dx, dy) in enumerate(offsets) if valid(x + dx, y - dy, nr)), None
                )
                new = hit[0] if hit else None
                new_meta = (True, hit[1]) if hit else (False, 0)
            else:
                nx = x + (-1 if action == "left" else 1 if action == "right" else 0)
                ny = y + (action == "down")
                new = (nx, ny, r) if valid(nx, ny, r) else None
                new_meta = (False, 0)
            key = (new, new_meta) if spin_sensitive else new
            if new is not None and key not in seen:
                seen.add(key)
                q.append((new, path + (action,), new_meta))
    return list(result.values())


@lru_cache(maxsize=2048)
def _route(board, kind, start, target, rotation, counterclockwise):
    dest = frozenset(target)
    q = deque([(start, ())])
    seen = {start}
    actions = (
        ("left", "right")
        + (("up",) if rotation and kind != "O" else ())
        + (("z",) if rotation and counterclockwise else ())
        + ("down",)
    )
    while q:
        state, path = q.popleft()
        x, y, r = state
        p = orientations(kind)[r]
        y = hard_drop(board, p, x, y)
        if cellset(kind, (x, y, r)) == dest:
            return path + ("drop",)
        for action in actions:
            new = advance(board, kind, state, action)
            if new is not None and new not in seen:
                seen.add(new)
                q.append((new, path + (action,)))
    return None


def route_to(board, kind, start, target, rotation=True, counterclockwise=False, spin=None, initial_rotation=None):
    if spin and spin != "none":
        choices = [
            a
            for a in landings(
                board, kind, start, rotation, counterclockwise=counterclockwise, initial_rotation=initial_rotation
            )
            if frozenset(map(tuple, a["cells"])) == frozenset(map(tuple, target)) and a["spin"] == spin
        ]
        return min((a["path"] for a in choices), key=len, default=None)
    return _route(
        tuple(map(tuple, board)), kind, tuple(start), tuple(sorted(map(tuple, target))), rotation, counterclockwise
    )


def basic_candidates(
    board, kind, start, rotation=True, counterclockwise=False, scorer=evaluate, deadline=None, timing=None
):
    """Small complete-input proposals before deeper BFS/PC work; no soft drops."""
    from timing import route_feasible

    if not fits(board, orientations(kind)[start[2]], *start[:2]):
        return []
    results = {}
    turns = [()]
    if rotation and kind != "O":
        turns += [("up",) * n for n in range(1, 4)]
    if rotation and counterclockwise and kind != "O":
        turns += [("z",) * n for n in range(1, 4)]
    for turn in turns:
        for offset in (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8, -9, 9):
            if deadline is not None and perf_counter() >= deadline:
                return list(results.values())
            path = turn + (("left",) * -offset if offset < 0 else ("right",) * offset)
            state = start
            for action in path:
                state = advance(board, kind, state, action)
                if state is None:
                    break
            if state is None:
                continue
            x, y, r = state
            p = orientations(kind)[r]
            y = hard_drop(board, p, x, y)
            cells = cellset(kind, (x, y, r))
            path += ("drop",)
            if cells in results:
                continue
            if timing and not route_feasible(board, kind, start, path, cells, timing)[0]:
                continue
            b, lines = settle(board, p, x, y)
            results[cells] = dict(
                kind=kind,
                x=x,
                y=y,
                r=r,
                cells=sorted(cells),
                board=b,
                lines=lines,
                path=path,
                score=scorer(b, lines),
                hold=False,
                depth=1,
                spin="none",
                hard_distance=y - state[1],
                soft_distance=0,
            )
    return list(results.values())


def urgent_plan(
    board, kind, start, rotation=True, counterclockwise=False, scorer=evaluate, budget_ms=4, timing=None, next_kind=None
):
    begin = perf_counter()
    candidates = basic_candidates(
        board, kind, start, rotation, counterclockwise, scorer, begin + budget_ms / 1000, timing
    )
    spawn_kinds = (next_kind,) if next_kind and next_kind in "IJLOSTZ" else tuple("IJLOSTZ")
    candidates = [a for a in candidates if all(fits(a["board"], orientations(k)[0], 3, 0) for k in spawn_kinds)]
    best = max(candidates, key=lambda a: a["score"] - 0.01 * len(a["path"]), default=None)
    if best:
        best.update(strategy="Time-bounded survival", expected_points=None)
    return dict(
        result=best,
        search_ms=(perf_counter() - begin) * 1000,
        nodes=len(candidates),
        budget_ms=budget_ms,
        depth=1,
        pc_status="not_searched_execution_window",
        fallback_reason="Observed gravity leaves insufficient time for deep search",
        timing=timing,
    )


def plan(
    board,
    kind,
    start,
    held,
    nexts,
    use_hold,
    allow_hold=True,
    rotation=True,
    scorer=evaluate,
    budget_ms=160,
    max_depth=4,
    beam_width=6,
    counterclockwise=False,
    input_ms=70,
    timing=None,
    score_state=None,
    use_points=False,
):
    begin = perf_counter()
    deadline = begin + budget_ms / 1000
    queue = []
    for k in nexts:
        if k not in ("I", "J", "L", "O", "S", "T", "Z"):
            break
        queue.append(k)
    horizon = min(max_depth, 1 + len(queue))
    cache = {}
    nodes = 0
    rotated = 0
    held_candidates = 0
    max_seen = 0
    score_state = score_state or ScoreState()
    input_cost = 0.01 * input_ms if use_points else 0.0004 * input_ms

    def enrich(a, state):
        if not use_points:
            return a, state, 0
        event = award(
            a["lines"],
            a.get("spin", "none"),
            not any(map(any, a["board"])),
            a.get("hard_distance", 0),
            a.get("soft_distance", 0),
            state,
        )
        following = event.pop("score_state")
        event["scoring_after"] = asdict(following)
        return dict(a, **event), following, event["expected_points"] / max(1, state.level) / 25

    def spawn_safe(b, q):
        if not any(b[0]) and not any(b[1]):
            return True
        known = (q[0],) if q else tuple("IJLOSTZ")
        return all(fits(b, orientations(k)[0], 3, 0) for k in known)

    raw_scorer = scorer

    @lru_cache(maxsize=16384)
    def cached_score(b, lines):
        return raw_scorer(b, lines)

    def scorer(b, lines):
        return cached_score(tuple(map(tuple, b)), lines)

    def options(b, k, s):
        nonlocal nodes, rotated
        key = (tuple(map(tuple, b)), k, s)
        if key not in cache:
            check(deadline)
            # Complete root reachability; bounded lookahead uses fast legal
            # rotation/translation routes. T spin slots retain full BFS.
            if use_points and b != board and k != "T":
                cache[key] = basic_candidates(b, k, s, rotation, counterclockwise, scorer, deadline)
            else:
                cache[key] = landings(b, k, s, rotation, scorer, deadline, counterclockwise)
            nodes += len(cache[key])
            rotated += sum("up" in a["path"] or "z" in a["path"] for a in cache[key])
        return cache[key]

    def branches(b, k, h, q, can, s):
        nonlocal held_candidates
        choices = [(k, h, q, False, s)]
        # Same-kind filled swaps cannot improve a state and cannot be visually
        # acknowledged reliably. Empty HOLD still consumes a confirmed preview.
        if use_hold and can and (h or q) and (h != k or s[1] >= 6):
            choices.append((h or q[0], k, q if h else q[1:], True, (3, 0, 0)))
        for piece, nh, nq, hold, spawn in choices:
            for a in options(b, piece, spawn):
                if not spawn_safe(a["board"], nq):
                    continue
                if timing and b == board and k == kind and s == start:
                    from timing import route_feasible

                    if hold:
                        from timing import drop_distance

                        available = (
                            drop_distance(board, k, s) / timing["gravity_cps"] * 1000
                            if timing.get("gravity_cps")
                            else float("inf")
                        )
                        if available <= timing.get("age_ms", 0) + timing.get("step_ms", 70):
                            continue
                    elif not route_feasible(b, piece, spawn, a["path"], a["cells"], timing)[0]:
                        continue
                if hold:
                    held_candidates += 1
                yield dict(a, hold=hold), nh, nq

    best = None
    if not timing and fits(board, orientations(kind)[start[2]], *start[:2]):
        x, y, r = start
        y = hard_drop(board, orientations(kind)[r], x, y)
        b, l = settle(board, orientations(kind)[r], x, y)
        best = dict(
            kind=kind,
            x=x,
            y=y,
            r=r,
            cells=sorted(cellset(kind, (x, y, r))),
            board=b,
            lines=l,
            path=("drop",),
            score=scorer(b, l),
            hold=False,
            depth=1,
        )
        if not spawn_safe(b, queue):
            best = None
    initial = basic_candidates(
        board,
        kind,
        start,
        rotation,
        counterclockwise,
        scorer,
        min(deadline, begin + min(10, budget_ms * 0.15) / 1000),
        timing,
    )
    if use_hold and allow_hold and (held or queue) and (held != kind or start[1] >= 6):
        replacement = held or queue[0]
        held_initial = basic_candidates(
            board,
            replacement,
            (3, 0, 0),
            rotation,
            counterclockwise,
            scorer,
            min(deadline, begin + min(18, budget_ms * 0.25) / 1000),
        )
        initial.extend(dict(a, hold=True) for a in held_initial)
    initial = [a for a in initial if spawn_safe(a["board"], queue[1:] if a["hold"] and not held else queue)]
    if use_points:
        priced = []
        for a in initial:
            enriched, _, points = enrich(a, score_state)
            priced.append(dict(enriched, score=a["score"] + points - input_cost * (len(a["path"]) + a["hold"])))
        initial = priced
    if initial:
        best = max(initial, key=lambda a: a["score"] - 0.01 * len(a["path"]))
    pc_path = None
    timed_out = False
    pc_exhausted = False
    completed_depth = 0
    occupancy = sum(map(sum, board))
    targets = [d for d in range(1, horizon + 1) if (occupancy + 4 * d) % 10 == 0]
    pc_deadline = begin + budget_ms * 0.45 / 1000
    failed = set()

    def pc(b, k, h, q, can, s, left, path):
        nonlocal max_seen
        check(pc_deadline)
        max_seen = max(max_seen, len(path))
        # Every nonempty row must be deleted. Empty gaps between occupied
        # rows need not be cleared, so absolute stack height is not a proof.
        if not pc_row_bound(b, left):
            return None
        key = (tuple(map(tuple, b)), k, h, tuple(q), can, s, left)
        if key in failed:
            return None
        for a, nh, nq in sorted(branches(b, k, h, q, can, s), key=lambda e: e[0]["score"], reverse=True):
            check(pc_deadline)
            trail = path + [a]
            if a["lines"] and not any(map(any, a["board"])):
                return trail
            if left > 1 and nq:
                found = pc(a["board"], nq[0], nh, nq[1:], True, (3, 0, 0), left - 1, trail)
                if found:
                    return found
        failed.add(key)
        return None

    try:
        for depth in targets:
            pc_path = pc(board, kind, held, queue, allow_hold, start, depth, [])
            if pc_path:
                break
        pc_exhausted = pc_path is None
    except BudgetExpired:
        timed_out = True
    frontier = [(board, kind, held, queue, allow_hold, start, [], 0, score_state)]
    try:
        for depth in range(1, horizon + 1):
            expanded = []
            seen = set()
            for b, k, h, q, can, s, trail, reward, scoring in frontier:
                for a, nh, nq in branches(b, k, h, q, can, s):
                    check(deadline)
                    a, following, points = enrich(a, scoring)
                    newtrail = trail + [a]
                    total = reward + scorer(a["board"], a["lines"]) - scorer(a["board"], 0) + points
                    val = scorer(a["board"], 0) + total - input_cost * sum(len(p["path"]) + p["hold"] for p in newtrail)
                    state = (tuple(map(tuple, a["board"])), nh, tuple(nq), following)
                    if state in seen:
                        continue
                    seen.add(state)
                    expanded.append((val, a, nh, nq, newtrail, total, following))
                    if depth == 1 and (best is None or val > best["score"]):
                        best = dict(a, score=val, depth=1)
            if not expanded:
                break
            expanded.sort(key=lambda e: e[0], reverse=True)
            val, a, nh, nq, trail, total, following = expanded[0]
            best = dict(
                trail[0],
                score=val,
                depth=depth,
                next_hint=None,
                continuation=[dict(kind=p["kind"], cells=p["cells"], hold=p["hold"], lines=p["lines"]) for p in trail],
            )
            completed_depth = depth
            max_seen = max(max_seen, depth)
            frontier = [
                (a["board"], nq[0], nh, nq[1:], True, (3, 0, 0), trail, total, following)
                for val, a, nh, nq, trail, total, following in expanded[:beam_width]
                if nq
            ]
            if not frontier:
                break
    except BudgetExpired:
        timed_out = True
    height = max((20 - y for y, row in enumerate(board) if any(row)), default=0)
    pc_deferred = bool(pc_path and height >= 12 and len(pc_path) > 1)
    if pc_path and not pc_deferred:
        projected = []
        state = score_state
        pc_reward = 0
        for a in pc_path:
            enriched, state, points = enrich(a, state)
            projected.append(enriched)
            pc_reward += scorer(a["board"], a["lines"]) - scorer(a["board"], 0) + points
        pc_value = (
            scorer(pc_path[-1]["board"], 0) + pc_reward - input_cost * sum(len(a["path"]) + a["hold"] for a in pc_path)
        )
        if not use_points or best is None or pc_value >= best["score"]:
            best = dict(
                projected[0],
                score=pc_value,
                depth=len(pc_path),
                next_hint=None,
                continuation=[
                    dict(kind=a["kind"], cells=a["cells"], hold=a["hold"], lines=a["lines"]) for a in pc_path
                ],
            )
        else:
            pc_deferred = True
    status = "found_confirmed_queue" if pc_path else "exhausted_within_horizon" if pc_exhausted else "time_limit"
    if best:
        best.setdefault("depth", 1)
        best.setdefault("next_hint", None)
        if not use_points:
            best.update(expected_points=None, points_reason="Utility-only evaluator")
        best.update(
            input_count=len(best["path"]) + int(best["hold"]),
            estimated_input_ms=input_ms * (len(best["path"]) + int(best["hold"])),
        )
    return dict(
        result=best,
        search_ms=(perf_counter() - begin) * 1000,
        nodes=nodes,
        rotation_candidates=rotated,
        hold_candidates=held_candidates,
        depth=max_seen,
        completed_depth=completed_depth,
        budget_ms=budget_ms,
        visible_next=queue,
        pc_status=status,
        pc_remaining=len(pc_path) if pc_path else 0,
        pc_path=[dict(kind=a["kind"], cells=a["cells"], hold=a["hold"], lines=a["lines"]) for a in pc_path]
        if pc_path
        else [],
        pc_horizon=horizon,
        pc_targets=targets,
        pc_future="unknown_beyond_observed_queue",
        pc_deferred_for_survival=pc_deferred,
        timed_out=timed_out,
        fallback_reason="High board: survival"
        if pc_deferred
        else ""
        if pc_path
        else "PC " + status + "; survival/line utility, points unverified",
    )
