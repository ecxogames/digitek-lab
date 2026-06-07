import os
import shutil
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASE = os.path.join(ROOT, "release")
CONFIG = os.path.join(ROOT, "properties.config")


def read_properties():
    props = {}
    with open(CONFIG, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            props[key.strip()] = value.strip()
    return props


def should_include(rel):
    first = rel.split(os.sep, 1)[0]
    if first in {"release", "__pycache__", ".git"}:
        return False
    if rel.endswith((".pyc", ".pyo", ".tmp")):
        return False
    return True


def build():
    props = read_properties()
    plugin_id = props.get("PLUGIN_ID") or props.get("ID") or "plugin"
    version = props.get("VERSION") or "1.0.0"
    os.makedirs(RELEASE, exist_ok=True)
    out = os.path.join(RELEASE, f"{plugin_id}-{version}.dgtkplgn")
    if os.path.exists(out):
        os.remove(out)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if should_include(os.path.relpath(os.path.join(root, d), ROOT))]
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, ROOT)
                if should_include(rel):
                    zf.write(path, rel.replace(os.sep, "/"))

    print("Built", out)
    return out


if __name__ == "__main__":
    build()
