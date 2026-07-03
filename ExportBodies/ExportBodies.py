
import adsk.core
import adsk.fusion
import os
import traceback

app       = None
ui        = None
_cmd_def  = None
_handlers = []

PANEL_ID = "UtilityPanel"

FORMATS = {
    "3MF  (.3mf)" : (".3mf",  "3mf"),
    "STEP (.step)": (".step", "step"),
    "STL  (.stl)" : (".stl",  "stl"),
    "OBJ  (.obj)" : (".obj",  "obj"),
    "IGES (.iges)": (".iges", "iges"),
    "SAT  (.sat)" : (".sat",  "sat"),
}


def run(context):
    global app, ui, _cmd_def
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        old = ui.commandDefinitions.itemById("ExportBodiesCmd")
        if old:
            old.deleteMe()
        _cmd_def = ui.commandDefinitions.addButtonDefinition(
            "ExportBodiesCmd",
            "Export Selected Bodies",
            "Export bodies from selected components to a chosen format",
            ""
        )
        h = _CreatedHandler()
        _cmd_def.commandCreated.add(h)
        _handlers.append(h)
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById("ExportBodiesCmd")
            if not ctrl:
                panel.controls.addCommand(_cmd_def)
        else:
            ui.messageBox("ExportBodies: Utility panel not found.")
        ui.messageBox("ExportBodies loaded.\nFind it in the Utility panel.")
    except Exception:
        if ui:
            ui.messageBox("ExportBodies run() error:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById("ExportBodiesCmd")
            if ctrl:
                ctrl.deleteMe()
        if _cmd_def:
            _cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CommandCreated
# ---------------------------------------------------------------------------
class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            sel_input = inputs.addSelectionInput(
                "components", "Components",
                "Select one or more components to export bodies from"
            )
            sel_input.addSelectionFilter("Occurrences")
            sel_input.setSelectionLimits(1, 0)

            inputs.addBoolValueInput("chk_solid",      "Solid bodies",       True, "", True)
            inputs.addBoolValueInput("chk_surface",    "Surface bodies",     True, "", False)
            inputs.addBoolValueInput("chk_sheetmetal", "Sheet metal bodies",  True, "", False)

            drop = inputs.addDropDownCommandInput(
                "format", "Export Format",
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for label in FORMATS:
                drop.listItems.add(label, label == "STEP (.step)")

            inputs.addBoolValueInput(
                "chk_compname", "Include component name in filename", True, "", True
            )

            inputs.addTextBoxCommandInput(
                "info", "",
                "<b>Note:</b> After clicking OK, a folder picker will open.<br>"
                "Each body is fully isolated (bodies + sub-components hidden) before export.",
                3, True
            )

            h_exec = _ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _ValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)

        except Exception:
            ui.messageBox("ExportBodies commandCreated error:\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# ValidateInputs
# ---------------------------------------------------------------------------
class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            solid  = inputs.itemById("chk_solid").value
            surf   = inputs.itemById("chk_surface").value
            sm     = inputs.itemById("chk_sheetmetal").value
            sel    = inputs.itemById("components")
            args.areInputsValid = (solid or surf or sm) and sel.selectionCount > 0
        except Exception:
            args.areInputsValid = False


# ---------------------------------------------------------------------------
# Visibility helpers
# ---------------------------------------------------------------------------
def _save_and_isolate(comp, target_body_idx):
    """
    Save visibility state of all bodies and occurrences in comp,
    then isolate: show only the target body, hide everything else.
    Returns a snapshot dict that _restore() understands.
    """
    snapshot = {"bodies": {}, "occs": {}}

    # Bodies
    bodies = comp.bRepBodies
    for i in range(bodies.count):
        body = bodies.item(i)
        snapshot["bodies"][i] = body.isLightBulbOn
        body.isLightBulbOn = (i == target_body_idx)

    # Occurrences (sub-components)
    occs = comp.occurrences
    for i in range(occs.count):
        occ = occs.item(i)
        snapshot["occs"][i] = occ.isLightBulbOn
        occ.isLightBulbOn = False

    return snapshot


def _restore(comp, snapshot):
    """Restore visibility from a snapshot produced by _save_and_isolate."""
    bodies = comp.bRepBodies
    for i, state in snapshot["bodies"].items():
        try:
            bodies.item(i).isLightBulbOn = state
        except Exception:
            pass

    occs = comp.occurrences
    for i, state in snapshot["occs"].items():
        try:
            occs.item(i).isLightBulbOn = state
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs     = args.command.commandInputs
            fmt_label  = inputs.itemById("format").selectedItem.name
            ext, fmt   = FORMATS[fmt_label]
            want_solid = inputs.itemById("chk_solid").value
            want_surf  = inputs.itemById("chk_surface").value
            want_sm    = inputs.itemById("chk_sheetmetal").value
            inc_comp   = inputs.itemById("chk_compname").value
            sel_input  = inputs.itemById("components")

            # Folder picker
            dlg = ui.createFolderDialog()
            dlg.title            = "Select Output Folder"
            dlg.initialDirectory = os.path.expanduser("~")
            if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
                return
            folder = dlg.folder
            if not os.path.isdir(folder):
                ui.messageBox("Selected folder does not exist:\n" + folder)
                return

            design     = app.activeProduct
            export_mgr = design.exportManager

            # Collect unique components
            seen_ids   = set()
            components = []
            for i in range(sel_input.selectionCount):
                entity = sel_input.selection(i).entity
                occ    = adsk.fusion.Occurrence.cast(entity)
                comp   = occ.component if occ else adsk.fusion.Component.cast(entity)
                if comp and comp.id not in seen_ids:
                    seen_ids.add(comp.id)
                    components.append(comp)

            if not components:
                ui.messageBox("No valid components found in selection.")
                return

            # Build export plan
            plan    = []
            skipped = []

            for comp in components:
                comp_safe = _safe_name(comp.name)
                bodies    = comp.bRepBodies
                for i in range(bodies.count):
                    body = bodies.item(i)
                    if body.isSheetMetal:
                        keep = want_sm
                        kind = "sheet metal"
                    elif body.isSolid:
                        keep = want_solid
                        kind = "solid"
                    else:
                        keep = want_surf
                        kind = "surface"

                    if not keep:
                        skipped.append("{}/{} ({})".format(comp.name, body.name, kind))
                        continue

                    body_safe = _safe_name(body.name)
                    base_name = "{}_{}".format(comp_safe, body_safe) if inc_comp else body_safe
                    filepath  = os.path.join(folder, base_name + ext)
                    plan.append((comp, i, body.name, filepath))

            if not plan:
                msg_parts = ["No bodies matched the selected filters."]
                if skipped:
                    msg_parts.append("Skipped:\n" + "\n".join("  " + s for s in skipped))
                ui.messageBox("\n\n".join(msg_parts))
                return

            # Single overwrite check
            conflicts = [e for e in plan if os.path.exists(e[3])]
            overwrite = True
            if conflicts:
                conflict_names = "\n".join("  " + os.path.basename(e[3]) for e in conflicts)
                answer = ui.messageBox(
                    "{} file(s) already exist:\n{}\n\nOverwrite all?".format(
                        len(conflicts), conflict_names),
                    "Overwrite?",
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                    adsk.core.MessageBoxIconTypes.QuestionIconType
                )
                overwrite = (answer == adsk.core.DialogResults.DialogYes)

            # Execute plan grouped by component
            exported, errors = [], []
            from itertools import groupby
            plan_sorted = sorted(plan, key=lambda e: e[0].id)

            for _, group in groupby(plan_sorted, key=lambda e: e[0].id):
                group_list = list(group)
                comp       = group_list[0][0]

                for _, body_idx, body_name, filepath in group_list:
                    # Overwrite check
                    if os.path.exists(filepath):
                        if not overwrite:
                            skipped.append("{} (not overwritten)".format(
                                os.path.basename(filepath)))
                            continue
                        try:
                            os.remove(filepath)
                        except Exception as exc:
                            errors.append("{}: could not remove: {}".format(
                                os.path.basename(filepath), exc))
                            continue

                    # Isolate: hide all sibling bodies + all sub-component occurrences
                    snapshot = _save_and_isolate(comp, body_idx)
                    try:
                        body = comp.bRepBodies.item(body_idx)
                        if fmt == "step":
                            opts = export_mgr.createSTEPExportOptions(filepath, comp)
                        elif fmt == "3mf":
                            opts = export_mgr.createC3MFExportOptions(body, filepath)
                        elif fmt == "stl":
                            opts = export_mgr.createSTLExportOptions(body, filepath)
                        elif fmt == "obj":
                            opts = export_mgr.createOBJExportOptions(body, filepath)
                        elif fmt == "iges":
                            opts = export_mgr.createIGESExportOptions(filepath, comp)
                        elif fmt == "sat":
                            opts = export_mgr.createSATExportOptions(filepath, comp)
                        else:
                            errors.append("{}: unknown format".format(body_name))
                            _restore(comp, snapshot)
                            continue

                        if export_mgr.execute(opts):
                            exported.append(os.path.basename(filepath))
                        else:
                            errors.append("{}: execute() returned False".format(body_name))
                    except Exception as exc:
                        errors.append("{}: {}".format(body_name, exc))
                    finally:
                        # Always restore visibility after each body
                        _restore(comp, snapshot)

            # Summary
            parts = []
            if exported:
                parts.append("Exported {} file(s) to:\n{}\n\n{}".format(
                    len(exported), folder,
                    "\n".join("  " + f for f in exported)))
            if skipped:
                parts.append("Skipped {}:\n{}".format(
                    len(skipped), "\n".join("  " + s for s in skipped)))
            if errors:
                parts.append("Errors:\n" + "\n".join("  " + e for e in errors))
            ui.messageBox("\n\n".join(parts) or "Nothing exported.")

        except Exception:
            ui.messageBox("ExportBodies execute error:\n" + traceback.format_exc())


def _safe_name(name):
    return "".join("_" if ch in r'\/:|*?"<>' else ch for ch in name).strip()
