"""Pure-Python geometric algorithms and vector mathematics for FusionLaserJoints.

All functions operate with standard numbers and tuples, allowing comprehensive
automated unit testing without requiring an active Autodesk Fusion 360 session.
"""

import math
from typing import List, Tuple, Optional, Dict, NamedTuple


class Vec3:
    """Lightweight 3D Vector with standard algebraic operations."""
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __repr__(self) -> str:
        return f"Vec3({self.x:.4f}, {self.y:.4f}, {self.z:.4f})"

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> "Vec3":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: float) -> "Vec3":
        if abs(scalar) < 1e-12:
            raise ZeroDivisionError("Cannot divide Vec3 by zero")
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __neg__(self) -> "Vec3":
        return Vec3(-self.x, -self.y, -self.z)

    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x
        )

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> "Vec3":
        l = self.length()
        if l < 1e-12:
            return Vec3(1.0, 0.0, 0.0)
        return self / l

    def is_parallel(self, other: "Vec3", tol: float = 1e-4) -> bool:
        u1 = self.normalized()
        u2 = other.normalized()
        d = abs(u1.dot(u2))
        return abs(d - 1.0) < tol

    def is_perpendicular(self, other: "Vec3", tol: float = 1e-4) -> bool:
        u1 = self.normalized()
        u2 = other.normalized()
        return abs(u1.dot(u2)) < tol

    def to_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)


class Interval1D(NamedTuple):
    index: int
    start: float
    end: float
    center: float
    length: float
    is_tab: bool  # True for tab, False for slot/notch


def calculate_tab_intervals(
    total_length: float,
    count: int = 3,
    target_length: Optional[float] = None,
    margin: float = 5.0,
    mode: str = "by_count"
) -> List[Interval1D]:
    """Computes the 1D positions of tabs along an edge of length total_length.

    Tabs and gaps alternate across the active region:
    [Margin] [Tab 0] [Gap 0] [Tab 1] [Gap 1] ... [Tab N-1] [Margin]
    Total tabs = N, total internal gaps = N - 1.
    """
    if total_length <= 0.0:
        return []

    # Safeguard margins: cannot exceed half the total length
    effective_margin = max(0.0, margin)
    if effective_margin * 2.0 >= total_length * 0.9:
        effective_margin = max(0.0, total_length * 0.05)

    active_length = total_length - 2.0 * effective_margin

    if mode == "by_length" and target_length and target_length > 0.0:
        # Determine optimal count such that tab width ~ target_length
        # (2N - 1) * target_length = active_length => 2N - 1 = active_length / target_length
        raw_n = (active_length / target_length + 1.0) / 2.0
        n_tabs = max(1, int(round(raw_n)))
    else:
        n_tabs = max(1, int(count))

    if n_tabs == 1:
        # Single tab centered in active area
        tab_len = active_length * 0.6 if active_length > 0.0 else total_length
        start = (total_length - tab_len) / 2.0
        end = start + tab_len
        return [Interval1D(0, start, end, (start + end) / 2.0, tab_len, True)]

    # Alternating tabs and gaps: 2 * n_tabs - 1 segments
    n_segments = 2 * n_tabs - 1
    segment_len = active_length / n_segments

    intervals: List[Interval1D] = []
    current_pos = effective_margin

    for i in range(n_tabs):
        tab_start = current_pos
        tab_end = tab_start + segment_len
        tab_center = (tab_start + tab_end) / 2.0
        intervals.append(Interval1D(i, tab_start, tab_end, tab_center, segment_len, True))
        current_pos = tab_end + segment_len  # Skip gap

    return intervals


def calculate_finger_intervals(
    total_length: float,
    finger_count: int = 5,
    invert: bool = False
) -> Tuple[List[Interval1D], List[Interval1D]]:
    """Divides an edge of length total_length into N equal alternating fingers.

    Returns:
        (fingers_body1, fingers_body2)
    """
    if total_length <= 0.0:
        return ([], [])

    n = max(2, int(finger_count))
    finger_len = total_length / n

    body1_fingers: List[Interval1D] = []
    body2_fingers: List[Interval1D] = []

    for i in range(n):
        f_start = i * finger_len
        f_end = (i + 1) * finger_len
        f_center = (f_start + f_end) / 2.0
        interval = Interval1D(i, f_start, f_end, f_center, finger_len, True)

        # Alternating assignment
        is_even = (i % 2 == 0)
        belongs_to_body1 = is_even if not invert else not is_even

        if belongs_to_body1:
            body1_fingers.append(interval)
        else:
            body2_fingers.append(interval)

    return (body1_fingers, body2_fingers)


class Box3DParams(NamedTuple):
    center: Vec3
    length_dir: Vec3   # Along tab/edge axis
    width_dir: Vec3    # Along plate thickness axis
    height_dir: Vec3   # Along slot penetration / depth axis
    length: float      # Full length along length_dir
    width: float       # Full width along width_dir
    height: float      # Full height along height_dir


def create_tab_box_params(
    tab_center_pos: Vec3,
    length_dir: Vec3,
    thickness_dir: Vec3,
    penetration_dir: Vec3,
    tab_length: float,
    plate_thickness: float,
    penetration_depth: float,
    protrusion: float = 0.0
) -> Box3DParams:
    """Computes parameters for a 3D rectangular tab body (tenon)."""
    u_len = length_dir.normalized()
    u_thk = thickness_dir.normalized()
    u_pen = penetration_dir.normalized()

    total_height = penetration_depth + protrusion
    # Box center is offset into the slot body by half the total height
    box_center = tab_center_pos + u_pen * (total_height / 2.0)

    return Box3DParams(
        center=box_center,
        length_dir=u_len,
        width_dir=u_thk,
        height_dir=u_pen,
        length=tab_length,
        width=plate_thickness,
        height=total_height
    )


def create_slot_box_params(
    tab_box: Box3DParams,
    clearance: float,
    overshoot: float = 0.5
) -> Box3DParams:
    """Computes parameters for the slot cutting tool body.

    Applies clearance to tab length and tab thickness, and adds overshoot
    along penetration direction to guarantee a clean through-cut without coplanar faces.
    """
    c = max(0.0, clearance)
    ov = max(0.0, overshoot)

    expanded_length = tab_box.length + 2.0 * c
    expanded_width = tab_box.width + 2.0 * c
    expanded_height = tab_box.height + 2.0 * ov

    # Center is preserved or adjusted slightly for overshoot along penetration axis
    return Box3DParams(
        center=tab_box.center,
        length_dir=tab_box.length_dir,
        width_dir=tab_box.width_dir,
        height_dir=tab_box.height_dir,
        length=expanded_length,
        width=expanded_width,
        height=expanded_height
    )


def calculate_cross_joint_slots(
    intersection_center: Vec3,
    edge_dir: Vec3,
    normal_1: Vec3,
    normal_2: Vec3,
    height_1: float,
    height_2: float,
    thickness_1: float,
    thickness_2: float,
    clearance: float,
    overshoot: float = 0.5
) -> Tuple[Box3DParams, Box3DParams]:
    """Computes the two half-depth interlocking slot boxes for a Cross / Halving joint.

    Slot 1 cuts Body 1 from top edge to mid-height.
    Slot 2 cuts Body 2 from bottom edge to mid-height.
    """
    c = max(0.0, clearance)
    ov = max(0.0, overshoot)

    # Slot 1 dimensions: width receives Body 2 (thickness_2 + 2c), depth is height_1 / 2
    slot1_len = height_1 / 2.0 + ov
    slot1_center = intersection_center + edge_dir.normalized() * (slot1_len / 2.0)
    box1 = Box3DParams(
        center=slot1_center,
        length_dir=edge_dir.normalized(),
        width_dir=normal_2.normalized(),
        height_dir=normal_1.normalized(),
        length=slot1_len,
        width=thickness_2 + 2.0 * c,
        height=thickness_1 + 2.0 * ov
    )

    # Slot 2 dimensions: opposite direction
    slot2_len = height_2 / 2.0 + ov
    slot2_center = intersection_center - edge_dir.normalized() * (slot2_len / 2.0)
    box2 = Box3DParams(
        center=slot2_center,
        length_dir=edge_dir.normalized(),
        width_dir=normal_1.normalized(),
        height_dir=normal_2.normalized(),
        length=slot2_len,
        width=thickness_1 + 2.0 * c,
        height=thickness_2 + 2.0 * ov
    )

    return (box1, box2)
