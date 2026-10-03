"""Core algorithms and feature generation for FusionLaserJoints."""

from .geometry_math import (
    Vec3,
    calculate_tab_intervals,
    calculate_finger_intervals,
    calculate_cross_joint_slots,
    create_tab_box_params,
    create_slot_box_params,
    Box3DParams
)
from .detection import (
    JointGeometryContext,
    detect_body_thickness,
    analyze_edge_and_face,
    analyze_bodies_contact
)
from .feature_builder import (
    create_transient_box,
    add_transient_body_to_component,
    apply_combine_cut,
    apply_combine_join
)
from .tab_slot_generator import generate_tab_and_slot
from .finger_joint_generator import generate_finger_joint
from .cross_joint_generator import generate_cross_joint
