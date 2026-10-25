"""Synthetic RGB + real-clock mock only. Never sends Windows input."""

import sys, time, copy, json, threading, zlib, platform, statistics
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / "src"), str(root / "tests")]
import numpy as np
from helpers import C, FakeBackend
from timed_game import TimedGame
from recognition import Recognizer
from controller import AutoController
from runtime import Session
from input_win import KeyPulse


def run(cps, limit=10, seconds=18, record=False):
    game = TimedGame(cps=cps)
    lock = threading.RLock()
    truth = {}
    records = []
    first = {}
    first_available = {}

    class Source:
        def grab(self, box):
            with lock:
                game.update(time.monotonic())
                rgb = game.image()[: box["height"], : box["width"]]
                key = zlib.adler32(rgb.tobytes())
                truth[key] = (game.generation, game.visible, tuple(map(tuple, game.board)), game.kind, game.state)
                if len(truth) > 1024:
                    truth.pop(next(iter(truth)))
            a = np.zeros((*rgb.shape[:2], 4), np.uint8)
            a[:, :, :3] = rgb[:, :, ::-1]
            return a

        def close(self):
            pass

    c = copy.deepcopy(C)
    c.update(
        enable_hold=False,
        lock_delay_verified=True,
        lock_delay_ms=250,
        record_tracking_frames=record,
        allow_stationary_bootstrap=False,
    )
    backend = FakeBackend()
    pulse = KeyPulse(backend)
    ctl = AutoController(pulse, c)

    def key(vk, down):
        backend.events.append((vk, down))
        with lock:
            game.key(vk, down, getattr(pulse, "expected_generation", None))

    backend.key = key
    session = Session(c, ctl, None, Source)
    original = Recognizer.process

    def recognize(rec, rgb, *args, **kwargs):
        o = original(rec, rgb, *args, **kwargs)
        with lock:
            t = truth.get(zlib.adler32(rgb.tobytes()))
        if t:
            gen, visible, board, kind, state = t
            correct = (
                o.active is not None
                and o.board_key == board
                and o.active.kind == kind
                and o.active.cells == __import__("recognition").cellset(kind, state)
            )
            records.append(
                dict(
                    captured=o.captured,
                    generation=gen,
                    visible=visible,
                    valid=o.valid,
                    correct=correct,
                    state=o.active.state if o.active else None,
                )
            )
            if visible and o.valid and correct:
                first.setdefault(gen, o.captured)
                first_available.setdefault(gen, time.monotonic())
        return o

    Recognizer.process = recognize
    start = time.monotonic()
    last_packet = None
    targets = []
    old_emit = ctl.emit

    def emit(action, o, now):
        if action == "drop" and ctl.plan:
            targets.append((game.generation, tuple(sorted(map(tuple, ctl.plan["cells"])))))
        old_emit(action, o, now)

    ctl.emit = emit
    try:
        session.start()
        session.request_toggle(99)
        while time.monotonic() - start < seconds and ctl.blocks < limit and not session.error:
            if game.topout:
                break
            if not ctl.running and (ctl.started_at is not None):
                break
            time.sleep(0.005)
        elapsed = time.monotonic() - start
        expected = {gen: cells for gen, cells in targets}
        target_attempts = sum(e["action"] == "drop" and e["visible"] for e in game.inputs)
        bygen = {l["generation"]: l for l in game.locks if l["hard"]}
        target_success = sum(
            1 for gen, cells in expected.items() if gen in bygen and tuple(map(tuple, bygen[gen]["cells"])) == cells
        )
        visible = [r for r in records if r["visible"]]
        invalid = sum(not r["valid"] for r in visible)
        wrong = sum(r["valid"] and not r["correct"] for r in visible)
        spawn_delays = [
            (first_available[g] - at) * 1000
            for g, at in game.spawns
            if g in first_available and first_available[g] >= at
        ]
        spawn_capture_delays = [(first[g] - at) * 1000 for g, at in game.spawns if g in first and first[g] >= at]
        stale = sum(e["visible"] and e["expected_generation"] != e["generation"] for e in game.inputs)
        return dict(
            kind="synthetic_frames_and_real_clock_mock",
            recording_enabled=record,
            gravity_cps=cps,
            lock_delay_ms=250,
            entry_ms=40,
            line_clear_ms=80,
            seconds=elapsed,
            confirmed_blocks=ctl.blocks,
            natural_locks=sum(not x["hard"] for x in game.locks),
            total_locks=len(game.locks),
            pps=ctl.blocks / max(0.001, elapsed),
            visible_frames=len(visible),
            recognition_invalid=invalid,
            recognition_wrong_valid=wrong,
            recognition_failure_rate=(invalid + wrong) / max(1, len(visible)),
            spawn_first_valid_ms=stats(spawn_delays),
            spawn_first_valid_capture_ms=stats(spawn_capture_delays),
            inputs=len(game.inputs),
            cross_generation_inputs=stale,
            input_while_no_piece=sum(not e["visible"] for e in game.inputs),
            held_key_carryover=game.carryover,
            raw_held_overlap=game.held_overlap,
            target_attempts=target_attempts,
            target_success=target_success,
            targets_verified=True,
            reason="MOCK_TOPOUT"
            if game.topout
            else ctl.reason
            if not ctl.running or ctl.blocks >= limit
            else "HARNESS_TIME_LIMIT: " + ctl.reason,
            error=session.error,
            topout=game.topout,
            telemetry=session.telemetry.snapshot(),
            session_folder=str(session.telemetry.folder),
            recorded_frames=records,
            spawns=game.spawns,
            locks=game.locks,
            input_events=game.inputs,
        )
    finally:
        session.stop()
        Recognizer.process = original


def stats(v):
    v = sorted(v)
    return (
        dict(n=len(v), mean=statistics.mean(v), p95=v[min(len(v) - 1, int(0.95 * len(v)))], max=max(v))
        if v
        else dict(n=0)
    )


if __name__ == "__main__":
    results = [run(rate) for rate in (2, 30, 120)]
    recording_runs = [run(30, limit=4, seconds=10, record=True)]
    import shutil
    from replay_tracking import replay

    for p in recording_runs:
        source = Path(p["session_folder"])
        destination = root / "diagnostics/highspeed_recordings" / str(p["gravity_cps"])
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "events.jsonl", destination / "events.jsonl")
        for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event") == "recorded_frame" and event.get("image_file"):
                shutil.copy2(source / event["image_file"], destination / event["image_file"])
        replay_result = replay(destination)
        (destination / "replay.json").write_text(
            json.dumps(replay_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        p["replay"] = {k: v for k, v in replay_result.items() if k != "results"}
        p["recording_folder"] = str(destination.relative_to(root))
    out = root / "diagnostics/highspeed_benchmark.json"
    out.write_text(
        json.dumps(
            dict(
                environment={"platform": platform.platform(), "python": sys.version},
                real_game_tested=False,
                results=results,
                recording_runs=recording_runs,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            [
                {
                    k: p[k]
                    for k in (
                        "gravity_cps",
                        "confirmed_blocks",
                        "recognition_failure_rate",
                        "cross_generation_inputs",
                        "held_key_carryover",
                        "reason",
                    )
                }
                for p in results
            ],
            ensure_ascii=False,
        )
    )
