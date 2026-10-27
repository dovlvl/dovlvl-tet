import copy
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from config import validate, regions
from gui_settings import reset_verification
from gui_capture import capture_desktop_rgb


class RegionEditor:
    def capture_desktop(self):
        rgb, origin = capture_desktop_rgb()
        return Image.fromarray(rgb), origin

    def regions(self):
        if not self.ws or not self.c.get("target"):
            self.status.set("게임 찾기 또는 대상 브라우저 선택을 먼저 하세요.")
            return
        self.stop()
        self.root.withdraw()
        self.root.after(200, self.region_dialog)

    def region_dialog(self):
        try:
            im, origin = self.capture_desktop()
        except Exception as e:
            self.root.deiconify()
            self.status.set(str(e))
            return
        draft = copy.deepcopy(self.c)
        win = tk.Toplevel(self.root)
        win.title("영역 확인 / 실패한 영역만 수정 · 정지 화면")
        scale = min(
            1, (self.root.winfo_screenwidth() - 100) / im.width, (self.root.winfo_screenheight() - 200) / im.height
        )
        photo = ImageTk.PhotoImage(im.resize((round(im.width * scale), round(im.height * scale))))
        canvas = tk.Canvas(win, width=photo.width(), height=photo.height(), highlightthickness=0)
        canvas.pack()
        canvas.create_image(0, 0, anchor="nw", image=photo)
        win.photo = photo
        target = tk.StringVar(value="BOARD")
        bar = ttk.Frame(win)
        bar.pack(fill="x")
        combo = ttk.Combobox(bar, textvariable=target, state="readonly", width=14)
        combo.pack(side="left")
        number = tk.IntVar(value=len(draft["next_slots"]))
        ttk.Spinbox(bar, from_=1, to=6, textvariable=number, width=4).pack(side="left")
        note = tk.StringVar(
            value="수정할 영역만 선택해 내부를 드래그하세요. BOARD 10×20, 글자·테두리 제외. 빈 화면도 저장 가능."
        )
        ttk.Label(win, textvariable=note, wraplength=1000).pack()
        start = []
        temp = [None]

        def choices():
            combo["values"] = ["BOARD", "HOLD"] + [f"NEXT {i + 1}" for i in range(len(draft["next_slots"]))]

        def boxes():
            return regions(draft)

        def draw():
            canvas.delete("box")
            for label, b in boxes():
                if not b:
                    continue
                x, y, r, z = b
                x = (x - origin[0]) * scale
                y = (y - origin[1]) * scale
                r = (r - origin[0]) * scale
                z = (z - origin[1]) * scale
                col = "lime" if label == "BOARD" else "yellow" if label == "HOLD" else "cyan"
                canvas.create_rectangle(x, y, r, z, outline=col, width=2, tags="box")
                canvas.create_text(x + 4, y + 5, text=label, anchor="nw", fill=col, tags="box")
                if label == "BOARD":
                    for i in range(1, 10):
                        canvas.create_line(x + (r - x) * i / 10, y, x + (r - x) * i / 10, z, fill="#22aa66", tags="box")
                    for i in range(1, 20):
                        canvas.create_line(x, y + (z - y) * i / 20, r, y + (z - y) * i / 20, fill="#22aa66", tags="box")

        def count():
            try:
                n = number.get()
                assert 1 <= n <= 6
                draft["next_slots"] = (draft["next_slots"] + [None] * 6)[:n]
                draft["next_default_count"] = n
                choices()
                target.set("NEXT 1")
                draw()
            except Exception:
                note.set("NEXT 개수는 1~6입니다.")

        ttk.Button(bar, text="NEXT 개수 적용", command=count).pack(side="left")

        def down(e):
            start[:] = [e.x, e.y]
            temp[0] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="white")

        def move(e):
            if start:
                canvas.coords(temp[0], *start, e.x, e.y)

        def up(e):
            if not start:
                return
            x, y = start
            start.clear()
            box = [
                round(min(x, e.x) / scale) + origin[0],
                round(min(y, e.y) / scale) + origin[1],
                round(max(x, e.x) / scale) + origin[0],
                round(max(y, e.y) / scale) + origin[1],
            ]
            name = target.get()
            if name == "BOARD":
                draft["board"] = box
            elif name == "HOLD":
                draft["hold"] = box
            else:
                draft["next_slots"][int(name.split()[1]) - 1] = box
            canvas.delete(temp[0])
            draw()

        def finish(commit=False):
            if commit:
                try:
                    if any(draft[k] != self.c[k] for k in ("board", "hold", "next_slots")):
                        reset_verification(draft)
                    validate(draft, True)
                    self.c = draft
                    self.c["client"] = self.ws.info(self.c["target"]["hwnd"])["client"]
                    self.start_session()
                    self.show_geometry()
                except Exception as e:
                    note.set(str(e))
                    return
            win.destroy()
            self.root.deiconify()

        ttk.Button(bar, text="저장", command=lambda: finish(True)).pack(side="right")
        ttk.Button(bar, text="취소", command=finish).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", finish)
        canvas.bind("<ButtonPress-1>", down)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", up)
        choices()
        draw()
