"""Batch Bodies Exporter - exports every body to its own file."""
import os
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting, _do_events, _safe_name
from ..lib.folders import _pick_output_folder
from ..lib.naming import _add_naming_inputs, _resolve_affixes
from ..lib.selection import (_add_selection_inputs, _add_body_type_inputs,
                             _ValidateHandler, _InputChangedHandler)
from ..lib.step_post import _add_split_bodies_input, _split_step_bodies

CMD_ID      = "ExportBodiesCmd"
CMD_NAME    = "Batch Bodies Exporter"
CMD_TOOLTIP = "Batch export bodies from selected components to a chosen format"

FORMATS = {
    "3MF  (.3mf)" : (".3mf",  "3mf"),
    "STEP (.step)": (".step", "step"),
    "STL  (.stl)" : (".stl",  "stl"),
    "OBJ  (.obj)" : (".obj",  "obj"),
    "IGES (.iges)": (".iges", "iges"),
    "SAT  (.sat)" : (".sat",  "sat"),
}


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


CreatedHandler = _CreatedHandler
