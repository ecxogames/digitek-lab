# DigiTek Lab Plugin SDK

Plugins are packaged as `.dgtkplgn` zip archives. A plugin folder can contain:

- `properties.config`: plugin metadata read by DigiTek Lab (`PLUGIN_ID` or `ID`, `TITLE`, `VERSION`, `ICON`, `DESCRIPTION`, `MAIN_PAGE`, and optional marketplace fields).
- `requirements.txt`: Python packages installed when the plugin is imported or installed from the marketplace.
- `permissions.txt`: one permission identifier per line.
- `ui/`: frontend files. `ui/index.html` is the default entry.
- `server/`: Python backend. Expose `handle_message(message_str)` from `server/api.py`.
- `public/`: Python helper modules intended for public/plugin API use.
- `private/`: Python helper modules for internal implementation.
- `scripts/`: build, test, and dev scripts.
- `release/`: generated plugin packages.

Build the template with:

```bash
python template/scripts/build.py
```

Import the generated `.dgtkplgn` in DigiTek Lab from `Plugins > Import plugin`.
