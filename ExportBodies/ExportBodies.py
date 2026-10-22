
import adsk
import adsk.core
import adsk.fusion
import json
import os
import re
import time
import traceback

app       = None
ui        = None
_handlers = []

PANEL_ID = "UtilityPanel"
# Also shown under Export while editing a sheet metal flat pattern, where the
# Utilities panel is not available
PANEL_IDS = (PANEL_ID, "SheetmetalFlatPatternExportPanel")

CMD_BATCH_ID    = "ExportBodiesCmd"
CMD_COMBINED_ID = "ExportCombinedCmd"

FORMATS = {
    "3MF  (.3mf)" : (".3mf",  "3mf"),
    "STEP (.step)": (".step", "step"),
    "STL  (.stl)" : (".stl",  "stl"),
    "OBJ  (.obj)" : (".obj",  "obj"),
    "IGES (.iges)": (".iges", "iges"),
    "SAT  (.sat)" : (".sat",  "sat"),
}

# Formats that hold multiple bodies (and the assembly structure) in one file
COMBINED_FORMATS = {
    "STEP (.step)": (".step", "step"),
    "IGES (.iges)": (".iges", "iges"),
    "SAT  (.sat)" : (".sat",  "sat"),
}


def run(context):
    global app, ui
    try:
        _disable_ghosting()
        app = adsk.core.Application.get()
        ui  = app.userInterface

        _remove_command(ui, CMD_BATCH_ID)
        _remove_command(ui, CMD_COMBINED_ID)

        batch_def = ui.commandDefinitions.addButtonDefinition(
            CMD_BATCH_ID,
            "Batch Bodies Exporter",
            "Batch export bodies from selected components to a chosen format",
            ""
        )
        h = _CreatedHandler()
        batch_def.commandCreated.add(h)
        _handlers.append(h)

        combined_def = ui.commandDefinitions.addButtonDefinition(
            CMD_COMBINED_ID,
            "Combined Bodies Exporter",
            "Export multiple bodies/components into one single STEP (or IGES/SAT) file",
            ""
        )
        h = _CombinedCreatedHandler()
        combined_def.commandCreated.add(h)
        _handlers.append(h)

        missing = []
        for panel_id in PANEL_IDS:
            panel = ui.allToolbarPanels.itemById(panel_id)
            if panel:
                panel.controls.addCommand(batch_def)
                panel.controls.addCommand(combined_def)
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
            _remove_command(ui_stop, CMD_BATCH_ID)
            _remove_command(ui_stop, CMD_COMBINED_ID)
        _handlers.clear()
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


# ---------------------------------------------------------------------------
# CommandCreated
# ---------------------------------------------------------------------------
class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            _add_selection_inputs(inputs)
            _add_body_type_inputs(inputs)

            grp_export = inputs.addGroupCommandInput("grp_export", "Export Options")
            drop = grp_export.children.addDropDownCommandInput(
                "format", "Export Format",
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for label in FORMATS:
                drop.listItems.add(label, label == "STEP (.step)")
            grp_export.children.addBoolValueInput(
                "chk_compname", "Include component name in filename", True, "", False
            )
            _add_split_bodies_input(grp_export)

            _add_naming_inputs(inputs)

            h_exec = _ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _ValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)
            
            h_in = _InputChangedHandler()
            cmd.inputChanged.add(h_in)
            _handlers.append(h_in)

        except Exception:
            ui.messageBox("ExportBodies commandCreated error:\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# Shared command inputs (used by both the batch and combined exporters)
# ---------------------------------------------------------------------------
def _add_selection_inputs(inputs):
    grp_sel = inputs.addGroupCommandInput("grp_sel", "Selection")
    sel_mode = grp_sel.children.addDropDownCommandInput(
        "sel_mode", "Select By",
        adsk.core.DropDownStyles.TextListDropDownStyle
    )
    sel_mode.listItems.add("Components", True)
    sel_mode.listItems.add("Bodies", False)

    sel_input = grp_sel.children.addSelectionInput(
        "components", "Selection",
        "Select components or bodies to export"
    )
    sel_input.addSelectionFilter("Occurrences")
    sel_input.addSelectionFilter("RootComponents")
    sel_input.setSelectionLimits(1, 0)

    grp_sel.children.addBoolValueInput(
        "chk_recurse", "Include sub-component bodies", True, "", False
    )
    return grp_sel, sel_input


def _add_body_type_inputs(inputs):
    grp_types = inputs.addGroupCommandInput("grp_types", "Body Types")
    grp_types.children.addBoolValueInput("chk_solid",      "Solid bodies",      True, "", True)
    grp_types.children.addBoolValueInput("chk_surface",    "Surface bodies",    True, "", False)
    grp_types.children.addBoolValueInput("chk_sheetmetal", "Sheet metal bodies", True, "", False)
    grp_types.children.addBoolValueInput("chk_visible_only", "Export only visible bodies", True, "", True)


def _add_split_bodies_input(grp_export):
    chk_split = grp_export.children.addBoolValueInput(
        "chk_split_bodies", "Name every body in STEP (slicer friendly)", True, "", True
    )
    chk_split.tooltip = (
        "Puts each body into its own STEP part named after the body (Component_Body "
        "inside sub-components), so slicers like Bambu Studio show body names instead "
        "of Component-SOLID-1. STEP only."
    )


def _add_naming_inputs(inputs):
    grp_naming = inputs.addGroupCommandInput("grp_naming", "Naming Options")
    grp_naming.children.addStringValueInput("prefix", "Filename Prefix", "")
    grp_naming.children.addBoolValueInput("chk_filename_prefix", "Use document name as prefix", True, "", False)
    grp_naming.children.addStringValueInput("suffix", "Filename Suffix", "")
    grp_naming.children.addBoolValueInput("chk_milestone_suffix", "Use milestone as suffix (V#)", True, "", False)


def _split_doc_name():
    """Return (document name without version, version number or "")."""
    doc_name = app.activeDocument.name
    match = re.search(r'^(.*?)(?:\s+v(\d+))?$', doc_name, re.IGNORECASE)
    base_doc_name = match.group(1).strip() if match else doc_name
    version_num = match.group(2) if (match and match.group(2)) else ""
    return base_doc_name, version_num


def _resolve_affixes(inputs):
    """Build the filesystem-safe (prefix, suffix) from the Naming Options."""
    custom_prefix = inputs.itemById("prefix").value.strip()
    custom_suffix = inputs.itemById("suffix").value.strip()

    chk_filename_prefix = inputs.itemById("chk_filename_prefix").value
    chk_milestone_suffix = inputs.itemById("chk_milestone_suffix").value

    base_doc_name, version_num = _split_doc_name()

    combined_prefix = custom_prefix
    if chk_filename_prefix:
        if combined_prefix:
            combined_prefix = combined_prefix + "_" + base_doc_name
        else:
            combined_prefix = base_doc_name

    combined_suffix = custom_suffix
    if chk_milestone_suffix:
        ver_str = "V" + version_num if version_num else "V1"
        if combined_suffix:
            combined_suffix = combined_suffix + "_" + ver_str
        else:
            combined_suffix = ver_str

    prefix = _safe_name(combined_prefix) if combined_prefix else ""
    suffix = _safe_name(combined_suffix) if combined_suffix else ""
    return prefix, suffix


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
            
            has_bodies = False
            for i in range(sel.selectionCount):
                if adsk.fusion.BRepBody.cast(sel.selection(i).entity):
                    has_bodies = True
                    break
                    
            args.areInputsValid = (solid or surf or sm or has_bodies) and sel.selectionCount > 0
        except Exception:
            args.areInputsValid = False


# ---------------------------------------------------------------------------
# InputChanged
# ---------------------------------------------------------------------------
class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            _handle_sel_mode(args.input)
        except Exception:
            pass


def _handle_sel_mode(cmd_input):
    if cmd_input.id == "sel_mode":
        inputs = cmd_input.parentCommand.commandInputs
        sel_input = inputs.itemById("components")
        sel_input.clearSelectionFilter()
        sel_input.clearSelection()
        if cmd_input.selectedItem.name == "Bodies":
            sel_input.addSelectionFilter("SolidBodies")
            sel_input.addSelectionFilter("SurfaceBodies")
        else:
            sel_input.addSelectionFilter("Occurrences")
            sel_input.addSelectionFilter("RootComponents")


# ---------------------------------------------------------------------------
# Output folder picker - opens at the last used folder (shared by both
# exporters and kept between Fusion sessions), else the user's Documents
# ---------------------------------------------------------------------------
_SETTINGS_PATH = os.path.join(
    os.getenv("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"),
    "UntestedPrototypes", "ExportBodies.json"
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




# ---------------------------------------------------------------------------
# Visibility helpers
# ---------------------------------------------------------------------------
def _hide_all_occs_recursive(comp, path, snapshot_occs):
    """Recursively hide all occurrences at every depth.
    Uses a tuple path (comp.name, index, ...) as a stable key instead of
    entityToken, which is only valid for root-level proxies.
    """
    occs = comp.occurrences
    for i in range(occs.count):
        occ = occs.item(i)
        key = path + (i,)
        snapshot_occs[key] = occ.isLightBulbOn
        occ.isLightBulbOn = False
        if occ.component:
            _hide_all_occs_recursive(occ.component, key, snapshot_occs)


def _save_and_isolate(comp, target_body_idx):
    snapshot = {"bodies": {}, "occs": {}}
    bodies = comp.bRepBodies
    for i in range(bodies.count):
        body = bodies.item(i)
        snapshot["bodies"][i] = body.isLightBulbOn
        body.isLightBulbOn = (i == target_body_idx)
    _hide_all_occs_recursive(comp, (), snapshot["occs"])
    return snapshot


def _restore(comp, snapshot):
    bodies = comp.bRepBodies
    for i, state in snapshot["bodies"].items():
        try:
            bodies.item(i).isLightBulbOn = state
        except Exception:
            pass
    # Restore all occurrences at every depth using the same path-tuple keys
    def _restore_occs_recursive(c, path):
        occs = c.occurrences
        for i in range(occs.count):
            occ = occs.item(i)
            key = path + (i,)
            if key in snapshot["occs"]:
                try:
                    occ.isLightBulbOn = snapshot["occs"][key]
                except Exception:
                    pass
            if occ.component:
                _restore_occs_recursive(occ.component, key)
    _restore_occs_recursive(comp, ())


# ---------------------------------------------------------------------------
# Collect (comp, body_index) pairs - recurse only when recurse=True
# ---------------------------------------------------------------------------
def _collect_bodies(node, want_solid, want_surf, want_sm, visible_only, inc_comp,
                    prefix, suffix, folder, ext, plan, skipped,
                    seen_comp_ids, seen_body_tokens, recurse, is_top_level):
    comp = node.component if adsk.fusion.Occurrence.cast(node) else node
    if not comp:
        return
    if comp.id in seen_comp_ids:
        return
    seen_comp_ids.add(comp.id)

    comp_safe = _safe_name(comp.name)
    bodies    = node.bRepBodies

    for i in range(bodies.count):
        proxy_body = bodies.item(i)
        native_body = proxy_body.nativeObject if proxy_body.assemblyContext else proxy_body
        
        if native_body.entityToken in seen_body_tokens:
            continue
            
        if native_body.isSheetMetal:
            keep = want_sm
            kind = "sheet metal"
        elif native_body.isSolid:
            keep = want_solid
            kind = "solid"
        else:
            keep = want_surf
            kind = "surface"

        if not keep:
            skipped.append("{}/{} ({})".format(comp.name, native_body.name, kind))
            continue
            
        # Check proxy body visibility
        if visible_only and not proxy_body.isVisible:
            skipped.append("{}/{} (hidden)".format(comp.name, native_body.name))
            continue
            
        seen_body_tokens.add(native_body.entityToken)

        body_safe = _safe_name(native_body.name)
        base_name = "{}_{}".format(comp_safe, body_safe) if inc_comp else body_safe

        if prefix:
            base_name = prefix + "_" + base_name
        if suffix:
            base_name = base_name + "_" + suffix

        filepath = os.path.join(folder, base_name + ext)
        # Store native_body index
        # We need the index of native_body in comp.bRepBodies for _save_and_isolate
        native_idx = -1
        for j in range(comp.bRepBodies.count):
            if comp.bRepBodies.item(j).entityToken == native_body.entityToken:
                native_idx = j
                break
        
        if native_idx != -1:
            plan.append((comp, native_idx, native_body.name, filepath))

    if recurse:
        occs = node.childOccurrences if adsk.fusion.Occurrence.cast(node) else node.occurrences
        for j in range(occs.count):
            sub_occ = occs.item(j)
            if sub_occ:
                _collect_bodies(sub_occ, want_solid, want_surf, want_sm, visible_only, inc_comp,
                                prefix, suffix, folder, ext, plan, skipped,
                                seen_comp_ids, seen_body_tokens, recurse, is_top_level=False)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs     = args.command.commandInputs
            fmt_label  = inputs.itemById("format").selectedItem.name
            ext, fmt   = FORMATS[fmt_label]
            want_solid = inputs.itemById("chk_solid").value
            want_surf  = inputs.itemById("chk_surface").value
            want_sm    = inputs.itemById("chk_sheetmetal").value
            visible_only = inputs.itemById("chk_visible_only").value
            inc_comp   = inputs.itemById("chk_compname").value
            recurse    = inputs.itemById("chk_recurse").value
            split_bodies = inputs.itemById("chk_split_bodies").value
            sel_input  = inputs.itemById("components")

            prefix, suffix = _resolve_affixes(inputs)

            folder = _pick_output_folder()
            if not folder:
                return

            design     = app.activeProduct
            export_mgr = design.exportManager

            seen_sel_ids   = set()
            top_components = []
            selected_bodies = []
            
            for i in range(sel_input.selectionCount):
                entity = sel_input.selection(i).entity
                body = adsk.fusion.BRepBody.cast(entity)
                
                if body:
                    native_body = body.nativeObject if body.assemblyContext else body
                    comp = native_body.parentComponent
                    selected_bodies.append((comp, native_body))
                else:
                    occ    = adsk.fusion.Occurrence.cast(entity)
                    node   = occ if occ else adsk.fusion.Component.cast(entity)
                    comp   = occ.component if occ else node
                    if comp and comp.id not in seen_sel_ids:
                        seen_sel_ids.add(comp.id)
                        top_components.append(node)

            if not top_components and not selected_bodies:
                ui.messageBox("No valid components or bodies found in selection.")
                return

            plan          = []
            skipped       = []
            seen_comp_ids = set()
            seen_body_tokens = set()

            for comp, native_body in selected_bodies:
                if native_body.entityToken in seen_body_tokens:
                    continue
                seen_body_tokens.add(native_body.entityToken)
                
                # We do NOT check visibility here because the user explicitly selected this body

                body_idx = -1
                for j in range(comp.bRepBodies.count):
                    if comp.bRepBodies.item(j).entityToken == native_body.entityToken:
                        body_idx = j
                        break
                
                if body_idx == -1:
                    skipped.append("{}/{} (not found in native component)".format(comp.name, native_body.name))
                    continue

                body_safe = _safe_name(native_body.name)
                comp_safe = _safe_name(comp.name)
                base_name = "{}_{}".format(comp_safe, body_safe) if inc_comp else body_safe
                
                if prefix:
                    base_name = prefix + "_" + base_name
                if suffix:
                    base_name = base_name + "_" + suffix
                    
                filepath = os.path.join(folder, base_name + ext)
                plan.append((comp, body_idx, native_body.name, filepath))

            for node in top_components:
                _collect_bodies(node, want_solid, want_surf, want_sm, visible_only, inc_comp,
                                prefix, suffix, folder, ext, plan, skipped,
                                seen_comp_ids, seen_body_tokens, recurse, is_top_level=True)

            if not plan:
                msg_parts = ["No bodies matched the selected filters."]
                if skipped:
                    msg_parts.append("Skipped:\n" + "\n".join("  " + s for s in skipped))
                ui.messageBox("\n\n".join(msg_parts))
                return

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

            exported, errors = [], []
            cancelled = False
            total = len(plan)

            progress = None
            try:
                progress = ui.createProgressDialog()
                if progress:
                    progress.isCancelButtonShown = True
                    # show(title, message, min, max, delay)
                    # Passing delay=0 ensures the dialog appears immediately without delay
                    progress.show("Exporting Bodies", "Preparing export (%v of %m)...", 0, total, 0)
                    _do_events()
                    if progress.wasCancelled:
                        cancelled = True
            except Exception:
                progress = None

            try:
                if not cancelled:
                    for idx, (comp, body_idx, body_name, filepath) in enumerate(plan):
                        _do_events()
                        if progress and progress.wasCancelled:
                            progress.message = "Cancelling export... Stopping."
                            _do_events()
                            cancelled = True
                            break

                        filename = os.path.basename(filepath)
                        display_name = body_name if len(body_name) <= 30 else body_name[:27] + "..."
                        pct = int((idx / total) * 100)

                        if progress:
                            progress.progressValue = idx
                            progress.message = "Exporting body {} of {} ({}%):\n{}".format(
                                idx + 1, total, pct, display_name
                            )
                        _do_events()

                        if progress and progress.wasCancelled:
                            progress.message = "Cancelling export... Stopping."
                            _do_events()
                            cancelled = True
                            break

                        if os.path.exists(filepath):
                            if not overwrite:
                                skipped.append("{} (not overwritten)".format(filename))
                                if progress:
                                    progress.progressValue = idx + 1
                                    _do_events()
                                continue
                            try:
                                os.remove(filepath)
                            except Exception as exc:
                                errors.append("{}: could not remove: {}".format(filename, exc))
                                if progress:
                                    progress.progressValue = idx + 1
                                    _do_events()
                                continue

                        snapshot = _save_and_isolate(comp, body_idx)
                        _do_events()
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
                                continue

                            if export_mgr.execute(opts):
                                exported.append(filename)
                                if split_bodies and fmt == "step":
                                    try:
                                        _split_step_bodies(filepath, force=True)
                                    except Exception as exc:
                                        errors.append("{}: exported, but body naming failed: {}".format(
                                            filename, exc))
                            else:
                                errors.append("{}: execute() returned False".format(body_name))
                        except Exception as exc:
                            errors.append("{}: {}".format(body_name, exc))
                        finally:
                            _restore(comp, snapshot)
                            _do_events()

                        pct_done = int(((idx + 1) / total) * 100)
                        if progress:
                            progress.progressValue = idx + 1
                            progress.message = "Exported body {} of {} ({}%):\n{}".format(
                                idx + 1, total, pct_done, display_name
                            )
                        _do_events()

                        if progress and progress.wasCancelled:
                            progress.message = "Cancelling export... Stopping."
                            _do_events()
                            cancelled = True
                            break

            finally:
                if progress:
                    try:
                        progress.hide()
                    except Exception:
                        pass
                    progress = None
                _do_events()

            parts = []
            if cancelled:
                parts.append("Export cancelled by user.")
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


# ===========================================================================
# Combined Bodies Exporter - each export group of bodies/components into ONE
# file; several groups can be queued and exported in one go
# ===========================================================================

# Groups queued in the current command session:
#   [{"entities": [BRepBody | Occurrence | Component, ...], "name_id": str}]
_groups = []
_group_row_seq = [0]

# Groups and options are remembered per document as a design attribute
STATE_ATTR_GROUP = "UntestedPrototypes_ExportBodies"
STATE_ATTR_NAME  = "combined_state"

STATE_BOOL_IDS   = ("chk_recurse", "chk_solid", "chk_surface", "chk_sheetmetal",
                    "chk_visible_only", "chk_compname", "chk_split_bodies",
                    "chk_filename_prefix", "chk_milestone_suffix")
STATE_STRING_IDS = ("prefix", "suffix")


class _CombinedCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            _groups.clear()

            _, sel_input = _add_selection_inputs(inputs)
            # Selection may be empty once groups have been queued
            sel_input.setSelectionLimits(0, 0)

            grp_groups = inputs.addGroupCommandInput("grp_groups", "Export Groups")
            base_doc_name, _ = _split_doc_name()
            grp_groups.children.addStringValueInput("group_name", "Group / File Name", base_doc_name)

            table = grp_groups.children.addTableCommandInput("tbl_groups", "Groups", 2, "3:1")
            table.minimumVisibleRows = 3
            table.maximumVisibleRows = 8
            table.tooltip = "Each group is exported to its own combined file"
            btn_add = table.commandInputs.addBoolValueInput("btn_add_group", "Add Group", False, "", False)
            btn_add.tooltip = "Store the current selection as a new export group"
            table.addToolbarCommandInput(btn_add)
            btn_rem = table.commandInputs.addBoolValueInput("btn_remove_group", "Remove", False, "", False)
            btn_rem.tooltip = "Remove the selected group"
            table.addToolbarCommandInput(btn_rem)
            btn_clr = table.commandInputs.addBoolValueInput("btn_clear_groups", "Clear", False, "", False)
            btn_clr.tooltip = "Remove all groups"
            table.addToolbarCommandInput(btn_clr)

            grp_groups.children.addTextBoxCommandInput(
                "groups_hint", "",
                "Select objects, enter a name and click <b>Add Group</b>. "
                "Any selection left when you click OK is exported as one more group.",
                2, True
            )

            _add_body_type_inputs(inputs)

            grp_export = inputs.addGroupCommandInput("grp_export", "Export Options")
            drop = grp_export.children.addDropDownCommandInput(
                "format", "Export Format",
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for label in COMBINED_FORMATS:
                drop.listItems.add(label, label == "STEP (.step)")
            grp_export.children.addBoolValueInput(
                "chk_compname", "Include component name in filename", True, "", False
            )
            _add_split_bodies_input(grp_export)

            _add_naming_inputs(inputs)

            _load_combined_state(inputs)

            h_exec = _CombinedExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _CombinedValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)

            h_in = _CombinedInputChangedHandler()
            cmd.inputChanged.add(h_in)
            _handlers.append(h_in)

            h_destroy = _CombinedDestroyHandler()
            cmd.destroy.add(h_destroy)
            _handlers.append(h_destroy)

        except Exception:
            ui.messageBox("Combined exporter commandCreated error:\n" + traceback.format_exc())


class _CombinedValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            solid  = inputs.itemById("chk_solid").value
            surf   = inputs.itemById("chk_surface").value
            sm     = inputs.itemById("chk_sheetmetal").value
            sel    = inputs.itemById("components")

            entity_lists = [g["entities"] for g in _groups]
            entity_lists.append([sel.selection(i).entity for i in range(sel.selectionCount)])

            has_bodies = any(adsk.fusion.BRepBody.cast(e)
                             for ents in entity_lists for e in ents)
            has_items = any(entity_lists)

            args.areInputsValid = (solid or surf or sm or has_bodies) and has_items
        except Exception:
            args.areInputsValid = False


class _CombinedInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            cmd_input = args.input
            inputs = cmd_input.parentCommand.commandInputs
            if cmd_input.id == "sel_mode":
                _handle_sel_mode(cmd_input)
            elif cmd_input.id == "btn_add_group":
                _add_group_from_selection(inputs)
            elif cmd_input.id == "btn_remove_group":
                table = inputs.itemById("tbl_groups")
                row = table.selectedRow
                if 0 <= row < len(_groups):
                    table.deleteRow(row)
                    _groups.pop(row)
            elif cmd_input.id == "btn_clear_groups":
                table = inputs.itemById("tbl_groups")
                for row in range(len(_groups) - 1, -1, -1):
                    table.deleteRow(row)
                _groups.clear()
        except Exception:
            ui.messageBox("Combined exporter inputChanged error:\n" + traceback.format_exc())


class _CombinedDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _groups.clear()


def _add_group_from_selection(inputs):
    sel_input = inputs.itemById("components")
    if sel_input.selectionCount == 0:
        ui.messageBox("Select one or more components or bodies first, then click Add Group.")
        return

    entities = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    name_input = inputs.itemById("group_name")
    name = name_input.value.strip() or "Group {}".format(len(_groups) + 1)

    _add_group_row(inputs.itemById("tbl_groups"), name, entities)

    sel_input.clearSelection()
    name_input.value = "Group {}".format(len(_groups) + 1)


def _add_group_row(table, name, entities, missing=0):
    _group_row_seq[0] += 1
    seq = _group_row_seq[0]
    row = table.rowCount
    name_id = "group_name_{}".format(seq)

    count_text = "{} item{}".format(len(entities), "" if len(entities) == 1 else "s")
    if missing:
        count_text += " ({} missing)".format(missing)

    name_box = table.commandInputs.addStringValueInput(name_id, "Name", name)
    count_box = table.commandInputs.addTextBoxCommandInput(
        "group_count_{}".format(seq), "Items", count_text, 1, True
    )
    table.addCommandInput(name_box, row, 0)
    table.addCommandInput(count_box, row, 1)

    _groups.append({"entities": entities, "name_id": name_id})


# ---------------------------------------------------------------------------
# Remembered state (stored in the document, so it is kept when it is saved)
# ---------------------------------------------------------------------------
def _entity_ref(entity):
    """Describe a selected entity so it can be found again in a later session."""
    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        native_body = body.nativeObject if body.assemblyContext else body
        return {"type": "body",
                "path": body.assemblyContext.fullPathName if body.assemblyContext else "",
                "name": native_body.name,
                "token": body.entityToken}
    occ = adsk.fusion.Occurrence.cast(entity)
    if occ:
        return {"type": "occ", "path": occ.fullPathName, "token": occ.entityToken}
    if adsk.fusion.Component.cast(entity):
        return {"type": "root"}
    return None


def _resolve_entity_ref(design, ref, occ_by_path):
    """Find an entity from _entity_ref(): token first, then occurrence path/name."""
    kind = ref.get("type")
    if kind == "root":
        return design.rootComponent

    token = ref.get("token")
    if token:
        try:
            found = design.findEntityByToken(token)
            for ent in found or []:
                if kind == "body" and adsk.fusion.BRepBody.cast(ent):
                    return ent
                if kind == "occ" and adsk.fusion.Occurrence.cast(ent):
                    return ent
        except Exception:
            pass

    path = ref.get("path", "")
    if kind == "occ":
        return occ_by_path.get(path)
    if kind == "body":
        container = occ_by_path.get(path) if path else design.rootComponent
        if container:
            bodies = container.bRepBodies
            for i in range(bodies.count):
                if bodies.item(i).name == ref.get("name"):
                    return bodies.item(i)
    return None


def _read_state(design):
    try:
        attr = design.attributes.itemByName(STATE_ATTR_GROUP, STATE_ATTR_NAME)
        return json.loads(attr.value) if attr else {}
    except Exception:
        return {}


def _write_state(design, updates):
    state = _read_state(design)
    state.update(updates)
    design.attributes.add(STATE_ATTR_GROUP, STATE_ATTR_NAME, json.dumps(state))


def _save_combined_state(design, inputs, group_specs):
    groups = []
    for name, entities in group_specs:
        refs = [r for r in (_entity_ref(e) for e in entities) if r]
        if refs:
            groups.append({"name": name, "items": refs})
    _write_state(design, {
        "groups":  groups,
        "format":  inputs.itemById("format").selectedItem.name,
        "bools":   {i: inputs.itemById(i).value for i in STATE_BOOL_IDS},
        "strings": {i: inputs.itemById(i).value for i in STATE_STRING_IDS},
    })


def _load_combined_state(inputs):
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return
    state = _read_state(design)
    if not state:
        return

    for input_id, value in state.get("bools", {}).items():
        inp = inputs.itemById(input_id)
        if inp:
            inp.value = bool(value)
    for input_id, value in state.get("strings", {}).items():
        inp = inputs.itemById(input_id)
        if inp:
            inp.value = value
    fmt_label = state.get("format")
    if fmt_label in COMBINED_FORMATS:
        drop = inputs.itemById("format")
        for i in range(drop.listItems.count):
            item = drop.listItems.item(i)
            item.isSelected = (item.name == fmt_label)

    saved_groups = state.get("groups", [])
    if saved_groups:
        root = design.rootComponent
        all_occs = root.allOccurrences
        occ_by_path = {all_occs.item(i).fullPathName: all_occs.item(i)
                       for i in range(all_occs.count)}
        table = inputs.itemById("tbl_groups")
        for g in saved_groups:
            entities = []
            missing = 0
            for ref in g.get("items", []):
                ent = _resolve_entity_ref(design, ref, occ_by_path)
                if ent:
                    entities.append(ent)
                else:
                    missing += 1
            _add_group_row(table, g.get("name", "Group {}".format(len(_groups) + 1)),
                           entities, missing)
        inputs.itemById("group_name").value = "Group {}".format(len(_groups) + 1)


def _collect_combined(node, want_solid, want_surf, want_sm, visible_only, recurse,
                      keep, skipped, seen_keys):
    """Collect proxy bodies under node (Occurrence or root Component).
    Unlike the batch collector, repeated instances of the same component are
    kept - each occurrence is a separate placement in the combined file.
    """
    occ  = adsk.fusion.Occurrence.cast(node)
    comp = node.component if occ else node
    if not comp:
        return
    path = occ.fullPathName if occ else ""

    bodies = node.bRepBodies
    for i in range(bodies.count):
        proxy_body  = bodies.item(i)
        native_body = proxy_body.nativeObject if proxy_body.assemblyContext else proxy_body

        key = (path, native_body.entityToken)
        if key in seen_keys:
            continue

        if native_body.isSheetMetal:
            wanted = want_sm
            kind = "sheet metal"
        elif native_body.isSolid:
            wanted = want_solid
            kind = "solid"
        else:
            wanted = want_surf
            kind = "surface"

        if not wanted:
            skipped.append("{}/{} ({})".format(comp.name, native_body.name, kind))
            continue

        if visible_only and not proxy_body.isVisible:
            skipped.append("{}/{} (hidden)".format(comp.name, native_body.name))
            continue

        seen_keys.add(key)
        keep.append(proxy_body)

    if recurse:
        occs = node.childOccurrences if occ else node.occurrences
        for j in range(occs.count):
            sub_occ = occs.item(j)
            if sub_occ:
                _collect_combined(sub_occ, want_solid, want_surf, want_sm, visible_only,
                                  recurse, keep, skipped, seen_keys)


def _gather_group_bodies(entities, want_solid, want_surf, want_sm, visible_only, recurse):
    """Resolve a group's selected entities to proxy bodies.
    Returns (keep, skipped, comp_names).
    """
    keep       = []
    skipped    = []
    seen_keys  = set()
    comp_names = []

    for entity in entities:
        body = adsk.fusion.BRepBody.cast(entity)
        try:
            if body:
                # Explicitly selected bodies bypass the type/visibility filters
                native_body = body.nativeObject if body.assemblyContext else body
                path = body.assemblyContext.fullPathName if body.assemblyContext else ""
                key = (path, native_body.entityToken)
                if key not in seen_keys:
                    seen_keys.add(key)
                    keep.append(body)
                comp_name = native_body.parentComponent.name
            else:
                occ  = adsk.fusion.Occurrence.cast(entity)
                node = occ if occ else adsk.fusion.Component.cast(entity)
                if not node:
                    continue
                comp_name = occ.component.name if occ else node.name
                _collect_combined(node, want_solid, want_surf, want_sm, visible_only,
                                  recurse, keep, skipped, seen_keys)
        except Exception as exc:
            skipped.append("(invalid selection: {})".format(exc))
            continue

        if comp_name not in comp_names:
            comp_names.append(comp_name)

    return keep, skipped, comp_names


def _save_and_isolate_many(design, keep):
    """Hide every body and occurrence in the design except the bodies in keep
    (and the occurrence chains that lead to them). Returns a snapshot for
    _restore_many().
    """
    root = design.rootComponent
    snapshot = {"bodies": [], "occs": [], "folders": []}

    for c in range(design.allComponents.count):
        comp = design.allComponents.item(c)
        snapshot["folders"].append((comp, comp.isBodiesFolderLightBulbOn))
        bodies = comp.bRepBodies
        for i in range(bodies.count):
            body = bodies.item(i)
            snapshot["bodies"].append((body, body.isLightBulbOn))
            body.isLightBulbOn = False

    all_occs = root.allOccurrences
    for i in range(all_occs.count):
        occ = all_occs.item(i)
        snapshot["occs"].append((occ, occ.isLightBulbOn))
        occ.isLightBulbOn = False

    for proxy_body in keep:
        native_body = proxy_body.nativeObject if proxy_body.assemblyContext else proxy_body
        native_body.isLightBulbOn = True
        native_body.parentComponent.isBodiesFolderLightBulbOn = True
        occ = proxy_body.assemblyContext
        while occ:
            occ.isLightBulbOn = True
            occ = occ.assemblyContext

    return snapshot


def _restore_many(snapshot):
    for key in ("folders", "occs"):
        for obj, state in snapshot[key]:
            try:
                if key == "folders":
                    obj.isBodiesFolderLightBulbOn = state
                else:
                    obj.isLightBulbOn = state
            except Exception:
                pass
    for body, state in snapshot["bodies"]:
        try:
            body.isLightBulbOn = state
        except Exception:
            pass


class _CombinedExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs     = args.command.commandInputs
            fmt_label  = inputs.itemById("format").selectedItem.name
            ext, fmt   = COMBINED_FORMATS[fmt_label]
            want_solid = inputs.itemById("chk_solid").value
            want_surf  = inputs.itemById("chk_surface").value
            want_sm    = inputs.itemById("chk_sheetmetal").value
            visible_only = inputs.itemById("chk_visible_only").value
            inc_comp   = inputs.itemById("chk_compname").value
            recurse    = inputs.itemById("chk_recurse").value
            split_bodies = inputs.itemById("chk_split_bodies").value and fmt == "step"
            sel_input  = inputs.itemById("components")

            prefix, suffix = _resolve_affixes(inputs)

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("No active Fusion design.")
                return

            # Queued groups, plus whatever is still selected as a final group
            group_specs = []
            for g in _groups:
                name_input = inputs.itemById(g["name_id"])
                name = name_input.value.strip() if name_input else ""
                group_specs.append((name or "Group {}".format(len(group_specs) + 1), g["entities"]))
            if sel_input.selectionCount > 0:
                name = inputs.itemById("group_name").value.strip()
                group_specs.append((
                    name or "Group {}".format(len(group_specs) + 1),
                    [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
                ))

            try:
                _save_combined_state(design, inputs, group_specs)
            except Exception:
                pass  # remembering groups must never block the export

            # plan entries: (group name, keep bodies, filepath placeholder base)
            plan    = []
            skipped = []
            used_names = set()
            for group_name, entities in group_specs:
                keep, g_skipped, comp_names = _gather_group_bodies(
                    entities, want_solid, want_surf, want_sm, visible_only, recurse)
                skipped.extend("[{}] {}".format(group_name, s) for s in g_skipped)
                if not keep:
                    skipped.append("[{}] no bodies matched the filters".format(group_name))
                    continue

                base_name = _safe_name(group_name)
                if inc_comp and comp_names:
                    base_name = "_".join(_safe_name(n) for n in comp_names) + "_" + base_name
                if prefix:
                    base_name = prefix + "_" + base_name
                if suffix:
                    base_name = base_name + "_" + suffix

                # Keep filenames unique between groups
                unique = base_name
                n = 2
                while unique.lower() in used_names:
                    unique = "{}_{}".format(base_name, n)
                    n += 1
                used_names.add(unique.lower())

                plan.append((group_name, keep, unique))

            if not plan:
                msg_parts = ["No bodies matched the selected filters."]
                if skipped:
                    msg_parts.append("Skipped:\n" + "\n".join("  " + s for s in skipped))
                ui.messageBox("\n\n".join(msg_parts))
                return

            folder = _pick_output_folder(_read_state(design).get("folder", ""))
            if not folder:
                return
            try:
                _write_state(design, {"folder": folder})
            except Exception:
                pass

            plan = [(g, keep, os.path.join(folder, base + ext)) for g, keep, base in plan]

            conflicts = [e for e in plan if os.path.exists(e[2])]
            overwrite = True
            if conflicts:
                conflict_names = "\n".join("  " + os.path.basename(e[2]) for e in conflicts)
                answer = ui.messageBox(
                    "{} file(s) already exist:\n{}\n\nOverwrite all?".format(
                        len(conflicts), conflict_names),
                    "Overwrite?",
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                    adsk.core.MessageBoxIconTypes.QuestionIconType
                )
                overwrite = (answer == adsk.core.DialogResults.DialogYes)

            export_mgr = design.exportManager
            root       = design.rootComponent
            exported, errors = [], []
            cancelled = False
            total = len(plan)

            progress = None
            try:
                progress = ui.createProgressDialog()
                if progress:
                    progress.isCancelButtonShown = True
                    progress.show("Exporting Combined Files", "Preparing export...", 0, total, 0)
                    _do_events()
            except Exception:
                progress = None

            try:
                for idx, (group_name, keep, filepath) in enumerate(plan):
                    _do_events()
                    if progress and progress.wasCancelled:
                        cancelled = True
                        break

                    filename = os.path.basename(filepath)
                    if progress:
                        progress.progressValue = idx
                        progress.message = "Exporting group {} of {} ({} bodies):\n{}".format(
                            idx + 1, total, len(keep), filename)
                    _do_events()

                    if os.path.exists(filepath):
                        if not overwrite:
                            skipped.append("{} (not overwritten)".format(filename))
                            continue
                        try:
                            os.remove(filepath)
                        except Exception as exc:
                            errors.append("{}: could not remove: {}".format(filename, exc))
                            continue

                    snapshot = None
                    try:
                        snapshot = _save_and_isolate_many(design, keep)
                        _do_events()

                        if fmt == "step":
                            opts = export_mgr.createSTEPExportOptions(filepath, root)
                        elif fmt == "iges":
                            opts = export_mgr.createIGESExportOptions(filepath, root)
                        else:
                            opts = export_mgr.createSATExportOptions(filepath, root)

                        if export_mgr.execute(opts):
                            exported.append((group_name, filename, keep))
                            if split_bodies:
                                if progress:
                                    progress.message = "Naming bodies in {}...".format(filename)
                                _do_events()
                                try:
                                    _split_step_bodies(filepath)
                                except Exception as exc:
                                    errors.append("{}: exported, but body naming failed: {}".format(
                                        filename, exc))
                        else:
                            errors.append("{}: execute() returned False".format(filename))
                    except Exception as exc:
                        errors.append("{}: {}".format(filename, exc))
                    finally:
                        if snapshot:
                            _restore_many(snapshot)
                        _do_events()

                    if progress:
                        progress.progressValue = idx + 1
                    _do_events()
            finally:
                if progress:
                    try:
                        progress.hide()
                    except Exception:
                        pass
                    progress = None
                _do_events()

            parts = []
            if cancelled:
                parts.append("Export cancelled by user.")
            if exported:
                lines = []
                for group_name, filename, keep in exported:
                    lines.append("  {}  ({} bodies)".format(filename, len(keep)))
                parts.append("Exported {} file(s) to:\n{}\n\n{}".format(
                    len(exported), folder, "\n".join(lines)))
            if skipped:
                parts.append("Skipped {}:\n{}".format(
                    len(skipped), "\n".join("  " + s for s in skipped)))
            if errors:
                parts.append("Errors:\n" + "\n".join("  " + e for e in errors))
            ui.messageBox("\n\n".join(parts) or "Nothing exported.")

        except Exception:
            ui.messageBox("Combined exporter execute error:\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
# STEP post-processing: one product per body so slicers show body names
# ---------------------------------------------------------------------------
# Fusion writes every component as a PRODUCT whose shape holds all of that
# component's bodies. Slicers such as Bambu Studio name parts after the
# PRODUCT and number the rest ("Robotanics_Layer1-SOLID-1"), ignoring the
# body names Fusion puts on the solids. So every body of a component that has
# several bodies (or also has sub-components) is moved into its own child
# PRODUCT with an identity placement. Geometry is left untouched.
#
# Chain in the file:
#   solid -> ADVANCED_BREP_SHAPE_REPRESENTATION (items)
#         -> SHAPE_REPRESENTATION_RELATIONSHIP -> component SHAPE_REPRESENTATION
#         -> SHAPE_DEFINITION_REPRESENTATION -> PRODUCT_DEFINITION_SHAPE
#         -> PRODUCT_DEFINITION -> PRODUCT_DEFINITION_FORMATION -> PRODUCT
_STR  = r"(?:'(?:[^']|'')*'|\$)"   # a STEP string or $
_SEP  = r"\s*,\s*"
_STEP_SOLID_RE = re.compile(
    r"^#(\d+)\s*=\s*(?:MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS|SHELL_BASED_SURFACE_MODEL|FACETED_BREP)"
    r"\s*\(\s*'((?:[^']|'')*)'", re.M)
_STEP_ITEMS_REP_RE = re.compile(
    r"^#(\d+)\s*=\s*(\w*SHAPE_REPRESENTATION)\s*\(\s*" + _STR + _SEP
    + r"\(([^)]*)\)" + _SEP + r"#(\d+)\s*\)\s*;", re.M)
_STEP_SRR_RE = re.compile(
    r"^#(\d+)\s*=\s*SHAPE_REPRESENTATION_RELATIONSHIP\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)" + _SEP + r"#(\d+)\s*\)\s*;", re.M)
_STEP_SDR_RE = re.compile(
    r"^#\d+\s*=\s*SHAPE_DEFINITION_REPRESENTATION\s*\(\s*#(\d+)" + _SEP + r"#(\d+)\s*\)", re.M)
_STEP_PDS_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION_SHAPE\s*\(\s*" + _STR + _SEP + _STR + _SEP + r"#(\d+)", re.M)
_STEP_PD_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)" + _SEP + r"#(\d+)", re.M)
_STEP_PDF_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION_FORMATION\w*\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)", re.M)
_STEP_PRODUCT_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT\s*\(\s*" + _STR + _SEP + r"'((?:[^']|'')*)'" + _SEP + _STR + _SEP
    + r"(\([^)]*\))", re.M)
_STEP_NAUO_RE = re.compile(
    r"^#\d+\s*=\s*NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*" + _STR + _SEP + _STR + _SEP + _STR
    + _SEP + r"#(\d+)" + _SEP + r"#(\d+)", re.M)
_STEP_PLACEMENT_RE = re.compile(r"^#(\d+)\s*=\s*AXIS2_PLACEMENT_3D\s*\(", re.M)
_STEP_ID_RE = re.compile(r"^#(\d+)\s*=", re.M)


def _split_step_bodies(filepath, force=False):
    """Give every body of a multi-body component its own PRODUCT, named
    "<Component>_<Body>" (just "<Body>" for bodies of the top-level component).
    With force, single-body components are split too (used for one-body files,
    so the part shows the body name instead of the component name).
    Names are copied as already-encoded STEP strings, so non-ASCII names stay
    intact. Returns the number of bodies split out.
    """
    # latin-1 maps every byte 1:1, so untouched content round-trips unchanged
    with open(filepath, "r", encoding="latin-1", newline="") as f:
        text = f.read()

    solid_name = {m.group(1): m.group(2) for m in _STEP_SOLID_RE.finditer(text)}
    if not solid_name or (len(solid_name) < 2 and not force):
        return 0

    reps = {}            # rep id -> (match, keyword, [item ids], context id)
    for m in _STEP_ITEMS_REP_RE.finditer(text):
        reps[m.group(1)] = (m, m.group(2), re.findall(r"#(\d+)", m.group(3)), m.group(4))
    srr_by_child = {}    # brep rep id -> (match, component shape rep id)
    for m in _STEP_SRR_RE.finditer(text):
        srr_by_child[m.group(3)] = (m, m.group(2))
    rep_pds   = {m.group(2): m.group(1) for m in _STEP_SDR_RE.finditer(text)}
    pds_pd    = {m.group(1): m.group(2) for m in _STEP_PDS_RE.finditer(text)}
    pd_info   = {m.group(1): (m.group(2), m.group(3)) for m in _STEP_PD_RE.finditer(text)}
    pdf_prod  = {m.group(1): m.group(2) for m in _STEP_PDF_RE.finditer(text)}
    prod_info = {m.group(1): (m.group(2), m.group(3)) for m in _STEP_PRODUCT_RE.finditer(text)}
    placements = {m.group(1) for m in _STEP_PLACEMENT_RE.finditer(text)}
    nauo = [(m.group(1), m.group(2)) for m in _STEP_NAUO_RE.finditer(text)]
    child_pds  = {c for _, c in nauo}
    parent_pds = {p for p, _ in nauo}

    # Group brep reps by the component shape rep they belong to
    by_comp = {}         # component shape rep id -> [brep rep id]
    for rep_id, (_, _, items, _) in reps.items():
        if rep_id in srr_by_child and any(i in solid_name for i in items):
            by_comp.setdefault(srr_by_child[rep_id][1], []).append(rep_id)

    edits    = []        # (start, end, replacement) on the original text
    new_recs = []
    next_id  = [max(int(i) for i in _STEP_ID_RE.findall(text)) + 1]

    def new(record):
        rid = next_id[0]
        next_id[0] += 1
        new_recs.append("#{}={};".format(rid, record))
        return "#{}".format(rid)

    split = 0
    for comp_rep, brep_reps in by_comp.items():
        pd = pds_pd.get(rep_pds.get(comp_rep))
        if pd not in pd_info or comp_rep not in reps:
            continue
        pdf, pd_ctx = pd_info[pd]
        prod = pdf_prod.get(pdf)
        if prod not in prod_info:
            continue
        comp_name, prod_ctx = prod_info[prod]
        is_root = pd not in child_pds

        solids = [s for r in brep_reps for s in reps[r][2] if s in solid_name]
        if len(solids) < 2 and pd not in parent_pds and not force:
            continue          # single body, no sub-components: already named well

        comp_items = reps[comp_rep][2]
        origin = next((i for i in comp_items if i in placements), None)
        if origin is None:
            continue

        for brep_rep in brep_reps:
            m_rep, keyword, items, ctx = reps[brep_rep]
            rep_solids = [i for i in items if i in solid_name]
            for solid in rep_solids:
                body = solid_name[solid]
                name = body if is_root else ("{}_{}".format(comp_name, body) if body else comp_name)
                p     = new("PRODUCT('{0}','{0}',$,{1})".format(name, prod_ctx))
                p_pdf = new("PRODUCT_DEFINITION_FORMATION('',$,{})".format(p))
                p_pd  = new("PRODUCT_DEFINITION('{0}','{0}',{1},#{2})".format(name, p_pdf, pd_ctx))
                p_pds = new("PRODUCT_DEFINITION_SHAPE('',$,{})".format(p_pd))
                p_sr  = new("SHAPE_REPRESENTATION('',(#{}),#{})".format(origin, ctx))
                new("SHAPE_DEFINITION_REPRESENTATION({},{})".format(p_pds, p_sr))
                p_br  = new("{}('',(#{}),#{})".format(keyword, solid, ctx))
                new("SHAPE_REPRESENTATION_RELATIONSHIP('SRR','None',{},{})".format(p_sr, p_br))
                occ   = new("NEXT_ASSEMBLY_USAGE_OCCURRENCE('{0}','{0}','',#{1},{2},$)".format(
                    name, pd, p_pd))
                o_pds = new("PRODUCT_DEFINITION_SHAPE($,$,{})".format(occ))
                xf    = new("ITEM_DEFINED_TRANSFORMATION($,$,#{0},#{0})".format(origin))
                rr    = new("(REPRESENTATION_RELATIONSHIP($,$,{},#{})"
                            "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({})"
                            "SHAPE_REPRESENTATION_RELATIONSHIP())".format(p_sr, comp_rep, xf))
                new("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({},{})".format(rr, o_pds))
                split += 1

            # The component's own brep rep no longer holds these solids. A rep
            # cannot be empty, so drop it (and its link) when nothing is left.
            remaining = [i for i in items if i not in solid_name]
            if remaining:
                start, end = m_rep.span(3)
                edits.append((start, end, ",".join("#" + i for i in remaining)))
            else:
                edits.append((m_rep.start(), m_rep.end(), ""))
                m_srr = srr_by_child[brep_rep][0]
                edits.append((m_srr.start(), m_srr.end(), ""))

    if not split:
        return 0

    # Apply edits back to front, then add the new records before DATA's ENDSEC
    for start, end, repl in sorted(edits, reverse=True):
        text = text[:start] + repl + text[end:]
    data_end = text.rfind("ENDSEC;")
    text = text[:data_end] + "\n".join(new_recs) + "\n" + text[data_end:]

    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    os.replace(tmp, filepath)
    return split


def _safe_name(name):
    bad = set('/ \\:|*?"<>'.replace(' ', ''))
    return ''.join('_' if ch in bad else ch for ch in name).strip()
