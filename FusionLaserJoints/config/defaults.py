"""Default configuration constants and parameters for FusionLaserJoints."""

# Joint Types
JOINT_TYPE_TAB_SLOT = "tab_slot"
JOINT_TYPE_FINGER = "finger"
JOINT_TYPE_CROSS = "cross"

JOINT_TYPES = [
    JOINT_TYPE_TAB_SLOT,
    JOINT_TYPE_FINGER,
    JOINT_TYPE_CROSS,
]

JOINT_TYPE_LABELS = {
    JOINT_TYPE_TAB_SLOT: "Tab & Slot (T-Joint / Mortise & Tenon)",
    JOINT_TYPE_FINGER: "Finger Joint (Corner / Box Joint)",
    JOINT_TYPE_CROSS: "Cross Joint (Halving / Slotted Grid)",
}

# Selection Modes
SELECT_MODE_EDGE_FACE = "edge_face"
SELECT_MODE_BODIES = "bodies"

SELECT_MODE_LABELS = {
    SELECT_MODE_EDGE_FACE: "Edge & Face Selection (Precise)",
    SELECT_MODE_BODIES: "Body-to-Body (Auto-detect Contact)",
}

# Distribution Modes
DIST_BY_COUNT = "by_count"
DIST_BY_LENGTH = "by_length"

# Depth / Protrusion Modes
DEPTH_FLUSH = "flush"
DEPTH_PROTRUDING = "protruding"

# Defaults (all spatial lengths in millimeters for UI display; converted to cm for Fusion API)
DEFAULT_JOINT_TYPE = JOINT_TYPE_TAB_SLOT
DEFAULT_SELECT_MODE = SELECT_MODE_EDGE_FACE
DEFAULT_DIST_MODE = DIST_BY_COUNT

DEFAULT_TAB_COUNT = 3
DEFAULT_TAB_LENGTH_MM = 15.0
DEFAULT_MARGIN_MM = 5.0
DEFAULT_CLEARANCE_MM = 0.15
DEFAULT_PROTRUSION_MM = 0.0
DEFAULT_ENABLE_CHAMFER = True
DEFAULT_CHAMFER_MM = 0.8
DEFAULT_INVERT_ORDER = False

# Geometric thresholds
EPSILON = 1e-5
OVERSHOOT_MM = 0.5  # Tool cut overshoot in mm to prevent coplanar surface artifacts
MIN_PLATE_THICKNESS_MM = 0.5
MAX_PLATE_THICKNESS_MM = 50.0

# Fusion 360 internal length unit is Centimeter
MM_TO_CM = 0.1
CM_TO_MM = 10.0
