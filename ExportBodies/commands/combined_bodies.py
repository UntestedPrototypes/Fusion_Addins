"""Combined Bodies Exporter - exports groups of bodies/components, each
group into one single file."""
import json
import os
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting, _do_events, _safe_name
from ..lib.folders import _pick_output_folder
from ..lib.naming import _add_naming_inputs, _resolve_affixes, _split_doc_name
from ..lib.selection import _add_selection_inputs, _add_body_type_inputs, _handle_sel_mode
from ..lib.step_post import _add_split_bodies_input, _split_step_bodies

CMD_ID      = "ExportCombinedCmd"
CMD_NAME    = "Combined Bodies Exporter"
CMD_TOOLTIP = "Export multiple bodies/components into one single STEP (or IGES/SAT) file"

# Formats that hold multiple bodies (and the assembly structure) in one file
COMBINED_FORMATS = {
    "STEP (.step)": (".step", "step"),
    "IGES (.iges)": (".iges", "iges"),
    "SAT  (.sat)" : (".sat",  "sat"),
}


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


CreatedHandler = _CombinedCreatedHandler
