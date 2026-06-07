import json
import os
import queue
import subprocess
import threading

from settings import load_settings, save_settings, update_settings
from budget import calculate_work_income, format_money, shorten_money
from picker import pick_point, pick_region
from process_utils import popen, python_cmd, run

_worker = None
_worker_lock = threading.RLock()
_worker_reader = None
_worker_lines = None


def _ok(result):
    return json.dumps({"status": "ok", "result": result})


def _err(reason):
    return json.dumps({"status": "error", "reason": str(reason)})


def handle_message(message_str):
    try:
        req = json.loads(message_str or "{}")
        action = req.get("action")

        if action == "status":
            return _ok({"settings": load_settings(), "bot": _worker_status()})
        if action == "health":
            return _ok(_health())
        if action == "save_settings":
            settings = update_settings(req.get("settings", {}))
            _worker_call({"action": "live_settings", "settings": settings}, optional=True)
            return _ok(settings)
        if action == "live_settings":
            settings = update_settings(req.get("settings", {}))
            return _ok({"settings": settings, "bot": _worker_call({"action": "live_settings", "settings": settings})})
        if action == "set_region":
            s = load_settings()
            s["bbox"] = _norm_rect(req)
            return _ok(save_settings(s))
        if action == "pick_region":
            s = load_settings()
            s["bbox"] = pick_region()
            return _ok(save_settings(s))
        if action == "set_click_location":
            s = load_settings()
            s["clickLocation"] = _norm_point(req)
            return _ok(save_settings(s))
        if action == "pick_click_location":
            s = load_settings()
            s["clickLocation"] = pick_point()
            return _ok(save_settings(s))
        if action == "start":
            settings = update_settings(req.get("settings", {}))
            return _ok(_worker_call({"action": "start", "settings": settings}))
        if action == "stop":
            return _ok(_worker_call({"action": "stop"}))
        if action == "budget":
            settings = update_settings(req.get("settings", {}))
            data = calculate_work_income(
                int(req.get("overallLevel", 1) or 1),
                int(req.get("fishermanLevel", 1) or 1),
                bool(req.get("excellentEmployee", False)),
                float(req.get("moodPercent", 0.7) or 0.7),
                settings,
            )
            return _ok({
                "estimatedIncome": data[0],
                "excellentEmployeeBonus": data[1],
                "humanizationExpense": data[2],
                "formatted": {
                    "income": shorten_money(data[0]),
                    "bonus": format_money(data[1]),
                    "expense": format_money(data[2]),
                },
            })

        return _err("Unknown Fishbot action: " + str(action))
    except Exception as exc:
        return _err(exc)


def _screen_size():
    try:
        data = _worker_call({"action": "screen_size"})
        return int(data.get("width", 1920)), int(data.get("height", 1080))
    except Exception:
        return 1920, 1080


def _worker_status():
    return _worker_call({"action": "status"}, optional=True) or {
        "running": False,
        "paused": False,
        "catches": 0,
        "misses": 0,
        "lastWhiteVsBlackPercent": 100.0,
        "lastUnderwater": False,
        "message": "Ready",
        "error": "",
        "overlay": "off",
    }


def _worker_call(payload, optional=False):
    global _worker
    with _worker_lock:
        try:
            proc = _ensure_worker()
            proc.stdin.write(json.dumps(payload or {}) + "\n")
            proc.stdin.flush()
            deadline = 30.0 if (payload or {}).get("action") == "start" else 8.0
            while True:
                try:
                    line = _worker_lines.get(timeout=deadline)
                except queue.Empty:
                    raise RuntimeError("Fishbot worker timed out while handling " + str((payload or {}).get("action", "request")) + ".")
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if data.get("status") == "error":
                    raise RuntimeError(data.get("reason") or "Fishbot worker error")
                if data.get("status") == "ok":
                    return data.get("result")
                return data
            raise RuntimeError("Fishbot worker did not return a valid response.")
        except Exception:
            if _worker and _worker.poll() is not None:
                _worker = None
            if optional:
                return None
            raise


def _ensure_worker():
    global _worker, _worker_reader, _worker_lines
    if _worker and _worker.poll() is None:
        return _worker
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
    _worker_lines = queue.Queue()
    _worker = popen(
        [script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _worker_reader = threading.Thread(target=_read_worker_output, args=(_worker, _worker_lines), name="FishbotWorkerReader", daemon=True)
    _worker_reader.start()
    return _worker


def _read_worker_output(proc, lines):
    try:
        for line in proc.stdout:
            lines.put(line)
    except Exception:
        pass


def shutdown():
    global _worker
    with _worker_lock:
        proc = _worker
        _worker = None
        if not proc:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write(json.dumps({"action": "stop"}) + "\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _health():
    child = _child_health()
    ok = bool(child.get("ok"))
    missing = child.get("missing", [])
    message = "Ready"
    if missing:
        message = "Missing Python packages: " + ", ".join(sorted(set(missing)))
    elif not child.get("ok"):
        message = child.get("error") or "Fishbot Python child process is unavailable."
    return {
        "ok": ok,
        "message": message,
        "child": child,
    }


def _import_available(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _child_health():
    script = (
        "import json, sys\n"
        "mods={'PIL':'Pillow','pynput':'pynput','tkinter':'tkinter'}\n"
        "missing=[]\n"
        "errors={}\n"
        "for module,label in mods.items():\n"
        "    try:\n"
        "        __import__(module)\n"
        "    except Exception as exc:\n"
        "        missing.append(label)\n"
        "        errors[label]=str(exc)\n"
        "print(json.dumps({'ok': not missing, 'missing': missing, 'errors': errors, 'executable': sys.executable, 'version': sys.version.split()[0]}))\n"
    )
    try:
        proc = run(["-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        output = (proc.stdout or "").strip()
        data = json.loads(output.splitlines()[-1]) if output else {}
        if proc.returncode != 0:
            data["ok"] = False
            data["error"] = output[-500:]
        return data
    except Exception as exc:
        return {
            "ok": False,
            "missing": [],
            "cmd": " ".join(python_cmd()),
            "error": str(exc),
        }


def _norm_point(req):
    w, h = _screen_size()
    return [
        int(max(0, min(1, float(req.get("x", 0)))) * w),
        int(max(0, min(1, float(req.get("y", 0)))) * h),
    ]


def _norm_rect(req):
    w, h = _screen_size()
    x1 = int(max(0, min(1, float(req.get("fromX", 0)))) * w)
    y1 = int(max(0, min(1, float(req.get("fromY", 0)))) * h)
    x2 = int(max(0, min(1, float(req.get("toX", 1)))) * w)
    y2 = int(max(0, min(1, float(req.get("toY", 1)))) * h)
    return [min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)]
def log_trace(msg): open("C:/Users/vivix/AppData/Local/DigiTek Lab/plugin-data/fishbot/trace.log", "a").write(msg + "\n")
