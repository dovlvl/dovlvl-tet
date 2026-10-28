"""Bounded metrics and nonblocking diagnostic persistence, off the control/UI path."""

import json, time, threading, platform, sys
from collections import defaultdict, deque
from pathlib import Path
from queue import Queue, Empty, Full
from paths import app_root


def drop_waiting_for_pixels(observation, pending):
    """Diagnostic classification only; never acknowledges an input."""
    if pending is None or pending.action != "drop" or not observation.valid:
        return False
    if observation.seq <= pending.seq or observation.captured <= pending.sent:
        return True
    before = pending.before
    if before.active is None:
        return False
    x, y, rotation = observation.active.state
    bx, by, br = before.active.state
    return (
        observation.board_key == before.board_key
        and observation.generation == before.generation
        and observation.queue == before.queue
        and observation.active.kind == before.active.kind
        and (x, rotation) == (bx, br)
        and y >= by
    )


def has_recognition_failure(observation, pending=None):
    return not observation.valid or (
        observation.prediction_match is False and not drop_waiting_for_pixels(observation, pending)
    )


def record_landing_mismatch(telemetry, pending, observation):
    if (
        telemetry
        and pending.action == "drop"
        and observation.prediction_match is False
        and not pending.mismatch_logged
        and not drop_waiting_for_pixels(observation, pending)
    ):
        telemetry.record(
            "landing_mismatch", expected=pending.expected_board, observed=observation.fixed, seq=observation.seq
        )
        pending.mismatch_logged = True


class Telemetry:
    def __init__(self, folder=None):
        self.samples = defaultdict(lambda: deque(maxlen=4096))
        self.lock = threading.Lock()
        self.events = Queue(maxsize=32)
        self.dropped = 0
        self.closed = threading.Event()
        root = app_root()
        self.folder = Path(folder) if folder else root / "diagnostics" / "sessions" / time.strftime("%Y%m%d_%H%M%S")
        self.thread = None
        self.started = time.monotonic()
        self.confirmed = 0

    def start(self):
        self.thread = threading.Thread(target=self.writer, daemon=True)
        self.thread.start()

    def add(self, name, value):
        with self.lock:
            self.samples[name].append(value)

    def record(self, event, **data):
        try:
            self.events.put_nowait(dict(event=event, monotonic=time.monotonic(), **data))
        except Full:
            self.dropped += 1

    def snapshot(self):
        with self.lock:
            values = {k: list(v) for k, v in self.samples.items()}
        stats = {}
        for k, v in values.items():
            if not v:
                continue
            v.sort()
            stats[k] = {
                "n": len(v),
                "mean": sum(v) / len(v),
                "p50": v[len(v) // 2],
                "p95": v[min(len(v) - 1, int(len(v) * 0.95))],
                "max": max(v),
            }
        return dict(
            environment={"platform": platform.platform(), "python": sys.version, "processor": platform.processor()},
            metrics=stats,
            confirmed=self.confirmed,
            elapsed_s=time.monotonic() - self.started,
            pps=self.confirmed / max(0.001, time.monotonic() - self.started),
            dropped_events=self.dropped,
        )

    def reset_run(self):
        self.started = time.monotonic()
        self.confirmed = 0

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)

    def writer(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / "events.jsonl").open("a", encoding="utf-8") as stream:
                while not self.closed.is_set() or not self.events.empty():
                    try:
                        event = self.events.get(timeout=0.1)
                    except Empty:
                        continue
                    image = event.pop("image", None)
                    if image is not None:
                        from PIL import Image

                        prefix = "tracking" if event["event"] == "recorded_frame" else "failure"
                        name = f"{prefix}_{event.get('seq', 0)}.png"
                        Image.fromarray(image).save(self.folder / name)
                        event["image_file"] = name
                    stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
            (self.folder / "metrics.json").write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            import logging

            logging.exception("Diagnostic writer failed")
