"""
HoleToSlot v4.1

- Replaced deprecated sk.project() with sk.project2() throughout.
- Removed fallback manual centre_pt — raises clearly if projection fails.
- Constraint fix: addCoincident(centre_pt, con_line) + addTangent(proj_circle, line1/line2)
  instead of addMidPoint.
"""
import adsk.core, adsk.fusion, math, traceback

_app      = None
_ui       = None
_handlers = []

CMD_ID   = 'HoleToSlot_Cmd'
CMD_NAME = 'Hole to Slot'
CMD_DESC = 'Parametric slot cut perpendicular to a bend axis.'


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------
def _norm(v):
    l = math.sqrt(v.x**2+v.y**2+v.z**2)
    return adsk.core.Vector3D.create(v.x/l,v.y/l,v.z/l) if l>1e-12 else v
def _cross(a,b):
    return adsk.core.Vector3D.create(
        a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x)
def _dot(a,b): return a.x*b.x+a.y*b.y+a.z*b.z
def _dist3(a,b):
    return math.sqrt((a.x-b.x)**2+(a.y-b.y)**2+(a.z-b.z)**2)

def _inside_slot(px, py, cx, cy, su, sv, pu, pv, half_len, radius, tol=1e-4):
    dx, dy = px - cx, py - cy
    along  = dx*su + dy*sv
    perp   = dx*pu + dy*pv
    return (abs(along) <= half_len + radius + tol and
            abs(perp)  <= radius + tol)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_slot(root, hole_face, bend_edge, slot_length_cm, slot_length_expr):

    # 1. Hole geometry
    surf = hole_face.geometry
    if not isinstance(surf, adsk.core.Cylinder):
        raise ValueError('Selected face is not cylindrical.')
    hole_axis   = _norm(surf.axis)
    hole_origin = surf.origin
    radius      = surf.radius

    # 2. Slot elongation direction — derived directly from the bend edge
    edge_geom = bend_edge.geometry
    if not isinstance(edge_geom, adsk.core.Line3D):
        raise ValueError('Bend reference edge is not a straight line.')
    bend_axis = _norm(edge_geom.asInfiniteLine().direction)
    slot_dir  = _norm(_cross(hole_axis, bend_axis))

    # 3. Find the two flat faces adjacent to the hole (one per rim circle).
    #    Closest to hole_origin → sketch face. Farthest → extrude target.
    flat_faces = []
    for edge in hole_face.edges:
        if not isinstance(edge.geometry, adsk.core.Circle3D):
            continue
        for adj in edge.faces:
            if adj.entityToken == hole_face.entityToken:
                continue
            if not isinstance(adj.geometry, adsk.core.Plane):
                continue
            if abs(_dot(adj.geometry.normal, hole_axis)) > 0.85:
                flat_faces.append((adj, edge))

    if len(flat_faces) == 0:
        raise RuntimeError('No flat face adjacent to the hole.')

    def _face_dist(fe):
        c = fe[0].geometry.origin
        return _dist3(c, hole_origin)

    flat_faces.sort(key=_face_dist)
    sketch_face   = flat_faces[0][0]
    hole_edge     = flat_faces[0][1]
    opposite_face = flat_faces[-1][0] if len(flat_faces) >= 2 else None

    # 4. Create sketch — projections must happen before deferring compute
    sk = root.sketches.add(sketch_face)
    sk.name = 'Slot_'

    # 5. Project hole rim circle — linked so it updates with the hole
    projected = sk.project2([hole_edge], True)
    proj_circle = None
    for item in projected:
        c = adsk.fusion.SketchCircle.cast(item)
        if c is not None:
            c.isConstruction = True
            proj_circle = c
            break

    if proj_circle is None:
        raise RuntimeError(
            f'project2() returned {len(projected)} item(s), none were SketchCircle: '
            + ', '.join(type(item).__name__ for item in projected))

    centre_pt = proj_circle.centerSketchPoint

    # 6. Project the selected bend edge — linked
    bend_proj_line = None
    try:
        projected_bend = sk.project2([bend_edge], True)
        for item in projected_bend:
            sl = adsk.fusion.SketchLine.cast(item)
            if sl is not None:
                sl.isConstruction = True
                bend_proj_line = sl
                break
    except Exception:
        pass

    # Now defer recomputes while adding curves and constraints
    sk.isComputeDeferred = True

    # 7. Slot 2-D layout
    sxd = sk.xDirection
    syd = sk.yDirection
    su  = _dot(slot_dir, sxd)
    sv  = _dot(slot_dir, syd)
    sl_n = math.sqrt(su**2 + sv**2)
    if sl_n < 1e-10:
        raise ValueError('Slot direction is zero in sketch plane.')
    su /= sl_n;  sv /= sl_n
    pu, pv = -sv, su

    half_len = slot_length_cm / 2.0
    cx = centre_pt.geometry.x
    cy = centre_pt.geometry.y

    c1x, c1y = cx + su*half_len, cy + sv*half_len
    c2x, c2y = cx - su*half_len, cy - sv*half_len
    p1 = adsk.core.Point3D.create(c1x + pu*radius, c1y + pv*radius, 0)
    p2 = adsk.core.Point3D.create(c1x - pu*radius, c1y - pv*radius, 0)
    p3 = adsk.core.Point3D.create(c2x - pu*radius, c2y - pv*radius, 0)
    p4 = adsk.core.Point3D.create(c2x + pu*radius, c2y + pv*radius, 0)
    c1 = adsk.core.Point3D.create(c1x, c1y, 0)
    c2 = adsk.core.Point3D.create(c2x, c2y, 0)

    # 8. Draw slot profile curves
    curves   = sk.sketchCurves
    line1    = curves.sketchLines.addByTwoPoints(p1, p4)
    line2    = curves.sketchLines.addByTwoPoints(p2, p3)
    arc1     = curves.sketchArcs.addByCenterStartSweep(c1, p2, math.pi)
    arc2     = curves.sketchArcs.addByCenterStartSweep(c2, p4, math.pi)
    con_line = curves.sketchLines.addByTwoPoints(
        arc1.centerSketchPoint.geometry,
        arc2.centerSketchPoint.geometry)
    con_line.isConstruction = True

        # 9. Constraints
    con = sk.geometricConstraints
    constraint_errors = []

    def _try(label, fn):
        try:
            fn()
        except Exception as e:
            constraint_errors.append(f'{label}: {e}')

    # Profile closure
    _try('coincident line1.start = arc1.start', lambda: con.addCoincident(line1.startSketchPoint, arc1.startSketchPoint))
    _try('coincident line2.start = arc1.end',   lambda: con.addCoincident(line2.startSketchPoint, arc1.endSketchPoint))
    _try('coincident line1.end = arc2.end',     lambda: con.addCoincident(line1.endSketchPoint,   arc2.endSketchPoint))
    _try('coincident line2.end = arc2.start',   lambda: con.addCoincident(line2.endSketchPoint,   arc2.startSketchPoint))

    # Arc-to-line tangents
    _try('tangent arc1 line1', lambda: con.addTangent(arc1, line1))
    _try('tangent arc1 line2', lambda: con.addTangent(arc1, line2))
    _try('tangent arc2 line1', lambda: con.addTangent(arc2, line1))
    _try('tangent arc2 line2', lambda: con.addTangent(arc2, line2))

    # Equal arcs
    _try('equal arc1 arc2', lambda: con.addEqual(arc1, arc2))

    # Construction centre line endpoints on arc centres
    _try('coincident con_line.start = arc1.center', lambda: con.addCoincident(con_line.startSketchPoint, arc1.centerSketchPoint))
    _try('coincident con_line.end = arc2.center',   lambda: con.addCoincident(con_line.endSketchPoint,   arc2.centerSketchPoint))

    # Hole centre on construction centre line
    _try('midpoint centre_pt on con_line', lambda: con.addMidPoint(centre_pt, con_line))

    # Slot lines tangent to projected hole circle
    _try('tangent proj_circle line1', lambda: con.addTangent(proj_circle, line1))

    # Perpendicular to bend edge
    if bend_proj_line is not None:
        _try('perpendicular con_line bend', lambda: con.addPerpendicular(con_line, bend_proj_line))

    if constraint_errors:
        raise RuntimeError('Constraint errors:\n' + '\n'.join(constraint_errors))

    # 10. Dimensions
    dims     = sk.sketchDimensions
    text_len = adsk.core.Point3D.create(
        (c1x+c2x)/2 + pu*radius*2.5,
        (c1y+c2y)/2 + pv*radius*2.5, 0)
    len_dim = dims.addDistanceDimension(
        arc1.centerSketchPoint, arc2.centerSketchPoint,
        adsk.fusion.DimensionOrientations.AlignedDimensionOrientation,
        text_len, True)
    try:
        len_dim.parameter.expression = slot_length_expr
    except Exception:
        pass

    try:
        dims.addRadialDimension(
            arc1,
            adsk.core.Point3D.create(c1x + radius*2.0, c1y, 0),
            False)
    except Exception:
        pass

    sk.isComputeDeferred = False

    # 11. Select profiles inside the slot bounding box.
    #     Reject profiles larger than the theoretical slot area.
    slot_area_max = (2.0 * radius * slot_length_cm
                     + math.pi * radius ** 2) * 1.10

    slot_profiles = adsk.core.ObjectCollection.create()
    for prof in sk.profiles:
        try:
            props = prof.areaProperties()
            if props.area > slot_area_max:
                continue
            cen = props.centroid
            if _inside_slot(cen.x, cen.y, cx, cy,
                            su, sv, pu, pv, half_len, radius):
                slot_profiles.add(prof)
        except Exception:
            pass

    if slot_profiles.count == 0:
        raise RuntimeError(
            f'No profiles found inside slot boundary.\n'
            f'Sketch has {sk.profiles.count} profile(s).\n'
            'Check hole and bend edge selection.')

    # 12. Extrude cut — To Entity: opposite flat face of the hole.
    if opposite_face is None:
        raise RuntimeError(
            'Could not find the opposite flat face of the hole.\n'
            'Ensure the hole passes fully through the body.')

    extrudes = root.features.extrudeFeatures
    ext_in   = extrudes.createInput(
        slot_profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    to_entity = adsk.fusion.ToEntityExtentDefinition.create(opposite_face, False)
    ext_in.setOneSideExtent(
        to_entity,
        adsk.fusion.ExtentDirections.PositiveExtentDirection)

    return sk, extrudes.add(ext_in)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        try:
            cmd  = args.command
            inps = cmd.commandInputs
            hs = inps.addSelectionInput(
                'holeFace', 'Hole Faces',
                'Select the cylindrical WALL of one or more holes')
            hs.addSelectionFilter('CylindricalFaces')
            hs.setSelectionLimits(1, 0)
            be = inps.addSelectionInput(
                'bendEdge', 'Bend Reference Edge',
                'Select a straight edge aligned with the bend axis')
            be.addSelectionFilter('LinearEdges')
            be.setSelectionLimits(1, 1)
            inps.addValueInput(
                'slotLength', 'Slot Length (centre to centre)', 'mm',
                adsk.core.ValueInput.createByString('10 mm'))
            on_exec = ExecuteHandler()
            cmd.execute.add(on_exec); _handlers.append(on_exec)
            on_val = ValidateHandler()
            cmd.validateInputs.add(on_val); _handlers.append(on_val)
        except Exception:
            _ui.messageBox('CommandCreated:\n' + traceback.format_exc())

class ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        inps = args.inputs
        h = inps.itemById('holeFace')
        b = inps.itemById('bendEdge')
        l = inps.itemById('slotLength')
        args.areInputsValid = (
            h and h.selectionCount >= 1 and
            b and b.selectionCount == 1 and
            l and l.isValidExpression)

class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        try:
            inps          = args.command.commandInputs
            hole_sel      = inps.itemById('holeFace')
            bend_edge     = inps.itemById('bendEdge').selection(0).entity
            len_input     = inps.itemById('slotLength')
            slot_len_cm   = len_input.value
            slot_len_expr = len_input.expression
            design = adsk.fusion.Design.cast(_app.activeProduct)
            root   = design.rootComponent
            design.timeline.moveToEnd()
            errors = []
            for i in range(hole_sel.selectionCount):
                hole_face = hole_sel.selection(i).entity
                try:
                    build_slot(root, hole_face, bend_edge,
                               slot_len_cm, slot_len_expr)
                except Exception as e:
                    errors.append(f'Hole {i+1}: {e}')
            if errors:
                _ui.messageBox('Some slots failed:\n' + '\n'.join(errors))
        except Exception:
            _ui.messageBox('Execute failed:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui  = _app.userInterface
        cmd_defs = _ui.commandDefinitions
        ex = cmd_defs.itemById(CMD_ID)
        if ex: ex.deleteMe()
        cmd_def = cmd_defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)
        on_create = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_create)
        _handlers.append(on_create)
        for pid in ['SolidModifyPanel', 'SheetMetalModifyPanel']:
            p = _ui.allToolbarPanels.itemById(pid)
            if p: p.controls.addCommand(cmd_def)
    except Exception:
        if _ui: _ui.messageBox('run() failed:\n' + traceback.format_exc())

def stop(context):
    try:
        d = _ui.commandDefinitions.itemById(CMD_ID)
        if d: d.deleteMe()
        for pid in ['SolidModifyPanel', 'SheetMetalModifyPanel']:
            p = _ui.allToolbarPanels.itemById(pid)
            if p:
                c = p.controls.itemById(CMD_ID)
                if c: c.deleteMe()
        _handlers.clear()
    except Exception: pass
