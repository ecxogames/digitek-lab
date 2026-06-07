import json

from public import utils
from private import secret_processor


def _ok(result):
    return json.dumps({"status": "ok", "result": result})


def _err(reason):
    return json.dumps({"status": "error", "reason": str(reason)})


def handle_message(message_str):
    try:
        req = json.loads(message_str or "{}")
        action = req.get("action")

        if action == "ping":
            return _ok(utils.greeting(req.get("name") or "Plugin developer"))
        if action == "private_demo":
            return _ok(secret_processor.process(req.get("value", "")))

        return _err("Unknown plugin action: " + str(action))
    except Exception as exc:
        return _err(exc)
