"""Selection and Body Types inputs for the body exporters.

The selection box takes components and bodies together. With component
selection priority Fusion picks the component (or the top-level component, for
bodies directly in it - always the case inside a flat pattern) when you click in
the canvas, so a canvas pick on a component is swapped for the body under the
cursor; picks in the browser tree stay components.
"""
import adsk.core
import adsk.fusion

from .common import app, _as_component

# Canvas picks waiting to be swapped: [(pick key, body)], where the key is the
# occurrence's full path or ROOT_KEY. The swap happens in validateInputs, where
# the API allows changing the selection.
ROOT_KEY = "<top-level component>"
_pending_body_picks = []
_rebuilding = [False]


def _add_selection_inputs(inputs):
    grp_sel = inputs.addGroupCommandInput("grp_sel", "Selection")
    sel_input = grp_sel.children.addSelectionInput(
        "components", "Components / Bodies",
        "Click bodies in the canvas, or components in the browser"
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
    _pending_body_picks.clear()
    return grp_sel, sel_input


def _add_body_type_inputs(inputs):
    grp_types = inputs.addGroupCommandInput("grp_types", "Body Types")
    grp_types.children.addBoolValueInput("chk_solid",      "Solid bodies",      True, "", True)
    grp_types.children.addBoolValueInput("chk_surface",    "Surface bodies",    True, "", False)
    grp_types.children.addBoolValueInput("chk_sheetmetal", "Sheet metal bodies", True, "", False)
    grp_types.children.addBoolValueInput("chk_visible_only", "Export only visible bodies", True, "", True)


def _pick_key(entity):
    """Key for a picked component: occurrence path, ROOT_KEY, or None."""
    occ = adsk.fusion.Occurrence.cast(entity)
    if occ:
        return occ.fullPathName
    return ROOT_KEY if _as_component(entity) else None


def _body_at_point(key, point):
    """The body under a canvas pick point that belongs to the picked component:
    inside the occurrence (or its sub-components) for an occurrence key, or
    directly in the top-level component for ROOT_KEY."""
    # Browser picks carry no real pick point: Fusion reports exactly (0, 0, 0)
    if point is None or (point.x == 0.0 and point.y == 0.0 and point.z == 0.0):
        return None
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None
    hits = design.rootComponent.findBRepUsingPoint(
        point, adsk.fusion.BRepEntityTypes.BRepBodyEntityType, -1, True)
    for i in range(hits.count):
        body = adsk.fusion.BRepBody.cast(hits.item(i))
        if not body:
            continue
        ctx = body.assemblyContext
        if key == ROOT_KEY:
            if ctx is None:
                return body
        elif ctx and (ctx.fullPathName == key or ctx.fullPathName.startswith(key + "+")):
            return body
    return None


class _CanvasBodyPickHandler(adsk.core.SelectionEventHandler):
    """Command.select: remember canvas picks on components to swap for bodies."""
    def notify(self, args):
        try:
            if _rebuilding[0]:
                return
            active = getattr(args, "activeInput", None)
            if active is not None and active.id != "components":
                return
            sel = args.selection
            key = _pick_key(sel.entity)
            if key is None:
                return
            body = _body_at_point(key, sel.point)
            if body:
                _pending_body_picks.append((key, body))
        except Exception:
            pass


def _add_canvas_body_picks(cmd, handlers):
    h = _CanvasBodyPickHandler()
    cmd.select.add(h)
    handlers.append(h)


def _apply_canvas_body_picks(inputs):
    """Call from validateInputs: replace canvas-picked components with the
    bodies that were under the cursor."""
    if not _pending_body_picks or _rebuilding[0]:
        return
    picks = list(_pending_body_picks)
    _pending_body_picks.clear()
    sel_input = inputs.itemById("components")
    if not sel_input:
        return
    keys = {key for key, _ in picks}
    entities = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    keep = [e for e in entities if _pick_key(e) not in keys]
    _rebuilding[0] = True
    try:
        sel_input.clearSelection()
        for entity in keep:
            sel_input.addSelection(entity)
        for _, body in picks:
            sel_input.addSelection(body)
    finally:
        _rebuilding[0] = False
