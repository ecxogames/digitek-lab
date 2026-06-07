# DigiTek Lab — Native file dialogs
#
# Save-As / Open dialogs for exporting and importing macros and executions,
# implemented with tkinter (already part of the embedded Python runtime, so no
# extra dependency). Each call spins up a hidden, top-most Tk root so the dialog
# appears above the WebView window, then tears it down.

import tkinter as tk
from tkinter import filedialog

_MACRO_TYPES = [("DigiTek Macro", "*.dgtmcr"), ("All files", "*.*")]
_EXEC_TYPES = [("DigiTek Execution", "*.dgtexec"), ("All files", "*.*")]


def _root():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def save_as(default_name, kind="macro"):
    """Ask where to export. Returns the chosen path, or None if cancelled."""
    types = _MACRO_TYPES if kind == "macro" else _EXEC_TYPES
    ext = ".dgtmcr" if kind == "macro" else ".dgtexec"
    root = _root()
    try:
        path = filedialog.asksaveasfilename(
            parent=root,
            title="Export " + ("Macro" if kind == "macro" else "Execution"),
            defaultextension=ext,
            initialfile=default_name + ext,
            filetypes=types,
        )
    finally:
        root.destroy()
    return path or None


def open_file(kind="macro"):
    """Ask which file to import. Returns the chosen path, or None if cancelled."""
    types = _MACRO_TYPES if kind == "macro" else _EXEC_TYPES
    root = _root()
    try:
        path = filedialog.askopenfilename(
            parent=root,
            title="Import " + ("Macro" if kind == "macro" else "Execution"),
            filetypes=types,
        )
    finally:
        root.destroy()
    return path or None
