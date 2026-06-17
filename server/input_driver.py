# Slice AMAS — Input Driver
#
# Thin wrapper around `pynput` that the recorder and player share. It is the ONLY
# module that talks to the real keyboard/mouse, so the rest of the engine stays
# testable and `pynput` is imported lazily (the UI must still load if it is missing).
#
# Coordinates used by the engine are NORMALIZED to the 0..1 range of the primary
# screen so a macro recorded at one resolution replays correctly at another. This
# module is the single place that converts between normalized and pixel space.

import os
import importlib
import json
import queue
import shutil
import subprocess
import sys
import threading
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
_vgamepad = None
_Controller_gamepad = None
_gamepad_error = None
_external_python = None
_external_python_paths_added = False
_support_job_lock = threading.Lock()
_support_job = {
    "running": False,
    "kind": None,
    "phase": "idle",
    "progress": 0,
    "message": "",
    "detail": "",
    "done": True,
    "ok": False,
    "error": None,
    "controllerAvailable": False,
    "controllerError": None,
    "log": [],
}


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


class ControllerUnavailable(RuntimeError):
    """Raised when virtual Xbox controller output is not available."""


def _ensure_gamepad():
    """
    Lazily create a virtual Xbox 360 controller.

    Requires the optional `vgamepad` package and the ViGEmBus driver on Windows.
    Keeping this separate from pynput lets keyboard/mouse playback keep working
    even on machines without virtual controller support.
    """
    global _vgamepad, _Controller_gamepad, _gamepad_error
    if _Controller_gamepad is not None:
        return
    if _gamepad_error is not None:
        raise ControllerUnavailable(_gamepad_error)
    try:
        _add_computer_python_paths()
        import vgamepad as _vg
        _vgamepad = _vg
        _Controller_gamepad = _vg.VX360Gamepad()
        _Controller_gamepad.update()
    except Exception as e:
        _gamepad_error = (
            "Virtual controller output is not available (" + str(e) + "). "
            "Install 'vgamepad' and the ViGEmBus driver to play Controller Axis actions."
        )
        raise ControllerUnavailable(_gamepad_error)


def controller_available():
    try:
        _ensure_gamepad()
        return True
    except ControllerUnavailable:
        return False


def controller_availability_error():
    try:
        _ensure_gamepad()
        return None
    except ControllerUnavailable as e:
        return str(e)


def _reset_gamepad_cache():
    global _vgamepad, _Controller_gamepad, _gamepad_error
    importlib.invalidate_caches()
    _vgamepad = None
    _Controller_gamepad = None
    _gamepad_error = None


def _run_dependency_command(args, timeout=300):
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    return {
        "command": " ".join(args),
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def _support_job_snapshot():
    with _support_job_lock:
        snap = dict(_support_job)
        snap["log"] = list(_support_job.get("log", []))[-80:]
        return snap


def _support_job_update(**kwargs):
    with _support_job_lock:
        _support_job.update(kwargs)


def _support_job_log(line):
    line = (line or "").strip()
    if not line:
        return
    with _support_job_lock:
        _support_job.setdefault("log", []).append(line)
        _support_job["log"] = _support_job["log"][-120:]
        _support_job["detail"] = line[-240:]


def _looks_like_app_executable(path):
    name = os.path.basename(path or "").lower()
    return name in {"esdengine.exe", "slice amas.exe"}


def _candidate_python_commands():
    seen = set()

    def add(cmd):
        key = tuple((cmd or []))
        if cmd and key not in seen:
            seen.add(key)
            yield cmd

    env_python = os.environ.get("SLICE_AMAS_PYTHON_EXECUTABLE")
    if env_python:
        yield from add([env_python])

    if os.name == "nt":
        py_launcher = shutil.which("py")
        if py_launcher:
            yield from add([py_launcher, "-3"])

    for name in ("python", "python3"):
        exe = shutil.which(name)
        if exe:
            yield from add([exe])

    base_exe = getattr(sys, "_base_executable", None)
    if base_exe and not _looks_like_app_executable(base_exe):
        yield from add([base_exe])

    prefix_exe = os.path.join(sys.exec_prefix or "", "python.exe" if os.name == "nt" else "python")
    if os.path.exists(prefix_exe) and not _looks_like_app_executable(prefix_exe):
        yield from add([prefix_exe])


def _probe_python_command(cmd):
    probe = (
        "import json, site, sys\n"
        "paths=[]\n"
        "for attr in ('USER_SITE',):\n"
        "    p=getattr(site, attr, None)\n"
        "    if p: paths.append(p)\n"
        "try:\n"
        "    paths.extend(site.getsitepackages())\n"
        "except Exception:\n"
        "    pass\n"
        "print(json.dumps({'executable': sys.executable, 'version': sys.version.split()[0], 'paths': paths}))\n"
    )
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        cmd + ["-c", probe],
        capture_output=True,
        text=True,
        timeout=20,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Python probe failed.").strip())
    data = json.loads((proc.stdout or "").strip().splitlines()[-1])
    exe = data.get("executable") or cmd[0]
    if _looks_like_app_executable(exe):
        raise RuntimeError("Rejected app executable masquerading as Python: " + exe)
    return {
        "cmd": cmd,
        "executable": exe,
        "version": data.get("version"),
        "paths": [p for p in data.get("paths", []) if p],
    }


def _computer_python():
    global _external_python
    if _external_python:
        return _external_python
    errors = []
    for cmd in _candidate_python_commands():
        try:
            info = _probe_python_command(cmd)
            _external_python = info
            return info
        except Exception as e:
            errors.append(" ".join(cmd) + ": " + str(e))
    raise RuntimeError(
        "Could not find a real Python interpreter in the computer PATH. "
        "Install Python from python.org with 'Add python.exe to PATH' enabled, "
        "or set SLICE_AMAS_PYTHON_EXECUTABLE to python.exe. Tried: " + "; ".join(errors)
    )


def _add_computer_python_paths():
    global _external_python_paths_added
    if _external_python_paths_added:
        return
    try:
        info = _computer_python()
    except Exception:
        return
    added = []
    for path in info.get("paths", []):
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)
            added.append(path)
    if added:
        importlib.invalidate_caches()
    _external_python_paths_added = True


def _vgamepad_package_available():
    _add_computer_python_paths()
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec("vgamepad") is not None
    except Exception:
        return False


def _run_dependency_command_stream(args, phase, base_progress, end_progress, timeout=600):
    _support_job_update(phase=phase, message=phase, progress=base_progress)
    _support_job_log("> " + " ".join(args))
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    start = time.time()
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    lines = queue.Queue()

    def _reader():
        try:
            if not proc.stdout:
                return
            for line in iter(proc.stdout.readline, ""):
                if line == "":
                    break
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    output = []
    reader_done = False
    while True:
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                break
            if line is None:
                reader_done = True
                continue
            if line:
                output.append(line.rstrip())
                _support_job_log(line)
                lower = line.lower()
                msg = None
                if "collecting" in lower or "fetch" in lower or "source" in lower:
                    msg = "Fetching from source..."
                elif "download" in lower:
                    msg = "Downloading package..."
                elif "install" in lower:
                    msg = "Installing files..."
                elif "success" in lower:
                    msg = "Finishing up..."
                if msg:
                    _support_job_update(message=msg)
        code = proc.poll()
        elapsed = time.time() - start
        span = max(1, end_progress - base_progress)
        timed_progress = min(end_progress - 2, base_progress + int(span * min(0.92, elapsed / max(20, timeout))))
        _support_job_update(progress=timed_progress)
        if code is not None:
            flush_until = time.time() + 1.0
            while not reader_done and time.time() < flush_until:
                try:
                    line = lines.get(timeout=0.05)
                except queue.Empty:
                    continue
                if line is None:
                    reader_done = True
                    break
                output.append(line.rstrip())
                _support_job_log(line)
            return {
                "command": " ".join(args),
                "returncode": code,
                "stdout": "\n".join(output).strip(),
                "stderr": "",
            }
        if elapsed > timeout:
            proc.kill()
            raise TimeoutError("Command timed out: " + " ".join(args))
        time.sleep(0.08)


def _controller_support_worker(kind):
    results = []
    try:
        if kind in ("install", "reinstall"):
            reinstall = kind == "reinstall"
            _support_job_update(message="Preparing installer...", phase="Preparing", progress=4)
            _reset_gamepad_cache()
            if _vgamepad_package_available() and not reinstall:
                _support_job_update(message="vgamepad is already installed.", phase="Checking vgamepad", progress=38)
                _support_job_log("vgamepad Python package is already installed.")
            else:
                py = _computer_python()
                _support_job_log("Using Python " + (py.get("version") or "") + ": " + py.get("executable", " ".join(py["cmd"])))
                pip_args = ["-m", "pip", "--disable-pip-version-check", "install", "--user", "--no-input"]
                if reinstall:
                    pip_args.extend(["--upgrade", "--force-reinstall"])
                results.append(_run_dependency_command_stream(
                    py["cmd"] + pip_args + ["vgamepad"],
                    "Reinstalling vgamepad" if reinstall else "Installing vgamepad",
                    8,
                    45,
                    timeout=420,
                ))

            _reset_gamepad_cache()
            _support_job_update(message="Checking virtual controller driver...", phase="Checking", progress=50)
            if not controller_available() and os.name == "nt":
                _support_job_update(
                    message="Requesting administrator privilege...",
                    detail="Windows may ask permission to install the ViGEmBus driver.",
                    phase="Requesting admin",
                    progress=58,
                )
                try:
                    results.append(_run_dependency_command_stream(
                        [
                            "winget", "install", "-e", "--id", "ViGEm.ViGEmBus",
                            "--silent",
                            "--accept-source-agreements", "--accept-package-agreements",
                        ],
                        "Downloading driver",
                        60,
                        88,
                        timeout=900,
                    ))
                except FileNotFoundError as e:
                    results.append({
                        "command": "winget install -e --id ViGEm.ViGEmBus",
                        "returncode": 127,
                        "stdout": "",
                        "stderr": str(e),
                    })
                    _support_job_log("winget was not found: " + str(e))

            _support_job_update(message="Verifying controller support...", phase="Verifying", progress=94)
            _reset_gamepad_cache()
            available = controller_available()
            err = controller_availability_error()
            _support_job_update(
                running=False,
                done=True,
                ok=available,
                progress=100,
                phase="Complete" if available else "Needs attention",
                message="Controller Axis support is ready." if available else "Controller support could not be verified.",
                controllerAvailable=available,
                controllerError=err,
                error=None if available else err,
                result={"steps": results},
            )
            return

        if kind == "uninstall":
            _support_job_update(message="Preparing uninstall...", phase="Preparing", progress=6)
            try:
                controller_axis_reset()
            except Exception:
                pass
            _reset_gamepad_cache()
            py = _computer_python()
            _support_job_log("Using Python " + (py.get("version") or "") + ": " + py.get("executable", " ".join(py["cmd"])))
            results.append(_run_dependency_command_stream(
                py["cmd"] + ["-m", "pip", "uninstall", "-y", "vgamepad"],
                "Removing vgamepad",
                12,
                46,
                timeout=300,
            ))
            if os.name == "nt":
                _support_job_update(
                    message="Requesting administrator privilege...",
                    detail="Windows may ask permission to remove the ViGEmBus driver.",
                    phase="Requesting admin",
                    progress=55,
                )
                try:
                    results.append(_run_dependency_command_stream(
                        ["winget", "uninstall", "-e", "--id", "ViGEm.ViGEmBus", "--silent"],
                        "Removing driver",
                        58,
                        90,
                        timeout=900,
                    ))
                except FileNotFoundError as e:
                    results.append({
                        "command": "winget uninstall -e --id ViGEm.ViGEmBus",
                        "returncode": 127,
                        "stdout": "",
                        "stderr": str(e),
                    })
                    _support_job_log("winget was not found: " + str(e))
            _reset_gamepad_cache()
            available = controller_available()
            _support_job_update(
                running=False,
                done=True,
                ok=True,
                progress=100,
                phase="Complete",
                message="Controller support uninstall finished.",
                controllerAvailable=available,
                controllerError=controller_availability_error(),
                result={"steps": results},
            )
            return
    except Exception as e:
        _reset_gamepad_cache()
        _support_job_log(str(e))
        _support_job_update(
            running=False,
            done=True,
            ok=False,
            phase="Failed",
            progress=100,
            message="Controller support setup failed.",
            error=str(e),
            controllerAvailable=controller_available(),
            controllerError=controller_availability_error(),
            result={"steps": results},
        )


def start_controller_support_job(kind="install"):
    kind = kind if kind in ("install", "reinstall", "uninstall") else "install"
    with _support_job_lock:
        if _support_job.get("running"):
            return dict(_support_job)
        _support_job.clear()
        _support_job.update({
            "running": True,
            "kind": kind,
            "phase": "Starting",
            "progress": 2,
            "message": "Starting controller support uninstall..." if kind == "uninstall" else "Starting controller support setup...",
            "detail": "",
            "done": False,
            "ok": False,
            "error": None,
            "controllerAvailable": False,
            "controllerError": None,
            "log": [],
            "result": None,
        })
    threading.Thread(target=_controller_support_worker, args=(kind,), daemon=True).start()
    return _support_job_snapshot()


def controller_support_job_status():
    return _support_job_snapshot()


def install_controller_support():
    """
    Install/repair the optional virtual-controller stack.

    vgamepad is the Python package. On Windows it uses ViGEmBus, a Nefarius
    kernel-mode driver that exposes virtual Xbox/PlayStation controllers.
    """
    start_controller_support_job("install")
    while True:
        st = controller_support_job_status()
        if st.get("done") or not st.get("running"):
            return st
        time.sleep(0.2)


def uninstall_controller_support():
    """Best-effort uninstall for the optional virtual-controller stack."""
    start_controller_support_job("uninstall")
    while True:
        st = controller_support_job_status()
        if st.get("done") or not st.get("running"):
            return st
        time.sleep(0.2)


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


# ── Virtual Xbox controller output ───────────────────────────────────
def controller_axis(part, x=0.0, y=0.0, value=0.0):
    """Set one Xbox-compatible analog axis. Sticks use -1..1, triggers use 0..1."""
    _ensure_gamepad()
    part = str(part or "left_stick")
    x = max(-1.0, min(1.0, float(x or 0.0)))
    y = max(-1.0, min(1.0, float(y or 0.0)))
    value = max(0.0, min(1.0, float(value or 0.0)))
    if part == "left_stick":
        _Controller_gamepad.left_joystick_float(x_value_float=x, y_value_float=-y)
    elif part == "right_stick":
        _Controller_gamepad.right_joystick_float(x_value_float=x, y_value_float=-y)
    elif part == "left_trigger":
        _Controller_gamepad.left_trigger_float(value_float=value)
    elif part == "right_trigger":
        _Controller_gamepad.right_trigger_float(value_float=value)
    _Controller_gamepad.update()


def controller_axis_reset(part=None):
    """Return one axis, or all known axes, to neutral."""
    if part is None and _Controller_gamepad is None:
        return
    _ensure_gamepad()
    parts = [part] if part else ["left_stick", "right_stick", "left_trigger", "right_trigger"]
    for p in parts:
        controller_axis(p, 0.0, 0.0, 0.0)
