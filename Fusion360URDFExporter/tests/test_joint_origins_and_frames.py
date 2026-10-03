"""Unit tests for Joint Origin frame extraction and kinematic tree frame propagation."""

import unittest
import math
from config.defaults import CM_TO_M
from core.transform_utils import (
    make_frame_4x4,
    pure_matrix_invert,
    pure_matrix_multiply,
    pure_matrix_to_rpy,
    to_flat_matrix,
    IDENTITY_16
)
from core.tree_walker import OccurrenceNode
from core.joint_analyzer import JointInfo, JointAnalyzer
from core.kinematic_builder import KinematicTreeBuilder


class TestJointOriginsAndFrames(unittest.TestCase):
    def test_make_frame_4x4_orthonormality(self):
        """Test that make_frame_4x4 produces a valid orthonormal, right-handed frame."""
        origin = [10.0, 20.0, 30.0]
        # Primary axis along X (1, 0, 0), secondary along Y (0, 1, 0)
        frame = make_frame_4x4(origin, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

        # Verify origin in column 3
        self.assertAlmostEqual(frame[3], 10.0)
        self.assertAlmostEqual(frame[7], 20.0)
        self.assertAlmostEqual(frame[11], 30.0)

        # In make_frame_4x4: Z is primary axis [1, 0, 0] -> column 2
        self.assertAlmostEqual(frame[2], 1.0)
        self.assertAlmostEqual(frame[6], 0.0)
        self.assertAlmostEqual(frame[10], 0.0)

        # X is secondary -> column 0
        self.assertAlmostEqual(frame[0], 0.0)
        self.assertAlmostEqual(frame[4], 1.0)
        self.assertAlmostEqual(frame[8], 0.0)

        # Y = Z x X -> column 1: [1,0,0] x [0,1,0] = [0,0,1]
        self.assertAlmostEqual(frame[1], 0.0)
        self.assertAlmostEqual(frame[5], 0.0)
        self.assertAlmostEqual(frame[9], 1.0)

        # Determinant of 3x3 must be +1
        det = (
            frame[0] * (frame[5] * frame[10] - frame[6] * frame[9]) -
            frame[1] * (frame[4] * frame[10] - frame[6] * frame[8]) +
            frame[2] * (frame[4] * frame[9] - frame[5] * frame[8])
        )
        self.assertAlmostEqual(det, 1.0)

    def test_relative_transform_chaining(self):
        """Test relative transform between two chained joint frames."""
        # Joint 1 at world (0, 0, 10 cm), rotation identity
        t1 = make_frame_4x4([0.0, 0.0, 10.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])

        # Joint 2 at world (0, 15 cm, 10 cm), rotated 90 deg around X:
        # Z axis is [0, 1, 0], X axis is [1, 0, 0]
        t2 = make_frame_4x4([0.0, 15.0, 10.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0])

        # T_rel = T1^-1 * T2
        t1_inv = pure_matrix_invert(t1)
        t_rel = pure_matrix_multiply(t1_inv, t2)

        # Relative translation: should be dx=0, dy=15 cm, dz=0 cm
        dx = t_rel[3] * CM_TO_M
        dy = t_rel[7] * CM_TO_M
        dz = t_rel[11] * CM_TO_M

        self.assertAlmostEqual(dx, 0.0)
        self.assertAlmostEqual(dy, 0.15)
        self.assertAlmostEqual(dz, 0.0)

    def test_kinematic_builder_frame_propagation(self):
        """Test that KinematicTreeBuilder correctly uses Joint Origin world frames."""
        # Setup base_link, link_1, link_2
        base_node = OccurrenceNode(None, None, depth=0)
        base_node.name = 'base_link'
        base_node.full_path = 'root'

        node1 = OccurrenceNode(None, base_node, depth=1)
        node1.name = 'arm_link1:1'
        node1.full_path = 'root/arm_link1:1'

        node2 = OccurrenceNode(None, node1, depth=2)
        node2.name = 'arm_link2:1'
        node2.full_path = 'root/arm_link1:1/arm_link2:1'

        nodes = {
            'root': base_node,
            node1.full_path: node1,
            node2.full_path: node2
        }

        # Joint 1: connects base to link1 at (0, 0, 20 cm)
        j1 = JointInfo()
        j1.name = 'joint1'
        j1.joint_type = 'revolute'
        j1.parent_link_path = 'root'
        j1.child_link_path = node1.full_path
        j1.world_frame_cm = make_frame_4x4([0.0, 0.0, 20.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
        j1.axis = [0.0, 0.0, 1.0]

        # Joint 2: connects link1 to link2 at (0, 30 cm, 20 cm)
        j2 = JointInfo()
        j2.name = 'joint2'
        j2.joint_type = 'revolute'
        j2.parent_link_path = node1.full_path
        j2.child_link_path = node2.full_path
        j2.world_frame_cm = make_frame_4x4([0.0, 30.0, 20.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
        j2.axis = [0.0, 0.0, 1.0]

        builder = KinematicTreeBuilder(nodes, [j1, j2])
        links, joints = builder.build()

        self.assertEqual(len(links), 3)
        self.assertEqual(len(joints), 2)

        link_map = {l.name: l for l in links}
        joint_map = {j.name: j for j in joints}

        # Base link frame must be identity
        self.assertEqual(link_map['base_link'].frame_world_transform, IDENTITY_16)

        # Link 1 frame must match Joint 1 world frame
        self.assertEqual(link_map['arm_link1_link'].frame_world_transform, j1.world_frame_cm)

        # Link 2 frame must match Joint 2 world frame
        self.assertEqual(link_map['arm_link2_link'].frame_world_transform, j2.world_frame_cm)

        # Joint 1 origin in base: (0, 0, 0.2 m)
        urdf_j1 = joints[0]
        self.assertAlmostEqual(urdf_j1.origin_xyz[0], 0.0)
        self.assertAlmostEqual(urdf_j1.origin_xyz[1], 0.0)
        self.assertAlmostEqual(urdf_j1.origin_xyz[2], 0.20)
        self.assertEqual(urdf_j1.axis, [0.0, 0.0, 1.0])

        # Joint 2 origin relative to Joint 1: dx=0, dy=0.3 m, dz=0 m
        urdf_j2 = joints[1]
        self.assertAlmostEqual(urdf_j2.origin_xyz[0], 0.0)
        self.assertAlmostEqual(urdf_j2.origin_xyz[1], 0.30)
        self.assertAlmostEqual(urdf_j2.origin_xyz[2], 0.0)
        self.assertEqual(urdf_j2.axis, [0.0, 0.0, 1.0])

    def test_custom_base_origin_and_root_component(self):
        """Test that selecting a root component occurrence and custom Joint Origin frame anchors base_link."""
        # Base occurrence at (10, 20, 5 cm)
        base_occ_node = OccurrenceNode(None, None, depth=1)
        base_occ_node.name = 'robot_base:1'
        base_occ_node.full_path = 'root/robot_base:1'

        node1 = OccurrenceNode(None, base_occ_node, depth=2)
        node1.name = 'arm_link1:1'
        node1.full_path = 'root/robot_base:1/arm_link1:1'

        nodes = {
            'root': OccurrenceNode(None, None, depth=0),
            base_occ_node.full_path: base_occ_node,
            node1.full_path: node1
        }

        # User selected a Joint Origin at world (10, 20, 15 cm) as the URDF base origin
        custom_base_origin = make_frame_4x4([10.0, 20.0, 15.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])

        # Joint 1 connects robot_base to arm_link1 at world (10, 20, 35 cm)
        j1 = JointInfo()
        j1.name = 'joint1'
        j1.joint_type = 'revolute'
        j1.parent_link_path = base_occ_node.full_path
        j1.child_link_path = node1.full_path
        j1.world_frame_cm = make_frame_4x4([10.0, 20.0, 35.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
        j1.axis = [0.0, 0.0, 1.0]

        builder = KinematicTreeBuilder(
            nodes,
            [j1],
            base_node=base_occ_node,
            base_origin_world_frame=custom_base_origin
        )
        links, joints = builder.build()

        link_map = {l.name: l for l in links}
        joint_map = {j.name: j for j in joints}

        # Verify base_link corresponds to robot_base and has custom base frame
        self.assertIn('base_link', link_map)
        self.assertEqual(link_map['base_link'].frame_world_transform, custom_base_origin)

        # Verify joint1 connects base_link -> arm_link1_link
        urdf_j1 = joints[0]
        self.assertEqual(urdf_j1.parent_link, 'base_link')
        self.assertEqual(urdf_j1.child_link, 'arm_link1_link')

        # Origin of joint1 relative to base origin:
        # dx = 10 - 10 = 0 cm -> 0.0 m
        # dy = 20 - 20 = 0 cm -> 0.0 m
        # dz = 35 - 15 = 20 cm -> 0.20 m
        self.assertAlmostEqual(urdf_j1.origin_xyz[0], 0.0)
        self.assertAlmostEqual(urdf_j1.origin_xyz[1], 0.0)
        self.assertAlmostEqual(urdf_j1.origin_xyz[2], 0.20)

    def test_assembly_tree_walker_selected_base_occ(self):
        """Test that AssemblyTreeWalker designates selected_base_occ as base_node."""
        from core.tree_walker import AssemblyTreeWalker

        class MockOcc:
            def __init__(self, name, full_path, is_grounded=False):
                self.name = name
                self.fullPathName = full_path
                self.component = None
                self.isGrounded = is_grounded
                self.bRepBodies = []
                self.childOccurrences = []

        class MockRoot:
            def __init__(self, occs):
                self.name = 'RootAssembly'
                self.bRepBodies = []
                self.occurrences = occs

        occ_base = MockOcc('BasePart:1', 'Root+BasePart:1')
        occ_link1 = MockOcc('LinkPart:1', 'Root+LinkPart:1')
        mock_root = MockRoot([occ_base, occ_link1])

        # Walker with selected base occurrence
        walker = AssemblyTreeWalker(mock_root, selected_base_occ=occ_base)
        walker.walk()

        self.assertIsNotNone(walker.base_node)
        self.assertEqual(walker.base_node.occurrence, occ_base)

    def test_gimbal_lock_pitch_negative_90_preserves_z_axis(self):
        """Verify that pitch = -90 deg (common on wrist roll joints) does not invert yaw or Z axis."""
        def rpy_to_matrix(roll, pitch, yaw):
            cr, sr = math.cos(roll), math.sin(roll)
            cp, sp = math.cos(pitch), math.sin(pitch)
            cy, sy = math.cos(yaw), math.sin(yaw)
            r00 = cy * cp
            r01 = cy * sp * sr - sy * cr
            r02 = cy * sp * cr + sy * sr
            r10 = sy * cp
            r11 = sy * sp * sr + cy * cr
            r12 = sy * sp * cr - cy * sr
            r20 = -sp
            r21 = cp * sr
            r22 = cp * cr
            return (r00, r01, r02, r10, r11, r12, r20, r21, r22)

        # Test various yaw angles at pitch = -pi/2
        for yaw_deg in [-135, -90, -45, 0, 45, 90, 135, 180]:
            yaw = math.radians(yaw_deg)
            m = rpy_to_matrix(0.0, -math.pi / 2, yaw)
            r_out, p_out, y_out = pure_matrix_to_rpy(*m)
            m_rec = rpy_to_matrix(r_out, p_out, y_out)

            # Reconstructed matrix must match original
            for orig_val, rec_val in zip(m, m_rec):
                self.assertAlmostEqual(orig_val, rec_val, places=5)

            # Specifically verify Z axis vector (column 2) is NOT flipped
            orig_z = (m[2], m[5], m[8])
            rec_z = (m_rec[2], m_rec[5], m_rec[8])
            self.assertAlmostEqual(orig_z[0], rec_z[0], places=5)
            self.assertAlmostEqual(orig_z[1], rec_z[1], places=5)
            self.assertAlmostEqual(orig_z[2], rec_z[2], places=5)

    def test_motion_flipped_does_not_trigger_on_joint_is_flipped(self):
        """Verify that CAD geometric alignment isFlipped does not flip the kinematic motion axis."""
        analyzer = JointAnalyzer(None)
        
        class MockJoint:
            def __init__(self, joint_flipped, motion_flipped):
                self.isFlipped = joint_flipped
                self.jointMotion = MockMotion(motion_flipped)

        class MockMotion:
            def __init__(self, flipped):
                self.isFlipped = flipped

        j_geom_flipped = MockJoint(joint_flipped=True, motion_flipped=False)
        self.assertFalse(analyzer._is_motion_flipped(j_geom_flipped))

        j_motion_flipped = MockJoint(joint_flipped=False, motion_flipped=True)
        self.assertTrue(analyzer._is_motion_flipped(j_motion_flipped))


if __name__ == '__main__':
    unittest.main()
