import importlib
import importlib.util
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.request
import zipfile

from . import macros

PLUGIN_EXT = ".dgtkplgn"
PLUGIN_MANIFEST = "properties.config"
PLUGIN_INSTALL_META = os.path.join(".digitek", "install.json")
PLUGIN_REQUIREMENTS = "requirements.txt"
PLUGIN_PERMISSIONS = "permissions.txt"
PLUGINS_DIR = os.path.join(macros.DATA_DIR, "plugins")
PLUGIN_PACKAGES_DIR = os.path.join(macros.DATA_DIR, "plugin-packages")
PLUGIN_DATA_DIR = os.path.join(macros.DATA_DIR, "plugin-data")
PINNED_PLUGINS_FILE = os.path.join(macros.DATA_DIR, "pinned_plugins.json")
MARKETPLACE_MANIFEST_URL = "https://raw.githubusercontent.com/dummtoby/digitek-lab/plugins/manifest.json"
MARKETPLACE_RAW_BASE_URL = "https://raw.githubusercontent.com/dummtoby/digitek-lab/plugins"
MARKETPLACE_CONTENTS_API_BASE = "https://api.github.com/repos/dummtoby/digitek-lab/contents"
MARKETPLACE_BRANCH = "plugins"
MARKETPLACE_BLOB_BASE_URL = "https://github.com/dummtoby/digitek-lab/blob/plugins"

_MODULE_CACHE = {}


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slugify(value, fallback="plugin"):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def ensure_dirs():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    os.makedirs(PLUGIN_PACKAGES_DIR, exist_ok=True)
    os.makedirs(PLUGIN_DATA_DIR, exist_ok=True)
    _add_plugin_packages_path()


def plugins_dir():
    ensure_dirs()
    return PLUGINS_DIR


def get_pinned_plugins():
    try:
        data = _read_json(PINNED_PLUGINS_FILE)
        if isinstance(data, list):
            return _normalize_plugin_id_list(data)
    except Exception:
        pass
    return []


def set_pinned_plugins(plugin_ids):
    ensure_dirs()
    ids = _normalize_plugin_id_list(plugin_ids if isinstance(plugin_ids, list) else [])
    _write_json(PINNED_PLUGINS_FILE, ids)
    return ids


def _normalize_plugin_id_list(plugin_ids):
    seen = set()
    out = []
    for plugin_id in plugin_ids or []:
        pid = _slugify(plugin_id, "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _add_plugin_packages_path():
    if PLUGIN_PACKAGES_DIR not in sys.path:
        sys.path.insert(0, PLUGIN_PACKAGES_DIR)


def _safe_join(base, *parts):
    base_abs = os.path.abspath(base)
    path = os.path.abspath(os.path.join(base_abs, *parts))
    if path != base_abs and not path.startswith(base_abs + os.sep):
        raise ValueError("Plugin archive contains an unsafe path.")
    return path


def _path_within(path, root):
    try:
        path_abs = os.path.abspath(path or "")
        root_abs = os.path.abspath(root or "")
        return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)
    except Exception:
        return False


def _plugin_module_name(plugin_id):
    return "dgt_plugin_" + re.sub(r"[^a-zA-Z0-9_]", "_", _slugify(plugin_id))


def _remove_pycache(root):
    if not root or not os.path.isdir(root):
        return
    for dirpath, dirnames, _files in os.walk(root):
        for dirname in list(dirnames):
            if dirname == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, dirname), ignore_errors=True)


def _clear_plugin_runtime(plugin):
    plugin_id = plugin.get("id") if isinstance(plugin, dict) else _slugify(plugin)
    root = plugin.get("path", "") if isinstance(plugin, dict) else ""
    if plugin_id:
        cached = _MODULE_CACHE.pop(plugin_id, None)
        module = cached.get("module") if isinstance(cached, dict) else cached
        shutdown = getattr(module, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass
    prefix = _plugin_module_name(plugin_id) if plugin_id else ""
    root_abs = os.path.abspath(root) if root else ""
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", "") or ""
        if (prefix and name == prefix) or (root_abs and module_file and _path_within(module_file, root_abs)):
            sys.modules.pop(name, None)
    _remove_pycache(root_abs)
    _remove_plugin_temp_dirs(plugin_id)
    importlib.invalidate_caches()


def _remove_plugin_temp_dirs(plugin_id):
    if not plugin_id:
        return
    temp_root = tempfile.gettempdir()
    prefixes = (
        "fishbot_overlay_" if plugin_id == "fishbot" else plugin_id + "_",
        plugin_id + "_",
    )
    try:
        for name in os.listdir(temp_root):
            if any(name.startswith(prefix) for prefix in prefixes):
                shutil.rmtree(os.path.join(temp_root, name), ignore_errors=True)
    except Exception:
        pass


def _plugin_fingerprint(plugin):
    root = plugin.get("path", "")
    if not root or not os.path.isdir(root):
        return 0.0
    latest = 0.0
    skip_dirs = {"__pycache__", ".git", "release"}
    skip_exts = {".pyc", ".pyo", ".tmp"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in skip_exts:
                continue
            latest = max(latest, os.path.getmtime(os.path.join(dirpath, filename)))
    return latest


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _manifest_path(root):
    return os.path.join(root, PLUGIN_MANIFEST)


def _parse_properties(path):
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def _load_manifest(root):
    path = _manifest_path(root)
    if not os.path.exists(path):
        raise ValueError("Plugin is missing properties.config.")
    props = _parse_properties(path)
    data = {
        "id": props.get("PLUGIN_ID") or props.get("ID"),
        "name": props.get("TITLE") or props.get("NAME"),
        "version": props.get("VERSION", "1.0.0"),
        "author": props.get("AUTHOR", ""),
        "description": props.get("DESCRIPTION", ""),
        "entry": props.get("MAIN_PAGE", "ui/index.html"),
        "icon": props.get("ICON", ""),
        "game": props.get("GAME", ""),
        "category": props.get("CATEGORY", ""),
        "topic": props.get("TOPIC", ""),
        "website": props.get("WEBSITE", ""),
        "github": props.get("GITHUB", ""),
        "pythonMinVersion": props.get("PYTHON_MIN_VERSION") or props.get("MIN_PYTHON_VERSION") or "",
    }
    data = dict(data or {})
    data["id"] = _slugify(data.get("id") or data.get("name"))
    data.setdefault("name", data["id"])
    data.setdefault("version", "1.0.0")
    data.setdefault("author", "")
    data.setdefault("description", "")
    data.setdefault("entry", "ui/index.html")
    data["requirements"] = _plugin_requirement_lines(root)
    data["permissions"] = _plugin_permissions(root)
    install_meta = _plugin_install_meta(root)
    if install_meta:
        data.update({k: v for k, v in install_meta.items() if k in {"installedAt"}})
    return data


def _plugin_install_meta(root):
    path = os.path.join(root, PLUGIN_INSTALL_META)
    if not os.path.exists(path):
        return {}
    try:
        return _read_json(path)
    except Exception:
        return {}


def _write_plugin_install_meta(root, data):
    _write_json(os.path.join(root, PLUGIN_INSTALL_META), data)


def _plugin_requirement_lines(root):
    path = os.path.join(root, PLUGIN_REQUIREMENTS)
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            if line.startswith(("-", "--")):
                continue
            lines.append(line)
    return lines


def _plugin_permissions(root):
    path = os.path.join(root, PLUGIN_PERMISSIONS)
    if not os.path.exists(path):
        return []
    permissions = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            if line:
                permissions.append(line)
    return permissions


def _summary(root):
    data = _load_manifest(root)
    data["path"] = root
    data["installedAt"] = data.get("installedAt", "")
    data["hasUi"] = os.path.exists(os.path.join(root, data.get("entry", "ui/index.html")))
    data["hasServer"] = os.path.exists(os.path.join(root, "server", "api.py"))
    data["iconDataUri"] = _icon_data_uri(root, data)
    data["iconPath"] = _native_icon_path(root, data)
    return data


def _version_key(value):
    parts = []
    for part in re.split(r"[^0-9A-Za-z]+", str(value or "0")):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    while len(parts) > 1 and parts[-1] == (0, 0):
        parts.pop()
    return parts or [(0, 0)]


def _is_newer_version(latest, current):
    return _version_key(latest) > _version_key(current)


def _icon_data_uri(root, manifest):
    icon = str(manifest.get("icon") or "").strip()
    if not icon:
        return ""
    try:
        path = _safe_join(root, *icon.replace("\\", "/").split("/"))
        if not os.path.isfile(path):
            return ""
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return ""


def _native_icon_path(root, manifest):
    icon = str(manifest.get("icon") or "").strip()
    if not icon:
        return ""
    try:
        path = _safe_join(root, *icon.replace("\\", "/").split("/"))
        if not os.path.isfile(path):
            return ""
        if path.lower().endswith(".ico"):
            return path
        cache_dir = os.path.join(root, ".digitek")
        ico_path = os.path.join(cache_dir, "icon.ico")
        if os.path.exists(ico_path) and os.path.getmtime(ico_path) >= os.path.getmtime(path):
            return ico_path
        try:
            from PIL import Image
            os.makedirs(cache_dir, exist_ok=True)
            img = Image.open(path).convert("RGBA")
            img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128)])
            return ico_path
        except Exception:
            return ""
    except Exception:
        return ""


def list_plugins():
    ensure_dirs()
    out = []
    for name in sorted(os.listdir(PLUGINS_DIR)):
        root = os.path.join(PLUGINS_DIR, name)
        if not os.path.isdir(root):
            continue
        try:
            out.append(_summary(root))
        except Exception:
            continue
    return out


def get_plugin(plugin_id):
    ensure_dirs()
    root = _safe_join(PLUGINS_DIR, _slugify(plugin_id))
    if not os.path.isdir(root):
        raise ValueError("Plugin is not installed: " + str(plugin_id))
    return _summary(root)


def import_plugin(path):
    ensure_dirs()
    if not path:
        return {"cancelled": True}
    if not os.path.isfile(path):
        raise ValueError("Plugin file not found.")
    if not path.lower().endswith(PLUGIN_EXT):
        raise ValueError("Expected a .dgtkplgn file.")

    temp = os.path.join(PLUGINS_DIR, "_import_" + str(int(time.time() * 1000)))
    os.makedirs(temp, exist_ok=True)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = _safe_join(temp, info.filename)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        root = _normalize_extracted_root(temp)
        manifest = _load_manifest(root)
        dest = _safe_join(PLUGINS_DIR, manifest["id"])
        if os.path.exists(dest):
            _clear_plugin_runtime({"id": manifest["id"], "path": dest})
            shutil.rmtree(dest)
        if root == temp:
            os.replace(temp, dest)
            temp = None
        else:
            shutil.move(root, dest)
        _write_plugin_install_meta(dest, {"installedAt": _now_iso()})
        _clear_plugin_runtime({"id": manifest["id"], "path": dest})
        installed = _summary(dest)
        ensure_plugin_requirements(installed)
        return _summary(dest)
    finally:
        if temp and os.path.exists(temp):
            shutil.rmtree(temp, ignore_errors=True)


def marketplace_manifest():
    with _urlopen(MARKETPLACE_MANIFEST_URL, timeout=12) as res:
        data = json.loads(res.read().decode("utf-8"))
    installed = {p["id"]: p for p in list_plugins()}
    out = []
    for plugin_id, item in sorted((data or {}).items()):
        meta = _marketplace_plugin_meta(plugin_id, item)
        meta["id"] = _slugify(plugin_id)
        meta.setdefault("name", plugin_id)
        meta.setdefault("version", "1.0.0")
        package = meta.get("package") or _infer_package_path(meta["id"], meta.get("version"), meta.get("path", ""))
        package = _resolve_existing_marketplace_package(meta, package)
        meta["package"] = package
        local = installed.get(meta["id"])
        meta["installed"] = bool(local)
        meta["installedVersion"] = local.get("version", "") if local else ""
        meta["latestVersion"] = meta.get("version", "1.0.0")
        meta["updateAvailable"] = bool(local and str(local.get("version", "")) != str(meta["latestVersion"]))
        out.append(meta)
    return out


def _marketplace_plugin_meta(plugin_id, item):
    if isinstance(item, str):
        path = item
        props = _read_remote_plugin_properties(path)
        return _properties_to_manifest(props, plugin_id, path)
    meta = dict(item or {})
    path = meta.get("path") or ("/" + _slugify(plugin_id) + "/")
    props = _read_remote_plugin_properties(path)
    resolved = _properties_to_manifest(props, plugin_id, path)
    resolved.update({k: v for k, v in meta.items() if v not in (None, "")})
    return resolved


def _read_remote_plugin_properties(plugin_path):
    url = MARKETPLACE_RAW_BASE_URL + "/" + plugin_path.strip("/").replace("\\", "/") + "/" + PLUGIN_MANIFEST
    try:
        with _urlopen(url, timeout=12) as res:
            text = res.read().decode("utf-8")
    except Exception:
        return {}
    props = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key.strip()] = value.strip()
    return props


def _properties_to_manifest(props, plugin_id, plugin_path):
    plugin_id = _slugify(props.get("PLUGIN_ID") or props.get("ID") or plugin_id)
    version = props.get("VERSION", "1.0.0")
    return {
        "id": plugin_id,
        "path": "/" + plugin_path.strip("/").replace("\\", "/") + "/",
        "name": props.get("TITLE") or props.get("NAME") or plugin_id,
        "version": version,
        "author": props.get("AUTHOR", ""),
        "description": props.get("DESCRIPTION", ""),
        "entry": props.get("MAIN_PAGE", "ui/index.html"),
        "icon": props.get("ICON", ""),
        "game": props.get("GAME", ""),
        "category": props.get("CATEGORY", ""),
        "topic": props.get("TOPIC", ""),
        "website": props.get("WEBSITE", ""),
        "github": props.get("GITHUB", ""),
        "pythonMinVersion": props.get("PYTHON_MIN_VERSION") or props.get("MIN_PYTHON_VERSION") or "",
    }


def plugin_update_status(plugin_id=None):
    installed = {p["id"]: p for p in list_plugins()}
    market = {p["id"]: p for p in marketplace_manifest()}
    ids = [_slugify(plugin_id)] if plugin_id else sorted(installed)
    out = {}
    for pid in ids:
        local = installed.get(pid)
        remote = market.get(pid)
        if not local:
            out[pid] = {"installed": False, "updateAvailable": False}
            continue
        if not remote:
            out[pid] = {
                "installed": True,
                "updateAvailable": False,
                "installedVersion": local.get("version", ""),
                "latestVersion": "",
            }
            continue
        out[pid] = {
            "installed": True,
            "updateAvailable": str(local.get("version", "")) != str(remote.get("latestVersion") or remote.get("version", "")),
            "installedVersion": local.get("version", ""),
            "latestVersion": remote.get("latestVersion") or remote.get("version", ""),
            "name": remote.get("name") or local.get("name") or pid,
            "package": remote.get("package", ""),
        }
    return out.get(_slugify(plugin_id), {}) if plugin_id else out


def _infer_package_path(plugin_id, version, plugin_path=""):
    normalized_version = str(version or "1.0.0")
    base_path = (plugin_path or ("/" + plugin_id + "/")).strip("/")
    return f"/{base_path}/release/{plugin_id}-{normalized_version}.dgtkplgn"


def _resolve_existing_marketplace_package(meta, package):
    if _marketplace_url_exists(_marketplace_package_url(package)):
        return package
    latest = _latest_marketplace_release(meta)
    return latest or package


def _marketplace_package_url(package):
    package = str(package or "")
    if package.startswith("http://") or package.startswith("https://"):
        raw_base = MARKETPLACE_RAW_BASE_URL.rstrip("/") + "/"
        blob_base = MARKETPLACE_BLOB_BASE_URL.rstrip("/") + "/"
        if package.startswith(raw_base):
            return package
        if package.startswith(blob_base):
            return MARKETPLACE_RAW_BASE_URL.rstrip("/") + "/" + package[len(blob_base):].lstrip("/")
        return ""
    return MARKETPLACE_RAW_BASE_URL + "/" + package.lstrip("/")


def _marketplace_url_exists(url):
    if not url:
        return False
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_http_headers())
        with urllib.request.urlopen(req, timeout=10) as res:
            return 200 <= res.status < 400
    except Exception:
        try:
            req = urllib.request.Request(url, headers={**_http_headers(), "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=10) as res:
                return 200 <= res.status < 400
        except Exception:
            return False


def _latest_marketplace_release(meta):
    plugin_id = _slugify(meta.get("id"))
    plugin_path = str(meta.get("path") or ("/" + plugin_id + "/")).strip("/").replace("\\", "/")
    release_path = plugin_path + "/release"
    url = MARKETPLACE_CONTENTS_API_BASE + "/" + release_path + "?ref=" + MARKETPLACE_BRANCH
    try:
        with _urlopen(url, timeout=12) as res:
            items = json.loads(res.read().decode("utf-8"))
    except Exception:
        return ""
    candidates = []
    pattern = re.compile(r"^" + re.escape(plugin_id) + r"-(.+)\.dgtkplgn$", re.IGNORECASE)
    for item in items if isinstance(items, list) else []:
        name = str(item.get("name") or "")
        match = pattern.match(name)
        if not match:
            continue
        package = "/" + release_path.strip("/") + "/" + name
        candidates.append((match.group(1), package))
    if not candidates:
        return ""
    candidates.sort(key=lambda row: _version_key(row[0]))
    return candidates[-1][1]


def _version_from_package(plugin_id, package):
    name = os.path.basename(str(package or ""))
    match = re.match(r"^" + re.escape(_slugify(plugin_id)) + r"-(.+)\.dgtkplgn$", name, re.IGNORECASE)
    return match.group(1) if match else ""


def _http_headers():
    return {
        "User-Agent": "DigiTek-Lab-Plugin-Installer",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _urlopen(url, timeout=12):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_http_headers()), timeout=timeout)


def install_marketplace_plugin(plugin_id):
    plugin_id = _slugify(plugin_id)
    matches = [p for p in marketplace_manifest() if p["id"] == plugin_id]
    if not matches:
        raise ValueError("Marketplace plugin not found: " + plugin_id)
    meta = matches[0]
    package = _resolve_existing_marketplace_package(meta, str(meta.get("package") or ""))
    url = _marketplace_package_url(package)

    fd, path = tempfile.mkstemp(suffix=PLUGIN_EXT)
    os.close(fd)
    try:
        try:
            _download_url(url, path)
        except Exception as first_error:
            latest = _latest_marketplace_release(meta)
            if not latest or latest == package:
                raise first_error
            _download_url(_marketplace_package_url(latest), path)
        return import_plugin(path)
    finally:
        if os.path.exists(path):
            os.remove(path)


def _download_url(url, path):
    with _urlopen(url, timeout=30) as src, open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _normalize_extracted_root(temp):
    entries = [e for e in os.listdir(temp) if not e.startswith("__MACOSX")]
    if len(entries) == 1:
        only = os.path.join(temp, entries[0])
        if os.path.isdir(only) and os.path.exists(os.path.join(only, PLUGIN_MANIFEST)):
            return only
    return temp


def _plugin_requirements(plugin):
    reqs = plugin.get("requirements") or _plugin_requirement_lines(plugin.get("path", ""))
    return [str(req).strip() for req in reqs if str(req).strip()]


def _package_import_name(package):
    name = re.split(r"[<>=!~\[]+", str(package), 1)[0].strip()
    aliases = {
        "Pillow": "PIL",
        "opencv-python": "cv2",
        "pywin32": "win32api",
    }
    return aliases.get(name, name.replace("-", "_"))


def ensure_plugin_requirements(plugin):
    ensure_dirs()
    requirements = _plugin_requirements(plugin)
    py = _ensure_computer_python(plugin.get("pythonMinVersion", ""))
    if not requirements:
        _add_computer_python_paths()
        return {"ok": True, "python": py.get("version", ""), "installed": []}
    if _requirements_available(py, requirements):
        _add_computer_python_paths()
        return {"ok": True, "python": py.get("version", ""), "installed": []}
    req_path = os.path.join(plugin.get("path", ""), PLUGIN_REQUIREMENTS)
    if os.path.exists(req_path):
        _install_python_requirements_file(py, req_path)
    else:
        _install_python_packages(py, requirements)
    _add_computer_python_paths()
    return {"ok": True, "python": py.get("version", ""), "installed": requirements}


def _requirements_available(py, requirements):
    imports = [_package_import_name(req) for req in requirements]
    imports = [name for name in imports if name]
    if not imports:
        return True

    # Packages are installed into PLUGIN_PACKAGES_DIR and plugin child processes
    # bootstrap only that target path. A developer's global/site Python packages
    # must not satisfy this check, or production children can still miss imports.
    if _imports_available_in_plugin_target(imports):
        return True

    script = (
        "import importlib.machinery, json, sys\n"
        "target=sys.argv[1]\n"
        "mods=json.loads(sys.argv[2])\n"
        "missing=[m for m in mods if importlib.machinery.PathFinder.find_spec(m, [target]) is None]\n"
        "print(json.dumps(missing))\n"
        "raise SystemExit(1 if missing else 0)\n"
    )
    try:
        proc = _run_dependency_probe((py.get("cmd") or []) + ["-c", script, PLUGIN_PACKAGES_DIR, json.dumps(imports)])
        remote_missing = json.loads((proc.stdout or "[]").strip().splitlines()[-1])
        return not remote_missing
    except Exception:
        return False


def _imports_available_in_plugin_target(imports):
    try:
        importlib.invalidate_caches()
        return all(importlib.machinery.PathFinder.find_spec(name, [PLUGIN_PACKAGES_DIR]) is not None for name in imports)
    except Exception:
        return False


def _run_dependency_probe(args):
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def _ensure_computer_python(min_version=""):
    try:
        from . import input_driver
        py = input_driver._computer_python()
        _check_python_version(py, min_version)
        return py
    except Exception as first_error:
        if os.name == "nt" and shutil.which("winget"):
            try:
                _run_dependency_command([
                    "winget", "install", "-e", "--id", "Python.Python.3.12",
                    "--silent",
                    "--accept-source-agreements", "--accept-package-agreements",
                ], timeout=1200)
                from . import input_driver
                input_driver._external_python = None
                py = input_driver._computer_python()
                _check_python_version(py, min_version)
                return py
            except Exception as install_error:
                raise RuntimeError(
                    "A real Python interpreter is required for plugins, and automatic Python installation failed. "
                    + str(first_error) + " | " + str(install_error)
                )
        raise RuntimeError("A real Python interpreter is required for plugins. " + str(first_error))


def _check_python_version(py, min_version):
    if not min_version:
        return
    current = _version_tuple(py.get("version", "0"))
    required = _version_tuple(min_version)
    if current < required:
        raise RuntimeError(
            "Plugin requires Python " + str(min_version) + " or newer, but found Python " + str(py.get("version", "unknown")) + "."
        )


def _version_tuple(value):
    parts = []
    for part in re.split(r"[^0-9]+", str(value or "")):
        if part:
            parts.append(int(part))
        if len(parts) == 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _add_computer_python_paths():
    try:
        from . import input_driver
        input_driver._add_computer_python_paths()
    except Exception:
        pass
    _add_plugin_packages_path()
    importlib.invalidate_caches()


def _install_python_requirements_file(py, req_path):
    return _install_python_packages(py, ["-r", req_path])


def _install_python_packages(py, packages):
    errors = []
    for cmd in _python_install_commands(py, packages):
        try:
            _run_dependency_command(cmd, timeout=900)
            return errors
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError(" | ".join(errors))
    raise RuntimeError("No Python executable was available for package installation.")


def _python_install_commands(py, packages):
    base = ["-m", "pip", "--disable-pip-version-check", "install", "--target", PLUGIN_PACKAGES_DIR, "--upgrade", "--no-input"]
    yielded = set()
    candidates = [py.get("cmd") or []]
    if sys.executable and not str(sys.executable).lower().endswith("esdengine.exe"):
        candidates.append([sys.executable])
    for cmd in candidates:
        key = tuple(cmd)
        if not cmd or key in yielded:
            continue
        yielded.add(key)
        yield cmd + base + packages


def _run_dependency_command(args, timeout=600):
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "").strip() or ("Command failed: " + " ".join(args)))


def remove_plugin(plugin_id):
    plugin_id = _slugify(plugin_id)
    try:
        plugin = get_plugin(plugin_id)
    except Exception:
        _clear_plugin_cache({"id": plugin_id})
        return True
    _clear_plugin_runtime(plugin)
    _clear_plugin_cache(plugin)
    shutil.rmtree(plugin["path"])
    return True


def clear_plugin_cache(plugin_id):
    plugin_id = _slugify(plugin_id)
    try:
        plugin = get_plugin(plugin_id)
    except Exception:
        plugin = {"id": plugin_id, "path": _safe_join(PLUGINS_DIR, plugin_id)}
    _clear_plugin_runtime(plugin)
    return {"ok": True, "pluginId": plugin_id, "cacheBust": time.time()}


def _clear_plugin_cache(plugin):
    plugin_id = plugin.get("id") if isinstance(plugin, dict) else _slugify(plugin)
    if not plugin_id:
        return
    data_path = os.path.join(PLUGIN_DATA_DIR, plugin_id)
    shutil.rmtree(data_path, ignore_errors=True)
    _remove_plugin_temp_dirs(plugin_id)


def open_plugins_folder():
    ensure_dirs()
    if os.name == "nt":
        os.startfile(PLUGINS_DIR)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", PLUGINS_DIR])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", PLUGINS_DIR])
    return {"path": PLUGINS_DIR}


def load_ui(plugin_id):
    plugin = get_plugin(plugin_id)
    entry = plugin.get("entry", "ui/index.html")
    path = _safe_join(plugin["path"], *entry.replace("\\", "/").split("/"))
    if not os.path.exists(path):
        raise ValueError("Plugin UI entry not found: " + entry)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return {"plugin": plugin, "html": html, "cacheBust": _plugin_fingerprint(plugin)}


def _load_module(plugin):
    ensure_plugin_requirements(plugin)
    plugin_id = plugin["id"]
    fingerprint = _plugin_fingerprint(plugin)
    cached = _MODULE_CACHE.get(plugin_id)
    if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
        return cached.get("module")
    if cached:
        _clear_plugin_runtime(plugin)
    api_path = os.path.join(plugin["path"], "server", "api.py")
    if not os.path.exists(api_path):
        raise ValueError("Plugin has no server/api.py")
    module_name = _plugin_module_name(plugin_id)
    spec = importlib.util.spec_from_file_location(module_name, api_path)
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    for sub in ("server", "public", "private", ""):
        p = os.path.join(plugin["path"], sub) if sub else plugin["path"]
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    _MODULE_CACHE[plugin_id] = {"module": module, "fingerprint": fingerprint}
    return module


def call_plugin(plugin_id, payload):
    plugin = get_plugin(plugin_id)
    module = _load_module(plugin)
    if not hasattr(module, "handle_message"):
        raise ValueError("Plugin server/api.py does not expose handle_message(payload).")
    payload = dict(payload or {})
    payload.setdefault("pluginId", plugin["id"])
    return module.handle_message(json.dumps(payload))
