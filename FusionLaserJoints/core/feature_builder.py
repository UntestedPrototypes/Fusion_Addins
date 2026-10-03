"""Fusion 360 Feature Builder for creating tabs, slots, and boolean operations.

Converts geometric box specifications into real B-Rep bodies and combines them
with the target models using timeline-tracked Cut and Join features.
"""

from typing import List, Optional
from .geometry_math import Box3DParams, Vec3

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


def create_transient_box(box_params: Box3DParams):
    """Creates an in-memory BRepBody using TemporaryBRepManager."""
    if not HAS_ADSK:
        return None

    temp_mgr = adsk.fusion.TemporaryBRepManager.get()

    center = adsk.core.Point3D.create(box_params.center.x, box_params.center.y, box_params.center.z)
    length_dir = adsk.core.Vector3D.create(box_params.length_dir.x, box_params.length_dir.y, box_params.length_dir.z)
    width_dir = adsk.core.Vector3D.create(box_params.width_dir.x, box_params.width_dir.y, box_params.width_dir.z)

    # Ensure directions are normalized and orthogonal
    length_dir.normalize()
    width_dir.normalize()

    obb = adsk.core.OrientedBoundingBox3D.create(
        center,
        length_dir,
        width_dir,
        box_params.length,
        box_params.width,
        box_params.height
    )

    return temp_mgr.createBox(obb)


def add_transient_body_to_component(parent_comp, temp_body, name: str = "LaserJointTool"):
    """Adds a transient BRepBody into the component's geometry, wrapping in BaseFeature if parametric."""
    if not HAS_ADSK or not parent_comp or not temp_body:
        return None

    design = parent_comp.parentDesign
    if design and design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base_feat = parent_comp.features.baseFeatures.add()
        base_feat.startEdit()
        real_body = parent_comp.bRepBodies.add(temp_body, base_feat)
        base_feat.name = name
        base_feat.finishEdit()
        return real_body
    else:
        real_body = parent_comp.bRepBodies.add(temp_body)
        real_body.name = name
        return real_body


def apply_combine_cut(parent_comp, target_body, tool_bodies: list):
    """Executes a Combine Cut feature to remove tool bodies from the target body."""
    if not HAS_ADSK or not parent_comp or not target_body or not tool_bodies:
        return None

    tool_collection = adsk.core.ObjectCollection.create()
    for tb in tool_bodies:
        if tb and hasattr(tb, "isValid") and tb.isValid:
            tool_collection.add(tb)

    if tool_collection.count == 0:
        return None

    combines = parent_comp.features.combineFeatures
    cut_input = combines.createInput(target_body, tool_collection)
    cut_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    cut_input.isNewComponent = False
    cut_input.isKeepToolBodies = False

    return combines.add(cut_input)


def apply_combine_join(parent_comp, target_body, tool_bodies: list):
    """Executes a Combine Join feature to union tool bodies into the target body."""
    if not HAS_ADSK or not parent_comp or not target_body or not tool_bodies:
        return None

    tool_collection = adsk.core.ObjectCollection.create()
    for tb in tool_bodies:
        if tb and hasattr(tb, "isValid") and tb.isValid:
            tool_collection.add(tb)

    if tool_collection.count == 0:
        return None

    combines = parent_comp.features.combineFeatures
    join_input = combines.createInput(target_body, tool_collection)
    join_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    join_input.isNewComponent = False
    join_input.isKeepToolBodies = False

    return combines.add(join_input)
