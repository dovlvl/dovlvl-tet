import sys, time, copy, json, logging
from pathlib import Path
from paths import app_root, resource_root
from model import Phase
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageDraw
from config import load, save, validate, PATH, regions
from detection import detect
from windows import WindowSystem, shifted, same_size
from input_win import WindowsBackend, KeyPulse
from controller import AutoController
from runtime import Session
from timing import is_stale
from gui_settings import SettingsWindow, reset_verification
from gui_regions import RegionEditor
from gui_diagnostics import DiagnosticsWindow
from gui_previews import PreviewWindow
from gui_capture import capture_desktop_rgb


class App(SettingsWindow, RegionEditor, DiagnosticsWindow, PreviewWindow):
    def __init__(self, root, launch_game=False):
        self.auto_connect = False
        self.startup_autoplay = False
        self.find_background = False
        self.find_error = False
        self.root = root
        self.c = load()
        self.ws = WindowSystem() if sys.platform == "win32" else None
        self.backend = WindowsBackend() if self.ws else None
        self.ctl = AutoController(KeyPulse(self.backend), self.c) if self.backend else None
        self.session = None
        self.future = None
        self.import_future = None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.candidates = []
        self.photos = []
        self.closed = False
        self.revision = -1
        self.deferred = None
        root.title("Tetris Auto · 전략 자동 플레이")
        root.geometry("640x92")
        root.resizable(False, False)
        self.status = tk.StringVar(value="Chrome/Edge에서 게임을 직접 열고 게임 찾기를 누르세요.")
        self.results = tk.StringVar()
        self.readings = tk.StringVar()
        self.times = tk.StringVar()
        self.last = tk.StringVar()
        self.action = tk.StringVar(value="left")
        self.target_name = tk.StringVar()
        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        self.run_text = tk.StringVar(value="실행")
        self.summary = tk.StringVar(value="보드: 불확실   홀드: 불확실   넥스트: ?")
        for index, (text, fn) in enumerate(
            [("게임찾기", self.find), ("실행", self.button_auto), ("끝내기", self.close), ("설정", self.options)]
        ):
            button = ttk.Button(top, text=text, command=fn)
            if index == 1:
                button.configure(textvariable=self.run_text)
            button.grid(row=0, column=index, padx=3, sticky="ew")
            top.columnconfigure(index, weight=1)
        ttk.Label(root, textvariable=self.summary, anchor="w").pack(fill="x", padx=13, pady=(0, 8))
        # The selector is displayed only inside Settings. Keep its model here.
        self.combo = ttk.Combobox(root, textvariable=self.target_name, state="readonly")
        self.diag = None
        self.preview = None
        self.diagnostics_window = None
        root.report_callback_exception = self.ui_error
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.hotkeys = None
        if self.ws:
            from hotkeys import Hotkeys

            self.hotkeys = Hotkeys(
                self.hotkey_toggle,
                self.stop,
                tuple(0x6F + int(self.c.get(k, d)[1:]) for k, d in [("hotkey_toggle", "F6"), ("hotkey_stop", "F8")]),
            )
            try:
                self.candidates = self.ws.browsers()
                self.update_targets()
                target = self.c.get("target")
                if target and self.ws.info(target["hwnd"])["pid"] == target["pid"] and self.c["board"]:
                    info = self.ws.info(target["hwnd"])
                    if same_size(self.c["client"], info["client"]):
                        self.c.update(shifted(self.c, self.c["client"], info["client"]))
                        self.c["client"] = info["client"]
                        self.start_session()
            except Exception:
                logging.exception("saved configuration could not be reused")
        else:
            self.status.set("이 실행 환경은 Windows가 아닙니다. 화면/실제 입력 기능은 Windows 전용입니다.")
        root.after(10, self.poll)
        root.after(100, self.render)
        if launch_game and self.ws:
            root.after(300, self.open_game)

    def open_game(self):
        if self.closed:
            return
        try:
            from game_launcher import open_game

            self.stop()
            self.end_session()
            open_game()
            # A new window has different coordinates: discard saved geometry.
            self.c.update(
                board=None,
                hold=None,
                next_slots=[None] * self.c.get("next_default_count", 1),
                preview_verified=False,
                basic_auto_verified=False,
                opener_enabled=False,
            )
            self.auto_connect = True
            self.startup_autoplay = self.c.get("auto_start_on_launch", False)
            self.status.set(
                "PLAY를 누르세요. 게임판·HOLD·NEXT를 반복 탐지하고 판독이 안정되면 Auto를 시작합니다. F8: 취소"
            )
            self.root.iconify()
            self.root.after(1000, self.find_opened_game)
        except Exception as e:
            logging.exception("game launch failed")
            self.status.set("테트리스 자동 열기 실패: " + str(e))

    def find_opened_game(self):
        if self.closed or not self.auto_connect:
            return
        if not self.future and not self.session:
            self.find_background = True
            self.begin_find(False)
        self.root.after(1000, self.find_opened_game)

    def start_when_recognized(self):
        if not self.startup_autoplay or not self.session:
            return
        if self.session.error:
            return
        if self.session.visibility_error:
            return
        o = self.session.observations.get()
        if not o or not o.valid or is_stale(o, time.monotonic(), self.c):
            return
        if not o.hold.valid or o.hold_stable < 3 or not o.nexts or o.next_stable < 3:
            return
        if not all(r.valid and r.kind for r in o.nexts):
            return
        if self.backend.foreground() != self.c["target"]["hwnd"]:
            return
        self.startup_autoplay = False
        self.start_auto()
        self.status.set("화면 인식 완료: Auto 시작 요청됨. F8로 중지할 수 있습니다.")

    def update_targets(self):
        self.combo["values"] = [
            f"{i + 1}. {z['exe']} | {z['title']} | HWND {z['hwnd']}" for i, z in enumerate(self.candidates)
        ]
        if self.candidates:
            index = next(
                (i for i, z in enumerate(self.candidates) if z["hwnd"] == self.c.get("target", {}).get("hwnd")), 0
            )
            self.combo.current(index)
            if not self.c.get("target"):
                self.c["target"] = self.candidates[index]
                self.c["client"] = self.candidates[index]["client"]

    def choose_target(self, event=None):
        self.stop()
        self.end_session()
        info = self.candidates[self.combo.current()]
        self.c["target"] = info
        self.c["client"] = info["client"]
        reset_verification(self.c)
        self.c["board"] = None
        self.c["hold"] = None
        self.c["next_slots"] = [None] * self.c.get("next_default_count", 1)
        self.status.set("창 후보 선택됨. 게임 찾기 또는 수동 영역 지정이 필요합니다.")

    def end_session(self):
        if self.session:
            self.session.stop()
            self.session = None

    def stop(self):
        self.auto_connect = False
        self.startup_autoplay = False
        self.deferred = None
        try:
            if self.session:
                self.session.emergency()
            elif self.ctl:
                self.ctl.stop("F8 긴급 중지")
        except Exception as e:
            logging.exception("Stop/key release failed")
            if self.ctl:
                self.ctl.running = False
                self.ctl.phase = Phase.ERROR
                self.ctl.reason = "KEY_RELEASE_ERROR: " + str(e)

    def start_session(self):
        self.end_session()
        validate(self.c, True)
        self.ctl.c = self.c
        self.ctl.phase = Phase.IDLE
        self.ctl.reason = "대기: 게임 시작 후 F6 또는 입력 진단"
        self.session = Session(self.c, self.ctl, self.ws)
        self.session.start()
        self.revision = 0
        save(self.c)

    def find(self, target_only=False, background=False):
        if not self.ws:
            return
        if self.future:
            return
        self.stop()
        self.end_session()
        self.find_background = background
        self.find_error = False
        self.status.set("탐지 중: 브라우저 창 후보와 실제 게임 격자를 구분해 검사합니다.")
        if background:
            self.root.iconify()
        else:
            self.root.withdraw()
        self.root.after(200, lambda: self.begin_find(target_only))

    def begin_find(self, target_only):
        info = self.c.get("target") if target_only else None
        self.future = self.pool.submit(self.find_job, info)

    def find_job(self, selected):
        candidates = [self.ws.info(selected["hwnd"])] if selected else self.ws.browsers()
        if not candidates:
            raise ValueError("WINDOW_NOT_FOUND: 보이는 일반 Chrome/Edge 창이 없습니다.")
        desktop, (vx, vy) = capture_desktop_rgb()
        best = None
        for z in candidates:
            if z["minimized"]:
                continue
            x, y, r, b = z["client"]
            x = max(x, vx)
            y = max(y, vy)
            r = min(r, vx + desktop.shape[1])
            b = min(b, vy + desktop.shape[0])
            if r - x < 100 or b - y < 180:
                continue
            result = detect(desktop[y - vy : b - vy, x - vx : r - vx], (x, y), self.c.get("next_default_count", 1))
            if result["board"]:
                visible, why = self.ws.visible_regions(z["hwnd"], [b for _, b in regions(result)])
                if not visible:
                    result["reasons"]["visibility"] = why
                    continue
            score = (
                int(result["board"] is not None) * 4 + int(result["hold"] is not None) + int(bool(result["next_slots"]))
            )
            if best is None or score > best[0]:
                best = (score, z, result)
        if best is None:
            raise ValueError("VISIBILITY_ERROR: 창이 최소화되었거나 화면 밖/다른 창에 가려져 있습니다.")
        return candidates, best[1], best[2]

    def poll(self):
        if self.closed:
            return
        if self.import_future and self.import_future.done():
            self.finish_import()
        if self.future and self.future.done():
            f = self.future
            self.future = None
            background = self.find_background
            self.find_background = False
            if not background:
                self.root.deiconify()
            try:
                self.candidates, info, result = f.result()
                self.find_error = False
                if self.c.get("target", {}).get("hwnd") != info["hwnd"] or any(
                    self.c[k] != result[k] for k in ("board", "hold", "next_slots")
                ):
                    reset_verification(self.c)
                self.update_targets()
                self.combo.current(next(i for i, z in enumerate(self.candidates) if z["hwnd"] == info["hwnd"]))
                self.c["target"] = info
                self.c["client"] = info["client"]
                self.c.update({k: result[k] for k in ("board", "hold", "next_slots")})
                self.c["detection"] = result
                if not self.c["next_slots"]:
                    self.c["next_slots"] = [None] * self.c.get("next_default_count", 1)
                self.show_geometry(result)
                complete = bool(
                    result["board"] and result["hold"] and result["next_slots"] and all(result["next_slots"])
                )
                if result["board"] and (not background or complete):
                    self.start_session()
                    self.auto_connect = False
                    self.status.set("BOARD 준비. HOLD/NEXT 판독 중. F6: Auto 시작·중지 / F8: 중지")
                elif background:
                    self.status.set(
                        "BOARD·HOLD·NEXT 대기 중: PLAY를 누르고 게임 화면을 가리지 마세요. 자동으로 다시 탐지합니다. F8: 취소"
                    )
                else:
                    self.status.set(
                        "창 후보는 찾았으나 BOARD 미탐지. PLAY를 누른 뒤 다시 찾거나 수동 영역을 설정하세요."
                    )
            except Exception as e:
                logging.exception("find failed")
                self.find_error = True
                self.status.set(str(e))
        if self.hotkeys:
            from queue import Empty

            while True:
                try:
                    kind, action = self.hotkeys.events.get_nowait()
                except Empty:
                    break
                if kind == "error":
                    self.stop()
                    self.status.set("HOTKEY_ERROR: " + action)
                elif action == "stop":
                    self.stop()
                else:
                    self.toggle_auto()
        if self.deferred and time.monotonic() >= self.deferred:
            self.deferred = None
            self.toggle_auto()
        self.start_when_recognized()
        if self.session and self.session.need_detection and self.future is None:
            resume = self.session.auto_resume_requested
            self.find(True, background=True)
            self.startup_autoplay = resume
            self.auto_connect = True
            self.root.after(1000, self.find_opened_game)
        self.root.after(10, self.poll)

    def hotkey_toggle(self):
        # Called by message thread: no Tk access; starts via the same controller path.
        if not self.session:
            return
        if self.ctl.running:
            self.stop()
            return
        self.start_auto()

    def start_auto(self):
        try:
            if self.hotkeys and not self.hotkeys.ready:
                raise ValueError("전역 단축키 등록 실패: 설정에서 변경")
            if not self.c.get("board"):
                raise ValueError("Auto: BOARD 영역을 먼저 지정하세요. 입력 진단은 영역 없이 가능")
            if self.session.error or self.session.visibility_error:
                raise ValueError(self.session.error or self.session.visibility_error)
            target = self.c["target"]["hwnd"]
            if self.backend.foreground() != target:
                raise ValueError("게임 화면을 클릭하세요: 대상 브라우저 비활성")
            self.session.request_toggle(target)
        except Exception as e:
            logging.exception("Auto start rejected")
            self.ctl.stop(str(e))

    def toggle_auto(self):
        if not self.session or self.future:
            self.status.set("먼저 BOARD 영역과 대상 창을 설정하세요.")
            return
        if self.ctl.running:
            self.stop()
            return
        self.start_auto()

    def button_auto(self):
        if self.startup_autoplay:
            self.stop()
            return
        if self.auto_connect and not self.session:
            self.startup_autoplay = True
            return
        if self.ctl and self.ctl.running:
            self.stop()
            return
        if not self.session:
            self.status.set("먼저 게임 찾기 또는 BOARD 수동 설정을 완료하세요.")
            return
        self.deferred = time.monotonic() + self.c.get("input_countdown", 3)
        self.status.set(str(self.c.get("input_countdown", 3)) + "초 뒤 시작합니다. 게임판으로 돌아가 클릭하세요.")
        self.root.iconify()

    def show_geometry(self, result=None):
        c = self.c
        success = lambda b: "설정됨" if b else "실패/미설정"
        full = bool(c["board"] and c["hold"] and c["next_slots"] and all(c["next_slots"]))
        self.results.set(
            f"영역 전체: {'설정 완료' if full else '부분 설정'} | BOARD {success(c['board'])} | HOLD {success(c['hold'])} | NEXT "
            + ", ".join(f"{i + 1}:{success(b)}" for i, b in enumerate(c["next_slots"]))
        )

    def diagnose(self):
        if self.hotkeys and not self.hotkeys.ready:
            self.status.set("전역 단축키 등록 실패: 키 / 시간 설정에서 변경 후 진단하세요.")
            return
        if not self.session:
            if not self.c.get("target"):
                self.status.set("대상 브라우저를 먼저 선택하세요.")
                return
            self.ctl.c = self.c
            self.session = Session(self.c, self.ctl, self.ws)
            self.session.start(diagnostic_only=True)
        self.stop()
        win = tk.Toplevel(self.root)
        win.title("입력 진단 · 한 동작씩 실제 화면 확인")
        ttk.Label(win, text="키 1개를 보낸 뒤 실제 변화로 판정합니다. 게임을 시작/재개한 뒤 사용하세요.").pack(
            padx=15, pady=10
        )

        def run(action):
            win.destroy()
            self.session.schedule_diagnostic(action, self.c["target"]["hwnd"], time.monotonic())
            self.status.set(f"입력 진단 {action}: {self.c.get('input_countdown', 3)}초 뒤. 게임판으로 돌아가세요.")
            self.root.iconify()

        for action, title in [
            ("left", "좌"),
            ("right", "우"),
            ("up", "시계 회전"),
            ("down", "소프트드롭"),
            ("z", "설정된 반시계 회전"),
            ("hold", "홀드"),
            ("drop", "하드드롭"),
        ]:
            ttk.Button(win, text=title, command=lambda a=action: run(a)).pack(fill="x", padx=15, pady=3)

    def render(self):
        if self.closed:
            return
        from ui_status import summary

        begin = time.perf_counter()
        s = self.session
        o = s.observations.get() if s else None
        if s and s.revision != self.revision:
            with s.lock:
                self.c = copy.deepcopy(s.c)
            save(self.c)
            self.revision = s.revision
        self.summary.set(
            summary(
                self.c,
                s,
                o,
                searching=bool(self.future or self.auto_connect),
                error=self.status.get().startswith("UI_ERROR") or (self.find_error and not self.auto_connect),
            )
        )
        self.run_text.set(
            "중지" if self.startup_autoplay or self.deferred or (self.ctl and self.ctl.running) else "실행"
        )
        if s:
            s.telemetry.add("ui_render_ms", (time.perf_counter() - begin) * 1000)
        self.root.after(round(1000 / self.c["ui_fps"]), self.render)

    def choose_builtin_opener(self):
        self.stop()
        win = tk.Toplevel(self.root)
        win.title("기본 제공 개막 빌드")
        books = {
            "TKI / Fonzie (1가방)": "TKI_Fonzie.json",
            "스틱스핀 (2가방, 좌우대칭)": "Stickspin.json",
            "SDPC (2가방, 좌우대칭)": "SDPC.json",
        }
        choice = tk.StringVar(value=next(iter(books)))
        ttk.Combobox(win, textvariable=choice, values=list(books), state="readonly", width=40).pack(padx=15, pady=10)
        ttk.Label(
            win,
            text="모델 검증 완료 / 실게임 미검증\n완성 또는 보드·보이는 큐 불일치 시 중지합니다.\nSDPC의 PC 연계는 포함되지 않습니다. 선택만으로 실행되지 않습니다.",
            wraplength=390,
        ).pack(padx=15, pady=5)

        def select():
            path = resource_root() / "data" / "openers" / books[choice.get()]
            win.destroy()
            self.import_opener(path)

        ttk.Button(win, text="선택한 빌드 불러오기", command=select).pack(pady=10)

    def import_opener(self, path=None):
        self.stop()
        if path is None:
            path = filedialog.askopenfilename(
                title="오프너 JSON (가져오기만 하며 자동 실행하지 않음)", filetypes=[("JSON", "*.json")]
            )
        if not path:
            return
        from openers import load_book

        self.import_future = self.pool.submit(load_book, path)
        self.status.set("빌드 JSON 경로/보드 검증 중: 입력 중지")

    def finish_import(self):
        from openers import book_for_save

        future = self.import_future
        self.import_future = None
        try:
            book = future.result()
            folder = PATH.parent / "openers"
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / "selected.json"
            dest.write_text(json.dumps(book_for_save(book), ensure_ascii=False, indent=2), encoding="utf-8")
            self.c["opener_file"] = str(dest)
            self.c["opener_enabled"] = False
            self.c["opener_summary"] = {
                "name": book["name"],
                "variants": len(book["variants"]),
                "source": book["source"],
                "real_game_verified": False,
            }
            save(self.c)
            if self.session:
                self.start_session()
            self.status.set(
                f"가져오기 완료: {book['name']} / {len(book['variants'])}변형. 모델 검증 완료, 실게임 미검증. 실행은 설정에서 별도 선택"
            )
        except Exception as e:
            logging.exception("opener import failed")
            self.status.set("IMPORT_ERROR: " + str(e))

    def export_log(self):
        import shutil

        folder = app_root(resolve_executable=True) / "diagnostics"
        folder.mkdir(exist_ok=True)
        for f in PATH.parent.glob("trainer.log*"):
            shutil.copy2(f, folder / f.name)
        self.status.set("로그 저장: " + str(folder))

    def snapshot(self):
        if not self.session or not self.session.last_image.get():
            self.status.set("저장할 진단 프레임이 없습니다.")
            return
        rgb, box = self.session.last_image.get()
        folder = PATH.parent / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / time.strftime("%Y%m%d_%H%M%S")
        im = Image.fromarray(rgb)
        d = ImageDraw.Draw(im)
        for label, b in regions(self.c, next_prefix="NEXT"):
            if b:
                x, y, r, z = b
                d.rectangle((x - box[0], y - box[1], r - box[0], z - box[1]), outline="cyan", width=2)
                d.text((x - box[0] + 2, y - box[1] + 2), label, fill="white")
        im.save(str(stem) + ".png")
        Image.fromarray(rgb).save(str(stem) + "_raw.png")
        packet = self.session.preview_debug.get()
        if packet:
            for name, info in packet[1].items():
                for key in ("raw", "mask", "normalized"):
                    if key in info:
                        Image.fromarray(info[key]).save(str(stem) + "_" + name + "_" + key + ".png")
        Path(str(stem) + ".json").write_text(
            json.dumps(
                {
                    "capture_box": box,
                    "config": self.c,
                    "reason": self.ctl.reason,
                    "last_api": getattr(self.backend, "last_api", {}),
                    "preview_meta": {
                        k: {kk: vv for kk, vv in v.items() if kk not in ("raw", "mask", "normalized")}
                        for k, v in packet[1].items()
                    }
                    if packet
                    else {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.status.set("진단 저장: " + str(stem))

    def ui_error(self, kind, error, tb):
        self.stop()
        logging.error("UI error", exc_info=(kind, error, tb))
        self.status.set("UI_ERROR: " + str(error))

    def close(self):
        self.closed = True
        self.stop()
        self.end_session()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.hotkeys:
            self.hotkeys.close()
        self.root.destroy()
