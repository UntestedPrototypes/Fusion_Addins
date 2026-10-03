"""Comprehensive unit tests for pure-Python geometric math and joint algorithms."""

import unittest
import math
import sys
import os

# Ensure project root is in sys.path
ADDIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDIN_ROOT not in sys.path:
    sys.path.insert(0, ADDIN_ROOT)

from core.geometry_math import (
    Vec3,
    calculate_tab_intervals,
    calculate_finger_intervals,
    calculate_cross_joint_slots,
    create_tab_box_params,
    create_slot_box_params,
    Box3DParams
)


class TestVec3(unittest.TestCase):
    def test_basic_arithmetic(self):
        v1 = Vec3(1, 2, 3)
        v2 = Vec3(4, 5, 6)
        
        # Addition
        v_add = v1 + v2
        self.assertAlmostEqual(v_add.x, 5.0)
        self.assertAlmostEqual(v_add.y, 7.0)
        self.assertAlmostEqual(v_add.z, 9.0)

        # Subtraction
        v_sub = v2 - v1
        self.assertAlmostEqual(v_sub.x, 3.0)
        self.assertAlmostEqual(v_sub.y, 3.0)
        self.assertAlmostEqual(v_sub.z, 3.0)

        # Scalar multiplication
        v_mul = v1 * 2.0
        self.assertAlmostEqual(v_mul.x, 2.0)
        self.assertAlmostEqual(v_mul.y, 4.0)
        self.assertAlmostEqual(v_mul.z, 6.0)

        # Negation
        v_neg = -v1
        self.assertAlmostEqual(v_neg.x, -1.0)

    def test_dot_and_cross_product(self):
        vx = Vec3(1, 0, 0)
        vy = Vec3(0, 1, 0)
        vz = Vec3(0, 0, 1)

        # Orthogonal dot product
        self.assertAlmostEqual(vx.dot(vy), 0.0)
        self.assertAlmostEqual(vx.dot(vx), 1.0)

        # Cross product (Right hand rule)
        cross_xy = vx.cross(vy)
        self.assertAlmostEqual(cross_xy.x, vz.x)
        self.assertAlmostEqual(cross_xy.y, vz.y)
        self.assertAlmostEqual(cross_xy.z, vz.z)

    def test_length_and_normalize(self):
        v = Vec3(3, 4, 0)
        self.assertAlmostEqual(v.length(), 5.0)

        v_norm = v.normalized()
        self.assertAlmostEqual(v_norm.length(), 1.0)
        self.assertAlmostEqual(v_norm.x, 0.6)
        self.assertAlmostEqual(v_norm.y, 0.8)

    def test_parallel_and_perpendicular(self):
        v1 = Vec3(2, 0, 0)
        v2 = Vec3(-5, 0, 0)
        v3 = Vec3(0, 3, 0)

        self.assertTrue(v1.is_parallel(v2))
        self.assertFalse(v1.is_parallel(v3))
        self.assertTrue(v1.is_perpendicular(v3))


class TestTabIntervals(unittest.TestCase):
    def test_tab_intervals_by_count(self):
        total_len = 100.0
        count = 3
        margin = 5.0
        intervals = calculate_tab_intervals(total_len, count=count, margin=margin, mode="by_count")

        self.assertEqual(len(intervals), 3)

        # Total active length = 100 - 10 = 90
        # 3 tabs, 2 gaps => 5 segments of 18.0 each
        # Tab 0: [5, 23]
        # Tab 1: [41, 59]
        # Tab 2: [77, 95]
        for it in intervals:
            self.assertAlmostEqual(it.length, 18.0)
            self.assertGreaterEqual(it.start, margin)
            self.assertLessEqual(it.end, total_len - margin)

        self.assertAlmostEqual(intervals[0].start, 5.0)
        self.assertAlmostEqual(intervals[0].end, 23.0)
        self.assertAlmostEqual(intervals[1].start, 41.0)
        self.assertAlmostEqual(intervals[1].end, 59.0)
        self.assertAlmostEqual(intervals[2].start, 77.0)
        self.assertAlmostEqual(intervals[2].end, 95.0)

    def test_single_tab(self):
        intervals = calculate_tab_intervals(50.0, count=1, margin=5.0)
        self.assertEqual(len(intervals), 1)
        self.assertTrue(intervals[0].start >= 5.0)
        self.assertTrue(intervals[0].end <= 45.0)

    def test_tab_intervals_by_length(self):
        intervals = calculate_tab_intervals(100.0, target_length=20.0, margin=5.0, mode="by_length")
        self.assertGreaterEqual(len(intervals), 2)
        for it in intervals:
            self.assertGreater(it.length, 0.0)
            self.assertGreaterEqual(it.start, 5.0)

    def test_margin_exceeds_length(self):
        # Should gracefully clamp margin and not crash
        intervals = calculate_tab_intervals(10.0, count=2, margin=8.0)
        self.assertEqual(len(intervals), 2)
        for it in intervals:
            self.assertGreater(it.length, 0.0)


class TestFingerIntervals(unittest.TestCase):
    def test_finger_alternation(self):
        total_len = 50.0
        finger_count = 5
        b1, b2 = calculate_finger_intervals(total_len, finger_count=finger_count, invert=False)

        # 5 fingers: b1 gets 0, 2, 4 (3 fingers); b2 gets 1, 3 (2 fingers)
        self.assertEqual(len(b1), 3)
        self.assertEqual(len(b2), 2)

        # Finger length is 10.0
        for f in b1 + b2:
            self.assertAlmostEqual(f.length, 10.0)

        # Check total span
        total_finger_len = sum(f.length for f in b1) + sum(f.length for f in b2)
        self.assertAlmostEqual(total_finger_len, total_len)

    def test_invert_parity(self):
        b1, b2 = calculate_finger_intervals(50.0, finger_count=4, invert=True)
        # Even indices (0, 2) go to b2, odd (1, 3) to b1
        self.assertEqual(len(b1), 2)
        self.assertEqual(len(b2), 2)
        self.assertEqual(b1[0].index, 1)
        self.assertEqual(b2[0].index, 0)


class TestClearanceAndBoxes(unittest.TestCase):
    def test_clearance_expansion(self):
        center = Vec3(0, 0, 0)
        u_len = Vec3(1, 0, 0)
        u_thk = Vec3(0, 1, 0)
        u_pen = Vec3(0, 0, 1)

        tab_box = create_tab_box_params(
            tab_center_pos=center,
            length_dir=u_len,
            thickness_dir=u_thk,
            penetration_dir=u_pen,
            tab_length=20.0,
            plate_thickness=3.0,
            penetration_depth=3.0,
            protrusion=0.5
        )

        self.assertAlmostEqual(tab_box.length, 20.0)
        self.assertAlmostEqual(tab_box.width, 3.0)
        self.assertAlmostEqual(tab_box.height, 3.5)

        # Slot clearance 0.15mm and overshoot 0.5mm
        slot_box = create_slot_box_params(tab_box, clearance=0.15, overshoot=0.5)

        self.assertAlmostEqual(slot_box.length, 20.30)  # 20 + 2*0.15
        self.assertAlmostEqual(slot_box.width, 3.30)    # 3 + 2*0.15
        self.assertAlmostEqual(slot_box.height, 4.50)   # 3.5 + 2*0.5


class TestCrossJointSlots(unittest.TestCase):
    def test_cross_joint_dimensions(self):
        center = Vec3(0, 0, 0)
        edge_dir = Vec3(0, 0, 1)
        n1 = Vec3(1, 0, 0)
        n2 = Vec3(0, 1, 0)

        box1, box2 = calculate_cross_joint_slots(
            intersection_center=center,
            edge_dir=edge_dir,
            normal_1=n1,
            normal_2=n2,
            height_1=40.0,
            height_2=40.0,
            thickness_1=3.0,
            thickness_2=3.0,
            clearance=0.15,
            overshoot=0.5
        )

        # Half depth = 20.0 + 0.5 overshoot = 20.5
        self.assertAlmostEqual(box1.length, 20.5)
        self.assertAlmostEqual(box2.length, 20.5)

        # Slot 1 width receives Plate 2 (3.0 + 2*0.15 = 3.3)
        self.assertAlmostEqual(box1.width, 3.3)
        self.assertAlmostEqual(box2.width, 3.3)


if __name__ == "__main__":
    unittest.main()
