import json
import os
import shutil
import tempfile
import threading
import time

from process_utils import popen


class FishbotOverlay:
    def __init__(self, bbox, magic_value, stop_callback, error_callback=None, ready_callback=None, object_mode=False):
        self._bbox = self._normalize_bbox(bbox)
        self._magic_value = int(magic_value or 100)
        self._stop_callback = stop_callback
        self._error_callback = error_callback
        self._ready_callback = ready_callback
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._state_dir = tempfile.mkdtemp(prefix="fishbot_overlay_")
        self._state_path = os.path.join(self._state_dir, "state.json")
        self._frame_path = os.path.join(self._state_dir, "frame.png")
        self._object_path = os.path.join(self._state_dir, "object_mode.txt")
        self._close_path = os.path.join(self._state_dir, "close")
        self._stop_path = os.path.join(self._state_dir, "stop")
        self._object_mode = bool(object_mode)
        self._proc = None
        self._monitor = None
        self._write_text(self._object_path, "1" if self._object_mode else "0")
        self._write_state(None, 100.0, False, self._magic_value, None)
        self._start()

    def _start(self):
        try:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay_window.py")
            self._proc = popen([script, self._state_dir], visible=True)
            self._monitor = threading.Thread(target=self._monitor_proc, name="FishbotOverlayMonitor", daemon=True)
            self._monitor.start()
            self._report_ready()
        except Exception as exc:
            self._report_error(exc)

    def update(self, image, percent, detected, magic_value=None, object_box=None, object_mode=None):
        if self._closed.is_set():
            return
        with self._lock:
            if magic_value is not None:
                self._magic_value = int(magic_value or 100)
            if object_mode is not None:
                self._object_mode = bool(object_mode)
                self._write_text(self._object_path, "1" if self._object_mode else "0")
            try:
                tmp = self._frame_path + ".tmp"
                image.copy().save(tmp, "PNG")
                os.replace(tmp, self._frame_path)
            except Exception as exc:
                self._report_error(exc)
                return
            self._write_state(image, percent, detected, self._magic_value, object_box)
            self._check_stop_request()

    def close(self):
        self._closed.set()
        self._write_text(self._close_path, "1")
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        shutil.rmtree(self._state_dir, ignore_errors=True)

    def object_mode(self):
        try:
            self._object_mode = open(self._object_path, "r", encoding="utf-8").read().strip() == "1"
        except Exception:
            pass
        self._check_stop_request()
        return bool(self._object_mode)

    def _write_state(self, image, percent, detected, magic_value, object_box):
        data = {
            "bbox": self._bbox,
            "percent": float(percent or 0),
            "detected": bool(detected),
            "magicValue": int(magic_value or 100),
            "objectBox": object_box if object_box and len(object_box) == 4 else None,
            "objectMode": bool(self._object_mode),
            "updatedAt": time.time(),
        }
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._state_path)

    def _write_text(self, path, value):
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(value)
            os.replace(tmp, path)
        except Exception:
            pass

    def _monitor_proc(self):
        while not self._closed.is_set():
            self._check_stop_request()
            proc = self._proc
            if proc and proc.poll() is not None:
                break
            time.sleep(0.15)

    def _check_stop_request(self):
        if os.path.exists(self._stop_path) and not self._closed.is_set():
            self._closed.set()
            threading.Thread(target=self._stop_callback, name="FishbotOverlayStop", daemon=True).start()

    def _report_error(self, exc):
        if self._error_callback:
            self._error_callback(str(exc))

    def _report_ready(self):
        if self._ready_callback:
            self._ready_callback()

    def _normalize_bbox(self, bbox):
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return [0, 0, 800, 600]
        left, right, top, bottom = [int(v) for v in bbox]
        return [min(left, right), min(top, bottom), max(left, right), max(top, bottom)]
