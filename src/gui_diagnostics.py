import time
import copy
import json
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from config import save


class DiagnosticsWindow:
    def diagnostics(self):
        if self.diagnostics_window and self.diagnostics_window.winfo_exists():
            self.diagnostics_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("진단 정보")
        win.geometry("1000x740")
        self.diagnostics_window = win
        if self.session:
            self.session.debug_enabled = True
        for value in (self.status, self.readings, self.times, self.last):
            ttk.Label(win, textvariable=value, wraplength=970).pack(fill="x", padx=10, pady=3)
        self.preview = tk.Canvas(win, height=230, bg="#111827")
        self.preview.pack(fill="x", padx=10)
        self.diag = tk.Text(win, height=15, font=("Consolas", 10), state="disabled")
        self.diag.pack(fill="both", expand=True, padx=10, pady=5)
        self._render_diagnostics()

    def _render_diagnostics(self):
        render_begin = time.perf_counter()
        if self.closed or not self.diag or not self.diag.winfo_exists():
            return
        s = self.session
        o = s.observations.get() if s else None
        if s and s.revision != self.revision:
            with s.lock:
                self.c = copy.deepcopy(s.c)
            save(self.c)
            self.revision = s.revision
            self.show_geometry()
        if s and s.error:
            self.status.set(s.error)
        elif s and s.visibility_error:
            self.status.set("VISIBILITY_ERROR: " + s.visibility_error)
        elif self.ctl and (self.ctl.running or self.ctl.reason != "중지됨"):
            self.status.set(self.ctl.phase + " · " + self.ctl.reason)
        self.show_geometry()
        data = {
            "opener": {
                "enabled": self.c.get("opener_enabled"),
                "file": self.c.get("opener_file"),
                "summary": self.c.get("opener_summary"),
                "preview_verified": self.c.get("preview_verified"),
                "basic_auto_verified": self.c.get("basic_auto_verified"),
            },
            "window_candidate": self.c.get("target"),
            "regions": {k: self.c[k] for k in ("board", "hold", "next_slots")},
            "detection": self.c.get("detection"),
            "hotkeys": {
                "status": self.hotkeys.status,
                "received": self.hotkeys.received,
                "alive": self.hotkeys.thread.is_alive(),
            }
            if self.hotkeys
            else None,
            "workers": s.health if s else None,
            "worker_alive": {t.name: t.is_alive() for t in s.threads} if s else None,
            "ui_last": time.strftime("%H:%M:%S"),
            "stage_age_ms": {k: round((time.monotonic() - v["last"]) * 1000, 1) for k, v in s.health.items()}
            if s
            else None,
            "frame_number": o.seq if o else None,
            "SendInput": getattr(self.backend, "last_api", {}),
            "phase": self.ctl.phase if self.ctl else None,
            "reason": self.ctl.reason if self.ctl else None,
            "foreground_hwnd": self.backend.foreground() if self.backend else None,
            "foreground_matches": self.backend.foreground() == self.c.get("target", {}).get("hwnd")
            if self.backend
            else False,
            "game_canvas_clicked": "확인 불가: 게임판을 직접 클릭하세요",
            "blocks": self.ctl.blocks if self.ctl else 0,
            "countdown": max(0, s.diagnostic_due[0] - time.monotonic()) if s and s.diagnostic_due else None,
        }
        if o:

            def reading(r):
                return r.__dict__

            self.readings.set(
                "현재: "
                + (o.active.kind + " " + str(o.active.state) if o.active else "불확실")
                + " | HOLD: "
                + (str(o.hold.kind or "비어 있음") if o.hold.valid else "불확실")
                + " | HOLD 상태: "
                + o.hold.state
                + " | NEXT: "
                + " → ".join(str(r.kind) if r.valid and r.kind else "?" for r in o.nexts)
            )
            self.readings.set(
                self.readings.get()
                + f" | confidence active={o.confidence:.2f}, hold={o.hold.confidence:.2f}, next="
                + ",".join(f"{r.confidence:.2f}" for r in o.nexts)
            )
            data.update(
                {
                    "fixed_20x10": o.fixed,
                    "fixed_confidence": o.fixed_confidence,
                    "fixed_updated": o.fixed_updated,
                    "active": o.active.__dict__ if o.active else None,
                    "ghost": {"cells": o.ghost, "confidence": o.ghost_confidence, "updated": o.ghost_updated},
                    "preview_geometry": {
                        k: {kk: vv for kk, vv in v.items() if kk not in ("mask", "normalized", "raw")}
                        for k, v in (s.preview_debug.get()[1] if s.preview_debug.get() else {}).items()
                    },
                    "hold": reading(o.hold),
                    "next": [reading(r) for r in o.nexts],
                    "reason": o.reason,
                    "confidence": o.confidence,
                    "stable_frames": o.stable,
                    "updated": o.updated,
                    "target": self.c.get("target"),
                    "SendInput": getattr(self.backend, "last_api", {}),
                    "diagnostic": s.last_diagnostic,
                }
            )
            if data["active"]:
                data["active"] = dict(data["active"], cells=sorted(data["active"]["cells"]))
        if self.ctl:
            self.last.set(
                "전략: "
                + (((s.last_packet if s else None) or {}).get("result") or {}).get("strategy", "상태 대기")
                + " | 확인된 배치: "
                + str(self.ctl.blocks)
                + " | 마지막 입력: "
                + self.ctl.last_input
                + " | 확인: "
                + self.ctl.last_ack
            )
        if s and s.last_packet:
            packet = s.last_packet
            a = packet.get("result") or {}
            self.last.set(
                self.last.get()
                + f" | depth {packet.get('depth', '?')}/{packet.get('pc_horizon', '?')} | PC {packet.get('pc_status', 'opener')} ({packet.get('pc_remaining', 0)}) | candidates {packet.get('nodes', 0)}, rot {packet.get('rotation_candidates', 0)}, hold {packet.get('hold_candidates', 0)} | target ({a.get('x')},{a.get('y')},r{a.get('r')}) | "
                + " ".join(a.get("path", []))
                + " | points: unverified"
            )
            data["decision"] = packet
            data["telemetry"] = s.telemetry.snapshot()
            data["fallback_reason"] = packet.get("fallback_reason", "")
            data["prediction_match"] = o.prediction_match if o else None
        if o:
            data["tracking"] = {
                "generation": o.generation,
                "transition": o.transition,
                "captured": o.captured,
                "state": o.active.state if o.active else None,
                "gravity_cps": o.gravity_cps,
                "fall_cells": o.fall_cells,
                "fall_ms": o.fall_ms,
                "motion_samples": o.motion_samples,
            }
        self.times.set(s.performance_text(o) if s else "작업 중지 | 실측 FPS: — | 캡처/인식/탐색 시간: —")
        if s:
            data.update(workers=s.health_snapshot(), worker_error=s.error, traceback_file=s.failure_path)
        if o and o.active:
            angles = "/".join(str(r * 90) + "°" for r in o.active.rotation_candidates)
            self.last.set(
                self.last.get()
                + " | 방향: "
                + angles
                + (" (대칭 후보)" if len(o.active.rotation_candidates) > 1 else "")
            )
        self.diag.configure(state="normal")
        self.diag.delete("1.0", "end")
        self.diag.insert("end", json.dumps(data, ensure_ascii=False, indent=1))
        self.diag.configure(state="disabled")
        if s and s.last_image.get():
            rgb, box = s.last_image.get()
            self.preview.delete("all")
            self.photos = []
            xpos = 4
            for label, b, reading in [
                ("BOARD", self.c["board"], None),
                ("HOLD", self.c["hold"], o.hold if o else None),
            ] + [
                (f"NEXT {i + 1}", b, o.nexts[i] if o and i < len(o.nexts) else None)
                for i, b in enumerate(self.c["next_slots"])
            ]:
                if not b:
                    continue
                x, y, r, z = b
                crop = rgb[y - box[1] : z - box[1], x - box[0] : r - box[0]]
                if crop.size == 0:
                    continue
                caption = label
                color = "white"
                if label != "BOARD":
                    if reading and reading.valid:
                        value = reading.kind or "비어 있음"
                        if reading.state == "disabled":
                            value += " (사용 불가)"
                        caption += f" : {value} {reading.confidence:.0%}"
                        color = "#86efac"
                    else:
                        caption += " : 인식 불확실"
                        color = "#fbbf24"
                im = Image.fromarray(crop)
                im.thumbnail((140, 178))
                photo = ImageTk.PhotoImage(im)
                self.photos.append(photo)
                self.preview.create_text(xpos, 4, anchor="nw", text=caption, fill=color, width=160)
                self.preview.create_image(xpos, 48, anchor="nw", image=photo)
                self.preview.create_rectangle(xpos, 48, xpos + im.width, 48 + im.height, outline=color)
                xpos += max(im.width, 160) + 12
        if s:
            s.telemetry.add("ui_render_ms", (time.perf_counter() - render_begin) * 1000)
        self.diagnostics_window.after(500, self._render_diagnostics)
