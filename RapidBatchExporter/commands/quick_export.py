"""Quick Bodies Exporter - export the current selection straight away,
without groups: Separate (one file per body) or Combined (one file)."""
import os
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting
from ..lib.doc_state import _read_state, _write_state
from ..lib.export_runner import SEPARATE, COMBINED, MODES, MODE_FORMATS, DEFAULT_FORMAT, _run_export
from ..lib.naming import _add_naming_inputs, _split_doc_name
from ..lib.selection import (_add_selection_inputs, _add_body_type_inputs,
                             _add_canvas_body_picks, _apply_canvas_body_picks)
from ..lib.step_post import _add_split_bodies_input
from ..lib.flat_pattern_export import _add_dxf_inputs, DXF_BOOL_IDS

CMD_ID      = "QuickExportBodiesCmd"
CMD_NAME    = "Quick Bodies Exporter"
CMD_TOOLTIP = ("Export the selected components/bodies right away - one file per body "
               "or combined into one file")
CMD_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "resources", "quick_bodies")

# Options remembered per document (under their own key, apart from the
# Bodies Exporter's groups)
STATE_KEY        = "quick"
STATE_BOOL_IDS   = ("chk_recurse", "chk_solid", "chk_surface", "chk_sheetmetal",
                    "chk_visible_only", "chk_compname", "chk_split_bodies",
                    "chk_filename_prefix", "chk_milestone_suffix") + DXF_BOOL_IDS
STATE_STRING_IDS = ("prefix", "suffix")


def _selected(dropdown, fallback):
    item = dropdown.selectedItem if dropdown else None
    return item.name if item else fallback


def _fill_formats(dropdown, mode, keep=None):
    allowed = MODE_FORMATS[mode]
    chosen = keep if keep in allowed else DEFAULT_FORMAT
    dropdown.listItems.clear()
    for label in allowed:
        dropdown.listItems.add(label, label == chosen)


def _apply_mode(inputs, mode):
    fmt = inputs.itemById("quick_format")
    _fill_formats(fmt, mode, _selected(fmt, DEFAULT_FORMAT))
    inputs.itemById("quick_name").isVisible = (mode == COMBINED)
    _update_dxf_visibility(inputs)


def _update_dxf_visibility(inputs):
    grp = inputs.itemById("dxf_opts")
    if grp:
        grp.isVisible = (_selected(inputs.itemById("quick_format"), DEFAULT_FORMAT) == "DXF")


# ---------------------------------------------------------------------------
class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            _, sel_input = _add_selection_inputs(inputs)
            sel_input.setSelectionLimits(1, 0)

            _add_body_type_inputs(inputs)

            grp_export = inputs.addGroupCommandInput("grp_export", "Export Options")
            ec = grp_export.children
            mode = ec.addDropDownCommandInput(
                "quick_mode", "Output", adsk.core.DropDownStyles.TextListDropDownStyle)
            for m in MODES:
                mode.listItems.add(m, m == SEPARATE)
            mode.tooltip = "Separate = one file per body, Combined = one file for everything selected"
            fmt = ec.addDropDownCommandInput(
                "quick_format", "Export Format", adsk.core.DropDownStyles.TextListDropDownStyle)
            _fill_formats(fmt, SEPARATE)
            base_doc_name, _ = _split_doc_name()
            ec.addStringValueInput("quick_name", "File Name", base_doc_name)
            ec.addBoolValueInput(
                "chk_compname", "Include component name in filename", True, "", False
            )
            _add_split_bodies_input(grp_export)

            _add_dxf_inputs(inputs)

            _add_naming_inputs(inputs)

            _load_state(inputs)
            _apply_mode(inputs, _selected(inputs.itemById("quick_mode"), SEPARATE))

            h_exec = _ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _ValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)

            h_in = _InputChangedHandler()
            cmd.inputChanged.add(h_in)
            _handlers.append(h_in)

            # Canvas clicks select bodies, browser clicks select components
            _add_canvas_body_picks(cmd, _handlers)

        except Exception:
            ui.messageBox("Quick Bodies Exporter commandCreated error:\n" + traceback.format_exc())


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            _apply_canvas_body_picks(inputs)
            solid  = inputs.itemById("chk_solid").value
            surf   = inputs.itemById("chk_surface").value
            sm     = inputs.itemById("chk_sheetmetal").value
            sel    = inputs.itemById("components")
            has_bodies = any(adsk.fusion.BRepBody.cast(sel.selection(i).entity)
                             for i in range(sel.selectionCount))
            args.areInputsValid = sel.selectionCount > 0 and (solid or surf or sm or has_bodies)
        except Exception:
            args.areInputsValid = False


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.input.parentCommand.commandInputs
            if args.input.id == "quick_mode":
                _apply_mode(inputs, _selected(args.input, SEPARATE))
            elif args.input.id == "quick_format":
                _update_dxf_visibility(inputs)
        except Exception:
            pass


# ---------------------------------------------------------------------------
def _save_state(design, inputs):
    _write_state(design, {STATE_KEY: {
        "mode":    _selected(inputs.itemById("quick_mode"), SEPARATE),
        "format":  _selected(inputs.itemById("quick_format"), DEFAULT_FORMAT),
        "bools":   {i: inputs.itemById(i).value for i in STATE_BOOL_IDS},
        "strings": {i: inputs.itemById(i).value for i in STATE_STRING_IDS},
    }})


def _load_state(inputs):
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return
    state = _read_state(design).get(STATE_KEY)
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
    mode = state.get("mode", SEPARATE)
    if mode in MODES:
        mode_box = inputs.itemById("quick_mode")
        for i in range(mode_box.listItems.count):
            item = mode_box.listItems.item(i)
            item.isSelected = (item.name == mode)
        _fill_formats(inputs.itemById("quick_format"), mode, state.get("format"))


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs = args.command.commandInputs

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("No active Fusion design.")
                return

            # Read the selection first: writing the remembered options to the
            # document makes Fusion clear the command's selection
            sel  = inputs.itemById("components")
            entities = [sel.selection(i).entity for i in range(sel.selectionCount)]
            mode = _selected(inputs.itemById("quick_mode"), SEPARATE)
            fmt  = _selected(inputs.itemById("quick_format"), DEFAULT_FORMAT)
            if fmt not in MODE_FORMATS[mode]:
                fmt = DEFAULT_FORMAT
            if mode == COMBINED:
                name = inputs.itemById("quick_name").value.strip() or _split_doc_name()[0] or "Combined"
            else:
                name = "Selection"   # only used as the label in the summary

            try:
                _save_state(design, inputs)
            except Exception:
                pass  # remembering options must never block the export

            _run_export(inputs, design, [(name, mode, fmt, False, entities)])
        except Exception:
            ui.messageBox("Quick Bodies Exporter execute error:\n" + traceback.format_exc())
