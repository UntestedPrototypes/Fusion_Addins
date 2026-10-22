"""ExportBodies add-in: body and sheet-metal export commands.

Commands live in commands/ (one module each), shared building blocks in lib/.
"""
import importlib
import traceback

import adsk.core

from .lib import (common, naming, selection, folders, step_post, doc_state,
                  export_separate, export_combined)
from .commands import export_bodies, flat_pattern

# Fusion keeps submodules cached when the add-in is stopped and started again,
# so reload them (dependencies first) to pick up code changes without a restart.
for _module in (common, naming, selection, folders, step_post, doc_state,
                export_separate, export_combined, export_bodies, flat_pattern):
    importlib.reload(_module)

COMMANDS = (export_bodies, flat_pattern)

# Buttons of commands that were merged away (removed if still registered)
LEGACY_CMD_IDS = ("ExportCombinedCmd",)

PANEL_ID = "UtilityPanel"
# Also shown under Export while editing a sheet metal flat pattern, where the
# Utilities panel is not available
PANEL_IDS = (PANEL_ID, "SheetmetalFlatPatternExportPanel")


def run(context):
    ui = None
    try:
        common._disable_ghosting()
        ui = adsk.core.Application.get().userInterface

        for cmd_id in LEGACY_CMD_IDS:
            _remove_command(ui, cmd_id)

        cmd_defs = []
        for cmd in COMMANDS:
            _remove_command(ui, cmd.CMD_ID)
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                cmd.CMD_ID, cmd.CMD_NAME, cmd.CMD_TOOLTIP,
                getattr(cmd, "CMD_RESOURCES", "")
            )
            h = cmd.CreatedHandler()
            cmd_def.commandCreated.add(h)
            common._handlers.append(h)
            cmd_defs.append(cmd_def)

        missing = []
        for panel_id in PANEL_IDS:
            panel = ui.allToolbarPanels.itemById(panel_id)
            if panel:
                for cmd_def in cmd_defs:
                    panel.controls.addCommand(cmd_def)
            else:
                missing.append(panel_id)
        if PANEL_ID in missing:
            ui.messageBox("ExportBodies: Utility panel not found.")
    except Exception:
        if ui:
            ui.messageBox("ExportBodies run() error:\n" + traceback.format_exc())


def stop(context):
    try:
        app_stop = adsk.core.Application.get()
        ui_stop = app_stop.userInterface if app_stop else None
        if ui_stop:
            for cmd in COMMANDS:
                _remove_command(ui_stop, cmd.CMD_ID)
            for cmd_id in LEGACY_CMD_IDS:
                _remove_command(ui_stop, cmd_id)
        common._handlers.clear()
    except Exception:
        pass


def _remove_command(ui_obj, cmd_id):
    for panel_id in PANEL_IDS:
        panel = ui_obj.allToolbarPanels.itemById(panel_id)
        if panel:
            ctrl = panel.controls.itemById(cmd_id)
            if ctrl:
                ctrl.deleteMe()
    cmd_def = ui_obj.commandDefinitions.itemById(cmd_id)
    if cmd_def:
        cmd_def.deleteMe()
