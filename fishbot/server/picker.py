import json
import os
import shutil
import tempfile
import time

from process_utils import popen


def pick_point():
    result = _run_picker("point")
    return [result["x"], result["y"]]


def pick_region():
    result = _run_picker("region")
    return [result["left"], result["right"], result["top"], result["bottom"]]


def _run_picker(mode):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picker_window.py")
    state_dir = tempfile.mkdtemp(prefix="fishbot_picker_")
    result_path = os.path.join(state_dir, "result.json")
    try:
        proc = popen([script, mode, result_path], visible=True)
        deadline = time.time() + 3600
        while time.time() < deadline:
            if os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == "cancelled":
                    raise RuntimeError("Picker cancelled.")
                if data.get("status") != "ok":
                    raise RuntimeError(data.get("reason") or "Screen picker failed.")
                return data.get("result") or {}
            if proc.poll() is not None:
                break
            time.sleep(0.05)

        error = _window_error_tail()
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            raise RuntimeError("Screen picker did not return a selection. The overlay window may be blocked by Windows focus rules." + error)
        raise RuntimeError("Screen picker closed before returning a selection." + error)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


def _window_error_tail():
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        path = os.path.join(base, "DigiTek Lab", "plugin-data", "fishbot", "window-errors.log")
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()[-700:].strip()
        return " " + text if text else ""
    except Exception:
        return ""
