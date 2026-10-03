"""Tab & Slot (Mortise & Tenon / T-Joint) generator for FusionLaserJoints."""

from typing import Dict, Any, List
from .geometry_math import (
    calculate_tab_intervals,
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


def generate_tab_and_slot(
    context: JointGeometryContext,
    dist_mode: str = "by_count",
    tab_count: int = 3,
    tab_length_cm: float = 1.5,
    margin_cm: float = 0.5,
    clearance_cm: float = 0.015,
    protrusion_cm: float = 0.0,
    enable_chamfer: bool = True,
    chamfer_cm: float = 0.08,
    overshoot_cm: float = 0.05
) -> Dict[str, Any]:
    """Generates interlocking tabs on the tab plate and clearance slots on the mating plate."""
    if not HAS_ADSK:
        return {"success": False, "error": "Fusion 360 API unavailable"}

    # 1. Calculate 1D interval layout along the edge
    intervals = calculate_tab_intervals(
        total_length=context.joint_length,
        count=tab_count,
        target_length=tab_length_cm if dist_mode == "by_length" else None,
        margin=margin_cm,
        mode=dist_mode
    )

    if not intervals:
        return {"success": False, "error": "Edge length too short for specified margins/count."}

    parent_comp_tab = context.tab_body.parentComponent
    parent_comp_slot = context.slot_body.parentComponent

    tab_tool_bodies = []
    slot_tool_bodies = []

    # 2. Build transient bodies for each tab/slot pair
    for idx, interval in enumerate(intervals):
        tab_center_pos = context.start_point + context.edge_dir * interval.center

        # Create tab parameters (tenon)
        tab_params = create_tab_box_params(
            tab_center_pos=tab_center_pos,
            length_dir=context.edge_dir,
            thickness_dir=context.thickness_dir,
            penetration_dir=context.penetration_dir,
            tab_length=interval.length,
            plate_thickness=context.tab_thickness,
            penetration_depth=context.slot_thickness,
            protrusion=protrusion_cm
        )

        # Create slot parameters (mortise with clearance and overshoot)
        slot_params = create_slot_box_params(
            tab_box=tab_params,
            clearance=clearance_cm,
            overshoot=overshoot_cm
        )

        # Build transient BRep bodies
        tab_temp = create_transient_box(tab_params)
        slot_temp = create_transient_box(slot_params)

        if not tab_temp or not slot_temp:
            continue

        # Convert to component bodies
        tab_body_obj = add_transient_body_to_component(parent_comp_tab, tab_temp, f"LaserTab_{idx+1}")
        slot_body_obj = add_transient_body_to_component(parent_comp_slot, slot_temp, f"LaserSlotTool_{idx+1}")

        if tab_body_obj:
            tab_tool_bodies.append(tab_body_obj)
        if slot_body_obj:
            slot_tool_bodies.append(slot_body_obj)

    if not tab_tool_bodies or not slot_tool_bodies:
        return {"success": False, "error": "Failed to create tool bodies."}

    # 3. Apply Combine Join on Tab Body
    join_feature = apply_combine_join(parent_comp_tab, context.tab_body, tab_tool_bodies)

    # 4. Apply Combine Cut on Slot Body
    cut_feature = apply_combine_cut(parent_comp_slot, context.slot_body, slot_tool_bodies)

    # 5. Apply lead-in chamfers on outer corners of tabs if requested
    chamfer_applied = False
    if enable_chamfer and chamfer_cm > 0.001:
        try:
            # Add chamfer features to the leading edges of the joined tabs
            chamfer_feats = parent_comp_tab.features.chamferFeatures
            chamfer_edges = adsk.core.ObjectCollection.create()

            # Find leading edges of the tab body (edges perpendicular to tab thickness at outer face)
            for face in context.tab_body.faces:
                # Check if face normal aligns with penetration_dir
                if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
                    n = face.geometry.normal
                    from .detection import vector3d_to_vec3
                    if vector3d_to_vec3(n).dot(context.penetration_dir) > 0.9:
                        for edge in face.edges:
                            chamfer_edges.add(edge)

            if chamfer_edges.count > 0:
                chamfer_input = chamfer_feats.createInput2()
                dist_val = adsk.core.ValueInput.createByReal(chamfer_cm)
                chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(chamfer_edges, dist_val, True)
                chamfer_feats.add(chamfer_input)
                chamfer_applied = True
        except Exception:
            pass  # Chamfer is optional enhancement; preserve core joint if topology varies

    return {
        "success": True,
        "tab_count": len(tab_tool_bodies),
        "slot_count": len(slot_tool_bodies),
        "join_feature": join_feature,
        "cut_feature": cut_feature,
        "chamfer_applied": chamfer_applied
    }
