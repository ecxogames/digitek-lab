# Public Modal Library
# This module provides native system dialog helpers that can be called from the Python backend.
# All dialogs block until the user dismisses them and run on the main thread via tkinter.
#
# Usage from server/api.py:
#   from public import modals
#
#   modals.show_info("App Ready", "The application loaded successfully.")
#   confirmed = modals.show_confirm("Delete?", "Are you sure you want to delete this item?")
#   user_input = modals.show_prompt("Rename", "Enter a new name:", default="my_file")

import tkinter as tk
from tkinter import messagebox, simpledialog


def _hidden_root() -> tk.Tk:
    """Creates a hidden Tk root window required by tkinter dialog APIs."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def show_alert(title: str, message: str) -> None:
    """Show a native warning/alert dialog with a single OK button."""
    root = _hidden_root()
    messagebox.showwarning(title=title, message=message, parent=root)
    root.destroy()


def show_info(title: str, message: str) -> None:
    """Show a native information dialog with a single OK button."""
    root = _hidden_root()
    messagebox.showinfo(title=title, message=message, parent=root)
    root.destroy()


def show_error(title: str, message: str) -> None:
    """Show a native error dialog with a single OK button."""
    root = _hidden_root()
    messagebox.showerror(title=title, message=message, parent=root)
    root.destroy()


def show_confirm(title: str, message: str) -> bool:
    """Show a native Yes/No confirmation dialog. Returns True if the user clicks Yes."""
    root = _hidden_root()
    result = messagebox.askyesno(title=title, message=message, parent=root)
    root.destroy()
    return result


def show_prompt(title: str, message: str, default: str = "") -> str | None:
    """
    Show a native text input dialog.
    Returns the entered string, or None if the user cancels.
    """
    root = _hidden_root()
    result = simpledialog.askstring(title=title, prompt=message, initialvalue=default, parent=root)
    root.destroy()
    return result

