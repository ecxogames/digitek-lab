import json
import sys

from bot import fishbot


def _ok(result):
    return {"status": "ok", "result": result}


def _err(reason):
    return {"status": "error", "reason": str(reason)}


def handle(req):
    action = (req or {}).get("action")
    if action == "status":
        return _ok(fishbot.status())
    if action == "start":
        return _ok(fishbot.start((req or {}).get("settings", {})))
    if action == "stop":
        return _ok(fishbot.stop())
    if action == "live_settings":
        return _ok(fishbot.update_settings((req or {}).get("settings", {})))
    if action == "screen_size":
        w, h = fishbot.screen_size()
        return _ok({"width": w, "height": h})
    return _err("Unknown Fishbot worker action: " + str(action))


def main():
    for line in sys.stdin:
        try:
            req = json.loads(line)
            res = handle(req)
        except Exception as exc:
            res = _err(exc)
        print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
