"""Adaptive, bounded Auto policy. Sources and limits: docs/AUTO_STRATEGY_KO.md."""

from functools import lru_cache
from paths import resource_root
from geometry import board_metrics as metrics
from planner import plan


def position_score(board, lines):
    heights, holes, buried = metrics(board)
    danger = max(heights) >= 12 or holes >= 3
    # Clean side well, but never preserve it at the expense of survival.
    well = min(heights[0], heights[-1])
    clean = not holes and max(heights) < 12
    # Reuse the measured columns instead of walking the entire board again.
    score = (
        0.5 * lines
        - 0.45 * sum(heights)
        - 8 * holes
        - 0.35 * sum(abs(a - b) for a, b in zip(heights, heights[1:]))
        - 0.65 * max(heights)
        - 0.55 * buried
    )
    score -= 1.1 * max(0, max(heights) - 10) ** 2
    # Multiple deep wells force specific unseen pieces. Preserve at most one
    # clean edge well; penalize additional dependencies and top-out exposure.
    for x in range(1, 9):
        depth = min(heights[x - 1], heights[x + 1]) - heights[x]
        score -= 0.6 * max(0, depth - 2) ** 2
    if clean:
        score -= 0.9 * well
        interior = heights[1:] if heights[0] < heights[-1] else heights[:-1]
        score -= 0.15 * sum(abs(a - b) for a, b in zip(interior, interior[1:]))
    # PC emptiness is already represented by zero height/holes. The site does
    # not publish an extra PC score, so no other game's bonus is fabricated.
    return score


def pc_position_score(board, lines):
    """Prefer removing cells and keeping every column low; no reserved well."""
    heights, holes, buried = metrics(board)
    height = max(heights)
    return (
        6 * lines
        - sum(map(sum, board))
        - 0.7 * sum(heights)
        - 14 * holes
        - buried
        - 2 * height
        - 1.5 * max(0, height - 4) ** 2
        - 0.4 * sum(abs(a - b) for a, b in zip(heights, heights[1:]))
    )


@lru_cache(maxsize=1)
def builtin_book():
    from openers import load_book, compile_book, mirrored_variant

    root = resource_root()
    book = load_book(root / "data" / "openers" / "TKI_Fonzie.json")
    book["variants"].append(mirrored_variant(book["variants"][0]))
    return compile_book(book)


def auto_plan(
    board,
    kind,
    start,
    held,
    nexts,
    use_hold,
    allow_hold=True,
    rotation=True,
    previews=False,
    basic_verified=False,
    opening=True,
    budget_ms=160,
    max_depth=4,
    counterclockwise=False,
    input_ms=70,
    timing=None,
    score_state=None,
    goal="score",
):
    """Use only observed previews; never force an opener through a mismatch."""
    prioritize_pc = goal == "perfect_clear"
    if not prioritize_pc and opening and previews and basic_verified and rotation:
        from openers import opener_plan, board_key

        book = builtin_book()
        key = board_key(board)
        for variant in book["variants"]:
            for index, step in enumerate(variant["steps"]):
                if key != step["expected_before"]:
                    continue
                # Require at least the next two visible choices to fit before
                # committing to a setup. No guesses about unseen bag order.
                current = kind
                queue = list(nexts)
                hold = held
                possible = True
                # A setup is not entered on a lucky prefix. Every remaining
                # piece must be accounted for by current/HOLD/observed queue.
                required = variant["steps"][index:]
                for offset, following in enumerate(required):
                    desired = following["kind"]
                    if current != desired:
                        if not use_hold or not allow_hold:
                            possible = False
                            break
                        replacement = hold or (queue.pop(0) if queue else None)
                        if replacement != desired:
                            possible = False
                            break
                        hold = current
                    current = queue.pop(0) if queue else None
                    if current is None and offset < len(required) - 1:
                        possible = False
                        break
                if not possible:
                    continue
                packet = opener_plan(
                    book=book,
                    index=index,
                    chosen=variant["name"],
                    board=board,
                    kind=kind,
                    start=start,
                    held=held,
                    queue=nexts,
                    hold_used=not allow_hold,
                    hold_available=use_hold and allow_hold,
                    rotation=rotation,
                    counterclockwise=counterclockwise,
                )
                if packet["result"]:
                    from geometry import advance
                    from scoring import award
                    from dataclasses import asdict

                    state = (3, 0, 0) if packet["result"]["hold"] else start
                    for action in packet["result"]["path"][:-1]:
                        state = advance(board, packet["result"]["kind"], state, action)
                    projected = award(
                        packet["result"]["lines"],
                        packet["result"].get("spin", "none"),
                        not any(map(any, packet["result"]["board"])),
                        packet["result"]["y"] - state[1],
                        packet["result"]["path"].count("down"),
                        score_state,
                    )
                    projected["scoring_after"] = asdict(projected.pop("score_state"))
                    packet["result"].update(projected)
                    packet["result"]["strategy"] = "TKI / " + variant["name"]
                    return packet
    packet = plan(
        board,
        kind,
        start,
        held,
        nexts,
        use_hold,
        allow_hold,
        rotation,
        scorer=pc_position_score if prioritize_pc else position_score,
        budget_ms=budget_ms,
        max_depth=max_depth,
        beam_width=4 if prioritize_pc else 6,
        counterclockwise=counterclockwise,
        input_ms=input_ms,
        timing=timing,
        score_state=score_state,
        use_points=True,
        prioritize_pc=prioritize_pc,
    )
    if packet["result"]:
        heights, holes, buried = metrics(board)
        packet["result"]["strategy"] = "다운스택" if max(heights) >= 12 or holes >= 3 else "점수 / 평탄 쌓기"
        if prioritize_pc:
            packet["result"]["strategy"] = "PC 준비 / 낮게 줄 지우기"
        if packet["result"].get("spin") in ("full", "mini"):
            packet["result"]["strategy"] = "T-Spin / " + packet["result"]["spin"]
        if packet["result"]["lines"] == 4:
            packet["result"]["strategy"] = "Tetris 4줄"
        if packet["result"]["lines"] and not any(map(any, packet["result"]["board"])):
            packet["result"]["strategy"] = "Perfect Clear"
        elif packet.get("pc_status") == "found_confirmed_queue" and not packet.get("pc_deferred_for_survival"):
            packet["result"]["strategy"] = "PC path / " + str(packet["pc_remaining"]) + " placements"
        packet["result"]["evaluation"] = {
            "goal": goal,
            "heights": heights,
            "holes": holes,
            "buried": buried,
            "utility": packet["result"]["score"],
            "points": packet["result"].get("expected_points"),
            "actual_points": None,
        }
    return packet
