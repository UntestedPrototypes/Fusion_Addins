"""Default configuration and constants for the Fusion 360 URDF Exporter."""

# Unit conversions
# Fusion 360 internal calculation units: cm, kg, radians, seconds
# URDF standards: m, kg, radians, seconds
CM_TO_M = 0.01
M_TO_CM = 100.0
KG_CM2_TO_KG_M2 = 1e-4

# Default joint dynamics & limits
DEFAULT_REVOLUTE_LIMITS = {
    'lower': -3.141592653589793,   # -pi radians
    'upper': 3.141592653589793,    # +pi radians
    'effort': 100.0,               # N*m
    'velocity': 1.0                # rad/s
}

DEFAULT_PRISMATIC_LIMITS = {
    'lower': -1.0,                 # meters
    'upper': 1.0,                  # meters
    'effort': 100.0,               # N
    'velocity': 0.5                # m/s
}

DEFAULT_EFFORT = 100.0
DEFAULT_VELOCITY = 1.0

# Supported mesh refinement choices
MESH_QUALITIES = ['Low', 'Medium', 'High']
DEFAULT_MESH_QUALITY = 'Medium'
COLLISION_MESH_QUALITY = 'Low'
DEFAULT_SKIP_INVISIBLE = True
DEFAULT_INERTIA_VISIBLE_ONLY = False

# URDF joint type mappings
JOINT_TYPE_REVOLUTE = 'revolute'
JOINT_TYPE_CONTINUOUS = 'continuous'
JOINT_TYPE_PRISMATIC = 'prismatic'
JOINT_TYPE_FIXED = 'fixed'
JOINT_TYPE_PLANAR = 'planar'
JOINT_TYPE_FLOATING = 'floating'

# Joint naming conventions
DEFAULT_JOINT_NAMING_PATTERN = '{branch_name}_c{chain}_l{level}'

JOINT_NAMING_PRESETS = [
    ('{branch_name}_c{chain}_l{level}', '{branch_name}_c{chain}_l{level}  (Default: e.g. leg_1_c1_l1)'),
    ('{type}_c{chain}_l{level}', '{type}_c{chain}_l{level}  (e.g. revolute_c1_l1)'),
    ('{type}_{chain}_{level}', '{type}_{chain}_{level}  (e.g. revolute_1_1)'),
    ('joint_c{chain}_l{level}', 'joint_c{chain}_l{level}  (e.g. joint_c1_l1)'),
    ('{type}_chain{chain}_level{level}', '{type}_chain{chain}_level{level}  (e.g. revolute_chain1_level1)'),
    ('{branch_name}_joint_{level}', '{branch_name}_joint_{level}  (e.g. leg_1_joint_1)'),
    ('{branch_name}_{level}', '{branch_name}_{level}  (e.g. leg_1_1)'),
    ('{type}_{level}', '{type}_{level}  [Legacy Sequential]  (e.g. revolute_1A)'),
    ('Custom', 'Custom Pattern...'),
]

