"""Closed-loop controller: one acknowledged action at a time."""

import time, logging
from geometry import advance, settle, orientations, cellset, hard_drop, kick_offsets
from planner import route_to, landings, BudgetExpired
from timing import route_feasible, timing_profile, is_stale
from scoring import ScoreState, award, tspin
from model import Phase, PendingAction


class AutoController:
    def __init__(self, pulse, config):
        self.pulse = pulse
        self.c = config
        self.running = False
        self.phase = Phase.STOPPED
        self.reason = "중지됨"
        self.last_seq = -1
        self.hold_used = False
        self.failures = 0
        self.plan = None
        self.wait = None
        self.uncertain_since = None
        self.block_failures = 0
        self.diagnostic = False
        self.last_input = ""
        self.last_ack = ""
        self.frame_age_ms = 0
        self.blocks = 0
        self.raw_diagnostic = None
        self.opener_variant = None
        self.telemetry = None
        self.route_tail = None
        self.block_started = None
        self.started_at = None
        self.vision_paused = False
        self.vision_epoch = 0
        self.vision_phase = Phase.WAIT_VALID
        self.current_generation = None
        self.last_motion_cps = 0
        self.ack_bound_ms = 0
        self.hold_ack_bound_ms = 0
        self.drop_ack_bound_ms = 0
        self.urgent_requested = False
        self.execution_retry_seq = -1
        self.score_state = ScoreState()
        self.projected_points = 0
        self.last_rotation_meta = (False, 0)
        self.soft_distance = 0
        self.last_scoring_event = None

    def start(self, target, now):
        self.vision_paused = False
        self.vision_epoch = self.vision_epoch + 1
        self.score_state = ScoreState(level=self.c.get("score_level", 1))
        self.projected_points = 0
        self.last_rotation_meta = (False, 0)
        self.soft_distance = 0
        if self.pulse.backend.own_window(target):
            raise ValueError("게임 창을 클릭하고 F6을 누르세요.")
        logging.info("Auto start target=%s", target)
        self.current_generation = None
        self.last_motion_cps = 0
        self.ack_bound_ms = 0
        self.hold_ack_bound_ms = 0
        self.drop_ack_bound_ms = 0
        self.urgent_requested = False
        self.execution_retry_seq = -1
        self.blocks = 0
        self.raw_diagnostic = None
        self.opener_variant = None
        self.block_started = now
        self.started_at = now
        self.route_tail = None
        if self.telemetry:
            self.telemetry.reset_run()
        self.pulse.arm(target)
        self.block_failures = 0
        self.diagnostic = False
        self.running = True
        self.phase = Phase.WAIT_VALID
        self.reason = "유효 상태 대기"
        self.hold_used = False
        self.failures = 0
        self.wait = None
        self.plan = None
        self.uncertain_since = now
        self.last_seq = -1

    def stop(self, reason="사용자 중지"):
        if self.running or self.reason != reason:
            logging.info("Controller stop: %s", reason)
        self.running = False
        self.urgent_requested = False
        self.phase = Phase.STOPPED
        self.reason = reason
        self.plan = None
        self.wait = None
        self.pulse.cancel()

    def replan(self, reason, count_failure=True):
        self.plan = None
        self.wait = None
        self.phase = Phase.WAIT_VALID
        self.reason = reason
        self.last_ack = reason
        if count_failure:
            self.failures += 1
            self.block_failures += 1
        if self.failures >= 5 or self.block_failures >= 8:
            self.stop("입력 확인 반복 실패 (연속 5회 / 블록당 8회): 조작 키/입력 길이/영역을 확인하세요.")

    def accept_plan(self, packet, obs):
        if not self.running or self.pulse.abort.is_set() or not obs or not obs.active:
            return
        if packet["key"] != (obs.board_key, obs.active.kind, self.hold_used):
            return
        if packet["result"] is None:
            self.stop(packet.get("reason", "현재 상태에서 배치 경로를 찾지 못했습니다."))
            return
        if packet.get("generation", obs.generation) != obs.generation:
            return
        if not self.wait and obs.valid:
            self.vision_paused = False
            self.uncertain_since = None
        self.plan = dict(packet["result"])
        self.plan["_board_key"] = obs.board_key
        self.plan["_kind"] = obs.active.kind
        self.plan["_generation"] = obs.generation
        self.route_tail = None
        if self.telemetry:
            self.telemetry.record(
                "decision",
                packet=packet,
                observation={
                    "seq": obs.seq,
                    "current": obs.active.kind,
                    "hold": obs.hold.__dict__,
                    "next": [r.__dict__ for r in obs.nexts],
                    "confidence": obs.confidence,
                },
            )
        self.opener_variant = self.plan.get("opener_variant", self.opener_variant)
        self.phase = Phase.DECIDE
        self.reason = "배치 결정 완료"

    def invalid_observation(self, obs, now):
        return obs is None or is_stale(obs, now, self.c) or (not obs.valid) or (obs.confidence < self.c["confidence"])

    def execution_window_failed(self, reason, obs):
        self.pulse.release_all()
        if not self.running:
            return
        if self.diagnostic or self.c.get("opener_enabled", False):
            self.stop(reason)
            return
        self.route_tail = None
        self.execution_retry_seq = obs.seq
        self.urgent_requested = True
        self.replan(reason)

    def drop_state(self, obs):
        x, y, r = obs.active.state
        p = orientations(obs.active.kind)[r]
        y = hard_drop(obs.fixed, p, x, y)
        return x, y, r, p

    def tick(self, obs, now):
        if not self.running:
            return
        try:
            self.pulse.tick(now)
            if obs and obs.gravity_cps > 0:
                self.last_motion_cps = obs.gravity_cps
            if obs and obs.active and obs.confidence >= self.c["confidence"]:
                previous = obs.generation if self.current_generation is None else self.current_generation
                if previous != obs.generation:
                    self.last_rotation_meta = (False, 0)
                    self.soft_distance = 0
                    self.pulse.release_all()
                    self.route_tail = None
                    expected = self.wait and (
                        (self.wait.action == "drop" and obs.transition == "lock")
                        or (self.wait.action == "hold" and obs.board_key == self.wait.before.board_key)
                    )
                    if not expected:
                        self.plan = None
                        self.wait = None
                        self.phase = Phase.WAIT_VALID
                        self.reason = "GENERATION_CHANGED: old plan and pending keys cancelled"
                        if obs.transition == "lock":
                            self.hold_used = False
                    if self.telemetry:
                        self.telemetry.record(
                            "generation_change",
                            previous=previous,
                            current=obs.generation,
                            transition=obs.transition,
                            captured=obs.captured,
                            state=obs.active.state,
                        )
                self.current_generation = obs.generation
            if self.raw_diagnostic:
                action, started = self.raw_diagnostic
                if not self.pulse.focused():
                    self.stop("진단 포커스 상실")
                    return
                if now - started > max(0.5, (self.c["press_ms"] + self.c["gap_ms"]) / 1000):
                    self.last_ack = "확인 불가: 단일 키 API 전송 완료. 게임판 클릭/키 설정 확인 필요"
                    self.stop(self.last_ack)
                return
            if not self.pulse.focused():
                self.stop("게임 창 포커스 상실")
                return
            invalid = self.invalid_observation(obs, now)
            recoverable = not self.diagnostic and not self.c.get("opener_enabled", False)
            if recoverable and invalid:
                if not self.vision_paused:
                    self.vision_phase = self.phase
                    self.vision_paused = True
                    self.vision_epoch = self.vision_epoch + 1
                if self.wait and now - self.wait.sent > self.c["transition_ms"] / 1000:
                    action = self.wait.action
                    if action == "hold":
                        self.hold_used = True
                    self.wait = None
                    self.plan = None
                    self.last_ack = action + " 전환 확인 시간 초과: 이전 대기 폐기, 최신 블록 재동기화 대기"
                    if self.telemetry:
                        self.telemetry.record("transition_expired", action=action, seq=obs.seq if obs else None)
                if not self.wait:
                    self.plan = None
                self.route_tail = None
                self.phase = Phase.VISION_WAIT
                self.uncertain_since = self.uncertain_since or now
                self.reason = "인식 복구 대기: 키 입력 중지, 화면이 안정되면 자동 재탐색"
                self.pulse.release_all()
                return
            if recoverable and self.vision_paused:
                # Brief clear/spawn animations still need their pending drop or
                # HOLD acknowledgement; otherwise confirmed locks are lost.
                if self.wait and now - self.wait.sent <= self.c["transition_ms"] / 1000:
                    self.vision_paused = False
                    self.uncertain_since = None
                    self.phase = self.vision_phase
                    self.last_seq = obs.seq
                    self.verify(obs, now)
                    return
                if self.wait and self.wait.action == "hold":
                    self.hold_used = True
                self.vision_paused = False
                self.uncertain_since = None
                self.replan("인식 복구 완료: 현재 화면에서 배치 재탐색", count_failure=False)
                self.last_seq = obs.seq
                return
            if (
                self.wait
                and now - self.wait.sent > self.c["transition_ms"] / 1000
                and self.phase in ("WAIT_DROP", "WAIT_HOLD")
            ):
                reason = "INPUT_CONFIRMATION_ERROR: 드롭/홀드 후 새 상태를 확인하지 못했습니다."
                if self.diagnostic and self.wait.action == "hold" and not self.hold_clear(self.wait.before):
                    reason = "RECOGNITION_ERROR: 홀드 키는 보냈으나 프리뷰 불확실 및 현재 블록의 명확한 교체 변화가 없어 성공 판정 불가"
                self.stop(reason)
                return
            if self.invalid_observation(obs, now):
                self.uncertain_since = self.uncertain_since or now
                self.reason = (
                    obs.reason if obs and obs.reason else "RECOGNITION_ERROR: BOARD/현재 블록 불확실 또는 오래된 프레임"
                )
                # Release early on uncertainty, never keep pressing while blind.
                self.pulse.release_all()
                speed = self.last_motion_cps
                tracking_limit = (
                    max(0.2, min(self.c["uncertain_ms"] / 1000, 6 / speed)) if speed else self.c["uncertain_ms"] / 1000
                )
                if self.wait and self.wait.action in ("drop", "hold"):
                    # Expected clear/entry/hold animation is a transition with
                    # all keys released, not permission to send another input.
                    tracking_limit = max(tracking_limit, self.c["transition_ms"] / 1000)
                    self.reason = "TRANSITION_WAIT: awaiting observed fixed board/replacement piece"
                if speed and now - self.uncertain_since > tracking_limit:
                    self.stop(
                        f"TRACKING_WINDOW_EXCEEDED: no valid piece for {tracking_limit * 1000:.0f} ms; observed gravity {speed:.1f} cells/s"
                    )
                    return
                if now - self.uncertain_since > self.c["uncertain_ms"] / 1000:
                    self.stop("인식 대기 시간 초과: " + self.reason)
                return
            self.uncertain_since = None
            if obs.seq == self.last_seq:
                return
            self.last_seq = obs.seq
            if self.telemetry:
                self.telemetry.record(
                    "control_observation",
                    seq=obs.seq,
                    captured=obs.captured,
                    generation=obs.generation,
                    state=obs.active.state,
                    gravity_cps=obs.gravity_cps,
                    fall_ms=obs.fall_ms,
                    phase=self.phase,
                )
            if self.wait:
                self.verify(obs, now)
                return
            if self.plan is None:
                self.phase = Phase.WAIT_VALID
                return
            if self.plan.get("_generation", obs.generation) != obs.generation:
                self.replan("STALE_GENERATION: placement discarded", count_failure=False)
                return
            if self.plan["hold"]:
                if obs.fall_ms is not None and obs.fall_ms <= (now - obs.captured) * 1000 + max(
                    self.c["press_ms"] + self.c["gap_ms"], self.ack_bound_ms, self.hold_ack_bound_ms
                ):
                    self.execution_window_failed("EXECUTION_WINDOW_EXCEEDED: insufficient time to confirm HOLD", obs)
                    return
                if not self.hold_clear(obs):
                    self.replan("프리뷰 불확실: 홀드 없이 재탐색")
                    return
                if self.hold_used:
                    self.replan("한 블록당 홀드 1회 제한")
                    return
                self.emit("hold", obs, now)
                return
            if obs.board_key != self.plan.get("_board_key", obs.board_key) or obs.active.kind != self.plan.get(
                "_kind", obs.active.kind
            ):
                self.replan("OBSERVATION_CHANGED: resynchronize before input")
                return
            route_begin = time.perf_counter()
            path = self.route_tail[1] if self.route_tail and self.route_tail[0] == obs.active.cells else None
            if not path and self.plan.get("path"):
                # A cached path is only a proposal: replay against the observed
                # board/state, including gravity, before using its first key.
                proposal = tuple(self.plan["path"])
                state = obs.active.state
                if proposal[-1:] == ("drop",):
                    for action in proposal[:-1]:
                        state = advance(obs.fixed, obs.active.kind, state, action)
                        if state is None:
                            break
                    if state is not None:
                        x, y, r = state
                        p = orientations(obs.active.kind)[r]
                        y = hard_drop(obs.fixed, p, x, y)
                        if cellset(obs.active.kind, (x, y, r)) == frozenset(map(tuple, self.plan["cells"])):
                            path = proposal
                self.plan.pop("path", None)
            if not path:
                path = route_to(
                    obs.fixed,
                    obs.active.kind,
                    obs.active.state,
                    self.plan["cells"],
                    self.c.get("rotation_confirmed", True),
                    bool(self.c["keys"].get("z")),
                    self.plan.get("spin"),
                    self.last_rotation_meta,
                )
            if self.telemetry:
                self.telemetry.add("route_ms", (time.perf_counter() - route_begin) * 1000)
            self.route_tail = None
            if path:
                safe, why = route_feasible(
                    obs.fixed,
                    obs.active.kind,
                    obs.active.state,
                    path,
                    self.plan["cells"],
                    timing_profile(obs, self.c, (now - obs.captured) * 1000, self.ack_bound_ms),
                )
                if not safe:
                    self.execution_window_failed("EXECUTION_WINDOW_EXCEEDED: " + why, obs)
                    return
            if path and path[0] != "drop":
                expected = advance(obs.fixed, obs.active.kind, obs.active.state, path[0])
                if expected:
                    self.route_tail = (cellset(obs.active.kind, expected), path[1:])
            if path is None:
                self.replan("중력/지형 변화: 현재 위치에서 경로 재탐색")
                return
            self.emit(path[0], obs, now)
        except Exception as e:
            logging.exception("controller failed")
            self.stop("입력/제어 오류: " + str(e))

    def emit(self, action, obs, now):
        if obs is None or obs.active is None:
            raise ValueError("RECOGNITION_ERROR: 현재 블록 없이 입력할 수 없습니다.")
        age = (time.monotonic() - obs.captured) * 1000
        if self.plan and self.plan.get("_generation", obs.generation) != obs.generation:
            self.replan("STALE_GENERATION_BEFORE_INPUT", count_failure=False)
            return
        self.pulse.expected_generation = obs.generation
        if age > self.c.get("frame_age_ms", 200):
            self.reason = "RECOGNITION_ERROR: 입력 직전 프레임 나이 초과"
            return
        if action == "drop" and self.plan and "expected_after" in self.plan:
            x, y, r, p = self.drop_state(obs)
            expected = tuple(tuple(row) for row in settle(obs.fixed, p, x, y)[0])
            if expected != tuple(tuple(row) for row in self.plan["expected_after"]):
                self.stop("OPENER_BOARD_ERROR: 예상 고정 보드 불일치")
                return
        if action == "drop" and self.plan and self.plan.get("spin", "none") != "none":
            from timing import drop_distance

            actual = tspin(
                obs.fixed,
                obs.active.kind,
                obs.active.state,
                *self.last_rotation_meta,
                drop_distance=drop_distance(obs.fixed, obs.active.kind, obs.active.state),
            )
            if actual != self.plan["spin"]:
                self.replan("SPIN_ROUTE_CHANGED: 실제 회전 판정 경로 재탐색", count_failure=False)
                return
        if not self.pulse.press(self.c["keys"][action], now, self.c["press_ms"], self.c["gap_ms"]):
            return
        sent_clock = time.monotonic()
        self.frame_age_ms = max(0, age)
        self.last_input = action
        self.last_ack = action + " 확인 대기"
        logging.info("Input %s frame_age_ms=%.2f", action, self.frame_age_ms)
        if self.telemetry:
            self.telemetry.add("input_frame_age_ms", age)
            self.telemetry.add("capture_to_input_ms", (sent_clock - obs.captured) * 1000)
            self.telemetry.record(
                "input_sent",
                action=action,
                generation=obs.generation,
                seq=obs.seq,
                captured=obs.captured,
                sent=sent_clock,
                state=obs.active.state,
                frame_age_ms=(sent_clock - obs.captured) * 1000,
                gravity_cps=obs.gravity_cps,
                fall_ms=obs.fall_ms,
            )
        wait = PendingAction(action=action, sent=sent_clock, seq=obs.seq, before=obs)
        if action == "drop":
            x, y, r, p = self.drop_state(obs)
            wait.expected_board = tuple(tuple(row) for row in settle(obs.fixed, p, x, y)[0])
            self.phase = Phase.WAIT_DROP
            wait.score_spin = tspin(
                obs.fixed,
                obs.active.kind,
                (x, y, r),
                *self.last_rotation_meta,
                drop_distance=y - obs.active.state[1],
            )
            wait.hard_distance = y - obs.active.state[1]
        elif action == "hold":
            self.phase = Phase.WAIT_HOLD
        else:
            wait.expected = advance(obs.fixed, obs.active.kind, obs.active.state, action)
            self.phase = Phase.WAIT_ACK
        self.wait = wait
        self.reason = action + " 입력 → 화면 확인 중"

    def verify(self, obs, now):
        w = self.wait
        if obs.seq <= w.seq or obs.captured <= w.sent:
            return
        before = w.before
        action = w.action
        ok = False
        if action == "hold":
            expected = before.hold.kind or (before.queue[0] if before.queue else None)
            ok = (
                obs.hold.valid
                and obs.hold.kind == before.active.kind
                and obs.active.kind == expected
                and obs.board_key == before.board_key
            )
            if self.diagnostic and not self.hold_clear(before):
                ok = (
                    obs.board_key == before.board_key
                    and obs.active.kind != before.active.kind
                    and min(y for x, y in obs.active.cells) <= 3
                )
            # Require a visible change: same-kind swap is intentionally not auto-issued.
            respawned = obs.generation != before.generation and before.active.state[1] >= 6 and obs.active.state[1] <= 2
            ok = ok and (
                obs.hold.kind != before.hold.kind
                or obs.active.kind != before.active.kind
                or obs.queue != before.queue
                or respawned
            )
            expected_queue = before.queue if before.hold.kind else before.queue[1:]
            if expected_queue and all(k != "?" for k in expected_queue):
                ok = ok and obs.queue[: len(expected_queue)] == expected_queue
        elif action == "drop":
            board_changed = obs.board_key != before.board_key
            queue_changed = obs.queue != before.queue
            ok = obs.board_key == w.expected_board and (board_changed or queue_changed)
            # A stable, visibly advanced queue plus a legal alternative landing
            # can recover a missed movement. Prediction never overwrites pixels.
            advanced = board_changed
            advanced = advanced and (not before.queue or before.queue[0] == "?" or obs.active.kind == before.queue[0])
            prefix = before.queue[1:]
            advanced = advanced and (not prefix or "?" in prefix or obs.queue[: len(prefix)] == prefix)
            if not ok and advanced:
                key = obs.board_key
                w.mismatch_hits = w.mismatch_hits + 1 if key == w.mismatch_board else 1
                w.mismatch_board = key
                if w.mismatch_hits >= 3 and not w.resync_checked:
                    w.resync_checked = True
                    try:
                        legal = landings(
                            before.fixed,
                            before.active.kind,
                            before.active.state,
                            self.c.get("rotation_confirmed", True),
                            deadline=time.perf_counter() + 0.03,
                            counterclockwise=bool(self.c["keys"].get("z")),
                        )
                    except BudgetExpired:
                        legal = []
                    if any(tuple(map(tuple, a["board"])) == key for a in legal):
                        w.expected_board = key
                        w.resynchronized = True
                        ok = True
                        if self.telemetry:
                            self.telemetry.record(
                                "legal_landing_resync", seq=obs.seq, observed=obs.fixed, target_match=False
                            )
            if before.queue and before.queue[0] != "?":
                ok = ok and obs.active.kind == before.queue[0]
            expected_queue = before.queue[1:]
            if expected_queue and all(k != "?" for k in expected_queue):
                ok = ok and obs.queue[: len(expected_queue)] == expected_queue
        else:
            expected = w.expected
            if expected is not None and obs.active.kind == before.active.kind and obs.board_key == before.board_key:
                x, y, r = expected
                ok = obs.generation == before.generation and any(
                    cellset(obs.active.kind, (x, y + dy, r)) == obs.active.cells for dy in range(20)
                )
        if ok:
            latency = (now - w.sent) * 1000
            w.hits += 1
            if action in ("hold", "drop") and w.hits < 2:
                return
            # Spawn/clear animations are not movement latency. Keep their
            # measured bounds separate without relaxing per-key screen ACKs.
            if action == "hold":
                self.hold_ack_bound_ms = max(latency, self.hold_ack_bound_ms * 0.95)
            elif action == "drop":
                self.drop_ack_bound_ms = max(latency, self.drop_ack_bound_ms * 0.95)
            else:
                self.ack_bound_ms = max(latency, self.ack_bound_ms * 0.95)
            self.pulse.acknowledged(now, self.c["gap_ms"])
            if action in ("up", "z"):
                old = before.active.state
                expected = w.expected
                offsets = kick_offsets(before.active.kind, old[2], expected[2])
                kick = next((i for i, (dx, dy) in enumerate(offsets) if (old[0] + dx, old[1] - dy) == expected[:2]), 0)
                self.last_rotation_meta = (True, kick)
            elif action not in ("drop",):
                self.last_rotation_meta = (False, 0)
            if action == "down":
                self.soft_distance = self.soft_distance + max(0, obs.active.state[1] - before.active.state[1])
            if self.telemetry:
                self.telemetry.add("input_ack_ms", (now - w.sent) * 1000)
                self.telemetry.add(action + "_ack_ms", (now - w.sent) * 1000)
                self.telemetry.record(
                    "ack",
                    action=action,
                    seq=obs.seq,
                    latency_ms=(now - w.sent) * 1000,
                    prediction_match=obs.prediction_match,
                    board_match=obs.board_key == (w.expected_board if w.expected_board is not None else obs.board_key),
                )
            self.wait = None
            self.failures = 0
            self.last_ack = action + " 실제 화면 변화 확인"
            self.reason = self.last_ack
            if self.diagnostic:
                self.stop("입력 진단 성공: " + self.last_ack)
                return
            if action == "hold":
                self.block_failures = 0
                self.hold_used = True
                # Keep the searched placement only after the observed swap and
                # unchanged fixed board agree. Re-route from actual spawn cells.
                if self.plan and self.plan["kind"] == obs.active.kind and obs.board_key == before.board_key:
                    self.plan["hold"] = False
                    self.plan["_kind"] = obs.active.kind
                    self.plan["_board_key"] = obs.board_key
                    self.plan["_generation"] = obs.generation
                    self.route_tail = None
                    self.phase = Phase.DECIDE
                    if self.telemetry:
                        self.telemetry.record("hold_plan_retained", seq=obs.seq)
                else:
                    self.plan = None
                    self.phase = Phase.WAIT_VALID
            elif action == "drop":
                lines = max(0, min(4, (sum(map(sum, before.fixed)) + 4 - sum(map(sum, obs.fixed))) // 10))
                event = award(
                    lines,
                    "none" if w.resynchronized else w.score_spin,
                    not any(map(any, obs.fixed)),
                    w.hard_distance,
                    self.soft_distance,
                    self.score_state,
                )
                self.score_state = event.pop("score_state")
                self.projected_points = self.projected_points + event["expected_points"]
                self.last_scoring_event = event
                if self.telemetry:
                    self.telemetry.record("confirmed_lock_projection", actual_site_points=None, lines=lines, **event)
                self.last_rotation_meta = (False, 0)
                self.soft_distance = 0
                if w.resynchronized:
                    self.last_ack = "Observed legal alternative landing; prediction mismatch, replanning"
                self.blocks += 1
                if self.telemetry:
                    self.telemetry.confirmed += 1
                    if self.block_started is not None:
                        self.telemetry.add("block_ms", (now - self.block_started) * 1000)
                self.block_started = now
                self.route_tail = None
                self.block_failures = 0
                self.hold_used = False
                self.plan = None
                self.phase = Phase.WAIT_VALID
                if self.c.get("auto_mode", "continuous") == "one":
                    self.stop("한 블록 완료: 고정 및 새 블록 화면 확인")
            else:
                self.phase = Phase.DECIDE
        else:
            if self.telemetry and action == "drop" and obs.prediction_match is False and not w.mismatch_logged:
                self.telemetry.record("landing_mismatch", expected=w.expected_board, observed=obs.fixed, seq=obs.seq)
                w.mismatch_logged = True
            w.hits = 0
            if action not in ("hold", "drop") and now - w.sent > self.c["ack_ms"] / 1000:
                self.pulse.release_all()
                if self.diagnostic:
                    self.stop("INPUT_CONFIRMATION_ERROR: 진단 키의 실제 이동/회전을 확인하지 못했습니다.")
                    return
                self.replan("이동/회전 실패 또는 상태 불일치: 최신 화면 재탐색")

    def hold_clear(self, obs):
        return (
            (self.c.get("preview_verified", False) or obs.hold_stable >= 3)
            and obs.hold.valid
            and obs.hold.confidence >= self.c["confidence"]
            and obs.hold.state != "disabled"
            and (
                obs.hold.kind is not None
                or (
                    obs.hold.state == "empty"
                    and bool(obs.nexts)
                    and obs.nexts[0].valid
                    and obs.nexts[0].confidence >= self.c["confidence"]
                    and obs.nexts[0].kind is not None
                )
            )
        )

    def begin_diagnostic(self, target, obs, action, now):
        if not obs or not obs.valid or is_stale(obs, now, self.c) or action == "down":
            self.start(target, now)
            self.diagnostic = True
            self.raw_diagnostic = (action, now)
            self.pulse.press(self.c["keys"][action], now, self.c["press_ms"], self.c["gap_ms"])
            self.last_input = action
            self.last_ack = "API 전송 완료 / 실제 화면 변화 확인 불가"
            self.phase = Phase.DIAGNOSTIC
            return
        self.start(target, now)
        self.diagnostic = True
        self.emit(action, obs, now)
