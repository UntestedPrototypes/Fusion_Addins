"""Fusion handles and small helpers shared by every command."""
import adsk
import adsk.core

app       = adsk.core.Application.get()
ui        = app.userInterface
_handlers = []   # keeps event handlers alive while the add-in runs


def _disable_ghosting():
    try:
        import ctypes
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            ctypes.windll.user32.DisableProcessWindowsGhosting()
    except Exception:
        pass


def _do_events():
    try:
        for _ in range(3):
            adsk.doEvents()
    except Exception:
        pass


def _safe_name(name):
    bad = set('/ \\:|*?"<>'.replace(' ', ''))
    return ''.join('_' if ch in bad else ch for ch in name).strip()
