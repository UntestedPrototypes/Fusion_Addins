"""Bodies Exporter - export groups of components/bodies. Each group is
exported either as Separate files (one per body) or Combined into one file,
with its own format."""
import os
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting
from ..lib.doc_state import _entity_ref, _resolve_entity_ref, _read_state, _write_state
from ..lib.export_runner import (SEPARATE, COMBINED, MODES, FORMAT_INFO, MODE_FORMATS,
                                 DEFAULT_FORMAT, _run_export)
from ..lib.naming import _add_naming_inputs, _split_doc_name
from ..lib.selection import _add_selection_inputs, _add_body_type_inputs
from ..lib.step_post import _add_split_bodies_input
from ..lib.flat_pattern_export import _add_dxf_inputs, DXF_BOOL_IDS

CMD_ID      = "ExportBodiesCmd"
CMD_NAME    = "Bodies Exporter"
CMD_TOOLTIP = ("Export groups of components/bodies - each group as separate files "
               "(one per body) or combined into one file")
CMD_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "resources", "bodies_exporter")

STATE_BOOL_IDS   = ("chk_recurse", "chk_solid", "chk_surface", "chk_sheetmetal",
                    "chk_visible_only", "chk_compname", "chk_split_bodies",
                    "chk_filename_prefix", "chk_milestone_suffix") + DXF_BOOL_IDS
STATE_STRING_IDS = ("prefix", "suffix")

# Groups in the open dialog: [{"entities": [...], "seq": int}]. Row inputs
# are found by id: group_<field>_<seq>.
_groups = []
_group_row_seq = [0]

# Modify: seq of the group being changed, and items waiting to be loaded into
# the selection (done in validateInputs, where the API allows it)
_editing = [None]
_pending_load = []


def _row_id(field, seq):
    return "group_{}_{}".format(field, seq)


def _fill_formats(dropdown, mode, keep=None):
    """Refill a format dropdown for mode, keeping keep if it is still allowed."""
    allowed = MODE_FORMATS[mode]
    chosen = keep if keep in allowed else DEFAULT_FORMAT
    dropdown.listItems.clear()
    for label in allowed:
        dropdown.listItems.add(label, label == chosen)


def _fill_modes(dropdown, mode):
    for m in MODES:
        dropdown.listItems.add(m, m == mode)


def _selected(dropdown, fallback):
    item = dropdown.selectedItem if dropdown else None
    return item.name if item else fallback


# ---------------------------------------------------------------------------
# CommandCreated
# ---------------------------------------------------------------------------
class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            _groups.clear()
            _editing[0] = None
            del _pending_load[:]

            _add_selection_inputs(inputs)

            grp_groups = inputs.addGroupCommandInput("grp_groups", "Export Groups")
            gc = grp_groups.children
            base_doc_name, _ = _split_doc_name()
            gc.addStringValueInput("group_name", "Group / File Name", base_doc_name)
            new_mode = gc.addDropDownCommandInput(
                "new_mode", "New Group Output", adsk.core.DropDownStyles.TextListDropDownStyle)
            _fill_modes(new_mode, COMBINED)
            new_fmt = gc.addDropDownCommandInput(
                "new_format", "New Group Format", adsk.core.DropDownStyles.TextListDropDownStyle)
            _fill_formats(new_fmt, COMBINED)

            table = gc.addTableCommandInput("tbl_groups", "Groups", 6, "1:4:3:2:1:3")
            table.minimumVisibleRows = 3
            table.maximumVisibleRows = 8
            table.tooltip = ("Each row is exported on its own: Separate = one file per body, "
                             "Combined = one file for the whole group")
            btn_add = table.commandInputs.addBoolValueInput("btn_add_group", "Add Group", False, "", False)
            btn_add.tooltip = "Store the current selection as a new export group"
            table.addToolbarCommandInput(btn_add)
            btn_mod = table.commandInputs.addBoolValueInput("btn_modify_group", "Modify", False, "", False)
            btn_mod.tooltip = "Load the selected group's items into the selection to change them"
            table.addToolbarCommandInput(btn_mod)
            btn_upd = table.commandInputs.addBoolValueInput("btn_update_group", "Update", False, "", False)
            btn_upd.tooltip = "Replace the items of the group being modified with the current selection"
            table.addToolbarCommandInput(btn_upd)
            btn_rem = table.commandInputs.addBoolValueInput("btn_remove_group", "Remove", False, "", False)
            btn_rem.tooltip = "Remove the selected group"
            table.addToolbarCommandInput(btn_rem)
            btn_clr = table.commandInputs.addBoolValueInput("btn_clear_groups", "Clear", False, "", False)
            btn_clr.tooltip = "Remove all groups"
            table.addToolbarCommandInput(btn_clr)

            edit_status = gc.addTextBoxCommandInput("edit_status", "", "", 1, True)
            edit_status.isVisible = False

            gc.addTextBoxCommandInput(
                "groups_hint", "",
                "Select components and/or bodies, enter a name and click <b>Add Group</b>. "
                "To change a group, select its row, click <b>Modify</b>, adjust the selection "
                "and click <b>Update</b>. Only ticked groups are exported (first column). "
                "<b>Separate</b> = one file per body (tick Subfolder for a folder named after "
                "the group), <b>Combined</b> = one file.",
                4, True
            )

            _add_body_type_inputs(inputs)

            grp_export = inputs.addGroupCommandInput("grp_export", "Export Options")
            grp_export.children.addBoolValueInput(
                "chk_compname", "Include component name in filename", True, "", False
            )
            _add_split_bodies_input(grp_export)

            _add_dxf_inputs(inputs)

            _add_naming_inputs(inputs)

            _load_state(inputs)
            _update_dxf_visibility(inputs)

            h_exec = _ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _ValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)

            h_in = _InputChangedHandler()
            cmd.inputChanged.add(h_in)
            _handlers.append(h_in)

            h_destroy = _DestroyHandler()
            cmd.destroy.add(h_destroy)
            _handlers.append(h_destroy)

        except Exception:
            ui.messageBox("Bodies Exporter commandCreated error:\n" + traceback.format_exc())


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            _apply_pending_load(inputs)
            solid  = inputs.itemById("chk_solid").value
            surf   = inputs.itemById("chk_surface").value
            sm     = inputs.itemById("chk_sheetmetal").value

            enabled = [g for g in _groups if _group_enabled(inputs, g)]
            has_items  = any(g["entities"] for g in enabled)
            has_bodies = any(adsk.fusion.BRepBody.cast(e)
                             for g in enabled for e in g["entities"])

            args.areInputsValid = has_items and (solid or surf or sm or has_bodies)
        except Exception:
            args.areInputsValid = False


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            cmd_input = args.input
            inputs = cmd_input.parentCommand.commandInputs
            input_id = cmd_input.id

            if input_id == "new_mode":
                new_fmt = inputs.itemById("new_format")
                _fill_formats(new_fmt, _selected(cmd_input, COMBINED),
                              _selected(new_fmt, DEFAULT_FORMAT))
            elif input_id.startswith("group_mode_"):
                seq = int(input_id.rsplit("_", 1)[1])
                mode = _selected(cmd_input, COMBINED)
                fmt = inputs.itemById(_row_id("fmt", seq))
                _fill_formats(fmt, mode, _selected(fmt, DEFAULT_FORMAT))
                sub = inputs.itemById(_row_id("sub", seq))
                if sub:
                    sub.isEnabled = (mode == SEPARATE)
            elif input_id == "btn_add_group":
                _add_group_from_selection(inputs)
            elif input_id == "btn_modify_group":
                _start_modify(inputs)
            elif input_id == "btn_update_group":
                _update_group(inputs)
            elif input_id == "btn_remove_group":
                table = inputs.itemById("tbl_groups")
                row = table.selectedRow
                if 0 <= row < len(_groups):
                    if _groups[row]["seq"] == _editing[0]:
                        _set_editing(inputs, None)
                    table.deleteRow(row)
                    _groups.pop(row)
            elif input_id == "btn_clear_groups":
                table = inputs.itemById("tbl_groups")
                for row in range(len(_groups) - 1, -1, -1):
                    table.deleteRow(row)
                _groups.clear()
                _set_editing(inputs, None)

            _update_dxf_visibility(inputs)
        except Exception:
            ui.messageBox("Bodies Exporter inputChanged error:\n" + traceback.format_exc())


def _update_dxf_visibility(inputs):
    """Show DXF Options only while a group (or the new-group format) uses DXF."""
    formats = [_selected(inputs.itemById("new_format"), DEFAULT_FORMAT)]
    formats += [_selected(inputs.itemById(_row_id("fmt", g["seq"])), DEFAULT_FORMAT)
                for g in _groups]
    grp = inputs.itemById("dxf_opts")
    if grp:
        grp.isVisible = "DXF" in formats


class _DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        _groups.clear()
        _editing[0] = None
        del _pending_load[:]


# ---------------------------------------------------------------------------
# Group table
# ---------------------------------------------------------------------------
def _add_group_from_selection(inputs):
    sel_input = inputs.itemById("components")
    if sel_input.selectionCount == 0:
        ui.messageBox("Select one or more components or bodies first, then click Add Group.")
        return

    entities = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    name_input = inputs.itemById("group_name")
    name = name_input.value.strip() or "Group {}".format(len(_groups) + 1)
    mode = _selected(inputs.itemById("new_mode"), COMBINED)
    fmt  = _selected(inputs.itemById("new_format"), DEFAULT_FORMAT)

    _add_group_row(inputs.itemById("tbl_groups"), name, entities, mode, fmt, False)

    sel_input.clearSelection()
    name_input.value = "Group {}".format(len(_groups) + 1)


def _group_by_seq(seq):
    return next((g for g in _groups if g["seq"] == seq), None)


def _group_name(inputs, g):
    name_box = inputs.itemById(_row_id("name", g["seq"]))
    return name_box.value.strip() if name_box else ""


def _set_editing(inputs, seq):
    """Remember which group is being modified and show it above the hint."""
    _editing[0] = seq
    status = inputs.itemById("edit_status")
    if not status:
        return
    g = _group_by_seq(seq) if seq is not None else None
    if g:
        status.formattedText = ("Modifying <b>{}</b> - change the selection, then click "
                                "<b>Update</b>.".format(_group_name(inputs, g) or "group"))
        status.isVisible = True
    else:
        status.isVisible = False


def _start_modify(inputs):
    """Modify: load the selected row's items into the selection box."""
    table = inputs.itemById("tbl_groups")
    row = table.selectedRow
    if not (0 <= row < len(_groups)):
        ui.messageBox("Select a group in the table first, then click Modify.")
        return
    g = _groups[row]
    del _pending_load[:]
    _pending_load.append(list(g["entities"]))
    _set_editing(inputs, g["seq"])


def _apply_pending_load(inputs):
    """Call from validateInputs: put a Modify'd group's items into the selection."""
    if not _pending_load:
        return
    entities = _pending_load.pop()
    del _pending_load[:]
    sel_input = inputs.itemById("components")
    if not sel_input:
        return
    sel_input.clearSelection()
    for entity in entities:
        sel_input.addSelection(entity)


def _update_group(inputs):
    """Update: replace the modified group's items with the current selection."""
    g = _group_by_seq(_editing[0]) if _editing[0] is not None else None
    if not g:
        ui.messageBox("Select a group, click Modify, change the selection, then click Update.")
        return
    sel_input = inputs.itemById("components")
    if sel_input.selectionCount == 0:
        ui.messageBox("The selection is empty - select the group's components and/or bodies "
                      "before clicking Update (or use Remove to delete the group).")
        return
    g["entities"] = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    count_box = inputs.itemById(_row_id("count", g["seq"]))
    if count_box:
        count_box.text = _describe_items(g["entities"])
    sel_input.clearSelection()
    _set_editing(inputs, None)


def _describe_items(entities, missing=0):
    n_bodies = sum(1 for e in entities if adsk.fusion.BRepBody.cast(e))
    n_comps  = len(entities) - n_bodies
    parts = []
    if n_comps:
        parts.append("{} comp{}".format(n_comps, "" if n_comps == 1 else "s"))
    if n_bodies:
        parts.append("{} bod{}".format(n_bodies, "y" if n_bodies == 1 else "ies"))
    text = ", ".join(parts) or "empty"
    if missing:
        text += " ({} missing)".format(missing)
    return text


def _group_enabled(inputs, g):
    on_box = inputs.itemById(_row_id("on", g["seq"]))
    return bool(on_box.value) if on_box else True


def _add_group_row(table, name, entities, mode, fmt, subfolder, missing=0, enabled=True):
    _group_row_seq[0] += 1
    seq = _group_row_seq[0]
    row = table.rowCount
    tci = table.commandInputs

    on_box = tci.addBoolValueInput(_row_id("on", seq), "Export", True, "", bool(enabled))
    on_box.tooltip = "Export this group (untick to keep it in the list but skip it)"
    name_box = tci.addStringValueInput(_row_id("name", seq), "Name", name)
    mode_box = tci.addDropDownCommandInput(
        _row_id("mode", seq), "Output", adsk.core.DropDownStyles.TextListDropDownStyle)
    _fill_modes(mode_box, mode if mode in MODES else COMBINED)
    fmt_box = tci.addDropDownCommandInput(
        _row_id("fmt", seq), "Format", adsk.core.DropDownStyles.TextListDropDownStyle)
    _fill_formats(fmt_box, _selected(mode_box, COMBINED), fmt)
    sub_box = tci.addBoolValueInput(_row_id("sub", seq), "Subfolder", True, "", bool(subfolder))
    sub_box.tooltip = "Separate output only: put this group's files in a subfolder named after the group"
    sub_box.isEnabled = (_selected(mode_box, COMBINED) == SEPARATE)
    count_box = tci.addTextBoxCommandInput(
        _row_id("count", seq), "Items", _describe_items(entities, missing), 1, True)

    for col, box in enumerate((on_box, name_box, mode_box, fmt_box, sub_box, count_box)):
        table.addCommandInput(box, row, col)

    _groups.append({"entities": entities, "seq": seq})


def _group_specs(inputs):
    """Read the table: [(enabled, name, mode, format label, subfolder, entities)]."""
    specs = []
    for g in _groups:
        seq = g["seq"]
        name_box = inputs.itemById(_row_id("name", seq))
        name = name_box.value.strip() if name_box else ""
        mode = _selected(inputs.itemById(_row_id("mode", seq)), COMBINED)
        fmt  = _selected(inputs.itemById(_row_id("fmt", seq)), DEFAULT_FORMAT)
        if fmt not in MODE_FORMATS[mode]:
            fmt = DEFAULT_FORMAT
        sub_box = inputs.itemById(_row_id("sub", seq))
        subfolder = bool(sub_box.value) if (sub_box and mode == SEPARATE) else False
        specs.append((_group_enabled(inputs, g), name or "Group {}".format(len(specs) + 1),
                      mode, fmt, subfolder, g["entities"]))
    return specs


# ---------------------------------------------------------------------------
# Remembered state
# ---------------------------------------------------------------------------
def _save_state(design, inputs, specs):
    groups = []
    for enabled, name, mode, fmt, subfolder, entities in specs:
        refs = [r for r in (_entity_ref(e) for e in entities) if r]
        if refs:
            groups.append({"enabled": enabled, "name": name, "mode": mode, "format": fmt,
                           "subfolder": subfolder, "items": refs})
    _write_state(design, {
        "groups":     groups,
        "new_mode":   _selected(inputs.itemById("new_mode"), COMBINED),
        "new_format": _selected(inputs.itemById("new_format"), DEFAULT_FORMAT),
        "bools":      {i: inputs.itemById(i).value for i in STATE_BOOL_IDS},
        "strings":    {i: inputs.itemById(i).value for i in STATE_STRING_IDS},
    })


def _legacy_format(label):
    """Old Combined exporter stored labels like "STEP (.step)"."""
    word = (label or "").split(" ")[0].upper()
    return word if word in FORMAT_INFO else DEFAULT_FORMAT


def _load_state(inputs):
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

    legacy_fmt = _legacy_format(state.get("format"))
    new_mode = state.get("new_mode", COMBINED)
    if new_mode in MODES:
        mode_box = inputs.itemById("new_mode")
        for i in range(mode_box.listItems.count):
            item = mode_box.listItems.item(i)
            item.isSelected = (item.name == new_mode)
        _fill_formats(inputs.itemById("new_format"), new_mode,
                      state.get("new_format", legacy_fmt))

    saved_groups = state.get("groups", [])
    if saved_groups:
        root = design.rootComponent
        all_occs = getattr(root, "allOccurrences", None)   # none in a flat pattern
        occ_by_path = {all_occs.item(i).fullPathName: all_occs.item(i)
                       for i in range(all_occs.count if all_occs else 0)}
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
            # Groups saved by the old Combined exporter have no mode/format
            _add_group_row(table,
                           g.get("name", "Group {}".format(len(_groups) + 1)),
                           entities,
                           g.get("mode", COMBINED),
                           g.get("format", legacy_fmt),
                           g.get("subfolder", False),
                           missing,
                           g.get("enabled", True))
        inputs.itemById("group_name").value = "Group {}".format(len(_groups) + 1)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs = args.command.commandInputs

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("No active Fusion design.")
                return

            specs = _group_specs(inputs)
            try:
                _save_state(design, inputs, specs)
            except Exception:
                pass  # remembering groups must never block the export

            # Only groups whose Export box is ticked
            _run_export(inputs, design, [sp[1:] for sp in specs if sp[0]])
        except Exception:
            ui.messageBox("Bodies Exporter execute error:\n" + traceback.format_exc())
