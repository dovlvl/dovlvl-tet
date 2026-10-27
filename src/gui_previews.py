import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


class PreviewWindow:
    def preview_window(self):
        if self.session:
            self.session.debug_enabled = True
        win = tk.Toplevel(self.root)
        win.title("HOLD·NEXT 원본 / 색상 마스크 / 정규화")
        win.geometry("950x650")
        canvas = tk.Canvas(win, bg="#151b27")
        bar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        win.images = []

        def update():
            if not win.winfo_exists():
                return
            canvas.delete("all")
            win.images = []
            s = self.session
            packet = s.preview_debug.get() if s else None
            o = s.observations.get() if s else None
            image = s.last_image.get() if s else None
            if not packet or not image:
                canvas.create_text(
                    15, 15, anchor="nw", text="인식 세션 및 프리뷰 영역을 먼저 설정하세요.", fill="white"
                )
            else:
                seq, debug = packet
                rgb, box = image
                ypos = 10
                for name, roi, r in [("hold", self.c["hold"], o.hold if o else None)] + [
                    (f"next{i}", b, o.nexts[i] if o and i < len(o.nexts) else None)
                    for i, b in enumerate(self.c["next_slots"])
                ]:
                    info = debug.get(name, {})
                    if info.get("reading"):
                        from model import Reading

                        r = Reading(**info["reading"])
                    roi = info.get("roi", roi)
                    text = f"{name} ROI={roi} frame={seq} state={r.state if r else '?'} kind={r.kind if r else '?'} confidence={r.confidence if r else 0:.2f}"
                    canvas.create_text(10, ypos, anchor="nw", text=text, fill="white")
                    ypos += 22
                    canvas.create_text(
                        10,
                        ypos,
                        anchor="nw",
                        text=f"{r.reason if r else ''} bbox={info.get('bbox')} raw_shape={info.get('raw_shape')} updated={info.get('updated')} seen={r.seen if r else None}",
                        fill="#cbd5e1",
                    )
                    ypos += 22
                    views = [("원본", info["raw"])] if "raw" in info else []
                    if roi and not views:
                        x, y, rr, b = roi
                        if x >= box[0] and y >= box[1] and rr <= box[2] and b <= box[3]:
                            views.append(("원본", rgb[y - box[1] : b - box[1], x - box[0] : rr - box[0]]))
                    views.extend(
                        (label, info[key])
                        for label, key in [("처리 마스크", "mask"), ("크기/위치 정규화", "normalized")]
                        if key in info
                    )
                    xpos = 10
                    maxh = 0
                    for label, pixels in views:
                        if pixels.size == 0:
                            continue
                        im = Image.fromarray(pixels)
                        im.thumbnail((240, 125))
                        photo = ImageTk.PhotoImage(im)
                        win.images.append(photo)
                        canvas.create_text(xpos, ypos, anchor="nw", text=label, fill="cyan")
                        canvas.create_image(xpos, ypos + 20, anchor="nw", image=photo)
                        xpos += 270
                        maxh = max(maxh, im.height)
                    ypos += maxh + 40
                canvas.configure(scrollregion=(0, 0, 900, ypos))
            win.after(250, update)

        update()
