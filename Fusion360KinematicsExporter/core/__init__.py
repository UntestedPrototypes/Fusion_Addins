"""
Fusion 360 Kinematics Exporter — Core Data Structures

Shared data classes used by all modules. These are plain Python dataclasses
with no dependency on the adsk.* Fusion API, making them testable outside Fusion.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple


@dataclass
class LinkData:
    """Represents a single rigid link (component) in the kinematic tree."""
    name: str
    mass: float = 0.0                          # kg
    center_of_mass: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # meters, in link-local frame
    inertia: Dict[str, float] = field(default_factory=lambda: {
        'ixx': 1e-4, 'ixy': 0.0, 'ixz': 0.0,
        'iyy': 1e-4, 'iyz': 0.0, 'izz': 1e-4
    })  # kg·m², with minimum clamp for simulation stability
    visual_color: Tuple[float, float, float, float] = (0.7, 0.7, 0.7, 1.0)  # RGBA normalized
    bounding_box: Tuple[float, float, float] = (0.01, 0.01, 0.01)  # (sx, sy, sz) meters
    world_transform: Optional[list] = None     # 4x4 matrix    # Generated meshes
    stl_filename: Optional[str] = None
    col_stl_filename: Optional[str] = None         # Relative path to exported STL mesh
    visual_origin_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # mesh offset in link frame
    visual_origin_rpy: Tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class JointData:
    """Represents a kinematic joint connecting two links."""
    name: str
    joint_type: str = 'fixed'                  # 'revolute', 'continuous', 'prismatic', 'fixed'
    parent_link: str = ''
    child_link: str = ''
    origin_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # meters, in parent frame
    origin_rpy: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # radians (roll, pitch, yaw)
    axis: Tuple[float, float, float] = (0.0, 0.0, 1.0)        # unit vector in joint frame
    limit_lower: float = 0.0                   # rad or m
    limit_upper: float = 0.0                   # rad or m
    limit_effort: float = 10.0                 # N·m or N
    limit_velocity: float = 3.14               # rad/s or m/s
    has_limits: bool = False


@dataclass
class DHParameter:
    """A single row of a DH parameter table."""
    joint_name: str
    joint_type: str = 'revolute'               # 'revolute' or 'prismatic'
    a: float = 0.0                             # link length (meters)
    alpha: float = 0.0                         # link twist (radians)
    d: float = 0.0                             # link offset (meters)
    theta_offset: float = 0.0                  # joint angle offset (radians)
    limit_min: float = -3.14159                # lower limit
    limit_max: float = 3.14159                 # upper limit


@dataclass
class KinematicChain:
    """A serial chain of joints/links (e.g. one leg of a walker)."""
    name: str
    joint_names: List[str] = field(default_factory=list)
    link_names: List[str] = field(default_factory=list)
    dh_standard: List[DHParameter] = field(default_factory=list)
    dh_modified: List[DHParameter] = field(default_factory=list)


@dataclass
class RobotModel:
    """Complete parsed robot model — the central data exchange object."""
    name: str = 'robot'
    links: Dict[str, LinkData] = field(default_factory=dict)
    joints: List[JointData] = field(default_factory=list)
    chains: List[KinematicChain] = field(default_factory=list)
    root_link_name: str = 'base_link'


# --- Naming configuration (user-editable in the UI) ---

@dataclass
class NamingConfig:
    """User-configurable naming conventions for links, joints, and chains."""
    base_link_name: str = 'base_link'
    link_prefix: str = ''                      # e.g. 'link_' → 'link_femur'
    link_suffix: str = ''
    joint_prefix: str = ''                     # e.g. 'joint_' → 'joint_coxa_yaw'
    joint_suffix: str = ''
    chain_prefix: str = 'leg_'                 # e.g. 'leg_' → 'leg_front_left'
    chain_suffix: str = ''
    # Replacement map: Fusion occurrence name → URDF-friendly name
    # e.g. {"Coxa Assembly:1": "coxa_FL", "Femur v3:1": "femur_FL"}
    custom_name_map: Dict[str, str] = field(default_factory=dict)
    # If True, auto-sanitize names (lowercase, replace spaces/colons with underscores)
    auto_sanitize: bool = True

    def sanitize(self, raw_name: str) -> str:
        """Apply naming rules to a raw Fusion occurrence/joint name."""
        # Check custom map first
        if raw_name in self.custom_name_map:
            return self.custom_name_map[raw_name]
        name = raw_name
        if self.auto_sanitize:
            # Remove version suffixes like ":1", " v3"
            if ':' in name:
                name = name.rsplit(':', 1)[0]
            name = name.strip()
            name = name.lower()
            name = name.replace(' ', '_').replace('-', '_')
            # Remove non-alphanumeric chars except underscore
            name = ''.join(c for c in name if c.isalnum() or c == '_')
            # Collapse multiple underscores
            while '__' in name:
                name = name.replace('__', '_')
            name = name.strip('_')
        return name

    def format_link_name(self, raw_name: str) -> str:
        base = self.sanitize(raw_name)
        return f"{self.link_prefix}{base}{self.link_suffix}"

    def format_joint_name(self, raw_name: str) -> str:
        base = self.sanitize(raw_name)
        return f"{self.joint_prefix}{base}{self.joint_suffix}"

    def format_chain_name(self, raw_name: str) -> str:
        base = self.sanitize(raw_name)
        return f"{self.chain_prefix}{base}{self.chain_suffix}"
