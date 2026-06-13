import json
import os
import re
import shutil
import time

from . import macros

THEME_EXT = ".theme"
THEMES_DIR = os.path.join(macros.DATA_DIR, "themes")
SETTINGS_PATH = os.path.join(THEMES_DIR, "settings.json")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slugify(value, fallback="theme"):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def ensure_dirs():
    os.makedirs(THEMES_DIR, exist_ok=True)


def _safe_join(base, *parts):
    base_abs = os.path.abspath(base)
    path = os.path.abspath(os.path.join(base_abs, *parts))
    if path != base_abs and not path.startswith(base_abs + os.sep):
        raise ValueError("Theme path is unsafe.")
    return path


def _read_settings():
    ensure_dirs()
    if not os.path.exists(SETTINGS_PATH):
        return {"active": ""}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"active": str((data or {}).get("active") or "")}
    except Exception:
        return {"active": ""}


def _write_settings(data):
    ensure_dirs()
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"active": str((data or {}).get("active") or "")}, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def _read_css(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _metadata(path):
    css = _read_css(path)
    head = css[:1200]
    name_match = re.search(r"@theme-name\s+([^\n\r*]+)", head, re.I)
    desc_match = re.search(r"@theme-description\s+([^\n\r*]+)", head, re.I)
    ident = os.path.splitext(os.path.basename(path))[0]
    return {
        "id": ident,
        "name": name_match.group(1).strip() if name_match else ident.replace("-", " ").title(),
        "description": desc_match.group(1).strip() if desc_match else "",
        "path": path,
        "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(path))),
    }


def list_themes():
    ensure_dirs()
    active = _read_settings().get("active", "")
    out = []
    for name in sorted(os.listdir(THEMES_DIR)):
        if not name.lower().endswith(THEME_EXT):
            continue
        path = os.path.join(THEMES_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            item = _metadata(path)
            item["active"] = item["id"] == active
            out.append(item)
        except Exception:
            continue
    return out


def import_theme(path):
    ensure_dirs()
    if not path:
        return {"cancelled": True}
    if not os.path.isfile(path):
        raise ValueError("Theme file not found.")
    if not path.lower().endswith((".theme", ".css")):
        raise ValueError("Expected a .theme or .css file.")
    css = _read_css(path)
    source_name = os.path.splitext(os.path.basename(path))[0]
    name_match = re.search(r"@theme-name\s+([^\n\r*]+)", css[:1200], re.I)
    ident = _slugify(name_match.group(1) if name_match else source_name)
    dest = _safe_join(THEMES_DIR, ident + THEME_EXT)
    shutil.copyfile(path, dest)
    os.utime(dest, None)
    data = _metadata(dest)
    data["installedAt"] = _now_iso()
    set_active(data["id"])
    data["active"] = True
    return data


def set_active(theme_id):
    theme_id = _slugify(theme_id, "")
    if theme_id:
        path = _safe_join(THEMES_DIR, theme_id + THEME_EXT)
        if not os.path.isfile(path):
            raise ValueError("Theme is not installed: " + str(theme_id))
    _write_settings({"active": theme_id})
    return active_theme()


def remove_theme(theme_id):
    theme_id = _slugify(theme_id, "")
    if not theme_id:
        raise ValueError("Theme id is required.")
    path = _safe_join(THEMES_DIR, theme_id + THEME_EXT)
    if os.path.isfile(path):
        os.remove(path)
    if _read_settings().get("active") == theme_id:
        _write_settings({"active": ""})
    return True


def active_theme():
    ensure_dirs()
    active = _read_settings().get("active", "")
    if not active:
        return {"id": "", "name": "Default", "css": "", "active": True}
    path = _safe_join(THEMES_DIR, active + THEME_EXT)
    if not os.path.isfile(path):
        _write_settings({"active": ""})
        return {"id": "", "name": "Default", "css": "", "active": True}
    data = _metadata(path)
    data["css"] = _read_css(path)
    data["active"] = True
    return data
