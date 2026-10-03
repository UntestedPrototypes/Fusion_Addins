"""Finger Joint (Corner / Box Joint) generator for FusionLaserJoints."""

from typing import Dict, Any, List
from .geometry_math import (
    calculate_finger_intervals,
    create_tab_box_params,
    create_slot_box_params,
    Vec3,
    Box3DParams
)
from .detection import JointGeometryContext
from .feature_builder import (
    create_transient_box,
    add_transient_body_to_component,
    apply_combine_join,
    apply_combine_cut
)

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


def generate_finger_joint(
    context: JointGeometryContext,
    finger_count: int = 5,
    clearance_cm: float = 0.015,
    invert: bool = False,
    overshoot_cm: float = 0.05
) -> Dict[str, Any]:
    """Generates alternating interlocking finger/box joints between two corner plates."""
    if not HAS_ADSK:
        return {"success": False, "error": "Fusion 360 API unavailable"}

    b1_fingers, b2_fingers = calculate_finger_intervals(
        total_length=context.joint_length,
        finger_count=finger_count,
        invert=invert
    )

    if not b1_fingers or not b2_fingers:
        return {"success": False, "error": "Invalid finger configuration."}

    parent_comp1 = context.tab_body.parentComponent
    parent_comp2 = context.slot_body.parentComponent

    # Fingers for Body 1: tabs on Body 1, cut from Body 2
    b1_tool_bodies = []
    b2_cut_tool_bodies = []

    for f in b1_fingers:
        pos = context.start_point + context.edge_dir * f.center
        tab_params = create_tab_box_params(
            tab_center_pos=pos,
            length_dir=context.edge_dir,
            thickness_dir=context.thickness_dir,
            penetration_dir=context.penetration_dir,
            tab_length=f.length,
            plate_thickness=context.tab_thickness,
            penetration_depth=context.slot_thickness,
            protrusion=0.0
        )
        slot_params = create_slot_box_params(tab_params, clearance_cm, overshoot_cm)

        tab_temp = create_transient_box(tab_params)
        slot_temp = create_transient_box(slot_params)

        if tab_temp:
            b_obj = add_transient_body_to_component(parent_comp1, tab_temp, f"FingerB1_{f.index+1}")
            if b_obj:
                b1_tool_bodies.append(b_obj)
        if slot_temp:
            s_obj = add_transient_body_to_component(parent_comp2, slot_temp, f"CutB2_{f.index+1}")
            if s_obj:
                b2_cut_tool_bodies.append(s_obj)

    # Fingers for Body 2: cut from Body 1
    b1_cut_tool_bodies = []
    for f in b2_fingers:
        pos = context.start_point + context.edge_dir * f.center
        tab_params = create_tab_box_params(
            tab_center_pos=pos,
            length_dir=context.edge_dir,
            thickness_dir=context.thickness_dir,
            penetration_dir=context.penetration_dir,
            tab_length=f.length,
            plate_thickness=context.tab_thickness,
            penetration_depth=context.slot_thickness,
            protrusion=0.0
        )
        slot_params = create_slot_box_params(tab_params, clearance_cm, overshoot_cm)
        slot_temp = create_transient_box(slot_params)

        if slot_temp:
            s_obj = add_transient_body_to_component(parent_comp1, slot_temp, f"CutB1_{f.index+1}")
            if s_obj:
                b1_cut_tool_bodies.append(s_obj)

    # Apply operations:
    # 1. Join fingers to Body 1 if butting
    if b1_tool_bodies:
        apply_combine_join(parent_comp1, context.tab_body, b1_tool_bodies)

    # 2. Cut notches from Body 2
    if b2_cut_tool_bodies:
        apply_combine_cut(parent_comp2, context.slot_body, b2_cut_tool_bodies)

    # 3. Cut notches from Body 1
    if b1_cut_tool_bodies:
        apply_combine_cut(parent_comp1, context.tab_body, b1_cut_tool_bodies)

    return {
        "success": True,
        "body1_fingers": len(b1_fingers),
        "body2_fingers": len(b2_fingers),
    }
