import json, copy
from pathlib import Path

PATH = Path.home() / ".tetris_trainer" / "config_v6.json"
DEFAULT = {
    "basic_auto_verified": False,
    "preview_verified": False,
    "opener_file": "",
    "opener_enabled": False,
    "site_profile": "actual_game",
    "hotkey_toggle": "F6",
    "hotkey_stop": "F8",
    "auto_mode": "continuous",
    "enable_hold": True,
    "rotation_confirmed": True,
    "search_budget_ms": 160,
    "search_depth": 4,
    "save_failure_frames": True,
    "rotation_system": "SRS",
    "lock_delay_verified": False,
    "lock_delay_ms": 0,
    "record_tracking_frames": False,
    "score_level": 1,
    "auto_start_on_launch": False,
    "realtime_search_cap_ms": 60,
    "version": 6,
    "board": None,
    "hold": None,
    "next_slots": [None],
    "keys": {"left": "LEFT", "right": "RIGHT", "down": "DOWN", "up": "UP", "z": "Z", "hold": "C", "drop": "SPACE"},
    "press_ms": 35,
    "gap_ms": 35,
    "ack_ms": 300,
    "uncertain_ms": 3500,
    "transition_ms": 2200,
    "capture_fps": 60,
    "vision_fps": 60,
    "ui_fps": 10,
    "min_s": 0.28,
    "min_v": 0.28,
    "confidence": 0.8,
    "input_countdown": 3,
    "next_default_count": 1,
    "frame_age_ms": 200,
    "plan_age_ms": 500,
}


def load(path=PATH):
    data = copy.deepcopy(DEFAULT)
    try:
        data.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if data.get("auto_ui_version", 0) < 1:
        data.update(auto_ui_version=1, auto_mode="continuous", enable_hold=True, opener_enabled=False)
    if data.get("site_profile") == "actual_game" and not data["keys"].get("hold"):
        data["keys"]["hold"] = "C"
    return data


def validate(c, complete=False):
    if not 1 <= c.get("score_level", 1) <= 30:
        raise ValueError("예측 점수 레벨은 1~30입니다.")
    if c.get("hotkey_toggle", "F6") == c.get("hotkey_stop", "F8"):
        raise ValueError("Hotkey conflict")
    for name in ("hotkey_toggle", "hotkey_stop"):
        if c.get(name, "F6") not in ["F" + str(i) for i in range(1, 25)]:
            raise ValueError("Hotkey: F1~F24")
    if c.get("opener_enabled") and (
        not c.get("preview_verified")
        or not c.get("basic_auto_verified")
        or not c.get("opener_file")
        or c.get("auto_mode") != "continuous"
        or not c.get("rotation_confirmed")
    ):
        raise ValueError(
            "빌드 실행은 기본 Auto/프리뷰 실게임 검증과 JSON 선택, 회전 확인 및 continuous 모드가 필요합니다."
        )
    boxes = []
    for label, box in [("BOARD", c["board"]), ("HOLD", c["hold"])] + [
        (f"NEXT {i + 1}", b) for i, b in enumerate(c["next_slots"])
    ]:
        if box is None:
            if complete and label == "BOARD":
                raise ValueError(label + " 영역을 지정하세요.")
            continue
        if len(box) != 4 or not all(isinstance(v, int) for v in box):
            raise ValueError(label + " 좌표 오류")
        x, y, r, b = box
        if r - x < 15 or b - y < 15:
            raise ValueError(label + " 영역이 너무 작습니다.")
        if label == "BOARD" and not 0.46 <= (r - x) / (b - y) <= 0.54:
            raise ValueError("BOARD는 내부 10×20칸만 지정하세요 (가로:세로=1:2).")
        boxes.append((label, box))
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1 :]:
            if min(ra[2], rb[2]) > max(ra[0], rb[0]) and min(ra[3], rb[3]) > max(ra[1], rb[1]):
                raise ValueError(a + " / " + b + " 영역이 겹칩니다.")
    valid_keys = {"LEFT", "RIGHT", "UP", "DOWN", "SPACE", "SHIFT", "CTRL"} | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    if set(c["keys"]) != set(DEFAULT["keys"]) or any(
        v not in valid_keys and not (k in ("z", "hold") and v == "") for k, v in c["keys"].items()
    ):
        raise ValueError("입력 키는 방향키, SPACE, SHIFT, CTRL, 영문자/숫자로 지정하세요.")
    assigned = [v for v in c["keys"].values() if v]
    if len(set(assigned)) != len(assigned):
        raise ValueError("조작 키를 중복 지정하지 마세요.")
    for k, lo, hi in [
        ("press_ms", 15, 150),
        ("gap_ms", 15, 300),
        ("ack_ms", 100, 1500),
        ("uncertain_ms", 500, 15000),
        ("transition_ms", 500, 8000),
        ("capture_fps", 10, 120),
        ("vision_fps", 10, 120),
        ("ui_fps", 2, 30),
    ]:
        if not lo <= c[k] <= hi:
            raise ValueError(f"{k}: {lo}~{hi} 범위로 지정하세요.")
    for k, lo, hi in [
        ("search_budget_ms", 20, 1000),
        ("search_depth", 1, 7),
        ("input_countdown", 1, 10),
        ("frame_age_ms", 50, 500),
        ("plan_age_ms", 100, 2000),
    ]:
        if not lo <= c.get(k, DEFAULT.get(k)) <= hi:
            raise ValueError(f"{k}: {lo}~{hi}")
    if not 1 <= len(c["next_slots"]) <= 6:
        raise ValueError("NEXT 슬롯은 1~6개입니다.")
    if not 0.05 <= c["min_s"] <= 0.9 or not 0.05 <= c["min_v"] <= 0.95 or not 0.5 <= c["confidence"] <= 0.99:
        raise ValueError("색상/신뢰도 범위 오류")
    ys = [b[1] for b in c["next_slots"] if b]
    if ys != sorted(ys):
        raise ValueError("NEXT 슬롯을 위에서 아래 순서로 지정하세요.")


def save(c, path=PATH):
    validate(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def union(c):
    boxes = [b for b in [c["board"], c["hold"], *c["next_slots"]] if b]
    if not boxes:
        raise ValueError("영역을 먼저 설정하세요.")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
