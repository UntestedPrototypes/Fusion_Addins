"""Cross / Halving Joint generator for intersecting plates."""

from typing import Dict, Any
from .geometry_math import calculate_cross_joint_slots, Vec3
from .detection import JointGeometryContext
from .feature_builder import (
    create_transient_box,
    add_transient_body_to_component,
    apply_combine_cut
)

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


def generate_cross_joint(
    context: JointGeometryContext,
    clearance_cm: float = 0.015,
    overshoot_cm: float = 0.05
) -> Dict[str, Any]:
    """Generates half-depth interlocking slot cuts for two intersecting plates."""
    if not HAS_ADSK:
        return {"success": False, "error": "Fusion 360 API unavailable"}

    # Midpoint of the intersection seam
    midpoint = context.start_point + context.edge_dir * (context.joint_length / 2.0)

    box1_params, box2_params = calculate_cross_joint_slots(
        intersection_center=midpoint,
        edge_dir=context.edge_dir,
        normal_1=context.thickness_dir,
        normal_2=context.penetration_dir,
        height_1=context.joint_length,
        height_2=context.joint_length,
        thickness_1=context.tab_thickness,
        thickness_2=context.slot_thickness,
        clearance=clearance_cm,
        overshoot=overshoot_cm
    )

    parent_comp1 = context.tab_body.parentComponent
    parent_comp2 = context.slot_body.parentComponent

    temp1 = create_transient_box(box1_params)
    temp2 = create_transient_box(box2_params)

    tool1 = add_transient_body_to_component(parent_comp1, temp1, "CrossSlotTool1")
    tool2 = add_transient_body_to_component(parent_comp2, temp2, "CrossSlotTool2")

    cut1 = apply_combine_cut(parent_comp1, context.tab_body, [tool1])
    cut2 = apply_combine_cut(parent_comp2, context.slot_body, [tool2])

    return {
        "success": True,
        "cut1": cut1 is not None,
        "cut2": cut2 is not None
    }
