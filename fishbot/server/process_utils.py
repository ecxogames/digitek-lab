import os
import json
import shutil
import subprocess
import sys


def _looks_like_app_executable(path):
    return os.path.basename(path or "").lower() in {"esdengine.exe", "digitek lab.exe"}


def _candidate_python_commands():
    seen = set()

    def add(exe, *args):
        if not exe:
            return
        key = (os.path.abspath(exe).lower(),) + tuple(args)
        if key in seen:
            return
        seen.add(key)
        if os.path.exists(exe) or shutil.which(exe):
            yield [exe, *args]

    env_python = os.environ.get("DIGITEK_PYTHON_EXECUTABLE")
    if env_python:
        yield from add(env_python)

    # In installed/standalone builds the app runs from DigiTek Lab.exe, while
    # the embeddable Python runtime lives beside it. Prefer that exact runtime
    # so Fishbot sees the packages and Tk files bundled by the installer.
    for base in (
        os.path.dirname(getattr(sys, "executable", "") or ""),
        sys.exec_prefix or "",
        sys.prefix or "",
    ):
        if base:
            yield from add(os.path.join(base, "python.exe" if os.name == "nt" else "python"))

    base_exe = getattr(sys, "_base_executable", "")
    if base_exe and not _looks_like_app_executable(base_exe):
        yield from add(base_exe)

    if os.name == "nt":
        py = shutil.which("py")
        if py:
            yield from add(py, "-3")

    for name in ("python", "python3"):
        exe = shutil.which(name)
        if exe:
            yield from add(exe)


def _probe_python(cmd):
    try:
        startupinfo, creationflags = _window_options(False)
        proc = subprocess.run(
            cmd + ["-c", "import json, sys; print(json.dumps({'executable': sys.executable, 'version': sys.version.split()[0]}))"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        return proc.returncode == 0
    except Exception:
        return False


def python_cmd():
    for cmd in _candidate_python_commands():
        if _probe_python(cmd):
            return cmd
    raise RuntimeError("Fishbot needs a real Python install to open picker and overlay windows.")


def python_env():
    env = dict(os.environ)
    paths = _python_paths(env)
    existing = env.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _python_paths(env=None):
    env = env or os.environ
    paths = []
    plugin_packages = os.path.join(
        env.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local"),
        "DigiTek Lab",
        "plugin-packages",
    )
    for path in (
        plugin_packages,
        os.path.dirname(os.path.abspath(__file__)),
        os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")),
    ):
        if path and os.path.isdir(path):
            paths.append(path)
    return paths


def plugin_packages_dir(env=None):
    env = env or os.environ
    return os.path.join(
        env.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local"),
        "DigiTek Lab",
        "plugin-packages",
    )


def install_requirements(*packages, force=False):
    packages = [str(package).strip() for package in packages if str(package).strip()]
    if not packages:
        return
    target = plugin_packages_dir()
    os.makedirs(target, exist_ok=True)
    args = [
        "-m",
        "pip",
        "--disable-pip-version-check",
        "install",
        "--target",
        target,
        "--upgrade",
        "--no-input",
    ]
    if force:
        args.append("--force-reinstall")
    args.extend(packages)
    proc = run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "").strip() or "Failed to install Fishbot Python requirements.")


def _bootstrap_args(args):
    args = list(args or [])
    paths = _python_paths()
    if not paths:
        return args
    bootstrap = (
        "import json, runpy, sys\n"
        "for p in reversed(json.loads(sys.argv[1])):\n"
        "    if p and p not in sys.path:\n"
        "        sys.path.insert(0, p)\n"
        "mode=sys.argv[2]\n"
        "if mode == '-c':\n"
        "    code=sys.argv[3]\n"
        "    sys.argv=['-c'] + sys.argv[4:]\n"
        "    exec(compile(code, '<string>', 'exec'), {'__name__': '__main__', '__file__': '<string>'})\n"
        "else:\n"
        "    script=sys.argv[3]\n"
        "    sys.argv=[script] + sys.argv[4:]\n"
        "    runpy.run_path(script, run_name='__main__')\n"
    )
    if args[:1] == ["-c"]:
        return ["-c", bootstrap, json.dumps(paths), "-c", args[1] if len(args) > 1 else "", *args[2:]]
    if args and not str(args[0]).startswith("-"):
        return ["-c", bootstrap, json.dumps(paths), "script", *args]
    return args


def _window_options(visible=False):
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if visible:
            startupinfo.wShowWindow = 5  # SW_SHOW for the GUI
        else:
            startupinfo.wShowWindow = 0  # SW_HIDE
    return startupinfo, creationflags


def popen(args, visible=False, **kwargs):
    startupinfo, creationflags = _window_options(visible)
    kwargs.setdefault("env", python_env())
    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
    if "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.DEVNULL
    if "stderr" not in kwargs:
        kwargs["stderr"] = subprocess.DEVNULL

    return subprocess.Popen(
        python_cmd() + _bootstrap_args(args),
        startupinfo=startupinfo,
        creationflags=creationflags,
        **kwargs,
    )


def run(args, visible=False, **kwargs):
    startupinfo, creationflags = _window_options(visible)
    kwargs.setdefault("env", python_env())
    if "stdin" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
    if "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.DEVNULL
    if "stderr" not in kwargs:
        kwargs["stderr"] = subprocess.DEVNULL

    return subprocess.run(
        python_cmd() + _bootstrap_args(args),
        startupinfo=startupinfo,
        creationflags=creationflags,
        **kwargs,
    )
