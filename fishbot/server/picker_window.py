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
            f.write("picker_window failed: " + repr(exc) + "\n")
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "region"
    result_path = sys.argv[2] if len(sys.argv) > 2 else ""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.35)
    root.configure(bg="black")
    root.overrideredirect(True)

    width = root.winfo_screenwidth()
    height = root.winfo_screenheight()
    canvas = tk.Canvas(root, width=width, height=height, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    label = "Click the fishing click target" if mode == "point" else "Drag over the bobber detection region"
    canvas.create_text(width // 2, 42, text=label + "  (Esc to cancel)", fill="white", font=("Segoe UI", 16, "bold"))

    state = {"start": None, "rect": None, "result": None, "cancelled": False}

    def write_result(payload):
        if result_path:
            tmp = result_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, result_path)
        print(json.dumps(payload), flush=True)

    def finish(value):
        state["result"] = value
        root.quit()

    def cancel(_event=None):
        state["cancelled"] = True
        root.quit()

    def on_down(event):
        if mode == "point":
            finish({"x": int(event.x_root), "y": int(event.y_root)})
            return
        state["start"] = (event.x_root, event.y_root)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(event.x_root, event.y_root, event.x_root, event.y_root, outline="#44ff44", width=2, dash=(10, 5))

    def on_drag(event):
        if mode != "region" or not state["start"] or not state["rect"]:
            return
        x1, y1 = state["start"]
        canvas.coords(state["rect"], x1, y1, event.x_root, event.y_root)

    def on_up(event):
        if mode != "region" or not state["start"]:
            return
        x1, y1 = state["start"]
        x2, y2 = event.x_root, event.y_root
        left, right = sorted((int(x1), int(x2)))
        top, bottom = sorted((int(y1), int(y2)))
        if right - left >= 4 and bottom - top >= 4:
            finish({"left": left, "right": right, "top": top, "bottom": bottom})

    root.bind("<Escape>", cancel)
    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)

    def force_front():
        root.attributes("-topmost", False)
        root.attributes("-topmost", True)
        root.lift()
        root.update_idletasks()
        root.focus_force()
        canvas.focus_set()
        root.grab_set()
        if os.name == "nt":
            try:
                import ctypes
                hwnd = int(root.winfo_id())
                ctypes.windll.user32.ShowWindow(hwnd, 5)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    root.deiconify()
    force_front()
    root.after(120, force_front)
    root.after(600, force_front)
    root.after(1200, force_front)
    root.mainloop()
    try:
        root.grab_release()
    except Exception:
        pass
    root.destroy()

    if state["cancelled"] or not state["result"]:
        write_result({"status": "cancelled"})
        return 2
    write_result({"status": "ok", "result": state["result"]})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log_error(exc)
        payload = {"status": "error", "reason": str(exc)}
        if len(sys.argv) > 2:
            try:
                tmp = sys.argv[2] + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                os.replace(tmp, sys.argv[2])
            except Exception:
                pass
        print(json.dumps(payload), flush=True)
        raise
