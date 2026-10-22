"""Separate output: one file per body, each body isolated and exported on
its own. Repeated instances of a component are exported once."""
import adsk.core
import adsk.fusion

from .common import _safe_name


# ---------------------------------------------------------------------------
# Visibility helpers
# ---------------------------------------------------------------------------
def _hide_all_occs_recursive(comp, path, snapshot_occs):
    """Recursively hide all occurrences at every depth.
    Uses a tuple path (comp.name, index, ...) as a stable key instead of
    entityToken, which is only valid for root-level proxies.
    """
    occs = comp.occurrences
    for i in range(occs.count):
        occ = occs.item(i)
        key = path + (i,)
        snapshot_occs[key] = occ.isLightBulbOn
        occ.isLightBulbOn = False
        if occ.component:
            _hide_all_occs_recursive(occ.component, key, snapshot_occs)


def _save_and_isolate(comp, target_body_idx):
    snapshot = {"bodies": {}, "occs": {}}
    bodies = comp.bRepBodies
    for i in range(bodies.count):
        body = bodies.item(i)
        snapshot["bodies"][i] = body.isLightBulbOn
        body.isLightBulbOn = (i == target_body_idx)
    _hide_all_occs_recursive(comp, (), snapshot["occs"])
    return snapshot


def _restore(comp, snapshot):
    bodies = comp.bRepBodies
    for i, state in snapshot["bodies"].items():
        try:
            bodies.item(i).isLightBulbOn = state
        except Exception:
            pass
    # Restore all occurrences at every depth using the same path-tuple keys
    def _restore_occs_recursive(c, path):
        occs = c.occurrences
        for i in range(occs.count):
            occ = occs.item(i)
            key = path + (i,)
            if key in snapshot["occs"]:
                try:
                    occ.isLightBulbOn = snapshot["occs"][key]
                except Exception:
                    pass
            if occ.component:
                _restore_occs_recursive(occ.component, key)
    _restore_occs_recursive(comp, ())


def _native_index(comp, native_body):
    for j in range(comp.bRepBodies.count):
        if comp.bRepBodies.item(j).entityToken == native_body.entityToken:
            return j
    return -1


def _base_name(comp, native_body, inc_comp, prefix, suffix):
    body_safe = _safe_name(native_body.name)
    base_name = "{}_{}".format(_safe_name(comp.name), body_safe) if inc_comp else body_safe
    if prefix:
        base_name = prefix + "_" + base_name
    if suffix:
        base_name = base_name + "_" + suffix
    return base_name


# ---------------------------------------------------------------------------
# Collect (comp, body_index) pairs - recurse only when recurse=True
# ---------------------------------------------------------------------------
def _collect_bodies(node, want_solid, want_surf, want_sm, visible_only, inc_comp,
                    prefix, suffix, plan, skipped,
                    seen_comp_ids, seen_body_tokens, recurse):
    comp = node.component if adsk.fusion.Occurrence.cast(node) else node
    if not comp:
        return
    if comp.id in seen_comp_ids:
        return
    seen_comp_ids.add(comp.id)

    bodies = node.bRepBodies
    for i in range(bodies.count):
        proxy_body = bodies.item(i)
        native_body = proxy_body.nativeObject if proxy_body.assemblyContext else proxy_body

        if native_body.entityToken in seen_body_tokens:
            continue

        if native_body.isSheetMetal:
            keep = want_sm
            kind = "sheet metal"
        elif native_body.isSolid:
            keep = want_solid
            kind = "solid"
        else:
            keep = want_surf
            kind = "surface"

        if not keep:
            skipped.append("{}/{} ({})".format(comp.name, native_body.name, kind))
            continue

        # Check proxy body visibility
        if visible_only and not proxy_body.isVisible:
            skipped.append("{}/{} (hidden)".format(comp.name, native_body.name))
            continue

        seen_body_tokens.add(native_body.entityToken)

        # The index in comp.bRepBodies is what _save_and_isolate needs
        native_idx = _native_index(comp, native_body)
        if native_idx != -1:
            plan.append((comp, native_idx, native_body.name,
                         _base_name(comp, native_body, inc_comp, prefix, suffix)))

    if recurse:
        occs = node.childOccurrences if adsk.fusion.Occurrence.cast(node) else node.occurrences
        for j in range(occs.count):
            sub_occ = occs.item(j)
            if sub_occ:
                _collect_bodies(sub_occ, want_solid, want_surf, want_sm, visible_only, inc_comp,
                                prefix, suffix, plan, skipped,
                                seen_comp_ids, seen_body_tokens, recurse)


def _plan_separate(entities, want_solid, want_surf, want_sm, visible_only, recurse,
                   inc_comp, prefix, suffix):
    """Resolve a group's entities to bodies to export one by one.
    Returns (plan, skipped) with plan entries (comp, body_idx, body_name, base_name).
    """
    plan             = []
    skipped          = []
    seen_sel_ids     = set()
    seen_comp_ids    = set()
    seen_body_tokens = set()
    top_components   = []

    for entity in entities:
        try:
            body = adsk.fusion.BRepBody.cast(entity)
            if body:
                # Explicitly selected bodies bypass the type/visibility filters
                native_body = body.nativeObject if body.assemblyContext else body
                comp = native_body.parentComponent
                if native_body.entityToken in seen_body_tokens:
                    continue
                seen_body_tokens.add(native_body.entityToken)
                body_idx = _native_index(comp, native_body)
                if body_idx == -1:
                    skipped.append("{}/{} (not found in native component)".format(
                        comp.name, native_body.name))
                    continue
                plan.append((comp, body_idx, native_body.name,
                             _base_name(comp, native_body, inc_comp, prefix, suffix)))
            else:
                occ  = adsk.fusion.Occurrence.cast(entity)
                node = occ if occ else adsk.fusion.Component.cast(entity)
                comp = occ.component if occ else node
                if comp and comp.id not in seen_sel_ids:
                    seen_sel_ids.add(comp.id)
                    top_components.append(node)
        except Exception as exc:
            skipped.append("(invalid selection: {})".format(exc))

    for node in top_components:
        _collect_bodies(node, want_solid, want_surf, want_sm, visible_only, inc_comp,
                        prefix, suffix, plan, skipped,
                        seen_comp_ids, seen_body_tokens, recurse)

    return plan, skipped


def _export_separate_body(export_mgr, comp, body_idx, filepath, fmt):
    """Isolate one body and export it. Returns export_mgr.execute()'s result."""
    snapshot = _save_and_isolate(comp, body_idx)
    try:
        adsk.doEvents()
        body = comp.bRepBodies.item(body_idx)
        if fmt == "step":
            opts = export_mgr.createSTEPExportOptions(filepath, comp)
        elif fmt == "3mf":
            opts = export_mgr.createC3MFExportOptions(body, filepath)
        elif fmt == "stl":
            opts = export_mgr.createSTLExportOptions(body, filepath)
        elif fmt == "obj":
            opts = export_mgr.createOBJExportOptions(body, filepath)
        elif fmt == "iges":
            opts = export_mgr.createIGESExportOptions(filepath, comp)
        elif fmt == "sat":
            opts = export_mgr.createSATExportOptions(filepath, comp)
        else:
            raise ValueError("unknown format " + fmt)
        return export_mgr.execute(opts)
    finally:
        _restore(comp, snapshot)
