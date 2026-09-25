
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
            "Batch Bodies Exporter",
            "Batch export bodies from selected components to a chosen format",
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

            grp_types = inputs.addGroupCommandInput("grp_types", "Body Types")
            grp_types.children.addBoolValueInput("chk_solid",      "Solid bodies",      True, "", True)
            grp_types.children.addBoolValueInput("chk_surface",    "Surface bodies",    True, "", False)
            grp_types.children.addBoolValueInput("chk_sheetmetal", "Sheet metal bodies", True, "", False)
            grp_types.children.addBoolValueInput("chk_visible_only", "Export only visible bodies", True, "", True)

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

            grp_naming = inputs.addGroupCommandInput("grp_naming", "Naming Options")
            grp_naming.children.addStringValueInput("prefix", "Filename Prefix", "")
            grp_naming.children.addBoolValueInput("chk_filename_prefix", "Use document name as prefix", True, "", False)
            grp_naming.children.addStringValueInput("suffix", "Filename Suffix", "")
            grp_naming.children.addBoolValueInput("chk_milestone_suffix", "Use milestone as suffix (V#)", True, "", False)

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
            cmd_input = args.input
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
            inputs     = args.command.commandInputs
            fmt_label  = inputs.itemById("format").selectedItem.name
            ext, fmt   = FORMATS[fmt_label]
            want_solid = inputs.itemById("chk_solid").value
            want_surf  = inputs.itemById("chk_surface").value
            want_sm    = inputs.itemById("chk_sheetmetal").value
            visible_only = inputs.itemById("chk_visible_only").value
            inc_comp   = inputs.itemById("chk_compname").value
            recurse    = inputs.itemById("chk_recurse").value
            sel_input  = inputs.itemById("components")

            custom_prefix = inputs.itemById("prefix").value.strip()
            custom_suffix = inputs.itemById("suffix").value.strip()
            
            chk_filename_prefix = inputs.itemById("chk_filename_prefix").value
            chk_milestone_suffix = inputs.itemById("chk_milestone_suffix").value

            doc_name = app.activeDocument.name
            import re
            match = re.search(r'^(.*?)(?:\s+v(\d+))?$', doc_name, re.IGNORECASE)
            base_doc_name = match.group(1).strip() if match else doc_name
            version_num = match.group(2) if (match and match.group(2)) else ""

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

            dlg = ui.createFolderDialog()
            dlg.title            = "Select Output Folder"
            dlg.initialDirectory = os.path.join(os.path.expanduser("~"), "Documents")
            if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
                return
            folder = dlg.folder
            if not os.path.isdir(folder):
                ui.messageBox("Selected folder does not exist:\n" + folder)
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

            for comp, body_idx, body_name, filepath in plan:
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
                    _restore(comp, snapshot)

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
    bad = set('/ \\:|*?"<>'.replace(' ', ''))
    return ''.join('_' if ch in bad else ch for ch in name).strip()
