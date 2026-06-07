# Public Utility Module
# This folder is intended for generic helper functions, formatting,
# non-sensitive data processors, and public API calls.

def generate_greeting(name):
    """Returns a friendly greeting string."""
    if not name:
        return "Hello, anonymous user!"
    return f"Hello, {name}! Welcome to the ESD Suite Framework."

def get_app_info():
    """Returns basic configuration or version info for the frontend UI."""
    return {
        "version": "1.0.0",
        "description": "Cross-platform runtime with embedded Python."
    }