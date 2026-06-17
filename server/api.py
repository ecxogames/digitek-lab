import json

# Public / private demo modules (kept from the SDK scaffold).
from public import utils
from public import modals
from private import secret_processor

# Slice AMAS engine modules (all under server/ so dist builds ship them).
from . import macros
from . import recorder
from . import player
from . import hotkeys
from . import dialogs
from . import input_driver
from . import plugins
from . import themes


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

        # ── Slice AMAS: app info ──────────────────────────────────────
        elif action == "slice_app_info":
            w, h = input_driver.get_screen_size()
            return _ok({
                "version": "1.0.0",
                "inputAvailable": input_driver.is_available(),
                "inputError": input_driver.availability_error(),
                "controllerAvailable": input_driver.controller_available(),
                "controllerError": input_driver.controller_availability_error(),
                "screen": {"width": w, "height": h},
                "hotkeys": hotkeys.info(),
                "dataDir": macros.DATA_DIR,
            })
        elif action == "slice_controller_support_install":
            return _ok(input_driver.install_controller_support())
        elif action == "slice_controller_support_uninstall":
            return _ok(input_driver.uninstall_controller_support())
        elif action == "slice_controller_support_job_start":
            return _ok(input_driver.start_controller_support_job(req.get("kind", "install")))
        elif action == "slice_controller_support_job_status":
            return _ok(input_driver.controller_support_job_status())
        elif action == "slice_controller_support_status":
            return _ok({
                "controllerAvailable": input_driver.controller_available(),
                "controllerError": input_driver.controller_availability_error(),
            })

        # ── Slice AMAS: macros ────────────────────────────────────────
        elif action == "slice_list_macros":
            return _ok({"user": macros.list_macros(), "core": macros.list_core_macros()})
        elif action == "slice_list_actions":
            return _ok(macros.list_core_actions())
        elif action == "slice_load_macro":
            return _ok(macros.resolve_macro(req.get("kind", "macro"), req.get("ref")))
        elif action == "slice_save_macro":
            return _ok(macros.save_macro(req.get("data", {})))
        elif action == "slice_delete_macro":
            return _ok(macros.delete_macro(req.get("ref")))

        # ── Slice AMAS: executions ────────────────────────────────────
        elif action == "slice_new_execution":
            return _ok(macros.new_execution(req.get("name", "Untitled Execution")))
        elif action == "slice_list_executions":
            return _ok(macros.list_executions())
        elif action == "slice_load_execution":
            return _ok(macros.load_execution(req.get("ref")))
        elif action == "slice_save_execution":
            return _ok(macros.save_execution(req.get("name"), req.get("data", {})))
        elif action == "slice_delete_execution":
            return _ok(macros.delete_execution(req.get("ref")))

        # ── Slice AMAS: import / export (native dialogs) ──────────────
        elif action == "slice_export_macro":
            data = macros.resolve_macro(req.get("kind", "macro"), req.get("ref"))
            path = dialogs.save_as(macros.slugify(data.get("name"), "macro"), kind="macro")
            if not path:
                return _ok({"cancelled": True})
            macros.write_raw_file(path, data)
            return _ok({"path": path})
        elif action == "slice_import_macro":
            path = dialogs.open_file(kind="macro")
            if not path:
                return _ok({"cancelled": True})
            data = macros.read_raw_file(path)
            return _ok(macros.save_macro(data))
        elif action == "slice_export_execution":
            data = req.get("data") or macros.load_execution(req.get("ref"))
            path = dialogs.save_as(macros.slugify(data.get("name"), "execution"), kind="execution")
            if not path:
                return _ok({"cancelled": True})
            macros.write_raw_file(path, data)
            return _ok({"path": path})
        elif action == "slice_import_execution":
            path = dialogs.open_file(kind="execution")
            if not path:
                return _ok({"cancelled": True})
            return _ok(macros.read_raw_file(path))

        # ── Slice AMAS: plugins ───────────────────────────────────────
        elif action == "slice_list_plugins":
            return _ok(plugins.list_plugins())
        elif action == "slice_import_plugin":
            path = dialogs.open_file(kind="plugin")
            if not path:
                return _ok({"cancelled": True})
            return _ok(plugins.import_plugin(path))
        elif action == "slice_remove_plugin":
            return _ok(plugins.remove_plugin(req.get("pluginId")))
        elif action == "slice_clear_plugin_cache":
            return _ok(plugins.clear_plugin_cache(req.get("pluginId")))
        elif action == "slice_open_plugins_folder":
            return _ok(plugins.open_plugins_folder())
        elif action == "slice_get_pinned_plugins":
            return _ok(plugins.get_pinned_plugins())
        elif action == "slice_set_pinned_plugins":
            return _ok(plugins.set_pinned_plugins(req.get("pluginIds", [])))
        elif action == "slice_marketplace_plugins":
            return _ok(plugins.marketplace_manifest())
        elif action == "slice_install_marketplace_plugin":
            return _ok(plugins.install_marketplace_plugin(req.get("pluginId")))
        elif action == "slice_plugin_update_status":
            return _ok(plugins.plugin_update_status(req.get("pluginId")))
        elif action == "slice_update_plugin":
            return _ok(plugins.install_marketplace_plugin(req.get("pluginId")))
        elif action == "slice_load_plugin_ui":
            return _ok(plugins.load_ui(req.get("pluginId")))
        elif action == "slice_plugin_call":
            raw = plugins.call_plugin(req.get("pluginId"), req.get("payload", {}))
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict) and parsed.get("status") == "error":
                    return _err(parsed.get("reason", "Plugin backend error"))
                if isinstance(parsed, dict) and parsed.get("status") == "ok":
                    return _ok(parsed.get("result"))
                return _ok(parsed)
            except Exception:
                return _ok(raw)

        # ── Slice AMAS: themes ────────────────────────────────────────
        elif action == "slice_list_themes":
            return _ok(themes.list_themes())
        elif action == "slice_active_theme":
            return _ok(themes.active_theme())
        elif action == "slice_import_theme":
            path = dialogs.open_file(kind="theme")
            if not path:
                return _ok({"cancelled": True})
            return _ok(themes.import_theme(path))
        elif action == "slice_set_theme":
            return _ok(themes.set_active(req.get("themeId", "")))
        elif action == "slice_remove_theme":
            return _ok(themes.remove_theme(req.get("themeId")))

        # ── Slice AMAS: recording ─────────────────────────────────────
        elif action == "slice_record_start":
            if not input_driver.is_available():
                return _err(input_driver.availability_error())
            hotkeys.ensure_started()
            return _ok(recorder.start(
                motion_controlled=req.get("motionControlled", False),
                stop_keys=hotkeys.stop_keys_for_recording(),
            ))
        elif action == "slice_record_stop":
            return _ok(recorder.stop())
        elif action == "slice_record_status":
            return _ok(recorder.status())

        # ── Slice AMAS: playback ──────────────────────────────────────
        elif action == "slice_play":
            if not input_driver.is_available():
                return _err(input_driver.availability_error())
            hotkeys.ensure_started()
            return _ok(player.play(req.get("execution", {}),
                                   countdown_ms=req.get("countdownMs", 0)))
        elif action == "slice_pause":
            return _ok(player.pause())
        elif action == "slice_resume":
            return _ok(player.resume())
        elif action == "slice_stop":
            return _ok(player.stop())
        elif action == "slice_playback_status":
            return _ok(player.status())

        return _err(f"Unknown action: {action}")
    except Exception as e:
        return _err(str(e))
