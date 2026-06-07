# DigiTek Lab — Global Hotkeys
#
# While recording or playing back, keyboard focus is on Roblox, not the app
# window. A global hotkey listener lets the user stop a recording (F8) or abort
# playback (F9) without alt-tabbing back. The listener is started lazily the
# first time recording/playback begins and runs for the app's lifetime.
#
# These names double as the recorder's `stop_keys` so the stop key never gets
# captured into the macro being recorded.

import threading

from . import input_driver
from . import recorder
from . import player

STOP_RECORD_KEY = "f8"
STOP_PLAYBACK_KEY = "f9"

_lock = threading.Lock()
_listener = None
_started = False


def stop_record_key():
    return STOP_RECORD_KEY


def stop_keys_for_recording():
    """Key names the recorder must ignore (so the stop hotkey isn't captured)."""
    return {STOP_RECORD_KEY}


def _on_press(key):
    try:
        name = input_driver.key_to_name(key)
    except Exception:
        return
    if name == STOP_RECORD_KEY and recorder.is_recording():
        try:
            # The api layer owns saving; here we just halt capture. The UI polls
            # record status, sees stoppedByHotkey, and finalizes via dgt_record_stop.
            recorder._state["stopped_by_hotkey"] = True
        except Exception:
            pass
    elif name == STOP_PLAYBACK_KEY and player.is_playing():
        try:
            player.stop()
        except Exception:
            pass


def ensure_started():
    """Start the global hotkey listener once. Safe to call repeatedly."""
    global _listener, _started
    with _lock:
        if _started:
            return
        try:
            input_driver._ensure_imported()
            _listener = input_driver._keyboard.Listener(on_press=_on_press)
            _listener.start()
            _started = True
        except Exception:
            # No pynput / no display — hotkeys simply unavailable; the in-app
            # Stop buttons still work.
            _started = False


def info():
    return {"stopRecord": STOP_RECORD_KEY, "stopPlayback": STOP_PLAYBACK_KEY}
