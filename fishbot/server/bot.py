import random
import threading
import time
import os

from overlay import FishbotOverlay
from process_utils import install_requirements

ImageGrab = None
_imagegrab_error = None


def _load_imagegrab(force_reinstall=False):
    global ImageGrab, _imagegrab_error
    if force_reinstall:
        install_requirements("Pillow", force=True)
        import importlib
        import sys
        for name in list(sys.modules):
            if name == "PIL" or name.startswith("PIL."):
                sys.modules.pop(name, None)
        importlib.invalidate_caches()
    try:
        from PIL import ImageGrab as _ImageGrab
        ImageGrab = _ImageGrab
        _imagegrab_error = None
        return ImageGrab
    except Exception as exc:
        ImageGrab = None
        _imagegrab_error = exc
        return None


_load_imagegrab()

try:
    from pynput.mouse import Button, Controller as MouseController
    from pynput.keyboard import Controller as KeyboardController, Key
except Exception:
    Button = None
    MouseController = None
    KeyboardController = None
    Key = None


class FishbotRuntime:
    def __init__(self):
        self._thread = None
        self._overlay = None
        self._settings = {}
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._status = {
            "running": False,
            "paused": False,
            "catches": 0,
            "misses": 0,
            "lastWhiteVsBlackPercent": 100.0,
            "lastUnderwater": False,
            "message": "Ready",
            "error": "",
        }

    def screen_size(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:
            pass
        if ImageGrab:
            try:
                img = ImageGrab.grab()
                return img.size
            except Exception:
                pass
        return 1920, 1080

    def start(self, settings):
        if ImageGrab is None and _load_imagegrab(force_reinstall=True) is None:
            detail = " (" + str(_imagegrab_error) + ")" if _imagegrab_error else ""
            raise RuntimeError("Fishbot requires Pillow for screen capture. Install Pillow into DigiTek Lab's Python runtime." + detail)
        if MouseController is None and os.name != "nt":
            raise RuntimeError("Fishbot requires pynput for mouse input on this platform.")
        settings = dict(settings or {})
        start_overlay = bool(settings.get("showOverlay"))
        with self._lock:
            if self._status["running"]:
                return self.status()
            self._settings = dict(settings)
            self._stop.clear()
            self._status.update({
                "running": True,
                "paused": bool(settings.get("startPaused")),
                "catches": 0,
                "misses": 0,
                "message": "Fishbot started",
                "error": "",
                "overlay": "off",
            })
            self._thread = threading.Thread(target=self._run, args=(settings,), name="Fishbot3", daemon=True)
            self._thread.start()
            started = dict(self._status)
        if start_overlay:
            self._open_overlay(settings)
        return self.status() if start_overlay else started

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(1.0)
        with self._lock:
            self._thread = None
            self._status["running"] = False
            self._status["message"] = "Stopped"
            self._status["overlay"] = "off"
        self._close_overlay()
        return self.status()

    def update_settings(self, settings):
        settings = dict(settings or {})
        open_overlay = False
        close_overlay = False
        current_settings = {}
        with self._lock:
            self._settings.update(settings)
            current_settings = dict(self._settings)
            running = bool(self._status.get("running"))
            wants_overlay = bool(self._settings.get("showOverlay"))
            has_overlay = self._overlay is not None
            open_overlay = running and wants_overlay and not has_overlay
            close_overlay = running and not wants_overlay and has_overlay
        if open_overlay:
            self._open_overlay(current_settings)
        elif close_overlay:
            self._close_overlay()
        return self.status()

    def status(self):
        with self._lock:
            return dict(self._status)

    def _set(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)

    def _bump(self, key, message):
        with self._lock:
            self._status[key] = int(self._status.get(key, 0) or 0) + 1
            self._status["message"] = message

    def _open_overlay(self, settings):
        self._close_overlay()
        try:
            self._set(overlay="starting", message="Fishbot started; opening overlay")
            self._overlay = FishbotOverlay(
                settings.get("bbox"),
                settings.get("magicValue", 100),
                self.stop,
                error_callback=self._overlay_error,
                ready_callback=self._overlay_ready,
                object_mode=bool(settings.get("objectDetectionOverlay")),
            )
        except Exception as exc:
            self._overlay_error(str(exc))

    def _close_overlay(self):
        overlay = self._overlay
        self._overlay = None
        if overlay:
            overlay.close()
        self._set(overlay="off")

    def _update_overlay(self, img, percent, underwater, settings, object_box):
        overlay = self._overlay
        if overlay:
            overlay.update(
                img,
                percent,
                underwater,
                int(settings.get("magicValue", 100) or 100),
                object_box,
            )

    def _overlay_ready(self):
        self._set(overlay="open", message="Fishbot started; overlay open")

    def _overlay_error(self, reason):
        self._close_overlay()
        self._set(overlay="error", message="Overlay unavailable: " + str(reason))

    def _run(self, settings):
        mouse = self._make_mouse()
        keyboard = KeyboardController() if KeyboardController else None
        previous_underwater = False
        current_failure_rate = int(settings.get("failingMultiplier", 0) or 0)
        catch_count = 0
        next_wave = random.randint(10, 15)
        timer_end = self._timer_end(settings)
        if settings.get("failingPattern") == "Getting tired":
            current_failure_rate = min(current_failure_rate, 5)
        elif settings.get("failingPattern") == "Improve over time":
            current_failure_rate = max(current_failure_rate, 100)

        try:
            while not self._stop.is_set():
                with self._lock:
                    settings = dict(self._settings or settings)

                if timer_end and time.time() >= timer_end:
                    self._timer_actions(settings, keyboard)
                    self._set(message="Timer ended")
                    break

                bbox = self._bbox(settings.get("bbox"))
                if not bbox:
                    self._set(message="Select a valid detection region")
                    time.sleep(1.5)
                    continue

                img = ImageGrab.grab(bbox=bbox)
                magic_value = int(settings.get("magicValue", 100) or 100)
                percent = self._white_vs_black_percent(img, magic_value)
                underwater = percent <= 0.1
                overlay = self._overlay
                object_box = self._bobber_box(img, magic_value) if overlay and overlay.object_mode() else None
                self._set(
                    lastWhiteVsBlackPercent=round(percent, 4),
                    lastUnderwater=underwater,
                    lastObjectBox=object_box,
                )
                self._update_overlay(img, percent, underwater, settings, object_box)

                if underwater and not previous_underwater:
                    if not settings.get("startPaused") and self._should_click(current_failure_rate):
                        self._click(mouse, settings.get("clickLocation"))
                        time.sleep(1.5)
                        self._click(mouse, settings.get("clickLocation"))
                        catch_count += 1
                        self._bump("catches", "Catch detected")
                        current_failure_rate = self._adjust_rate(settings, current_failure_rate, True)
                    else:
                        catch_count += 1
                        self._bump("misses", "Humanized miss")
                        current_failure_rate = self._adjust_rate(settings, current_failure_rate, False)

                    if catch_count >= next_wave:
                        if settings.get("failingPattern") == "Getting tired":
                            current_failure_rate += 5
                        elif settings.get("failingPattern") == "Improve over time":
                            current_failure_rate -= 5
                        current_failure_rate = self._clamp_rate(current_failure_rate)
                        next_wave = catch_count + random.randint(10, 15)

                previous_underwater = underwater
                time.sleep(0.15 if self._overlay else 1.5)
        except Exception as exc:
            self._set(error=str(exc), message="Error: " + str(exc))
        finally:
            self._set(running=False)
            self._close_overlay()

    def _bbox(self, bbox):
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        left, right, top, bottom = [int(v) for v in bbox]
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    def _white_vs_black_percent(self, img, magic_value):
        gray = img.convert("L")
        w, h = gray.size
        max_side = 420
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        hist = gray.histogram()
        threshold = max(0, min(255, int(magic_value)))
        black = sum(hist[:threshold + 1])
        total = sum(hist)
        if total <= 0:
            return 100.0
        black_ratio = black / total
        if black_ratio <= 0:
            return 100.0
        white_ratio = 1.0 - black_ratio
        return (white_ratio / black_ratio) * 100.0

    def _bobber_box(self, img, magic_value):
        gray = img.convert("L")
        src_w, src_h = gray.size
        if src_w <= 0 or src_h <= 0:
            return None
        max_side = 220
        scale = 1.0
        if max(src_w, src_h) > max_side:
            scale = max_side / float(max(src_w, src_h))
            gray = gray.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))))

        w, h = gray.size
        threshold = max(0, min(255, int(magic_value)))
        pixels = gray.load()
        dark = bytearray(w * h)
        dark_count = 0
        for y in range(h):
            row = y * w
            for x in range(w):
                if pixels[x, y] <= threshold:
                    dark[row + x] = 1
                    dark_count += 1

        total = w * h
        if total <= 0:
            return None
        dark_ratio = dark_count / float(total)
        if dark_ratio < 0.0005 or dark_ratio > 0.65:
            return None

        visited = bytearray(total)
        best = None
        min_area = max(6, int(total * 0.0008))
        max_area = max(min_area + 1, int(total * 0.18))
        for i, value in enumerate(dark):
            if not value or visited[i]:
                continue
            stack = [i]
            visited[i] = 1
            count = 0
            min_x = w
            min_y = h
            max_x = 0
            max_y = 0
            while stack:
                pos = stack.pop()
                x = pos % w
                y = pos // w
                count += 1
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

                for ny in (y - 1, y, y + 1):
                    if ny < 0 or ny >= h:
                        continue
                    row = ny * w
                    for nx in (x - 1, x, x + 1):
                        if nx < 0 or nx >= w or (nx == x and ny == y):
                            continue
                        ni = row + nx
                        if dark[ni] and not visited[ni]:
                            visited[ni] = 1
                            stack.append(ni)

            if count < min_area or count > max_area:
                continue
            bw = max_x - min_x + 1
            bh = max_y - min_y + 1
            if bw < 3 or bh < 3:
                continue
            fill = count / float(bw * bh)
            if fill < 0.12:
                continue
            if best is None or count > best[0]:
                best = (count, min_x, min_y, max_x, max_y)

        if not best:
            return None
        _, min_x, min_y, max_x, max_y = best
        inv = 1.0 / scale
        pad = max(2, int(4 * inv))
        return [
            max(0, int(min_x * inv) - pad),
            max(0, int(min_y * inv) - pad),
            min(src_w, int((max_x + 1) * inv) + pad),
            min(src_h, int((max_y + 1) * inv) + pad),
        ]

    def _should_click(self, failure_rate):
        return random.randrange(100) >= self._clamp_rate(failure_rate)

    def _adjust_rate(self, settings, current, clicked):
        pattern = settings.get("failingPattern") or "Random"
        if pattern == "Getting tired":
            current += random.randint(1, 2) if clicked else -random.randint(1, 4)
        elif pattern == "Improve over time":
            current += -random.randint(1, 2) if clicked else random.randint(1, 4)
        return self._clamp_rate(current)

    def _click(self, mouse, xy):
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            return
        x, y = int(xy[0]), int(xy[1])
        if x <= 0 or y <= 0:
            return
        mouse.click(x, y)

    def _make_mouse(self):
        if MouseController and Button:
            return _PynputMouse(MouseController(), Button.left)
        return _WindowsMouse()

    def _timer_end(self, settings):
        if not settings.get("timer"):
            return None
        duration = max(1, int(settings.get("timerDuration", 60) or 60))
        unit = settings.get("timerUnit", "minutes")
        seconds = duration if unit == "seconds" else duration * 3600 if unit == "hours" else duration * 60
        return time.time() + seconds

    def _timer_actions(self, settings, keyboard):
        if not keyboard:
            return
        if settings.get("goHome"):
            keyboard.press("h")
            keyboard.release("h")
            time.sleep(1)
        if settings.get("quitGame") and Key:
            keyboard.press(Key.alt)
            keyboard.press(Key.f4)
            keyboard.release(Key.f4)
            keyboard.release(Key.alt)

    def _clamp_rate(self, value):
        return max(0, min(100, int(value)))


class _PynputMouse:
    def __init__(self, mouse, left_button):
        self._mouse = mouse
        self._left_button = left_button

    def click(self, x, y):
        self._mouse.position = (x, y)
        self._mouse.press(self._left_button)
        time.sleep((20 + random.randint(0, 40)) / 1000.0)
        self._mouse.release(self._left_button)


class _WindowsMouse:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Mouse input is unavailable because pynput is not installed.")
        import ctypes
        self._user32 = ctypes.windll.user32
        self._mouse_event = self._user32.mouse_event
        self._left_down = 0x0002
        self._left_up = 0x0004

    def click(self, x, y):
        self._user32.SetCursorPos(int(x), int(y))
        self._mouse_event(self._left_down, 0, 0, 0, 0)
        time.sleep((20 + random.randint(0, 40)) / 1000.0)
        self._mouse_event(self._left_up, 0, 0, 0, 0)


fishbot = FishbotRuntime()
