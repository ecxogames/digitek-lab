# DigiTek Lab — Macro & Execution storage
#
# Owns the on-disk formats and the data directory. Two file types, both plain
# JSON under custom extensions:
#   .dgtmcr  — a recorded, reusable macro
#   .dgtexec — an execution (a timeline of items)
#
# Saved data lives in the per-user OS app-data directory (e.g.
# %LOCALAPPDATA%\DigiTek Lab on Windows) — NEVER the install/app folder, so a
# built app installed in Program Files or run from D:\ still saves to a writable,
# user-local location. Exporting a macro/execution uses a native Save dialog
# (see dialogs.py) so the user chooses where the exported file goes.
#
# Bundled engine assets ship read-only with the app under server/core/
# (core/macros/*.dgtmcr and core/actions/*.dgtact).

import os
import sys
import re
import json
import uuid
import time

SCHEMA = 1
MACRO_EXT = ".dgtmcr"   # a recorded/reusable macro
EXEC_EXT = ".dgtexec"   # an execution (timeline)
ACTION_EXT = ".dgtact"  # a parameterized action template

# ── Paths ─────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
APP_NAME = "DigiTek Lab"


def _user_data_dir(app=APP_NAME):
    """Per-user, writable data directory for the current OS — not the install dir."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, app)


# Saved macros/executions persist here (per-user, survives app updates/reinstalls).
DATA_DIR = _user_data_dir()
MACROS_DIR = os.path.join(DATA_DIR, "macros")
EXECS_DIR = os.path.join(DATA_DIR, "executions")
# Bundled, read-only engine assets live under server/core/:
#   core/macros/*.dgtmcr   — core engine macros
#   core/actions/*.dgtact  — parameterized action templates
CORE_DIR = os.path.join(_THIS_DIR, "core")
CORE_MACROS_DIR = os.path.join(CORE_DIR, "macros")
CORE_ACTIONS_DIR = os.path.join(CORE_DIR, "actions")


# Older builds saved into <app>/data — migrate those into the per-user dir once.
_LEGACY_DATA_DIR = os.path.join(APP_ROOT, "data")


def _migrate_legacy_data():
    if not os.path.isdir(_LEGACY_DATA_DIR):
        return
    if os.path.abspath(_LEGACY_DATA_DIR) == os.path.abspath(DATA_DIR):
        return
    import shutil
    for sub, dest in (("macros", MACROS_DIR), ("executions", EXECS_DIR)):
        src = os.path.join(_LEGACY_DATA_DIR, sub)
        if not os.path.isdir(src):
            continue
        os.makedirs(dest, exist_ok=True)
        for fname in os.listdir(src):
            s = os.path.join(src, fname)
            d = os.path.join(dest, fname)
            if os.path.isfile(s) and not os.path.exists(d):  # never clobber newer data
                try:
                    shutil.copy2(s, d)
                except Exception:
                    pass


def ensure_dirs():
    for d in (DATA_DIR, MACROS_DIR, EXECS_DIR):
        os.makedirs(d, exist_ok=True)
    _migrate_legacy_data()


# ── Helpers ───────────────────────────────────────────────────────────
def slugify(name, fallback="untitled"):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or fallback


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _unique_path(directory, slug, ext):
    """Return a non-clashing '<slug><ext>' path inside directory."""
    candidate = os.path.join(directory, slug + ext)
    if not os.path.exists(candidate):
        return candidate
    i = 2
    while True:
        candidate = os.path.join(directory, f"{slug}-{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _macro_summary(data, ref):
    return {
        "ref": ref,
        "name": data.get("name", os.path.splitext(ref)[0]),
        "kind": data.get("kind", "freeform"),
        "motionControlled": bool(data.get("motionControlled", False)),
        "duration": float(data.get("duration", 0.0) or 0.0),
        "events": len(data.get("events", []) or []),
    }


# ── Macros (.dgtmcr) ──────────────────────────────────────────────────
def save_macro(data):
    """
    Persist a macro dict. Fills in id/schema/timestamps and returns its summary.
    If data carries an existing 'ref' that lives in MACROS_DIR, it is overwritten.
    """
    ensure_dirs()
    data = dict(data or {})
    data["format"] = "dgtmcr"
    data["schema"] = SCHEMA
    data["type"] = "macro"
    data.setdefault("id", str(uuid.uuid4()))
    data.setdefault("kind", "freeform")
    data.setdefault("motionControlled", False)
    data.setdefault("events", [])
    data.setdefault("params", {})
    data.setdefault("createdAt", _now_iso())
    data["updatedAt"] = _now_iso()

    # Derive a duration from the events if missing.
    if not data.get("duration"):
        evs = data.get("events") or []
        data["duration"] = float(evs[-1].get("t", 0.0)) if evs else 0.0

    ref = data.get("ref")
    if ref and os.path.basename(ref) == ref and os.path.exists(os.path.join(MACROS_DIR, ref)):
        path = os.path.join(MACROS_DIR, ref)
    else:
        path = _unique_path(MACROS_DIR, slugify(data.get("name"), "macro"), MACRO_EXT)
        ref = os.path.basename(path)

    data.pop("ref", None)  # ref is derived from the filename, not stored inside
    _write_json(path, data)
    return _macro_summary(data, ref)


def load_macro(ref):
    """Load a user macro by filename ref (basename only)."""
    path = os.path.join(MACROS_DIR, os.path.basename(ref))
    data = _read_json(path)
    data["ref"] = os.path.basename(path)
    return data


def delete_macro(ref):
    path = os.path.join(MACROS_DIR, os.path.basename(ref))
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def list_macros():
    ensure_dirs()
    out = []
    for fname in sorted(os.listdir(MACROS_DIR)):
        if not fname.endswith(MACRO_EXT):
            continue
        try:
            out.append(_macro_summary(_read_json(os.path.join(MACROS_DIR, fname)), fname))
        except Exception:
            continue
    return out


# ── Core engine macros (read-only, bundled) ───────────────────────────
def list_core_macros():
    out = []
    if not os.path.isdir(CORE_MACROS_DIR):
        return out
    for fname in sorted(os.listdir(CORE_MACROS_DIR)):
        if not fname.endswith(MACRO_EXT):
            continue
        try:
            data = _read_json(os.path.join(CORE_MACROS_DIR, fname))
            key = os.path.splitext(fname)[0]  # stable id, e.g. "zoom_out_max"
            s = _macro_summary(data, key)
            s["core"] = True
            s["description"] = data.get("description", "")
            out.append(s)
        except Exception:
            continue
    return out


def load_core_macro(key):
    """Load a core macro by its key (filename without extension)."""
    path = os.path.join(CORE_MACROS_DIR, os.path.basename(key) + MACRO_EXT)
    data = _read_json(path)
    data["ref"] = key
    data["kind"] = "core"
    return data


def resolve_macro(kind, ref):
    """Load either a user macro ('macro') or a core macro ('core')."""
    if kind == "core":
        return load_core_macro(ref)
    return load_macro(ref)


# ── Core action templates (read-only, bundled, .dgtact) ───────────────
def list_core_actions():
    """
    Return the bundled, parameterized action templates the UI palette is built
    from. Each is a parsed .dgtact dict (actionType, name, icon, fields, defaults,
    optional `pick` descriptor for the coordinate-picker overlay).
    """
    out = []
    if not os.path.isdir(CORE_ACTIONS_DIR):
        return out
    for fname in sorted(os.listdir(CORE_ACTIONS_DIR)):
        if not fname.endswith(ACTION_EXT):
            continue
        try:
            data = _read_json(os.path.join(CORE_ACTIONS_DIR, fname))
            data.setdefault("actionType", os.path.splitext(fname)[0])
            out.append(data)
        except Exception:
            continue
    # Stable, author-defined ordering for the palette.
    out.sort(key=lambda a: (a.get("order", 999), a.get("name", "")))
    return out


# ── Executions (.dgtexec) ─────────────────────────────────────────────
def new_execution(name="Untitled Execution"):
    return {
        "format": "dgtexec",
        "schema": SCHEMA,
        "name": name,
        "motionControlled": False,
        "motionKeyMap": {},
        "timeline": [],
        "createdAt": _now_iso(),
    }


def save_execution(name, data):
    ensure_dirs()
    data = dict(data or {})
    data["format"] = "dgtexec"
    data["schema"] = SCHEMA
    data["name"] = name or data.get("name") or "Untitled Execution"
    data.setdefault("motionControlled", False)
    data.setdefault("motionKeyMap", {})
    data.setdefault("timeline", [])
    data.setdefault("createdAt", _now_iso())
    data["updatedAt"] = _now_iso()

    path = os.path.join(EXECS_DIR, slugify(data["name"], "execution") + EXEC_EXT)
    _write_json(path, data)
    return {"name": data["name"], "ref": os.path.basename(path)}


def load_execution(ref):
    path = os.path.join(EXECS_DIR, os.path.basename(ref))
    return _read_json(path)


def delete_execution(ref):
    path = os.path.join(EXECS_DIR, os.path.basename(ref))
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def list_executions():
    ensure_dirs()
    out = []
    for fname in sorted(os.listdir(EXECS_DIR)):
        if not fname.endswith(EXEC_EXT):
            continue
        try:
            data = _read_json(os.path.join(EXECS_DIR, fname))
            out.append({
                "ref": fname,
                "name": data.get("name", os.path.splitext(fname)[0]),
                "items": len(data.get("timeline", []) or []),
                "motionControlled": bool(data.get("motionControlled", False)),
            })
        except Exception:
            continue
    return out


# ── Import / export (raw file copy with a JSON validity check) ─────────
def read_raw_file(path):
    """Read & validate an external .dgtmcr/.dgtexec file. Returns the parsed dict."""
    data = _read_json(path)
    fmt = data.get("format")
    if fmt not in ("dgtmcr", "dgtexec"):
        raise ValueError("Not a DigiTek file (missing format marker).")
    return data


def write_raw_file(path, data):
    _write_json(path, data)
    return path
