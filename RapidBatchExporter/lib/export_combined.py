"""Combined output: all bodies of a group collected and exported as one
file (through the temporary document), every component instance in its place."""
import adsk.core
import adsk.fusion

from .common import _as_component, _child_occurrences
from .temp_doc_export import _world_matrix, _world_copy, _local_copy, _body_style


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


def _combined_items(keep):
    """Contents of a combined file for the temporary document: one component
    per source component, placed at every instance like in the design, with
    the instance's bodies in the component's own coordinates. Bodies of the
    top level go into the root. Returns (items, unverified body names) - see
    _TempDocSession.export()."""
    instances = {}      # occurrence path -> [occurrence, native component, [bodies]]
    order = []
    root_bodies = []
    for body in keep:
        ctx = body.assemblyContext
        if not ctx:
            root_bodies.append(body)
            continue
        native = body.nativeObject
        entry = instances.get(ctx.fullPathName)
        if entry is None:
            entry = instances[ctx.fullPathName] = [body, native.parentComponent, []]
            order.append(ctx.fullPathName)
        entry[2].append(body)

    items = []
    unverified = []
    shared = {}         # (component id, body tokens) -> item using that component
    for path in order:
        first_body, comp, bodies = instances[path]
        matrix = _world_matrix(first_body)
        if matrix is None:
            # No verified placement: copy this instance's bodies in place instead
            copies = []
            for body in bodies:
                copy, verified = _world_copy(body)
                if not verified:
                    unverified.append(body.name)
                copies.append((body.name, copy) + _body_style(body))
            items.append((comp.name, copies, [], comp.material))
            continue
        # Instances with the same bodies share one component, placed again.
        # The name is part of the key: configuration variants of a component
        # report the same id but have different geometry.
        # Appearances too: an instance can override them.
        styles = [_body_style(b) for b in bodies]
        key = (comp.id, comp.name,
               tuple(sorted(b.nativeObject.entityToken for b in bodies)),
               tuple(sorted((a.id if a else "", m.id if m else "") for a, m in styles)))
        item = shared.get(key)
        if item is None:
            item = (comp.name, [(b.name, _local_copy(b)) + st for b, st in zip(bodies, styles)],
                    [], comp.material)
            shared[key] = item
            items.append(item)
        item[2].append(matrix)

    for body in root_bodies:
        copy, verified = _world_copy(body)
        if not verified:
            unverified.append(body.name)
        items.append((None, [(body.name, copy) + _body_style(body)], [],
                      body.parentComponent.material))
    return items, unverified
