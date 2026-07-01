
"""
HoleToSlot v3.8

Full constraint set (minimal, non-redundant, fully defines sketch):
  4 x coincident   (arc/line endpoint closure)
  4 x tangent      (arc1->line1, arc1->line2, arc2->line1, arc2->line2)
  1 x equal        (arc1 == arc2, same radius)
  2 x coincident   (con_line ends on arc centres)
  1 x midpoint     (slot centre = projected hole centre)
  1 x perpendicular (con_line perp to projected bend edge)
  1 x driving distance dim (slot length on con_line)
  1 x driven radial dim    (arc1 radius = hole radius, reference)
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
def build_slot(root, hole_face, bend_face, slot_length_cm, slot_length_expr):

    # 1. Hole geometry
    surf = hole_face.geometry
    if not isinstance(surf, adsk.core.Cylinder):
        raise ValueError('Selected face is not cylindrical.')
    hole_axis   = _norm(surf.axis)
    hole_origin = surf.origin
    radius      = surf.radius

    # 2. Slot elongation direction
    bsurf = bend_face.geometry
    if not isinstance(bsurf, adsk.core.Plane):
        raise ValueError('Bend reference face is not planar.')
    bend_normal = _norm(bsurf.normal)
    bend_axis   = _norm(_cross(bend_normal, hole_axis))
    slot_dir    = _norm(_cross(hole_axis, bend_axis))

    # 3. Adjacent flat face + circular opening edge
    sketch_face = None
    hole_edge   = None
    for edge in hole_face.edges:
        for adj in edge.faces:
            if adj.entityToken == hole_face.entityToken: continue
            if not isinstance(adj.geometry, adsk.core.Plane): continue
            if abs(_dot(adj.geometry.normal, hole_axis)) > 0.85:
                sketch_face = adj
                if isinstance(edge.geometry, adsk.core.Circle3D):
                    hole_edge = edge
                break
        if sketch_face: break
    if sketch_face is None:
        raise RuntimeError('No flat face adjacent to the hole.')

    # 4. Closest straight edge on bend face
    best_bend_edge = None
    best_bend_dist = math.inf
    for bedge in bend_face.edges:
        if not isinstance(bedge.geometry, adsk.core.Line3D): continue
        d = _dist3(bedge.pointOnEdge, hole_origin)
        if d < best_bend_dist:
            best_bend_dist = d
            best_bend_edge = bedge

    # 5. Create sketch
    sk = root.sketches.add(sketch_face)

    # 6. Project hole circle -> construction only (does NOT touch slot curves)
    proj_circle = None
    centre_pt   = None
    if hole_edge is not None:
        for item in sk.project(hole_edge):
            c = adsk.fusion.SketchCircle.cast(item)
            if c is not None:
                c.isConstruction = True
                proj_circle = c
                centre_pt   = c.centerSketchPoint
                break
    if centre_pt is None:
        sxd_, syd_, sod_ = sk.xDirection, sk.yDirection, sk.origin
        def _w2s(pt):
            d = adsk.core.Vector3D.create(pt.x-sod_.x, pt.y-sod_.y, pt.z-sod_.z)
            return adsk.core.Point3D.create(_dot(d,sxd_), _dot(d,syd_), 0)
        centre_pt = sk.sketchPoints.add(_w2s(hole_origin))

    # 7. Project single closest bend edge -> construction only
    bend_proj_line = None
    if best_bend_edge is not None:
        try:
            for item in sk.project(best_bend_edge):
                sl = adsk.fusion.SketchLine.cast(item)
                if sl is not None:
                    sl.isConstruction = True
                    bend_proj_line = sl
                    break
        except Exception:
            pass

    # 8. Slot 2-D layout
    sxd = sk.xDirection;  syd = sk.yDirection
    su = _dot(slot_dir, sxd);  sv = _dot(slot_dir, syd)
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

    # 9. Draw slot profile curves
    curves = sk.sketchCurves
    line1 = curves.sketchLines.addByTwoPoints(p1, p4)
    line2 = curves.sketchLines.addByTwoPoints(p2, p3)
    arc1  = curves.sketchArcs.addByCenterStartSweep(c1, p2, math.pi)
    arc2  = curves.sketchArcs.addByCenterStartSweep(c2, p4, math.pi)
    con_line = curves.sketchLines.addByTwoPoints(
        arc1.centerSketchPoint.geometry,
        arc2.centerSketchPoint.geometry)
    con_line.isConstruction = True

    # 10. Constraints  --  minimal, non-redundant, NO line-circle tangent
    con = sk.geometricConstraints

    # Profile closure
    con.addCoincident(line1.startSketchPoint, arc1.startSketchPoint)
    con.addCoincident(line2.startSketchPoint, arc1.endSketchPoint)
    con.addCoincident(line1.endSketchPoint,   arc2.endSketchPoint)
    con.addCoincident(line2.endSketchPoint,   arc2.startSketchPoint)

    # Arc-to-line tangents (fully defines slot shape; implies parallel+equal lines)
    con.addTangent(arc1, line1)
    con.addTangent(arc1, line2)
    con.addTangent(arc2, line1)
    con.addTangent(arc2, line2)

    # Equal arcs
    con.addEqual(arc1, arc2)

    # Construction centre line
    con.addCoincident(con_line.startSketchPoint, arc1.centerSketchPoint)
    con.addCoincident(con_line.endSketchPoint,   arc2.centerSketchPoint)

    # Slot centre = hole centre
    con.addMidPoint(centre_pt, con_line)

    # Slot axis perpendicular to bend edge
    if bend_proj_line is not None:
        try: con.addPerpendicular(con_line, bend_proj_line)
        except Exception: pass

    # 11. Dimensions
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

    # Driven radial dim (reference)
    try:
        dims.addRadialDimension(
            arc1,
            adsk.core.Point3D.create(c1x + radius*2.0, c1y, 0),
            False)
    except Exception:
        pass

    # 12. Select profiles inside the slot bounding box
    slot_profiles = adsk.core.ObjectCollection.create()
    for prof in sk.profiles:
        try:
            cen = prof.areaProperties().centroid
            if _inside_slot(cen.x, cen.y, cx, cy,
                            su, sv, pu, pv, half_len, radius):
                slot_profiles.add(prof)
        except Exception:
            pass

    if slot_profiles.count == 0:
        raise RuntimeError(
            f'No profiles found inside slot boundary.\n'
            f'Sketch has {sk.profiles.count} profile(s).\n'
            'Check hole and bend face selection.')

    # 13. Extrude cut: two-sided through-all (explicit, robust with ObjectCollection)
    extrudes = root.features.extrudeFeatures
    ext_in   = extrudes.createInput(
        slot_profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)

    through_all_1 = adsk.fusion.ThroughAllExtentDefinition.create()
    through_all_2 = adsk.fusion.ThroughAllExtentDefinition.create()
    ext_in.setTwoSidesExtent(through_all_1, through_all_2)

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
            bs = inps.addSelectionInput(
                'bendFace', 'Bend Reference Face',
                'Select a flat face aligned with the bend direction')
            bs.addSelectionFilter('PlanarFaces')
            bs.setSelectionLimits(1, 1)
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
        b = inps.itemById('bendFace')
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
            bend_face     = inps.itemById('bendFace').selection(0).entity
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
                    build_slot(root, hole_face, bend_face,
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
        _ui.messageBox(
            f"\'{CMD_NAME}\' loaded (v3.8).\n\n"
            'Solid > Modify > Hole to Slot\n\n'
            'Slot Length: 10 mm  /  SlotLen  /  SlotLen + 2 mm')
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
