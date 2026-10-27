import copy
import tkinter as tk
from tkinter import ttk
from config import save, validate


def reset_verification(c, *, reset_preview=True):
    if reset_preview:
        c.update(preview_verified=False, basic_auto_verified=False, opener_enabled=False)
    else:
        c.update(basic_auto_verified=False, opener_enabled=False)


class SettingsWindow:
    def options(self):
        self.stop()
        dialog = tk.Toplevel(self.root)
        dialog.title("Auto 설정")
        dialog.geometry("650x720")
        viewport = tk.Canvas(dialog, highlightthickness=0)
        scroll = ttk.Scrollbar(dialog, orient="vertical", command=viewport.yview)
        viewport.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        viewport.pack(fill="both", expand=True)
        win = ttk.Frame(viewport)
        viewport.create_window((0, 0), window=win, anchor="nw")
        win.bind("<Configure>", lambda e: viewport.configure(scrollregion=viewport.bbox("all")))
        vars = {}
        row = 0
        ttk.Label(
            win, text="F6 실행·중지 / F8 긴급 중지. 게임 옵션의 실제 회전 키와 아래 설정을 맞추세요.", wraplength=580
        ).grid(row=row, columnspan=2, pady=8)
        row += 1
        actions = ttk.Frame(win)
        actions.grid(row=row, columnspan=2, pady=5)
        row += 1
        for label, fn in [
            ("영역 수정", self.regions),
            ("입력 확인", self.diagnose),
            ("진단 정보", self.diagnostics),
            ("HOLD·NEXT 확인", self.preview_window),
        ]:
            ttk.Button(actions, text=label, command=lambda f=fn: (dialog.destroy(), f())).pack(side="left", padx=2)
        ttk.Button(win, text="로그 저장", command=lambda: (self.export_log(), msg.set(self.status.get()))).grid(
            row=row, column=0
        )
        ttk.Button(win, text="진단 캡처 저장", command=lambda: (self.snapshot(), msg.set(self.status.get()))).grid(
            row=row, column=1
        )
        row += 1
        ttk.Button(win, text="개막 빌드 JSON 불러오기", command=lambda: (dialog.destroy(), self.import_opener())).grid(
            row=row, columnspan=2
        )
        row += 1
        ttk.Label(win, text="게임 창").grid(row=row, column=0)
        target = ttk.Combobox(
            win, textvariable=self.target_name, values=self.combo["values"], state="readonly", width=48
        )
        target.grid(row=row, column=1)
        target.bind("<<ComboboxSelected>>", self.choose_target)
        row += 1
        titles = {
            "left": "왼쪽",
            "right": "오른쪽",
            "up": "시계 회전",
            "down": "소프트드롭",
            "z": "반시계 회전",
            "hold": "홀드",
            "drop": "하드드롭",
            "press_ms": "키 누름 시간 (ms)",
            "gap_ms": "키 해제 간격 (ms)",
            "ack_ms": "이동 확인 제한 (ms)",
            "uncertain_ms": "인식 대기 기준 (ms)",
            "transition_ms": "블록 전환 제한 (ms)",
            "frame_age_ms": "사용할 프레임 최대 나이 (ms)",
            "input_countdown": "버튼 실행 준비 시간 (초)",
            "capture_fps": "캡처 빈도 (FPS)",
            "vision_fps": "인식 빈도 (FPS)",
            "ui_fps": "화면 갱신 빈도 (FPS)",
            "search_budget_ms": "탐색 시간 제한 (ms)",
            "search_depth": "확인된 큐 탐색 깊이",
            "min_s": "최소 채도",
            "min_v": "최소 밝기",
            "score_level": "예측 점수용 레벨 (실제 점수 자동 판독 아님)",
            "lock_delay_ms": "확인한 고정 지연 (ms)",
        }
        for k, v in self.c["keys"].items():
            ttk.Label(win, text=titles.get(k, k)).grid(row=row, column=0)
            x = tk.StringVar(value=v)
            vars["key_" + k] = x
            ttk.Combobox(
                win,
                textvariable=x,
                values=[
                    "",
                    "LEFT",
                    "RIGHT",
                    "UP",
                    "DOWN",
                    "SPACE",
                    "SHIFT",
                    "CTRL",
                    *list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
                ],
            ).grid(row=row, column=1)
            row += 1
        for k in (
            "press_ms",
            "gap_ms",
            "ack_ms",
            "uncertain_ms",
            "transition_ms",
            "frame_age_ms",
            "input_countdown",
            "capture_fps",
            "vision_fps",
            "ui_fps",
            "search_budget_ms",
            "search_depth",
            "min_s",
            "min_v",
            "score_level",
            "lock_delay_ms",
        ):
            ttk.Label(win, text=titles.get(k, k)).grid(row=row, column=0)
            x = tk.StringVar(value=str(self.c[k]))
            vars[k] = x
            ttk.Entry(win, textvariable=x).grid(row=row, column=1)
            row += 1
        ttk.Button(
            win,
            text="빠른 입력값 적용 (누름 20ms / 간격 15ms, 입력 확인 유지)",
            command=lambda: (vars["press_ms"].set("20"), vars["gap_ms"].set("15")),
        ).grid(row=row, columnspan=2, pady=5)
        row += 1
        for k, values in [
            ("hotkey_toggle", ["F" + str(i) for i in range(1, 25)]),
            ("hotkey_stop", ["F" + str(i) for i in range(1, 25)]),
            ("auto_mode", ["one", "continuous"]),
        ]:
            ttk.Label(win, text=k).grid(row=row, column=0)
            x = tk.StringVar(value=self.c[k])
            vars[k] = x
            ttk.Combobox(win, textvariable=x, values=values, state="readonly").grid(row=row, column=1)
            row += 1
        rotation = tk.BooleanVar(value=self.c.get("rotation_confirmed", False))
        ttk.Checkbutton(
            win, text="게임 설정에서 시계 회전 키 확인 완료 (미확인 시 회전 안 함)", variable=rotation
        ).grid(row=row, columnspan=2)
        row += 1
        hold_enabled = tk.BooleanVar(value=self.c.get("enable_hold", False))
        ttk.Checkbutton(win, text="연속 모드에서 설정한 HOLD 키 사용 (프리뷰가 확실할 때)", variable=hold_enabled).grid(
            row=row, columnspan=2
        )
        row += 1
        lock_verified = tk.BooleanVar(value=self.c.get("lock_delay_verified", False))
        ttk.Checkbutton(
            win, text="현재 게임의 고정 지연을 직접 측정·확인함 (확인한 값만 사용)", variable=lock_verified
        ).grid(row=row, columnspan=2)
        row += 1
        auto_launch = tk.BooleanVar(value=self.c.get("auto_start_on_launch", False))
        ttk.Checkbutton(win, text="프로그램 실행 시 게임 인식 후 Auto도 자동 시작", variable=auto_launch).grid(
            row=row, columnspan=2
        )
        row += 1
        gates = {}
        for key, title in [
            ("preview_verified", "현재 게임의 HOLD/NEXT 원본과 판독 결과를 실제 비교 검증 완료"),
            ("basic_auto_verified", "현재 게임에서 기본 Auto 목표 위치/고정 결과 검증 완료"),
            ("opener_enabled", "선택한 JSON 빌드 실행 (위 두 검증 및 continuous 필요)"),
        ]:
            var = tk.BooleanVar(value=self.c.get(key, False))
            gates[key] = var
            ttk.Checkbutton(win, text=title, variable=var).grid(row=row, columnspan=2)
            row += 1
        msg = tk.StringVar()
        ttk.Label(win, textvariable=msg, wraplength=450).grid(row=row, columnspan=2)
        row += 1

        def commit():
            try:
                c = copy.deepcopy(self.c)
                for k, v in vars.items():
                    if k.startswith("key_"):
                        c["keys"][k[4:]] = v.get().upper()
                    elif k in ("hotkey_toggle", "hotkey_stop", "auto_mode"):
                        c[k] = v.get()
                    else:
                        c[k] = float(v.get()) if k in ("min_s", "min_v") else int(v.get())
                c.update({k: v.get() for k, v in gates.items()})
                c["rotation_confirmed"] = rotation.get()
                c["enable_hold"] = hold_enabled.get()
                c["lock_delay_verified"] = lock_verified.get()
                c["auto_start_on_launch"] = auto_launch.get()
                if any(c[k] != self.c[k] for k in ("min_s", "min_v")):
                    reset_verification(c)
                if c["keys"] != self.c["keys"] or c["rotation_confirmed"] != self.c["rotation_confirmed"]:
                    reset_verification(c, reset_preview=False)
                validate(c)
                save(c)
                self.c = c
                if self.hotkeys:
                    from hotkeys import Hotkeys

                    self.hotkeys.close()
                    self.hotkeys = Hotkeys(
                        self.hotkey_toggle,
                        self.stop,
                        tuple(0x6F + int(c[k][1:]) for k in ("hotkey_toggle", "hotkey_stop")),
                    )
                if c["board"]:
                    self.start_session()
                dialog.destroy()
            except Exception as e:
                msg.set(str(e))

        ttk.Button(win, text="저장", command=commit).grid(row=row, column=1)
