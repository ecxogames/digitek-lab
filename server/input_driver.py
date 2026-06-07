# DigiTek Lab — Input Driver
#
# Thin wrapper around `pynput` that the recorder and player share. It is the ONLY
# module that talks to the real keyboard/mouse, so the rest of the engine stays
# testable and `pynput` is imported lazily (the UI must still load if it is missing).
#
# Coordinates used by the engine are NORMALIZED to the 0..1 range of the primary
# screen so a macro recorded at one resolution replays correctly at another. This
# module is the single place that converts between normalized and pixel space.

import time

# ── Lazy pynput handles ───────────────────────────────────────────────
_mouse = None
_keyboard = None
_Controller_mouse = None
_Controller_keyboard = None
_Button = None
_Key = None
_KeyCode = None
_import_error = None


class InputUnavailable(RuntimeError):
    """Raised when pynput (or a display) is not available."""


def _ensure_imported():
    """Import pynput on first use. Raises InputUnavailable on failure."""
    global _mouse, _keyboard, _Controller_mouse, _Controller_keyboard
    global _Button, _Key, _KeyCode, _import_error

    if _Controller_mouse is not None:
        return

    if _import_error is not None:
        raise InputUnavailable(_import_error)

    try:
        from pynput import mouse as _m, keyboard as _k
        _mouse, _keyboard = _m, _k
        _Button = _m.Button
        _Key = _k.Key
        _KeyCode = _k.KeyCode
        _Controller_mouse = _m.Controller()
        _Controller_keyboard = _k.Controller()
    except Exception as e:  # ImportError, or platform/display errors
        _import_error = (
            "pynput is not available (" + str(e) + "). "
            "Install it with 'pip install pynput' to enable recording and playback."
        )
        raise InputUnavailable(_import_error)


def is_available():
    """Return True if real input I/O can be performed."""
    try:
        _ensure_imported()
        return True
    except InputUnavailable:
        return False


def availability_error():
    """Return the human-readable reason input is unavailable, or None."""
    try:
        _ensure_imported()
        return None
    except InputUnavailable as e:
        return str(e)


# ── Screen geometry ───────────────────────────────────────────────────
_screen_size_cache = None


def get_screen_size():
    """Return (width, height) of the primary screen in pixels. Best-effort."""
    global _screen_size_cache
    if _screen_size_cache:
        return _screen_size_cache

    size = None
    # Windows: ctypes is reliable and dependency-free.
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        size = (int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))
    except Exception:
        size = None

    if not size or size[0] <= 0:
        # Fallback via tkinter.
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            size = (root.winfo_screenwidth(), root.winfo_screenheight())
            root.destroy()
        except Exception:
            size = (1920, 1080)

    _screen_size_cache = size
    return size


def to_pixels(nx, ny):
    """Normalized (0..1) → absolute pixel (x, y)."""
    w, h = get_screen_size()
    return int(round(nx * w)), int(round(ny * h))


def to_normalized(px, py):
    """Absolute pixel (x, y) → normalized (0..1, 0..1)."""
    w, h = get_screen_size()
    w = w or 1
    h = h or 1
    return px / w, py / h


# ── Key name <-> pynput translation ───────────────────────────────────
def key_to_name(key):
    """Convert a pynput key event object into a portable string name."""
    _ensure_imported()
    if isinstance(key, _KeyCode):
        if key.char is not None:
            return key.char
        # Some keys arrive as KeyCode with a virtual-key code only.
        return "vk_" + str(key.vk)
    if isinstance(key, _Key):
        return key.name  # e.g. "space", "ctrl_l", "f8"
    return str(key)


def name_to_key(name):
    """Convert a portable string name back into something pynput can press."""
    _ensure_imported()
    if name is None:
        return None
    if isinstance(name, str) and name.startswith("vk_"):
        try:
            return _KeyCode.from_vk(int(name[3:]))
        except Exception:
            return None
    # Named special key?
    if hasattr(_Key, str(name)):
        return getattr(_Key, name)
    # Single character / literal.
    if isinstance(name, str) and len(name) >= 1:
        return name
    return name


def _button_from_name(name):
    _ensure_imported()
    return getattr(_Button, name, _Button.left)


def button_to_name(button):
    _ensure_imported()
    try:
        return button.name
    except Exception:
        return "left"


# ── Output primitives (used by the player) ────────────────────────────
def move_to(nx, ny):
    _ensure_imported()
    _Controller_mouse.position = to_pixels(nx, ny)


def mouse_down(nx=None, ny=None, button="left"):
    _ensure_imported()
    if nx is not None and ny is not None:
        _Controller_mouse.position = to_pixels(nx, ny)
    _Controller_mouse.press(_button_from_name(button))


def mouse_up(nx=None, ny=None, button="left"):
    _ensure_imported()
    if nx is not None and ny is not None:
        _Controller_mouse.position = to_pixels(nx, ny)
    _Controller_mouse.release(_button_from_name(button))


def click(nx, ny, button="left", count=1):
    _ensure_imported()
    _Controller_mouse.position = to_pixels(nx, ny)
    _Controller_mouse.click(_button_from_name(button), max(1, int(count)))


def scroll(dx, dy):
    _ensure_imported()
    _Controller_mouse.scroll(int(dx), int(dy))


def key_press(name):
    _ensure_imported()
    k = name_to_key(name)
    if k is not None:
        _Controller_keyboard.press(k)


def key_release(name):
    _ensure_imported()
    k = name_to_key(name)
    if k is not None:
        _Controller_keyboard.release(k)


def tap(name, hold_ms=40):
    _ensure_imported()
    key_press(name)
    time.sleep(max(0, hold_ms) / 1000.0)
    key_release(name)


def smooth_move(from_n, to_n, duration_ms, steps=60, hold_button=None):
    """
    Interpolate the cursor from one normalized point to another over a duration.
    If hold_button is set, the button is held for the whole move (a drag).
    """
    _ensure_imported()
    steps = max(1, int(steps))
    fx, fy = from_n
    tx, ty = to_n
    if hold_button:
        mouse_down(fx, fy, hold_button)
    try:
        for i in range(1, steps + 1):
            f = i / steps
            move_to(fx + (tx - fx) * f, fy + (ty - fy) * f)
            time.sleep(max(0, duration_ms) / 1000.0 / steps)
    finally:
        if hold_button:
            mouse_up(tx, ty, hold_button)


def get_controllers():
    """Expose the raw pynput controllers (mouse, keyboard) for advanced use."""
    _ensure_imported()
    return _Controller_mouse, _Controller_keyboard


# ── Raw Windows SendInput (for game-reliable drags) ───────────────────
# Roblox's right-click camera pan locks the cursor and reads RELATIVE mouse
# motion via raw input — absolute SetCursorPos moves (what pynput sends) don't
# rotate the camera, and the held button can fail to register. These helpers use
# SendInput with a held button + relative deltas, which games read correctly.
try:
    import ctypes as _ct
    from ctypes import wintypes as _wt

    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _BTN_DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
    _BTN_UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}
    _ULONG_PTR = _ct.POINTER(_ct.c_ulong)

    class _MOUSEINPUT(_ct.Structure):
        _fields_ = [("dx", _ct.c_long), ("dy", _ct.c_long), ("mouseData", _ct.c_ulong),
                    ("dwFlags", _ct.c_ulong), ("time", _ct.c_ulong), ("dwExtraInfo", _ULONG_PTR)]

    class _INPUTUNION(_ct.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    class _INPUT(_ct.Structure):
        _fields_ = [("type", _ct.c_ulong), ("u", _INPUTUNION)]

    def _send_mouse(flags, dx=0, dy=0, data=0):
        extra = _ct.c_ulong(0)
        mi = _MOUSEINPUT(dx, dy, data, flags, 0, _ct.cast(_ct.pointer(extra), _ULONG_PTR))
        inp = _INPUT(0, _INPUTUNION(mi))  # type 0 = INPUT_MOUSE
        _ct.windll.user32.SendInput(1, _ct.byref(inp), _ct.sizeof(_INPUT))

    _SENDINPUT_OK = True
except Exception:  # non-Windows / no ctypes
    _SENDINPUT_OK = False

# Carries sub-pixel rounding remainder across a drag so relative motion doesn't drift.
_rel_remainder = [0.0, 0.0]


def raw_move_abs(nx, ny):
    """Place the cursor at a normalized point via SendInput (absolute) and reset drift."""
    _rel_remainder[0] = _rel_remainder[1] = 0.0
    if not _SENDINPUT_OK:
        move_to(nx, ny)
        return
    ax = int(max(0, min(65535, round(nx * 65535))))
    ay = int(max(0, min(65535, round(ny * 65535))))
    _send_mouse(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, ax, ay)


def raw_move_relative(ndx, ndy):
    """Send a RELATIVE mouse motion (normalized fractions of the screen)."""
    if not _SENDINPUT_OK:
        return
    w, h = get_screen_size()
    fx = ndx * w + _rel_remainder[0]
    fy = ndy * h + _rel_remainder[1]
    dx = int(round(fx))
    dy = int(round(fy))
    _rel_remainder[0] = fx - dx
    _rel_remainder[1] = fy - dy
    if dx or dy:
        _send_mouse(_MOUSEEVENTF_MOVE, dx, dy)


def raw_button(button, down):
    """Press/release a mouse button via SendInput at the current cursor position."""
    if not _SENDINPUT_OK:
        (mouse_down if down else mouse_up)(button=button)
        return
    table = _BTN_DOWN if down else _BTN_UP
    _send_mouse(table.get(button, table["left"]))
