"""Output folder picker that remembers the last folder used."""
import json
import os

import adsk.core

from .common import ui


# ---------------------------------------------------------------------------
# Output folder picker - opens at the last used folder (shared by both
# exporters and kept between Fusion sessions), else the user's Documents
# ---------------------------------------------------------------------------
_SETTINGS_PATH = os.path.join(
    os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"),
    "UntestedPrototypes", "ExportBodies.json"   # former name kept: remembers the last folder
)


def _load_settings():
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(updates):
    try:
        settings = _load_settings()
        settings.update(updates)
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass  # remembering the folder must never block the export


def _default_folder():
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return docs if os.path.isdir(docs) else os.path.expanduser("~")


def _pick_output_folder(preferred=""):
    """Show the folder dialog starting at preferred (e.g. this document's last
    folder), else the last folder used by either exporter, else Documents.
    Returns the chosen folder, or None when cancelled/invalid.
    """
    start = ""
    for candidate in (preferred, _load_settings().get("last_folder", "")):
        if candidate and os.path.isdir(candidate):
            start = candidate
            break

    dlg = ui.createFolderDialog()
    dlg.title            = "Select Output Folder"
    dlg.initialDirectory = start or _default_folder()
    if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
        return None
    folder = dlg.folder
    if not os.path.isdir(folder):
        ui.messageBox("Selected folder does not exist:\n" + folder)
        return None
    _save_settings({"last_folder": folder})
    return folder
