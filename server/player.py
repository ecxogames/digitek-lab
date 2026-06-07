# DigiTek Lab — Playback Engine (multi-track)
#
# Plays an execution back as real keyboard + mouse input. An execution is a set of
# CLIPS, each placed on a layer at a `start` time for a `duration` (with an optional
# `trimStart` head-trim). Clips that overlap in time — even on different layers —
# play simultaneously.
#
# Model: every clip's events are mapped to ABSOLUTE timeline seconds and merged into
# one time-sorted queue, played by a single worker against a pause-aware clock. This
# gives true parallelism with no per-clip threads.
#
# Resize semantics = TRIM / HOLD (no time-scaling): only a clip's events whose own
# time `t` falls in [trimStart, trimStart+duration) play, at native speed; a clip
# longer than its content simply idles (holds) to the end, shorter truncates.
#
# Motion-Controlled: when on and the timeline contains a motion-control macro, the
# `reset_character` + `first_person` core macros play ONCE as a lead-in before the
# timeline starts.

import time
import threading

from . import input_driver
from . import macros

# Notches used by FOV / zoom helpers when a core macro isn't supplying events.
_ZOOM_RANGE = 18  # enough scroll steps to traverse Roblox's full zoom range

_lock = threading.Lock()
_state = {
    "thread": None,
    "playing": False,
    "paused": False,
    "phase": "idle",          # idle | timeline | rewind
    "total": 0.0,
    "rewind_start": 0.0,
    "error": None,
    "stop": threading.Event(),
    "pause": threading.Event(),
}

# Pause-aware playback clock (timeline seconds, excluding paused time).
_clock = {"start": 0.0, "paused_total": 0.0, "paused_at": None}

# Timed log of reversible motion during the forward pass — used to play the
# execution BACKWARD when Motion Control is on. Entries are:
# (t_seconds, kind, a, b):
#   "rmove"               -> (dx, dy)
#   "scroll"              -> (notches, 0)
#   "key"                 -> (key_name, action)
#   "controller_axis_seg" -> (part, {"from":(fx,fy,fv), "to":(tx,ty,tv), "dur":seconds})
_cam_log = []
_track_cam = [False]   # log only during the forward timeline phase
# Per-part in-progress segment tracker; populated while _track_cam is True.
_axis_tracking = {}    # part -> {"t_start": float, "from": (x,y,v), "last": (x,y,v), "t_last": float}
_REVERSIBLE_KEY_OPPOSITES = {
    "w": "s",
    "s": "w",
    "a": "d",
    "d": "a",
}
_DEFAULT_MOTION_KEY_MAP = {
    "w": {"mode": "opposite", "target": "s"},
    "s": {"mode": "opposite", "target": "w"},
    "a": {"mode": "opposite", "target": "d"},
    "d": {"mode": "opposite", "target": "a"},
    "shift": {"mode": "same"},
    "shift_l": {"mode": "same"},
    "shift_r": {"mode": "same"},
    "ctrl": {"mode": "same"},
    "ctrl_l": {"mode": "same"},
    "ctrl_r": {"mode": "same"},
    "alt": {"mode": "same"},
    "alt_l": {"mode": "same"},
    "alt_gr": {"mode": "same"},
}
_motion_key_map = [{}]


class _Stopped(Exception):
    pass


def _clock_now():
    """Elapsed timeline seconds since the clock started, excluding paused time."""
    c = _clock
    t = time.perf_counter() - c["start"] - c["paused_total"]
    if c["paused_at"] is not None:
        t -= time.perf_counter() - c["paused_at"]
    return max(0.0, t)


# ── Cooperative waits ─────────────────────────────────────────────────
def _sleep(seconds):
    """Relative cooperative sleep (used by the sequential lead-in). Honours pause/stop."""
    end = time.perf_counter() + max(0.0, seconds)
    while True:
        if _state["stop"].is_set():
            raise _Stopped()
        while _state["pause"].is_set() and not _state["stop"].is_set():
            time.sleep(0.02)
            end = time.perf_counter() + max(0.0, end - time.perf_counter())
        remaining = end - time.perf_counter()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.01))


def _wait_until(target):
    """Block until the playback clock reaches `target` seconds. Honours pause/stop."""
    while True:
        if _state["stop"].is_set():
            raise _Stopped()
        if _state["pause"].is_set():
            time.sleep(0.02)
            continue
        now = _clock_now()
        if now >= target:
            return
        time.sleep(min(0.005, max(0.0, target - now)))


# ── Event playback ────────────────────────────────────────────────────
def _play_events(events):
    """Replay a relative, timestamped event list in real time (sequential, for lead-in)."""
    prev_t = 0.0
    for ev in sorted(events, key=lambda e: e.get("t", 0)):
        if _state["stop"].is_set():
            raise _Stopped()
        t = float(ev.get("t", prev_t))
        _sleep(max(0.0, t - prev_t))
        prev_t = t
        _dispatch_event(ev)


def _normalize_key_name(name):
    """Return a normalized key name for motion-map lookup."""
    if not isinstance(name, str):
        return None
    key = name.lower()
    return key or None


def _normalize_motion_key_map(mapping):
    if mapping is None:
        mapping = _DEFAULT_MOTION_KEY_MAP
    out = {}
    for key, spec in (mapping or {}).items():
        key = _normalize_key_name(key)
        if not key:
            continue
        if spec is None:
            out.pop(key, None)
            continue
        if isinstance(spec, str):
            mode, target = "opposite", spec
        else:
            mode = str(spec.get("mode", "opposite")).lower()
            target = spec.get("target", "")
        if mode not in ("opposite", "same", "disabled"):
            mode = "opposite"
        target = _normalize_key_name(target)
        out[key] = {"mode": mode, "target": target or ""}
    return out


def _dispatch_event(ev):
    etype = ev.get("type")
    if etype == "key":
        if ev.get("action") == "down":
            input_driver.key_press(ev.get("key"))
        else:
            input_driver.key_release(ev.get("key"))
        key = _normalize_key_name(ev.get("key"))
        spec = _motion_key_map[0].get(key) if key else None
        if _track_cam[0] and spec and spec.get("mode") != "disabled":
            _cam_log.append((_clock_now(), "key", key, ev.get("action")))
    elif etype == "move":
        input_driver.move_to(ev.get("x", 0), ev.get("y", 0))
    elif etype == "button":
        if ev.get("action") == "down":
            input_driver.mouse_down(ev.get("x"), ev.get("y"), ev.get("button", "left"))
        else:
            input_driver.mouse_up(ev.get("x"), ev.get("y"), ev.get("button", "left"))
    elif etype == "scroll":
        input_driver.scroll(ev.get("dx", 0), ev.get("dy", 0))
    elif etype == "rpos":
        input_driver.raw_move_abs(ev.get("x", 0.5), ev.get("y", 0.5))
    elif etype == "rmove":
        input_driver.raw_move_relative(ev.get("dx", 0.0), ev.get("dy", 0.0))
        if _track_cam[0]:
            _cam_log.append((_clock_now(), "rmove", ev.get("dx", 0.0), ev.get("dy", 0.0)))
    elif etype == "rbtn":
        input_driver.raw_button(ev.get("button", "left"), ev.get("action") == "down")
    elif etype == "controller_axis":
        part = ev.get("part", "left_stick")
        x    = float(ev.get("x",     0.0))
        y    = float(ev.get("y",     0.0))
        val  = float(ev.get("value", 0.0))
        input_driver.controller_axis(part, x, y, val)
        if _track_cam[0]:
            t_now = _clock_now()
            is_reset = (x == 0.0 and y == 0.0 and val == 0.0)
            if not is_reset:
                if part not in _axis_tracking:
                    _axis_tracking[part] = {"t_start": t_now, "from": (x, y, val)}
                _axis_tracking[part]["last"] = (x, y, val)
                _axis_tracking[part]["t_last"] = t_now
            else:
                if part in _axis_tracking:
                    seg = _axis_tracking.pop(part)
                    fx, fy, fv = seg["from"]
                    tx, ty, tv = seg["last"]
                    dur = max(0.05, seg.get("t_last", t_now) - seg["t_start"])
                    _cam_log.append((t_now, "controller_axis_seg", part, {
                        "from": (fx, fy, fv), "to": (tx, ty, tv), "dur": dur,
                    }))
    # Unknown event types (e.g. 'noop') are ignored on purpose.

    if _track_cam[0] and etype == "scroll":
        _cam_log.append((_clock_now(), "scroll", int(ev.get("dy", 0)), 0))


# ── Action compilation (single-use, parameterized) ───────────────────
# Scroll convention (matches Roblox): dy < 0 zooms OUT (wheel down),
# dy > 0 zooms IN toward first person (wheel up).
def _zoom_out_events(step_delay=0.012):
    return [{"t": i * step_delay, "type": "scroll", "dx": 0, "dy": -1}
            for i in range(_ZOOM_RANGE)]


def _scroll_in_events(notches, start_t=0.0, step_delay=0.012):
    return [{"t": start_t + i * step_delay, "type": "scroll", "dx": 0, "dy": 1}
            for i in range(max(0, int(notches)))]


def _compile_action(action_type, p):
    """Turn a parameterized action into an event list (relative t in seconds)."""
    p = p or {}
    if action_type == "wait":
        ms = float(p.get("ms", 500))
        return [{"t": ms / 1000.0, "type": "noop"}]
    if action_type == "keypress":
        key = p.get("key", "space")
        hold = float(p.get("holdMs", 40)) / 1000.0
        return [{"t": 0.0, "type": "key", "action": "down", "key": key},
                {"t": hold, "type": "key", "action": "up", "key": key}]
    if action_type == "keycombo":
        keys = p.get("keys", []) or []
        hold = float(p.get("holdMs", 60)) / 1000.0
        evs = [{"t": 0.0, "type": "key", "action": "down", "key": k} for k in keys]
        evs += [{"t": hold, "type": "key", "action": "up", "key": k} for k in reversed(keys)]
        return evs
    if action_type == "mousemove":
        return [{"t": 0.0, "type": "move", "x": float(p.get("x", 0.5)), "y": float(p.get("y", 0.5))}]
    if action_type == "mouseclick":
        x, y = float(p.get("x", 0.5)), float(p.get("y", 0.5))
        btn = p.get("button", "left")
        evs = []
        for i in range(max(1, int(p.get("count", 1)))):
            base = i * 0.12
            evs += [{"t": base, "type": "button", "action": "down", "button": btn, "x": x, "y": y},
                    {"t": base + 0.03, "type": "button", "action": "up", "button": btn, "x": x, "y": y}]
        return evs
    if action_type == "scroll":
        amount = int(p.get("amount", -3))
        steps = max(1, abs(amount))
        direction = 1 if amount > 0 else -1
        return [{"t": i * 0.012, "type": "scroll", "dx": 0, "dy": direction} for i in range(steps)]
    if action_type == "fov":
        evs = _zoom_out_events()
        last_t = evs[-1]["t"] if evs else 0.0
        evs += _scroll_in_events(p.get("targetNotches", 6), start_t=last_t + 0.05)
        return evs
    # mousedrag is a held action — see _held_events (raw SendInput + relative motion).
    return []


def _action_intrinsic(action_type, p):
    """Natural duration (seconds) of an action — mirrors the UI's estimateActionDuration."""
    p = p or {}
    if action_type == "wait":
        return float(p.get("ms", 0)) / 1000.0
    if action_type in ("keypress", "keycombo"):
        return float(p.get("holdMs", 0)) / 1000.0 + 0.05
    if action_type == "mousedrag":
        return float(p.get("durationMs", 0)) / 1000.0
    if action_type == "controlleraxis":
        return 1.0
    if action_type == "mouseclick":
        return 0.12 * max(1, int(p.get("count", 1)))
    if action_type == "scroll":
        return abs(int(p.get("amount", 0))) * 0.012
    if action_type == "fov":
        return (_ZOOM_RANGE + int(p.get("targetNotches", 0))) * 0.012 + 0.05
    return 0.1


# ── Held actions (length = clip length, no in-modal hold/duration) ────
# Their key-hold / drag spans the whole clip; the timeline length is the only
# control over how long they last.
_HELD = {"keypress", "keycombo", "mousedrag", "controlleraxis", "wait"}


def _held_events(action_type, p, duration):
    p = p or {}
    end = max(0.02, float(duration))
    if action_type == "keypress":
        key = p.get("key", "space")
        return [{"t": 0.0, "type": "key", "action": "down", "key": key},
                {"t": end, "type": "key", "action": "up", "key": key}]
    if action_type == "keycombo":
        keys = p.get("keys", []) or []
        evs = [{"t": 0.0, "type": "key", "action": "down", "key": k} for k in keys]
        evs += [{"t": end, "type": "key", "action": "up", "key": k} for k in reversed(keys)]
        return evs
    if action_type == "mousedrag":
        fx, fy = float(p.get("fromX", 0.4)), float(p.get("fromY", 0.5))
        tx, ty = float(p.get("toX", 0.6)), float(p.get("toY", 0.5))
        btn = p.get("button", "right")
        steps = 60
        # Lead/tail dwell so the held button registers before/after the motion.
        lead = min(0.05, end * 0.25)
        tail = min(0.04, end * 0.10)
        span = max(0.01, end - lead - tail)
        evs = [
            {"t": 0.0, "type": "rpos", "x": fx, "y": fy},                     # cursor → start
            {"t": min(0.02, lead * 0.5), "type": "rbtn", "action": "down", "button": btn},
        ]
        # Cursor is locked during the drag → move with RELATIVE deltas (camera pan).
        for i in range(1, steps + 1):
            evs.append({"t": lead + span * (i / steps), "type": "rmove",
                        "dx": (tx - fx) / steps, "dy": (ty - fy) / steps})
        evs.append({"t": end, "type": "rbtn", "action": "up", "button": btn})
        return evs
    if action_type == "controlleraxis":
        part = p.get("part", "left_stick")
        # Backward compatibility with the earlier single-value schema.
        from_x = float(p.get("fromX", 0.0) or 0.0)
        from_y = float(p.get("fromY", 0.0) or 0.0)
        to_x = float(p.get("toX", p.get("x", 0.0)) or 0.0)
        to_y = float(p.get("toY", p.get("y", 0.0)) or 0.0)
        from_value = float(p.get("fromValue", 0.0) or 0.0)
        to_value = float(p.get("toValue", p.get("value", 0.0)) or 0.0)
        steps = max(2, min(90, int(end / 0.016)))
        evs = []
        for i in range(steps + 1):
            f = i / steps
            evs.append({
                "t": end * f,
                "type": "controller_axis",
                "part": part,
                "x": from_x + (to_x - from_x) * f,
                "y": from_y + (to_y - from_y) * f,
                "value": from_value + (to_value - from_value) * f,
            })
        evs.append({"t": end, "type": "controller_axis", "part": part, "x": 0.0, "y": 0.0, "value": 0.0})
        return evs
    return []  # wait → no events; only reserves the clip's duration


# ── Clip / queue building ─────────────────────────────────────────────
def _item_events(item):
    """Return (sorted intrinsic events, intrinsic duration) for a timeline item."""
    kind = item.get("kind")
    if kind == "action":
        evs = [e for e in _compile_action(item.get("actionType"), item.get("params", {}))
               if e.get("type") != "noop"]
        return sorted(evs, key=lambda e: e.get("t", 0)), _action_intrinsic(
            item.get("actionType"), item.get("params", {}))
    data = macros.load_core_macro(item.get("ref")) if kind == "core" else macros.load_macro(item.get("ref"))
    evs = data.get("events", []) or []
    d0 = float(data.get("duration", 0) or (evs[-1].get("t", 0) if evs else 0))
    return sorted(evs, key=lambda e: e.get("t", 0)), d0


def _build_queue(execution):
    """
    Flatten all clips into a single time-sorted list of (absTime, event), applying
    trim/hold, and return (queue, total_seconds).
    """
    queue = []
    total = 0.0
    seq = 0.0  # fallback cursor for legacy items that have no explicit `start`
    for item in execution.get("timeline", []) or []:
        trim = float(item.get("trimStart", 0.0) or 0.0)
        is_held = item.get("kind") == "action" and item.get("actionType") in _HELD
        duration = float(item.get("duration", 0.0) or 0.0)
        if duration <= 0:
            duration = 1.0 if is_held else max(0.0, _item_events(item)[1] - trim)
        # Legacy executions (pre multi-track) have no `start` → play sequentially.
        start = seq if item.get("start") is None else float(item.get("start") or 0.0)
        seq = max(seq, start + duration)

        if is_held:
            # Length-driven: events span the clip; the up lands at the clip's end.
            for ev in _held_events(item.get("actionType"), item.get("params", {}), duration):
                queue.append((start + float(ev.get("t", 0.0)), ev))
        else:
            evs, _ = _item_events(item)
            win_end = trim + duration
            for ev in evs:
                t = float(ev.get("t", 0.0))
                if t < trim - 1e-9 or t >= win_end - 1e-9:
                    continue  # head-trim / tail-truncate
                queue.append((start + (t - trim), ev))
        total = max(total, start + duration)
    queue.sort(key=lambda x: x[0])
    return queue, total


def _has_motion_macro(execution):
    for item in execution.get("timeline", []) or []:
        if item.get("kind") != "macro":
            continue
        try:
            d = macros.load_macro(item.get("ref"))
            if d.get("kind") == "motion_control" or d.get("motionControlled"):
                return True
        except Exception:
            continue
    return False


# ── Worker ────────────────────────────────────────────────────────────
def _set_phase(phase):
    with _lock:
        _state["phase"] = phase


def _do_rewind(total):
    """
    Play the execution BACKWARD by replaying logged reversible motion with
    mirrored, inverted values.  All log entries are first expanded into a
    flat list of (rewind_t, callable) pairs and sorted by rewind_t so that
    events from parallel layers fire concurrently against a shared clock —
    the same model as the forward _build_queue / dispatch loop.

    Mapping: a forward event at time t fires at rewind time (total - t).
    For controller_axis_seg the segment spans [t - dur, t] forward, so in
    the rewind it spans [total - t, total - t + dur].
    """
    log = _cam_log[:]
    if not log:
        return

    has_pan = any(e[1] == "rmove" for e in log)

    # ── Build flat rewind event list ─────────────────────────────────
    rewind_events = []   # list of (rewind_t, callable)

    for (t, kind, a, b) in log:
        rt = total - t   # rewind clock time for this log entry

        if kind == "rmove":
            rewind_events.append((rt, lambda _a=a, _b=b:
                                  input_driver.raw_move_relative(-_a, -_b)))

        elif kind == "scroll":
            rewind_events.append((rt, lambda _a=a:
                                  input_driver.scroll(0, -_a)))

        elif kind == "controller_axis_seg":
            # t is the end of the forward segment; the inverted segment
            # starts at rt = total - t and lasts `dur` seconds.
            part_name = a
            fx, fy, fv = b["from"]
            tx, ty, tv = b["to"]
            dur = max(0.05, b["dur"])
            is_trigger = "trigger" in part_name
            if is_trigger:
                # Triggers 0..1: swap initial ↔ target, no negation.
                inv_fx, inv_fy, inv_fv = 0.0, 0.0, tv
                inv_tx, inv_ty, inv_tv = 0.0, 0.0, fv
            else:
                # Sticks -1..1: negate and swap.
                inv_fx, inv_fy, inv_fv = -tx, -ty, fv
                inv_tx, inv_ty, inv_tv = -fx, -fy, tv
            steps = max(2, min(90, int(dur / 0.016)))
            for i in range(steps + 1):
                f = i / steps
                step_rt = rt + dur * f
                x = inv_fx + (inv_tx - inv_fx) * f
                y = inv_fy + (inv_ty - inv_fy) * f
                v = inv_fv + (inv_tv - inv_fv) * f
                rewind_events.append((step_rt, lambda _p=part_name, _x=x, _y=y, _v=v:
                                      input_driver.controller_axis(_p, _x, _y, _v)))
            # Zero-reset after the segment ends.
            rewind_events.append((rt + dur, lambda _p=part_name:
                                  input_driver.controller_axis(_p, 0.0, 0.0, 0.0)))

        elif kind == "key":
            spec = _motion_key_map[0].get(a) or {}
            mode = spec.get("mode", "opposite")
            key = a if mode == "same" else spec.get("target") or _REVERSIBLE_KEY_OPPOSITES.get(a)
            rev_action = "down" if b == "up" else "up"
            if key:
                if rev_action == "down":
                    rewind_events.append((rt, lambda _k=key: input_driver.key_press(_k)))
                else:
                    rewind_events.append((rt, lambda _k=key: input_driver.key_release(_k)))

    if not rewind_events:
        return

    rewind_events.sort(key=lambda e: e[0])

    # ── Dispatch against a shared absolute rewind clock ──────────────
    if has_pan:
        input_driver.raw_button("right", True)   # hold RMB for camera pan
        _sleep(0.05)

    t0 = time.perf_counter()
    for (rt, fn) in rewind_events:
        if _state["stop"].is_set():
            break
        # Wait until elapsed rewind time reaches rt.
        while not _state["stop"].is_set():
            remaining = rt - (time.perf_counter() - t0)
            if remaining <= 0:
                break
            time.sleep(min(0.005, remaining))
        if not _state["stop"].is_set():
            fn()

    if has_pan:
        _sleep(0.04)
        input_driver.raw_button("right", False)


def _worker(execution):
    motion_controlled = bool(execution.get("motionControlled", False))
    try:
        # Reset the camera log; record motion only on the forward pass.
        _cam_log.clear()
        _axis_tracking.clear()
        _motion_key_map[0] = _normalize_motion_key_map(execution.get("motionKeyMap"))
        _track_cam[0] = motion_controlled

        # Start the timeline clock and build the merged event queue.
        with _lock:
            _clock["start"] = time.perf_counter()
            _clock["paused_total"] = 0.0
            _clock["paused_at"] = None
        queue, total = _build_queue(execution)
        with _lock:
            _state["total"] = total
            _state["phase"] = "timeline"

        for abs_t, ev in queue:
            if _state["stop"].is_set():
                break
            _wait_until(abs_t)
            _dispatch_event(ev)

        # Idle out any trailing hold/gap so total duration is honoured.
        if not _state["stop"].is_set():
            _wait_until(total)

        # Motion Control: play the execution backward to retrace the camera to its
        # start position, so the next take (e.g. a clean plate) repeats the move.
        if motion_controlled and not _state["stop"].is_set() and _cam_log:
            _track_cam[0] = False
            with _lock:
                _state["rewind_start"] = time.perf_counter()
                _state["phase"] = "rewind"
            _do_rewind(total)
    except _Stopped:
        pass
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        _track_cam[0] = False
        _safe_release_all()
        with _lock:
            _state["playing"] = False
            _state["paused"] = False
            _state["phase"] = "idle"
            _state["pause"].clear()


def _safe_release_all():
    for key in ("w", "a", "s", "d", "shift", "space", "ctrl_l", "alt_l", "esc", "enter"):
        try:
            input_driver.key_release(key)
        except Exception:
            pass
    for btn in ("left", "right", "middle"):
        try:
            input_driver.mouse_up(button=btn)
        except Exception:
            pass
        try:
            input_driver.raw_button(btn, False)   # also release any SendInput-held button
        except Exception:
            pass
    try:
        input_driver.controller_axis_reset()
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────
def play(execution, countdown_ms=0):
    input_driver._ensure_imported()
    with _lock:
        if _state["playing"]:
            return {"ok": False, "reason": "Already playing."}
        _state["stop"] = threading.Event()
        _state["pause"] = threading.Event()
        _state["playing"] = True
        _state["paused"] = False
        _state["phase"] = "starting"
        _state["total"] = 0.0
        _state["error"] = None

    if countdown_ms and countdown_ms > 0:
        time.sleep(countdown_ms / 1000.0)

    t = threading.Thread(target=_worker, args=(execution,), daemon=True)
    with _lock:
        _state["thread"] = t
    t.start()
    return {"ok": True}


def pause():
    with _lock:
        if not _state["playing"] or _state["paused"]:
            return {"ok": False, "reason": "Not playing."}
        _state["pause"].set()
        _state["paused"] = True
        if _clock["paused_at"] is None:
            _clock["paused_at"] = time.perf_counter()
    return {"ok": True}


def resume():
    with _lock:
        if not _state["playing"] or not _state["paused"]:
            return {"ok": False, "reason": "Not paused."}
        if _clock["paused_at"] is not None:
            _clock["paused_total"] += time.perf_counter() - _clock["paused_at"]
            _clock["paused_at"] = None
        _state["pause"].clear()
        _state["paused"] = False
    return {"ok": True}


def stop():
    with _lock:
        _state["stop"].set()
        _state["pause"].clear()
    return {"ok": True}


def is_playing():
    with _lock:
        return _state["playing"]


def status():
    with _lock:
        phase = _state["phase"]
        total = _state["total"]
        if phase == "timeline":
            elapsed = round(min(_clock_now(), total), 3)
        elif phase == "rewind":
            # Sweep the playhead back toward 0 as the execution plays backward.
            elapsed = round(max(0.0, total - (time.perf_counter() - _state["rewind_start"])), 3)
        else:
            elapsed = 0.0
        return {
            "playing": _state["playing"],
            "paused": _state["paused"],
            "phase": phase,
            "elapsed": elapsed,
            "total": round(total, 3),
            "error": _state["error"],
        }
