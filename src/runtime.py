import threading, time, copy, multiprocessing, logging, traceback
from queue import Queue, Empty
from concurrent.futures import ProcessPoolExecutor
from config import union, validate, regions
from recognition import Recognizer
from model import Phase
from planner import urgent_plan
from strategy import position_score
from strategy import auto_plan
from openers import load_book, opener_plan
from detection import panel_occluded, fit_grid, refine_saved_regions, refine_next_region
from windows import shifted, same_size
from telemetry import Telemetry
from timing import MotionTracker, search_budget, is_fresh


def warm_search_worker(compile_openers=False):
    if compile_openers:
        from strategy import builtin_book

        builtin_book()
    return True


class Latest:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None

    def put(self, v):
        with self.lock:
            self.value = v

    def get(self):
        with self.lock:
            return self.value


class Session:
    def __init__(self, c, controller, windows=None, source_factory=None):
        self.c = copy.deepcopy(c)
        self.controller = controller
        self.windows = windows
        self.source_factory = source_factory
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.frames = Latest()
        self.observations = Latest()
        self.last_image = Latest()
        self.preview_debug = Latest()
        self.recognizer = Recognizer()
        self.threads = []
        self.pool = None
        self.future = None
        self.job = None
        self.search_ms = 0
        self.revision = 0
        self.need_detection = False
        self.visibility_error = ""
        self.error = ""
        self.diagnostic_due = None
        self.last_diagnostic = ""
        self.last_packet = None
        self.opener_book = None
        self.commands = Queue()
        self.generation = 0
        self.telemetry = Telemetry()
        self.health = {
            k: {"last": time.monotonic(), "count": 0, "ms": 0} for k in ("capture", "vision", "control", "search")
        }
        self.motion = MotionTracker()
        self.auto_resume_requested = False
        self.failure_traceback = ""
        self.failure_path = ""
        self.debug_enabled = False
        self.warmup = None
        for h in self.health.values():
            h.update(state="waiting", last_success_at=None)
        if self.controller:
            self.controller.telemetry = self.telemetry
            self.controller.pulse.observation_guard = self.input_observation_valid

    def input_observation_valid(self, now, generation):
        if self.controller.diagnostic:
            return True
        o = self.observations.get()
        return bool(
            o
            and o.valid
            and o.generation == generation
            and 0 <= now - o.captured < self.c.get("frame_age_ms", 200) / 1000
        )

    def request_toggle(self, target):
        self.commands.put((self.generation, target))

    def beat(self, stage, begin):
        self.telemetry.add(
            "search_roundtrip_ms" if stage == "search" else stage + "_ms", (time.monotonic() - begin) * 1000
        )
        h = self.health[stage]
        h.update(
            last=time.monotonic(),
            count=h["count"] + 1,
            ms=(time.monotonic() - begin) * 1000,
            state="running",
            last_success_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def health_snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        result = {}
        for stage, h in self.health.items():
            state = h["state"]
            if state != "failed":
                if self.stop_event.is_set():
                    state = "stopped"
                elif stage == "search" and not self.future:
                    state = "idle"
                elif h["count"] and now - h["last"] > 2:
                    state = "stalled"
            result[stage] = dict(
                h,
                state=state,
                age_ms=round((now - h["last"]) * 1000, 1) if h["count"] else None,
                current_ms=h["ms"] if state == "running" else None,
            )
        return result

    def performance_text(self, o, now=None):
        now = time.monotonic() if now is None else now
        stages = self.health_snapshot(now)
        fresh = bool(o and now - o.captured < max(0.5, self.c.get("frame_age_ms", 200) / 500))
        halted = bool(
            self.error
            or self.stop_event.is_set()
            or any(stages[k]["state"] in ("failed", "stopped", "stalled") for k in ("capture", "vision"))
        )
        last = " | ".join(f"{k} 마지막 성공: {stages[k]['last_success_at'] or '없음'}" for k in ("capture", "vision"))
        if halted or not fresh:
            state = "작업 중단: " + (self.error or "캡처/인식 작업 중단") if halted else "최신 프레임 대기"
            return state + " | 실측 FPS: — | 캡처/인식/탐색 시간: — | " + last
        return (
            f"실측 인식 {o.fps:.1f} FPS | 캡처 {o.capture_ms:.2f} ms | 인식 {o.vision_ms:.2f} ms | 탐색 "
            + (f"{self.search_ms:.2f} ms" if self.future else "대기")
            + f" | 최신 프레임 나이 {(now - o.captured) * 1000:.1f} ms | "
            + last
        )

    def watchdog_loop(self):
        while not self.stop_event.wait(0.05):
            now = time.monotonic()
            try:
                self.controller.pulse.tick(now)
            except Exception:
                self.emergency("포커스 상실 또는 키 해제 오류")
            for stage in ("control",) if getattr(self, "diagnostic_only", False) else ("capture", "vision", "control"):
                if now - self.health[stage]["last"] > 2:
                    self.emergency("WORKER_STALL: " + stage + " 마지막 정상 처리 2초 초과")
            if self.future and now - self.future_started > 3:
                self.emergency("SEARCH_TIMEOUT: 배치 탐색 3초 초과")
                self.future.cancel()

    def start(self, diagnostic_only=False):
        self.diagnostic_only = diagnostic_only
        self.telemetry.start()
        validate(self.c, not diagnostic_only)
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        if not diagnostic_only:
            self.warmup_started = time.perf_counter()
            self.warmup = self.pool.submit(warm_search_worker, self.c.get("basic_auto_verified", False))
        for fn in (
            (self.control_loop, self.watchdog_loop)
            if diagnostic_only
            else (self.capture_loop, self.vision_loop, self.control_loop, self.watchdog_loop)
        ):
            t = threading.Thread(target=self.guard, args=(fn,), daemon=True)
            self.threads.append(t)
            t.start()

    def guard(self, fn):
        stage = fn.__name__.removesuffix("_loop")
        try:
            fn()
        except Exception as e:
            self.failure_traceback = traceback.format_exc()
            logging.exception("%s failed", fn.__name__)
            self.error = fn.__name__ + ": " + str(e)
            if stage in self.health:
                self.health[stage]["state"] = "failed"
            try:
                self.telemetry.folder.mkdir(parents=True, exist_ok=True)
                failure = self.telemetry.folder / (fn.__name__ + "_traceback.txt")
                failure.write_text(self.failure_traceback, encoding="utf-8")
                self.failure_path = str(failure)
            except OSError:
                logging.exception("Worker traceback file could not be written")
            try:
                self.emergency(self.error)
            finally:
                self.stop_event.set()
        finally:
            if stage in self.health and self.health[stage]["state"] != "failed":
                self.health[stage]["state"] = "stopped"

    def emergency(self, reason="F8 긴급 중지"):
        self.auto_resume_requested = False
        self.generation += 1
        errors = []
        try:
            self.controller.pulse.cancel()
        except Exception as e:
            errors.append(str(e))
            logging.exception("Key release failed")
        with self.lock:
            self.diagnostic_due = None
            try:
                self.controller.stop(reason)
            except Exception as e:
                errors.append(str(e))
                logging.exception("Controller release failed")
            if errors:
                self.controller.running = False
                self.controller.phase = Phase.ERROR
                self.controller.reason = "KEY_RELEASE_ERROR: " + " / ".join(errors)

    def stop(self):
        self.emergency("세션 중지")
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=0.5)
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
        self.telemetry.close()

    def schedule_diagnostic(self, action, target, now):
        self.emergency("입력 진단 준비")
        with self.lock:
            self.controller.diagnostic = False
            self.diagnostic_due = (now + self.c.get("input_countdown", 3), action, target)
            self.last_diagnostic = "예약됨: " + action

    def monitor(self, source, now):
        if not self.windows:
            return
        target = self.c["target"]
        info = self.windows.info(target["hwnd"])
        if info["pid"] != target["pid"]:
            raise OSError("대상 HWND가 다른 프로세스로 바뀌었습니다. 게임 찾기를 다시 실행하세요.")
        old = self.c["client"]
        new = info["client"]
        if not same_size(old, new):
            resume = self.controller.running
            self.emergency("LAYOUT_CHANGED: 창 크기 변경. 재탐지 중 입력 중지")
            self.auto_resume_requested = resume
            self.need_detection = True
            return
        if old[:2] != new[:2]:
            self.emergency("창 이동 감지: 좌표 보정 완료 후 F6으로 재시작하세요.")
            with self.lock:
                self.c.update(shifted(self.c, old, new))
                self.c["client"] = new
                self.revision += 1
                self.observations.put(None)
        boxes = [b for _, b in regions(self.c)]
        visible, why = self.windows.visible_regions(target["hwnd"], boxes)
        self.visibility_error = "" if visible else why
        if not visible:
            if not self.diagnostic_due or now >= self.diagnostic_due[0]:
                self.emergency("VISIBILITY_ERROR: " + why)
            self.observations.put(None)

    def capture_loop(self):
        import numpy as np

        if self.source_factory:
            source = self.source_factory()
        else:
            import mss

            source = mss.mss()
        last_check = 0
        try:
            while not self.stop_event.is_set():
                begin = time.monotonic()
                if begin - last_check > 0.1:
                    self.monitor(source, begin)
                    last_check = begin
                if not self.visibility_error and not self.need_detection:
                    with self.lock:
                        c = copy.deepcopy(self.c)
                        rev = self.revision
                    box = union(c)
                    x, y, r, b = box
                    grab_begin = time.monotonic()
                    grab_perf = time.perf_counter()
                    frame = source.grab({"left": x, "top": y, "width": r - x, "height": b - y})
                    rgb = np.asarray(frame)[:, :, :3][:, :, ::-1].copy()
                    self.frames.put(
                        (time.monotonic_ns(), grab_begin, rgb, box, (time.perf_counter() - grab_perf) * 1000, rev, c)
                    )
                    self.beat("capture", begin)
                self.stop_event.wait(max(0.001, 1 / self.c["capture_fps"] - (time.monotonic() - begin)))
        finally:
            source.close()

    def vision_loop(self):
        last_record = 0
        last = None
        rev = None
        seq = 0
        last_debug = 0
        last_failure = 0
        fps_start = time.monotonic()
        count = 0
        fps = 0
        grid_check = 0
        bad_grid = 0
        next_refine_at = 0
        while not self.stop_event.is_set():
            begin = time.monotonic()
            f = self.frames.get()
            if f and f[0] != last and not self.visibility_error and not self.need_detection:
                key, captured, rgb, box, cap_ms, revision, c = f
                last = key
                if revision != self.revision:
                    continue
                if time.monotonic() - captured > c.get("frame_age_ms", 200) / 1000:
                    self.telemetry.add("discarded_stale_capture", 1)
                    continue
                if self.windows and rev is None:
                    # A saved drag rectangle can contain the frame and the
                    # whole NEXT panel. Recover verified interiors before sampling.
                    refined = refine_saved_regions(rgb, box[:2], c)
                    if refined:
                        c.update(refined)
                        with self.lock:
                            self.c.update(refined)
                if revision != rev:
                    self.recognizer = Recognizer()
                    rev = revision
                # Menus can hide the board on the first frame. Retry NEXT
                # independently later, using only a verified first-piece ROI.
                prior = self.observations.get()
                if (
                    self.windows
                    and not c.get("opener_enabled", False)
                    and begin >= next_refine_at
                    and (not prior or not prior.nexts or not prior.nexts[0].valid)
                ):
                    next_refine_at = begin + 0.5
                    refined = refine_next_region(rgb, box[:2], c)
                    if refined:
                        with self.lock:
                            if revision != self.revision:
                                continue
                            self.controller.pulse.release_all()
                            self.observations.put(None)
                            c.update(refined, preview_verified=False, basic_auto_verified=False)
                            self.c.update(refined, preview_verified=False, basic_auto_verified=False)
                            self.controller.c.update(refined, preview_verified=False, basic_auto_verified=False)
                            self.revision += 1
                            revision = rev = self.revision
                            self.recognizer.cache.invalidate()
                        self.telemetry.record("preview_region_refined", seq=seq, next_slots=c["next_slots"])
                x, y, r, b = c["board"]
                ox, oy, _, _ = box
                board_image = rgb[y - oy : b - oy, x - ox : r - ox]
                # Large neutral panels are not tetrominoes. Do not infer through a popup.
                reading_begin = time.perf_counter()
                popup = panel_occluded(board_image)
                if self.windows and begin - grid_check > 0.5:
                    grid_check = begin
                    bad_grid = (
                        bad_grid + 1
                        if fit_grid(board_image, [0, 0, board_image.shape[1], board_image.shape[0]]) is None
                        else 0
                    )
                    recent = self.observations.get()
                    tracked = bool(recent and recent.valid and begin - recent.captured < 0.3)
                    if bad_grid >= 6 and not popup and not tracked:
                        resume = self.controller.running
                        self.emergency("LAYOUT_CHANGED: 확대율/페이지 배치 변경 의심. 재탐지 중")
                        self.auto_resume_requested = resume
                        self.need_detection = True
                        self.observations.put(None)
                        continue
                seq += 1
                pending = self.controller.wait
                expected = pending.expected_board if pending and pending.action == "drop" else None
                o = self.recognizer.process(rgb, box, c, seq, captured, cap_ms, expected_fixed=expected)
                if popup:
                    o.active = None
                    o.confidence = 0
                    o.stable = 0
                    o.fixed_confidence = 0
                    o.reason = "RECOGNITION_ERROR: BOARD에 팝업/중성 패널 가림 의심"
                elif o.active is None and pending and pending.action in ("drop", "hold"):
                    o.reason = "TRANSITION_WAIT: 줄 삭제/새 블록 생성 중, 현재 블록 판독 대기"
                self.motion.update(o, controlled_action=pending.action if pending else None)
                prior = self.observations.get()
                if prior and o.generation != prior.generation:
                    self.controller.pulse.release_all()
                self.telemetry.record(
                    "frame_tracking",
                    seq=seq,
                    captured=captured,
                    generation=o.generation,
                    transition=o.transition,
                    state=o.active.state if o.active else None,
                    valid=o.valid,
                    reason=o.reason,
                    gravity_cps=o.gravity_cps,
                    fall_ms=o.fall_ms,
                    queue=o.queue,
                )
                if c.get("record_tracking_frames", False) and begin - last_record >= 1 / 30:
                    last_record = begin
                    self.telemetry.record(
                        "recorded_frame",
                        seq=seq,
                        captured=captured,
                        box=box,
                        config={k: c[k] for k in ("board", "hold", "next_slots", "min_s", "min_v", "confidence")},
                        controlled_action=pending.action if pending else None,
                        image=rgb,
                    )
                o.vision_ms = (time.perf_counter() - reading_begin) * 1000
                count += 1
                elapsed = time.monotonic() - fps_start
                if elapsed >= 1:
                    fps = count / elapsed
                    count = 0
                    fps_start = time.monotonic()
                o.fps = fps
                self.last_image.put((rgb, box))
                self.telemetry.add("capture_grab_ms", cap_ms)
                self.telemetry.add("recognition_ms", o.vision_ms)
                self.telemetry.add("frame_age_ms", (time.monotonic() - captured) * 1000)
                if (
                    c.get("save_failure_frames", True)
                    and (not o.valid or o.prediction_match is False)
                    and begin - last_failure >= 1
                ):
                    last_failure = begin
                    self.telemetry.record(
                        "recognition_failure",
                        seq=seq,
                        reason=o.reason or "unstable observation",
                        prediction_match=o.prediction_match,
                        box=box,
                        raw=o.raw,
                        hold=o.hold.__dict__,
                        next=[r.__dict__ for r in o.nexts],
                        image=rgb,
                    )
                self.observations.put(o)
                self.beat("vision", begin)
                if not self.debug_enabled or begin - last_debug < 0.25:
                    self.stop_event.wait(max(0.001, 1 / c["vision_fps"] - (time.monotonic() - begin)))
                    continue
                last_debug = begin
                debug = copy.deepcopy(self.recognizer.cache.debug)
                for name, roi, reading in [("hold", c["hold"], o.hold)] + [
                    (f"next{i}", b, o.nexts[i]) for i, b in enumerate(c["next_slots"])
                ]:
                    info = debug.setdefault(name, {})
                    info["roi"] = roi
                    info["reading"] = reading.__dict__
                    info["frame"] = seq
                    if roi:
                        xx, yy, rr, bb = roi
                        if xx >= box[0] and yy >= box[1] and rr <= box[2] and bb <= box[3]:
                            info["raw"] = rgb[yy - box[1] : bb - box[1], xx - box[0] : rr - box[0]].copy()
                self.preview_debug.put((seq, debug))
                self.observations.put(o)
                self.beat("vision", begin)
            self.stop_event.wait(max(0.001, 1 / self.c["vision_fps"] - (time.monotonic() - begin)))

    def discard_stale_plan(self, ctl, reason):
        self.telemetry.add("discarded_stale_plan", 1)
        # A completed obsolete search must not erase an in-flight action/plan.
        if ctl.wait is None and ctl.plan is None:
            ctl.replan(reason, count_failure=False)

    def previews_ready(self, o):
        if self.c.get("preview_verified", False):
            return True
        if o.hold.valid and o.hold_stable < 3:
            return False
        if o.nexts and o.nexts[0].valid and o.next_stable < 3:
            return False
        return True

    def signature(self, o, used):
        return (
            getattr(self.controller, "vision_epoch", 0),
            o.generation,
            o.board_key,
            o.active.kind,
            used,
            o.hold.kind,
            o.hold.valid,
            o.hold.state,
            o.queue,
        )

    def dispatch_search(self, o, ctl, begin):
        previews = self.c.get("preview_verified", False) or o.next_stable >= 3
        nexts = []
        if previews and self.c.get("auto_mode") == "continuous":
            for r in o.nexts:
                if not r.valid or not r.kind or r.confidence < self.c["confidence"]:
                    break
                nexts.append(r.kind)
        clear = ctl.hold_clear(o) and self.c.get("enable_hold", False) and bool(self.c["keys"]["hold"])
        held = o.hold.kind if clear else None
        self.job = self.signature(o, ctl.hold_used)
        self.job_generation = self.generation
        self.job_started_at = ctl.started_at
        self.future_started = begin
        adaptive_budget, profile = search_budget(
            o, self.c, (begin - o.captured) * 1000, getattr(ctl, "ack_bound_ms", None)
        )
        # A configured budget is an upper bound, not a mandatory wait.
        # Repeated 160ms searches were frequently stale before input.
        adaptive_budget = min(adaptive_budget, self.c.get("realtime_search_cap_ms", 60))
        self.telemetry.record(
            "search_started",
            generation=o.generation,
            captured=o.captured,
            state=o.active.state,
            budget_ms=adaptive_budget,
            timing=profile,
        )
        if ctl.urgent_requested or (profile["calibrated"] and (o.fall_ms is not None and o.fall_ms < 600)):
            ctl.urgent_requested = False
            packet = urgent_plan(
                o.fixed,
                o.active.kind,
                o.active.state,
                self.c.get("rotation_confirmed", False),
                bool(self.c["keys"].get("z")),
                position_score,
                min(6, adaptive_budget),
                profile,
                next_kind=nexts[0] if nexts else None,
            )
            packet.update(key=(o.board_key, o.active.kind, ctl.hold_used), generation=o.generation)
            self.search_ms = packet["search_ms"]
            self.last_packet = packet
            self.telemetry.add("search_ms", self.search_ms)
            if packet["result"] is None:
                ctl.execution_window_failed("EXECUTION_WINDOW_EXCEEDED: no observed-state path can finish safely", o)
            else:
                ctl.accept_plan(packet, o)
            return True
        if self.opener_book:
            if (
                not self.c.get("preview_verified")
                or not self.c.get("basic_auto_verified")
                or not o.hold.valid
                or not all(r.valid and r.kind for r in o.nexts)
            ):
                ctl.stop("OPENER_GATE: 기본 Auto/프리뷰 실게임 검증 미완료 또는 HOLD/NEXT 불확실")
                return True
            self.future = self.pool.submit(
                opener_plan,
                book=self.opener_book,
                index=ctl.blocks,
                chosen=ctl.opener_variant,
                board=o.fixed,
                kind=o.active.kind,
                start=o.active.state,
                held=o.hold.kind,
                queue=list(o.queue),
                hold_used=ctl.hold_used,
                hold_available=o.hold.state != "disabled"
                and self.c.get("enable_hold", False)
                and bool(self.c["keys"]["hold"]),
                rotation=self.c.get("rotation_confirmed", False),
            )
        else:
            self.future = self.pool.submit(
                auto_plan,
                board=o.fixed,
                kind=o.active.kind,
                start=o.active.state,
                held=held,
                nexts=nexts,
                use_hold=clear,
                allow_hold=not ctl.hold_used and clear,
                rotation=self.c.get("rotation_confirmed", True) and self.c.get("rotation_system", "SRS") == "SRS",
                previews=previews,
                basic_verified=self.c.get("basic_auto_verified", False),
                opening=self.c.get("basic_auto_verified", False),
                budget_ms=adaptive_budget,
                max_depth=self.c.get("search_depth", 4),
                counterclockwise=bool(self.c["keys"].get("z")),
                input_ms=self.c["press_ms"] + self.c["gap_ms"],
                timing=profile,
                score_state=getattr(ctl, "score_state", None),
            )
        return False

    def control_loop(self):
        if self.c.get("opener_enabled"):
            self.opener_book = load_book(self.c["opener_file"])
        while not self.stop_event.is_set():
            begin = time.monotonic()
            o = self.observations.get()
            ctl = self.controller
            if self.warmup and self.warmup.done():
                self.warmup.result()
                self.warmup = None
                self.telemetry.add("worker_warmup_ms", (time.perf_counter() - self.warmup_started) * 1000)
            try:
                generation, target = self.commands.get_nowait()
                if generation == self.generation:
                    if ctl.running:
                        self.emergency("사용자 Auto 중지")
                    elif not self.error and not self.visibility_error:
                        try:
                            ctl.start(target, begin)
                        except Exception as e:
                            logging.exception("Auto start failed")
                            ctl.stop(str(e))
            except Empty:
                pass
            if self.diagnostic_due and begin >= self.diagnostic_due[0]:
                _, action, target = self.diagnostic_due
                self.diagnostic_due = None
                try:
                    if self.visibility_error or self.need_detection:
                        raise ValueError("VISIBILITY_ERROR: 대상 영역 사용 불가")
                    ctl.begin_diagnostic(target, o, action, begin)
                    self.last_diagnostic = "확인 중: " + action
                except Exception as e:
                    ctl.stop(str(e))
                    self.last_diagnostic = str(e)
            ctl.tick(o, begin)
            if ctl.diagnostic and not ctl.running:
                self.last_diagnostic = ctl.reason
            if self.future and self.future.done():
                self.beat("search", self.future_started)
                packet = self.future.result()
                job = self.job
                self.future = None
                self.search_ms = packet["search_ms"]
                self.telemetry.add("search_ms", self.search_ms)
                if (
                    ctl.running
                    and not ctl.diagnostic
                    and self.job_generation == self.generation
                    and self.job_started_at == ctl.started_at
                    and o
                    and o.active
                    and job == self.signature(o, ctl.hold_used)
                    and is_fresh(o, begin, self.c)
                    and begin - self.future_started < self.c.get("plan_age_ms", 500) / 1000
                ):
                    packet["key"] = (o.board_key, o.active.kind, ctl.hold_used)
                    packet["generation"] = o.generation
                    self.last_packet = packet
                    ctl.accept_plan(packet, o)
                elif ctl.running and not ctl.diagnostic:
                    self.discard_stale_plan(ctl, "STALE_PLAN: 탐색 결과/화면 나이 또는 상태 불일치. 최신 화면 재탐색")
            if (
                ctl.running
                and not ctl.diagnostic
                and ctl.wait is None
                and ctl.plan is None
                and not self.future
                and not self.warmup
                and o
                and o.valid
                and o.seq > ctl.execution_retry_seq
                and is_fresh(o, begin, self.c)
                and self.previews_ready(o)
            ):
                if self.dispatch_search(o, ctl, begin):
                    continue
            if self.future and ctl.running and not ctl.diagnostic and not ctl.wait:
                ctl.phase = Phase.SEARCH
                ctl.reason = f"배치 탐색 결과 대기 {begin - self.future_started:.2f}초 (제한 3초)"
            self.beat("control", begin)
            self.stop_event.wait(max(0.001, 0.005 - (time.monotonic() - begin)))
