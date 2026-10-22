"""Sheet-metal flat pattern export to DXF, shared by the Bodies Exporter,
the Quick Bodies Exporter and the Quick Flat Pattern Exporter."""
import os
import stat

import adsk.core
import adsk.fusion

from .common import _as_component

DXF_BOOL_IDS = ("bend_lines", "ext_lines", "spline_poly")


def _add_dxf_inputs(inputs):
    grp_dxf = inputs.addGroupCommandInput("dxf_opts", "DXF Options (flat patterns)")
    grp_dxf.children.addBoolValueInput("bend_lines",  "Include bend lines",           True, "", False)
    grp_dxf.children.addBoolValueInput("ext_lines",   "Include extent lines",         True, "", False)
    grp_dxf.children.addBoolValueInput("spline_poly", "Convert splines to polylines", True, "", False)
    return grp_dxf


def _dxf_options(inputs):
    """(bend_lines, ext_lines, spline_poly) from the DXF inputs, else defaults."""
    defaults = {"bend_lines": False, "ext_lines": False, "spline_poly": False}
    values = []
    for input_id in DXF_BOOL_IDS:
        inp = inputs.itemById(input_id)
        values.append(bool(inp.value) if inp else defaults[input_id])
    return tuple(values)


def _collect_components_recursive(root_comp, seen):
    result = []
    if root_comp.id in seen:
        return result
    seen.add(root_comp.id)
    result.append(root_comp)
    for occ in (getattr(root_comp, "occurrences", None) or []):
        child_comp = occ.component
        result.extend(_collect_components_recursive(child_comp, seen))
    return result


def _sheet_metal_components(entities, recurse):
    """Components with sheet-metal bodies for the selected entities: selected
    components (and their sub-components when recurse), and the components of
    selected sheet-metal bodies. Returns (components, skipped)."""
    seen       = set()
    top_level  = []
    skipped    = []
    for entity in entities:
        try:
            body = adsk.fusion.BRepBody.cast(entity)
            if body:
                native_body = body.nativeObject if body.assemblyContext else body
                if not native_body.isSheetMetal:
                    skipped.append("{} (not a sheet-metal body)".format(native_body.name))
                    continue
                comp = native_body.parentComponent
            else:
                occ = adsk.fusion.Occurrence.cast(entity)
                comp = occ.component if occ else _as_component(entity)
            if comp and comp.id not in seen:
                seen.add(comp.id)
                top_level.append((comp, bool(body)))
        except Exception as exc:
            skipped.append("(invalid selection: {})".format(exc))

    components = []
    added_ids  = set()
    recurse_seen = set()
    for comp, from_body in top_level:
        found = (_collect_components_recursive(comp, recurse_seen)
                 if recurse and not from_body else [comp])
        for c in found:
            if c.id not in added_ids:
                added_ids.add(c.id)
                components.append(c)

    result = [c for c in components if any(b.isSheetMetal for b in c.bRepBodies)]
    return result, skipped


def _ensure_file_writable(filepath):
    if not os.path.exists(filepath):
        return
    try:
        os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        with open(filepath, "r+b"):
            pass
    except OSError as e:
        raise RuntimeError(
            'Cannot overwrite "{}" because it is locked by another program.\n\n'
            "System message: {}\n\nPlease close the file and try again.".format(
                os.path.basename(filepath), e)
        )
    try:
        os.remove(filepath)
    except OSError as e:
        raise RuntimeError(
            'Cannot delete existing file "{}":\n{}'.format(os.path.basename(filepath), e)
        )


def _find_stationary_face(body):
    best_by_axis    = None
    best_large      = None
    best_large_area = 0.0

    for face in body.faces:
        if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
        if not ok:
            continue
        az = abs(normal.z)
        if az < 0.15:
            continue
        if az > 0.985 and best_by_axis is None:
            best_by_axis = face
        try:
            area = face.area
        except Exception:
            area = 0.0
        if area > best_large_area:
            best_large_area = area
            best_large      = face

    return best_by_axis or best_large


def _export_flat_pattern(export_mgr, comp, filepath, bend_lines, ext_lines, spline_poly):
    """Export comp's flat pattern to DXF, creating the flat pattern if needed.
    Raises RuntimeError with a readable reason when it cannot be exported."""
    sm_bodies = [b for b in comp.bRepBodies if b.isSheetMetal]
    if not sm_bodies:
        raise RuntimeError("no sheet-metal bodies")

    fp = comp.flatPattern
    if fp is None:
        station_face = _find_stationary_face(sm_bodies[0])
        if station_face is None:
            raise RuntimeError("no flat pattern and no top/bottom face found to create one")
        try:
            fp = comp.createFlatPattern(station_face)
        except Exception:
            fp = None
        if fp is None:
            raise RuntimeError("flat pattern could not be created automatically; please "
                               "create it manually in the Sheet Metal workspace.")

    opts = export_mgr.createDXFFlatPatternExportOptions(filepath, fp)
    opts.isCenterLinesExported       = bend_lines
    opts.isExtentLinesExported       = ext_lines
    opts.isSplineConvertedToPolyline = spline_poly
    return export_mgr.execute(opts)
