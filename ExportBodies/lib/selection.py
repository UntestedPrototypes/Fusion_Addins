"""Selection and Body Types inputs, with their shared validate and
input-changed handlers (used by the batch and combined body exporters)."""
import adsk.core
import adsk.fusion


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
