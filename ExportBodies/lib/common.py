"""Fusion handles and small helpers shared by every command."""
import adsk
import adsk.core
import adsk.fusion

app       = adsk.core.Application.get()
ui        = app.userInterface
_handlers = []   # keeps event handlers alive while the add-in runs


def _as_component(entity):
    """entity as a component: a normal Component, or the top level of a flat
    pattern (a FlatPattern, which is a BaseComponent but not a Component)."""
    return adsk.fusion.Component.cast(entity) or adsk.fusion.BaseComponent.cast(entity)


def _child_occurrences(node):
    """Occurrences directly under an Occurrence or component, or None - a flat
    pattern has no occurrences."""
    occ = adsk.fusion.Occurrence.cast(node)
    if occ:
        return occ.childOccurrences
    return getattr(node, "occurrences", None)


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
