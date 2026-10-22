"""Remembered export groups/options, stored in the document as an attribute
(kept when the document is saved)."""
import json

import adsk.fusion

STATE_ATTR_GROUP = "UntestedPrototypes_ExportBodies"
STATE_ATTR_NAME  = "combined_state"


def _entity_ref(entity):
    """Describe a selected entity so it can be found again in a later session."""
    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        native_body = body.nativeObject if body.assemblyContext else body
        return {"type": "body",
                "path": body.assemblyContext.fullPathName if body.assemblyContext else "",
                "name": native_body.name,
                "token": body.entityToken}
    occ = adsk.fusion.Occurrence.cast(entity)
    if occ:
        return {"type": "occ", "path": occ.fullPathName, "token": occ.entityToken}
    if adsk.fusion.Component.cast(entity):
        return {"type": "root"}
    return None


def _resolve_entity_ref(design, ref, occ_by_path):
    """Find an entity from _entity_ref(): token first, then occurrence path/name."""
    kind = ref.get("type")
    if kind == "root":
        return design.rootComponent

    token = ref.get("token")
    if token:
        try:
            found = design.findEntityByToken(token)
            for ent in found or []:
                if kind == "body" and adsk.fusion.BRepBody.cast(ent):
                    return ent
                if kind == "occ" and adsk.fusion.Occurrence.cast(ent):
                    return ent
        except Exception:
            pass

    path = ref.get("path", "")
    if kind == "occ":
        return occ_by_path.get(path)
    if kind == "body":
        container = occ_by_path.get(path) if path else design.rootComponent
        if container:
            bodies = container.bRepBodies
            for i in range(bodies.count):
                if bodies.item(i).name == ref.get("name"):
                    return bodies.item(i)
    return None


def _read_state(design):
    try:
        attr = design.attributes.itemByName(STATE_ATTR_GROUP, STATE_ATTR_NAME)
        return json.loads(attr.value) if attr else {}
    except Exception:
        return {}


def _write_state(design, updates):
    state = _read_state(design)
    state.update(updates)
    design.attributes.add(STATE_ATTR_GROUP, STATE_ATTR_NAME, json.dumps(state))
