"""Combined output: all bodies of a group isolated together and exported
as one file, keeping every component instance in its place."""
import adsk.core
import adsk.fusion

from .common import _as_component, _child_occurrences


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
        occs = _child_occurrences(node)
        for j in range(occs.count if occs else 0):
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
                node = occ if occ else _as_component(entity)
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


def _save_and_isolate_many(design, keep, snapshot):
    """Hide every body and occurrence in the design except the bodies in keep
    (and the occurrence chains that lead to them). Each original state is
    recorded in snapshot before it is changed, so _restore_many() can undo a
    failure part-way through.
    """
    root = design.rootComponent

    comps = [design.allComponents.item(c) for c in range(design.allComponents.count)]
    if not adsk.fusion.Component.cast(root):
        comps.append(root)       # flat pattern: its bodies live on the FlatPattern
    for comp in comps:
        if hasattr(comp, "isBodiesFolderLightBulbOn"):
            snapshot["folders"].append((comp, comp.isBodiesFolderLightBulbOn))
        bodies = comp.bRepBodies
        for i in range(bodies.count):
            body = bodies.item(i)
            snapshot["bodies"].append((body, body.isLightBulbOn))
            body.isLightBulbOn = False

    all_occs = getattr(root, "allOccurrences", None)
    for i in range(all_occs.count if all_occs else 0):
        occ = all_occs.item(i)
        snapshot["occs"].append((occ, occ.isLightBulbOn))
        occ.isLightBulbOn = False

    for proxy_body in keep:
        native_body = proxy_body.nativeObject if proxy_body.assemblyContext else proxy_body
        native_body.isLightBulbOn = True
        try:
            native_body.parentComponent.isBodiesFolderLightBulbOn = True
        except Exception:
            pass
        occ = proxy_body.assemblyContext
        while occ:
            occ.isLightBulbOn = True
            occ = occ.assemblyContext


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


def _export_combined_file(design, keep, filepath, fmt):
    """Isolate the bodies in keep and export the root component to one file.
    Returns export_mgr.execute()'s result."""
    export_mgr = design.exportManager
    root = design.rootComponent
    snapshot = {"bodies": [], "occs": [], "folders": []}
    try:
        _save_and_isolate_many(design, keep, snapshot)
        adsk.doEvents()
        if fmt == "step":
            opts = export_mgr.createSTEPExportOptions(filepath, root)
        elif fmt == "iges":
            opts = export_mgr.createIGESExportOptions(filepath, root)
        elif fmt == "sat":
            opts = export_mgr.createSATExportOptions(filepath, root)
        else:
            raise ValueError("format {} cannot hold a combined export".format(fmt))
        return export_mgr.execute(opts)
    finally:
        _restore_many(snapshot)
