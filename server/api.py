import json

# Public / private demo modules (kept from the SDK scaffold).
from public import utils
from public import modals
from private import secret_processor

# DigiTek Lab engine modules (all under server/ so dist builds ship them).
from . import macros
from . import recorder
from . import player
from . import hotkeys
from . import dialogs
from . import input_driver


def _ok(result):
    return json.dumps({"status": "ok", "result": result})


def _err(reason):
    return json.dumps({"status": "error", "reason": reason})


def handle_message(message_str):
    try:
        req = json.loads(message_str)
        action = req.get("action")

        # ── SDK base / modal demos (retained) ───────────────────────────
        if action == "ping":
            return _ok(f"Pong! I received: {req.get('data', '')}")
        elif action == "public_demo":
            return _ok(utils.generate_greeting(req.get("name", "")))
        elif action == "private_demo":
            return _ok(secret_processor.process_secure_data(req.get("secret_data", "")))
        elif action == "modal_alert":
            modals.show_alert(req.get("title", "Alert"), req.get("message", ""))
            return _ok(None)
        elif action == "modal_info":
            modals.show_info(req.get("title", "Info"), req.get("message", ""))
            return _ok(None)
        elif action == "modal_error":
            modals.show_error(req.get("title", "Error"), req.get("message", ""))
            return _ok(None)
        elif action == "modal_confirm":
            return _ok(modals.show_confirm(req.get("title", "Confirm"), req.get("message", "")))
        elif action == "modal_prompt":
            return _ok(modals.show_prompt(req.get("title", "Input"),
                                          req.get("message", ""), req.get("default", "")))

        # ── DigiTek Lab: app info ──────────────────────────────────────
        elif action == "dgt_app_info":
            w, h = input_driver.get_screen_size()
            return _ok({
                "version": "1.0.0",
                "inputAvailable": input_driver.is_available(),
                "inputError": input_driver.availability_error(),
                "screen": {"width": w, "height": h},
                "hotkeys": hotkeys.info(),
                "dataDir": macros.DATA_DIR,
            })

        # ── DigiTek Lab: macros ────────────────────────────────────────
        elif action == "dgt_list_macros":
            return _ok({"user": macros.list_macros(), "core": macros.list_core_macros()})
        elif action == "dgt_list_actions":
            return _ok(macros.list_core_actions())
        elif action == "dgt_load_macro":
            return _ok(macros.resolve_macro(req.get("kind", "macro"), req.get("ref")))
        elif action == "dgt_save_macro":
            return _ok(macros.save_macro(req.get("data", {})))
        elif action == "dgt_delete_macro":
            return _ok(macros.delete_macro(req.get("ref")))

        # ── DigiTek Lab: executions ────────────────────────────────────
        elif action == "dgt_new_execution":
            return _ok(macros.new_execution(req.get("name", "Untitled Execution")))
        elif action == "dgt_list_executions":
            return _ok(macros.list_executions())
        elif action == "dgt_load_execution":
            return _ok(macros.load_execution(req.get("ref")))
        elif action == "dgt_save_execution":
            return _ok(macros.save_execution(req.get("name"), req.get("data", {})))
        elif action == "dgt_delete_execution":
            return _ok(macros.delete_execution(req.get("ref")))

        # ── DigiTek Lab: import / export (native dialogs) ──────────────
        elif action == "dgt_export_macro":
            data = macros.resolve_macro(req.get("kind", "macro"), req.get("ref"))
            path = dialogs.save_as(macros.slugify(data.get("name"), "macro"), kind="macro")
            if not path:
                return _ok({"cancelled": True})
            macros.write_raw_file(path, data)
            return _ok({"path": path})
        elif action == "dgt_import_macro":
            path = dialogs.open_file(kind="macro")
            if not path:
                return _ok({"cancelled": True})
            data = macros.read_raw_file(path)
            return _ok(macros.save_macro(data))
        elif action == "dgt_export_execution":
            data = req.get("data") or macros.load_execution(req.get("ref"))
            path = dialogs.save_as(macros.slugify(data.get("name"), "execution"), kind="execution")
            if not path:
                return _ok({"cancelled": True})
            macros.write_raw_file(path, data)
            return _ok({"path": path})
        elif action == "dgt_import_execution":
            path = dialogs.open_file(kind="execution")
            if not path:
                return _ok({"cancelled": True})
            return _ok(macros.read_raw_file(path))

        # ── DigiTek Lab: recording ─────────────────────────────────────
        elif action == "dgt_record_start":
            if not input_driver.is_available():
                return _err(input_driver.availability_error())
            hotkeys.ensure_started()
            return _ok(recorder.start(
                motion_controlled=req.get("motionControlled", False),
                stop_keys=hotkeys.stop_keys_for_recording(),
            ))
        elif action == "dgt_record_stop":
            return _ok(recorder.stop())
        elif action == "dgt_record_status":
            return _ok(recorder.status())

        # ── DigiTek Lab: playback ──────────────────────────────────────
        elif action == "dgt_play":
            if not input_driver.is_available():
                return _err(input_driver.availability_error())
            hotkeys.ensure_started()
            return _ok(player.play(req.get("execution", {}),
                                   countdown_ms=req.get("countdownMs", 0)))
        elif action == "dgt_pause":
            return _ok(player.pause())
        elif action == "dgt_resume":
            return _ok(player.resume())
        elif action == "dgt_stop":
            return _ok(player.stop())
        elif action == "dgt_playback_status":
            return _ok(player.status())

        return _err(f"Unknown action: {action}")
    except Exception as e:
        return _err(str(e))
