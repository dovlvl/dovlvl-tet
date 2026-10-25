"""Strict local JSON data, not neural learning or a browser automation backend."""

import copy, json, time
from pathlib import Path
from geometry import orientations, fits, settle, cellset
from planner import route_to

KINDS = set("IJLOSTZ")
MIRROR = {"I": "I", "O": "O", "T": "T", "J": "L", "L": "J", "S": "Z", "Z": "S"}


def board_key(board):
    return tuple(tuple(int(bool(v)) for v in row) for row in board)


def compile_book(data):
    if data.get("schema") != "tetris-opener-v1":
        raise ValueError("지원 형식: tetris-opener-v1 JSON")
    if data.get("coordinates") != "visible-10x20-x-right-y-down":
        raise ValueError("좌표 기준 불일치")
    if not data.get("source") or not data.get("name"):
        raise ValueError("출처/빌드명 필수")
    if not isinstance(data.get("variants"), list) or not 1 <= len(data["variants"]) <= 64:
        raise ValueError("변형은 1~64개")
    result = copy.deepcopy(data)
    for variant in result["variants"]:
        if variant.get("order_status") != "explicit":
            raise ValueError("순서 없는 도형은 실행 데이터로 가져올 수 없습니다.")
        if variant.get("hold_policy") != "visible-only-single-hold":
            raise ValueError("HOLD 조건 누락/미지원")
        if not isinstance(variant.get("steps"), list) or not 1 <= len(variant["steps"]) <= 100:
            raise ValueError("단계는 1~100개")
        board = [[0] * 10 for _ in range(20)]
        for step in variant["steps"]:
            kind = step.get("kind")
            cells = step.get("cells")
            if kind not in KINDS or not isinstance(cells, list) or len(cells) != 4:
                raise ValueError("단계 블록/4칸 좌표 오류")
            if any(not isinstance(c, list) or len(c) != 2 or any(type(v) is not int for v in c) for c in cells):
                raise ValueError("정수 셀 좌표 필요")
            dest = frozenset(map(tuple, cells))
            matched = None
            for r, p in enumerate(orientations(kind)):
                x = min(c[0] for c in dest) - min(a for a, b in p)
                y = min(c[1] for c in dest) - min(b for a, b in p)
                if cellset(kind, (x, y, r)) == dest and fits(board, p, x, y) and not fits(board, p, x, y + 1):
                    matched = (x, y, r)
                    break
            if not matched:
                raise ValueError("겹침/공중 배치/도형 불일치: " + str(step))
            if route_to(board, kind, (3, 0, 0), cells) is None:
                raise ValueError("현재 SRS 모델에서 목표 경로 없음: " + kind)
            before = board_key(board)
            x, y, r = matched
            board, lines = settle(board, orientations(kind)[r], x, y)
            if "expected_before" in step and board_key(step["expected_before"]) != before:
                raise ValueError("예상 시작 보드 불일치")
            if "expected_after" in step and board_key(step["expected_after"]) != board_key(board):
                raise ValueError("예상 고정 보드 불일치")
            if "lines" in step and step["lines"] != lines:
                raise ValueError("줄 삭제 불일치")
            step.update(expected_before=before, expected_after=board_key(board), lines=lines, state=matched)
        variant["model_verified"] = True
    result["verification"] = {"model": "paths, occupancy and line clears checked", "real_game": False}
    return result


def load_book(path):
    p = Path(path)
    if p.stat().st_size > 2_000_000:
        raise ValueError("오프너 JSON은 2MB 이하")
    return compile_book(json.loads(p.read_text(encoding="utf-8-sig")))


def mirrored_variant(variant):
    v = copy.deepcopy(variant)
    v["name"] = v["name"] + " / mirror (derived)"
    for step in v["steps"]:
        step["kind"] = MIRROR[step["kind"]]
        step["cells"] = [[9 - x, y] for x, y in step["cells"]]
        for key in ("expected_before", "expected_after", "state", "lines"):
            step.pop(key, None)
    return v


def opener_plan(
    book, index, chosen, board, kind, start, held, queue, hold_used, hold_available, rotation, counterclockwise=False
):
    begin = time.perf_counter()
    key = board_key(board)
    for variant in book["variants"]:
        if chosen and variant["name"] != chosen:
            continue
        if index >= len(variant["steps"]):
            return dict(result=None, reason="OPENER_COMPLETE: 단계별 보드 확인 완료", search_ms=0, nodes=0)
        step = variant["steps"][index]
        if key != board_key(step["expected_before"]):
            continue
        desired = step["kind"]
        use_hold = kind != desired
        if use_hold and (hold_used or not hold_available or (held or (queue[0] if queue else None)) != desired):
            continue
        # Future variants are never selected using unseen queue entries.
        spawn = (3, 0, 0) if use_hold else start
        spin = "none"
        if desired == "T" and step["lines"]:
            path = route_to(board, desired, spawn, step["cells"], rotation, counterclockwise, spin="full")
            if path is not None:
                spin = "full"
            else:
                continue
        else:
            path = route_to(board, desired, spawn, step["cells"], rotation, counterclockwise)
        if path is None:
            continue
        x, y, r = step["state"]
        result = dict(
            kind=desired,
            x=x,
            y=y,
            r=r,
            board=[list(row) for row in step["expected_after"]],
            score=0,
            spin=spin,
            cells=step["cells"],
            hold=use_hold,
            path=path,
            opener_variant=variant["name"],
            expected_after=step["expected_after"],
            lines=step["lines"],
        )
        return dict(result=result, search_ms=(time.perf_counter() - begin) * 1000, nodes=1)
    return dict(
        result=None,
        reason="OPENER_CONDITION_ERROR: 보드/현재 큐/HOLD/도달 경로 불일치. 빌드 중지",
        search_ms=(time.perf_counter() - begin) * 1000,
        nodes=0,
    )
