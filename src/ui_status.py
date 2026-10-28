"""The main window contains only three short, nontechnical statuses."""

import time
from model import ReasonCode, reason_code


def failure_limit_message(reason):
    if reason.startswith("EXECUTION_WINDOW_EXCEEDED:"):
        return "안전한 배치 시간·경로를 확인하지 못해 중지했습니다 (연속 5회 / 블록당 8회 한도)."
    return "입력 확인 반복 실패 (연속 5회 / 블록당 8회): 조작 키/입력 길이/영역을 확인하세요."


def summary(config, session, observation, searching=False, error=False, now=None):
    now = time.monotonic() if now is None else now
    fresh = bool(observation and 0 <= now - observation.captured < 0.6)
    if error or (session and session.error):
        board = "오류"
    elif session and session.visibility_error:
        board = "가려짐"
    elif searching:
        board = "찾는 중"
    elif fresh and observation.valid:
        board = "정상"
    elif fresh and reason_code(observation.reason) == ReasonCode.OCCLUDED:
        board = "가려짐"
    else:
        board = "불확실"
    hold = "불확실"
    if fresh and observation.hold.valid and observation.hold.confidence >= config["confidence"]:
        hold = observation.hold.kind or "비어 있음"
    readings = observation.nexts if fresh else []
    nexts = [r.kind if r.valid and r.kind and r.confidence >= config["confidence"] else "?" for r in readings]
    if not nexts:
        nexts = ["?"] * max(1, len(config["next_slots"]))
    return f"보드: {board}   홀드: {hold}   넥스트: " + " → ".join(nexts)
