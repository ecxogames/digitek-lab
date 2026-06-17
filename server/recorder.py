# Slice AMAS — Macro Recorder
#
# Captures real keyboard + mouse input via pynput listeners and turns it into a
# timestamped, screen-normalized event stream that can be saved as a .slicemcr.
#
# Event schema (relative time `t` in seconds from record start):
#   {"t":.., "type":"key",    "action":"down|up", "key":"w"}
#   {"t":.., "type":"move",   "x":0..1, "y":0..1}
#   {"t":.., "type":"button", "action":"down|up", "button":"left", "x":.., "y":..}
#   {"t":.., "type":"scroll", "dx":int, "dy":int, "x":.., "y":..}
#
# A single global recording session is supported (the app records one macro at a
# time). All shared state is guarded by a lock.

import time
import threading

from . import input_driver

# Mouse moves fire extremely fast; throttle to keep files sane (~120 Hz max).
_MOVE_MIN_INTERVAL = 0.008

_lock = threading.Lock()
_state = {
    "recording": False,
    "events": [],
    "start": 0.0,
    "last_move": 0.0,
    "motionControlled": False,
    "km_listener": None,
    "ms_listener": None,
    # Keys that should stop the recording rather than be captured (set by caller).
    "stop_keys": set(),
    "stopped_by_hotkey": False,
}


def _elapsed():
    return time.perf_counter() - _state["start"]


def _append(ev):
    ev["t"] = round(_elapsed(), 4)
    _state["events"].append(ev)


# ── pynput callbacks ──────────────────────────────────────────────────
def _on_key_press(key):
    try:
        name = input_driver.key_to_name(key)
    except Exception:
        return
    with _lock:
        if not _state["recording"]:
            return
        if name in _state["stop_keys"]:
            _state["stopped_by_hotkey"] = True
            return  # do not record the stop key; stop() is triggered elsewhere
        _append({"type": "key", "action": "down", "key": name})


def _on_key_release(key):
    try:
        name = input_driver.key_to_name(key)
    except Exception:
        return
    with _lock:
        if not _state["recording"] or name in _state["stop_keys"]:
            return
        _append({"type": "key", "action": "up", "key": name})


def _on_move(x, y):
    now = time.perf_counter()
    with _lock:
        if not _state["recording"]:
            return
        if now - _state["last_move"] < _MOVE_MIN_INTERVAL:
            return
        _state["last_move"] = now
        nx, ny = input_driver.to_normalized(x, y)
        _append({"type": "move", "x": round(nx, 5), "y": round(ny, 5)})


def _on_click(x, y, button, pressed):
    with _lock:
        if not _state["recording"]:
            return
        nx, ny = input_driver.to_normalized(x, y)
        _append({
            "type": "button",
            "action": "down" if pressed else "up",
            "button": input_driver.button_to_name(button),
            "x": round(nx, 5), "y": round(ny, 5),
        })


def _on_scroll(x, y, dx, dy):
    with _lock:
        if not _state["recording"]:
            return
        nx, ny = input_driver.to_normalized(x, y)
        _append({
            "type": "scroll", "dx": int(dx), "dy": int(dy),
            "x": round(nx, 5), "y": round(ny, 5),
        })


# ── Public API ────────────────────────────────────────────────────────
def is_recording():
    with _lock:
        return _state["recording"]


def status():
    with _lock:
        return {
            "recording": _state["recording"],
            "elapsed": round(_elapsed(), 2) if _state["recording"] else 0.0,
            "events": len(_state["events"]),
            "stoppedByHotkey": _state["stopped_by_hotkey"],
        }


def start(motion_controlled=False, stop_keys=None):
    """
    Begin capturing input. Returns a status dict.
    `stop_keys` is an iterable of key names that must be ignored during capture
    (typically the global stop-record hotkey) so it never lands in the macro.
    """
    # pynput must be importable to attach listeners.
    input_driver._ensure_imported()

    with _lock:
        if _state["recording"]:
            return {"ok": False, "reason": "Already recording."}
        _state["events"] = []
        _state["start"] = time.perf_counter()
        _state["last_move"] = 0.0
        _state["motionControlled"] = bool(motion_controlled)
        _state["stop_keys"] = set(stop_keys or [])
        _state["stopped_by_hotkey"] = False
        _state["recording"] = True

    kb = input_driver._keyboard.Listener(
        on_press=_on_key_press, on_release=_on_key_release)
    ms = input_driver._mouse.Listener(
        on_move=_on_move, on_click=_on_click, on_scroll=_on_scroll)
    kb.start()
    ms.start()

    with _lock:
        _state["km_listener"] = kb
        _state["ms_listener"] = ms

    return {"ok": True, "motionControlled": bool(motion_controlled)}


def stop():
    """Stop capturing and return the recorded macro body (events + metadata)."""
    with _lock:
        if not _state["recording"]:
            return {"ok": False, "reason": "Not recording."}
        _state["recording"] = False
        events = list(_state["events"])
        duration = round(_elapsed(), 4)
        motion = _state["motionControlled"]
        kb = _state["km_listener"]
        ms = _state["ms_listener"]
        _state["km_listener"] = None
        _state["ms_listener"] = None

    # Stop listeners outside the lock (their threads may call back in).
    for lst in (kb, ms):
        try:
            if lst:
                lst.stop()
        except Exception:
            pass

    # A motion-controlled macro is, by default, tagged so the player knows to
    # prepend reset + first-person when the execution requests it.
    kind = "motion_control" if motion else "freeform"
    return {
        "ok": True,
        "events": events,
        "duration": duration,
        "motionControlled": motion,
        "kind": kind,
    }
