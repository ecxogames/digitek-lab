import json
import os
import sys
import traceback


def log_error(exc):
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        path = os.path.join(base, "DigiTek Lab", "plugin-data", "fishbot", "window-errors.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("overlay_window failed: " + repr(exc) + "\n")
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def write_text(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(value)
    os.replace(tmp, path)


def main():
    state_dir = sys.argv[1]
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk

    width = 460
    height = 300
    toolbar_h = 28
    state_path = os.path.join(state_dir, "state.json")
    frame_path = os.path.join(state_dir, "frame.png")
    close_path = os.path.join(state_dir, "close")
    stop_path = os.path.join(state_dir, "stop")
    object_path = os.path.join(state_dir, "object_mode.txt")

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#111111")
    root.geometry(f"{width}x{height + toolbar_h}+0+0")

    drag = {"x": 0, "y": 0}
    toolbar = tk.Frame(root, bg="#464646", height=toolbar_h)
    toolbar.pack(side="top", fill="x")
    toolbar.pack_propagate(False)
    percent_label = tk.Label(toolbar, text="W/B: 0.0%", bg="#464646", fg="white", font=("Segoe UI", 9))
    percent_label.pack(side="left", padx=(8, 4))
    object_btn = tk.Button(toolbar, text="Object: Off", bg="#5a5a5a", fg="white", activebackground="#707070", activeforeground="white", bd=0, padx=8, pady=1, font=("Segoe UI", 8))
    object_btn.pack(side="left", padx=4, pady=4)
    stop_btn = tk.Button(toolbar, text="■", command=lambda: (write_text(stop_path, "1"), root.destroy()), bg="#5a5a5a", fg="white", activebackground="#707070", activeforeground="white", bd=0, padx=8, pady=1, font=("Segoe UI", 9))
    stop_btn.pack(side="right", padx=6, pady=4)
    preview = tk.Label(root, bg="black", bd=0)
    preview.pack(side="top", fill="both", expand=True)
    preview.image_ref = None

    def begin_drag(event):
        drag["x"] = event.x_root - root.winfo_x()
        drag["y"] = event.y_root - root.winfo_y()

    def drag_window(event):
        root.geometry(f"+{event.x_root - drag['x']}+{event.y_root - drag['y']}")

    toolbar.bind("<ButtonPress-1>", begin_drag)
    toolbar.bind("<B1-Motion>", drag_window)
    percent_label.bind("<ButtonPress-1>", begin_drag)
    percent_label.bind("<B1-Motion>", drag_window)

    object_mode = read_json(state_path, {}).get("objectMode", False)

    def toggle_object_mode():
        nonlocal object_mode
        object_mode = not object_mode
        write_text(object_path, "1" if object_mode else "0")

    object_btn.configure(command=toggle_object_mode)

    def tick():
        nonlocal object_mode
        if os.path.exists(close_path):
            root.destroy()
            return
        state = read_json(state_path, {})
        if os.path.exists(object_path):
            try:
                object_mode = open(object_path, "r", encoding="utf-8").read().strip() == "1"
            except Exception:
                pass
        if os.path.exists(frame_path):
            try:
                frame = Image.open(frame_path).convert("RGB")
                magic_value = int(state.get("magicValue", 100) or 100)
                gray = frame.convert("L")
                threshold = max(0, min(255, magic_value))
                frame = gray.point(lambda px: 0 if px <= threshold else 255).convert("RGB")
                resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
                src_w, src_h = frame.size
                scale = min(width / float(max(1, src_w)), height / float(max(1, src_h)))
                view_w = max(1, int(src_w * scale))
                view_h = max(1, int(src_h * scale))
                offset_x = (width - view_w) // 2
                offset_y = (height - view_h) // 2
                frame = frame.resize((view_w, view_h), resample)
                canvas = Image.new("RGB", (width, height), "black")
                canvas.paste(frame, (offset_x, offset_y))
                frame = canvas
                draw = ImageDraw.Draw(frame)
                if object_mode and state.get("objectBox"):
                    x1, y1, x2, y2 = state["objectBox"]
                    rect = [offset_x + int(x1 * scale), offset_y + int(y1 * scale), offset_x + int(x2 * scale), offset_y + int(y2 * scale)]
                    for offset in range(2):
                        draw.rectangle([rect[0] - offset, rect[1] - offset, rect[2] + offset, rect[3] + offset], outline="#38bdf8")
                detected = bool(state.get("detected"))
                label = "Detected" if detected else "Not detected"
                color = "#22c55e" if detected else "#ef4444"
                draw.text((9, 8), label, fill="black")
                draw.text((8, 7), label, fill=color)
                photo = ImageTk.PhotoImage(frame)
                preview.configure(image=photo)
                preview.image_ref = photo
                percent_label.configure(text=f"W/B: {float(state.get('percent', 0) or 0):.1f}%")
            except Exception:
                pass
        object_btn.configure(text="Object: On" if object_mode else "Object: Off", bg="#2563eb" if object_mode else "#5a5a5a")
        root.after(80, tick)

    root.deiconify()
    root.lift()
    root.focus_force()
    if os.name == "nt":
        try:
            import ctypes
            hwnd = int(root.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 5)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    root.after(80, tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log_error(exc)
        raise
