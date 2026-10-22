"""Selection and Body Types inputs for the Bodies Exporter."""


def _add_selection_inputs(inputs):
    """One selection box that takes components and bodies together. In the
    canvas a click usually picks a body; the browser picks either."""
    grp_sel = inputs.addGroupCommandInput("grp_sel", "Selection")
    sel_input = grp_sel.children.addSelectionInput(
        "components", "Components / Bodies",
        "Select components and/or bodies, then add them as a group"
    )
    sel_input.addSelectionFilter("Occurrences")
    sel_input.addSelectionFilter("RootComponents")
    sel_input.addSelectionFilter("SolidBodies")
    sel_input.addSelectionFilter("SurfaceBodies")
    # Selection may be empty: only the groups in the table are exported
    sel_input.setSelectionLimits(0, 0)

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
