"""Selection and Body Types inputs for the body exporters.

The selection box accepts bodies and components (pick bodies in the canvas,
components in the browser). The filter belongs to the dialog, so nothing in
Fusion's own settings changes and nothing needs restoring when it closes.
"""

_FILTERS = ("SolidBodies", "SurfaceBodies", "Occurrences", "RootComponents")


def _add_selection_inputs(inputs):
    grp_sel = inputs.addGroupCommandInput("grp_sel", "Selection")
    sel_input = grp_sel.children.addSelectionInput(
        "components", "Bodies / Components",
        "Select bodies and/or components"
    )
    for name in _FILTERS:
        sel_input.addSelectionFilter(name)
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
