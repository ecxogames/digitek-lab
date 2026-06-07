import json
import os
import sys

APP_NAME = "DigiTek Lab"
PLUGIN_NAME = "fishbot"

DEFAULT_SETTINGS = {
    "bbox": [0, 800, 0, 600],
    "clickLocation": [0, 0],
    "magicValue": 100,
    "objectDetectionOverlay": False,
    "startPaused": False,
    "showOverlay": False,
    "failingMultiplier": 0,
    "failingPattern": "Random",
    "timer": False,
    "timerDuration": 60,
    "timerUnit": "minutes",
    "goHome": False,
    "quitGame": False,
    "notifyOnEnd": False,
}


def _data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME, "plugin-data", PLUGIN_NAME)


def _settings_path():
    return os.path.join(_data_dir(), "settings.json")


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    path = _settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)
        except Exception:
            pass
    return normalize_settings(data)


def save_settings(settings):
    data = normalize_settings(settings)
    os.makedirs(_data_dir(), exist_ok=True)
    tmp = _settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _settings_path())
    return data


def update_settings(patch):
    data = load_settings()
    if isinstance(patch, dict):
        data.update(patch)
    return save_settings(data)


def normalize_settings(settings):
    data = dict(DEFAULT_SETTINGS)
    data.update(settings or {})
    data["bbox"] = _int_list(data.get("bbox"), DEFAULT_SETTINGS["bbox"], 4)
    data["clickLocation"] = _int_list(data.get("clickLocation"), DEFAULT_SETTINGS["clickLocation"], 2)
    data["magicValue"] = _clamp_int(data.get("magicValue"), 0, 255, 100)
    data["failingMultiplier"] = _clamp_int(data.get("failingMultiplier"), 0, 100, 0)
    data["timerDuration"] = _clamp_int(data.get("timerDuration"), 1, 360, 60)
    if data.get("timerUnit") not in ("seconds", "minutes", "hours"):
        data["timerUnit"] = "minutes"
    if data.get("failingPattern") not in ("Random", "Getting tired", "Improve over time"):
        data["failingPattern"] = "Random"
    for key in ("startPaused", "showOverlay", "objectDetectionOverlay", "timer", "goHome", "quitGame", "notifyOnEnd"):
        data[key] = bool(data.get(key))
    return data


def _int_list(value, fallback, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return list(fallback)
    try:
        return [int(float(v)) for v in value]
    except Exception:
        return list(fallback)


def _clamp_int(value, lo, hi, fallback):
    try:
        n = int(float(value))
    except Exception:
        n = fallback
    return max(lo, min(hi, n))
