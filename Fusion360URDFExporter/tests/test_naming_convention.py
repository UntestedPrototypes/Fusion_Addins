"""Tests for kinematic tree builder and joint naming conventions."""

import unittest
from core.tree_walker import OccurrenceNode
from core.joint_analyzer import JointInfo
from core.kinematic_builder import KinematicTreeBuilder


class MockNode(OccurrenceNode):
    def __init__(self, name, full_path, depth=0, parent=None):
        super().__init__(None, parent, depth)
        self.name = name
        self.full_path = full_path
        self.depth = depth


class TestKinematicNaming(unittest.TestCase):
    def test_default_multi_chain_multi_level_naming(self):
        """Test default {branch_name}_c{chain}_l{level} naming on multi-limb robot (Leg 1 & Leg 2)."""
        root = MockNode('root', 'root', depth=0)
        leg1 = MockNode('Leg_1:1', 'Leg_1:1', depth=1, parent=root)
        leg1_coxa = MockNode('Coxa:1', 'Leg_1:1/Coxa:1', depth=2, parent=leg1)
        leg1_femur = MockNode('Femur:1', 'Leg_1:1/Femur:1', depth=2, parent=leg1)
        leg1_tibia = MockNode('Tibia:1', 'Leg_1:1/Tibia:1', depth=2, parent=leg1)

        leg2 = MockNode('Leg_2:1', 'Leg_2:1', depth=1, parent=root)
        leg2_coxa = MockNode('Coxa:1', 'Leg_2:1/Coxa:1', depth=2, parent=leg2)
        leg2_femur = MockNode('Femur:1', 'Leg_2:1/Femur:1', depth=2, parent=leg2)
        leg2_tibia = MockNode('Tibia:1', 'Leg_2:1/Tibia:1', depth=2, parent=leg2)

        nodes = {
            'root': root,
            'Leg_1:1': leg1,
            'Leg_1:1/Coxa:1': leg1_coxa,
            'Leg_1:1/Femur:1': leg1_femur,
            'Leg_1:1/Tibia:1': leg1_tibia,
            'Leg_2:1': leg2,
            'Leg_2:1/Coxa:1': leg2_coxa,
            'Leg_2:1/Femur:1': leg2_femur,
            'Leg_2:1/Tibia:1': leg2_tibia,
        }

        # Leg 1 joints: root -> Coxa -> Femur -> Tibia
        j1_1 = JointInfo(name="j1_1", joint_type="revolute", parent_link_path='root', child_link_path='Leg_1:1/Coxa:1')
        j1_2 = JointInfo(name="j1_2", joint_type="revolute", parent_link_path='Leg_1:1/Coxa:1', child_link_path='Leg_1:1/Femur:1')
        j1_3 = JointInfo(name="j1_3", joint_type="revolute", parent_link_path='Leg_1:1/Femur:1', child_link_path='Leg_1:1/Tibia:1')

        # Leg 2 joints: root -> Coxa -> Femur -> Tibia
        j2_1 = JointInfo(name="j2_1", joint_type="revolute", parent_link_path='root', child_link_path='Leg_2:1/Coxa:1')
        j2_2 = JointInfo(name="j2_2", joint_type="revolute", parent_link_path='Leg_2:1/Coxa:1', child_link_path='Leg_2:1/Femur:1')
        j2_3 = JointInfo(name="j2_3", joint_type="revolute", parent_link_path='Leg_2:1/Femur:1', child_link_path='Leg_2:1/Tibia:1')

        builder = KinematicTreeBuilder(nodes, [j1_1, j1_2, j1_3, j2_1, j2_2, j2_3])
        links, joints = builder.build()

        names = [j.name for j in joints]
        self.assertEqual(len(joints), 6)
        # Leg 1: Chain 1
        self.assertEqual(joints[0].name, "leg_1_c1_l1")
        self.assertEqual(joints[1].name, "leg_1_c1_l2")
        self.assertEqual(joints[2].name, "leg_1_c1_l3")
        # Leg 2: Chain 2
        self.assertEqual(joints[3].name, "leg_2_c2_l1")
        self.assertEqual(joints[4].name, "leg_2_c2_l2")
        self.assertEqual(joints[5].name, "leg_2_c2_l3")

    def test_type_c_l_preset(self):
        """Test {type}_c{chain}_l{level} preset."""
        root = MockNode('root', 'root', depth=0)
        arm1 = MockNode('Arm_1:1', 'Arm_1:1', depth=1, parent=root)
        arm2 = MockNode('Arm_2:1', 'Arm_2:1', depth=1, parent=root)

        nodes = {'root': root, 'Arm_1:1': arm1, 'Arm_2:1': arm2}
        j1 = JointInfo(name="j1", joint_type="revolute", parent_link_path='root', child_link_path='Arm_1:1')
        j2 = JointInfo(name="j2", joint_type="prismatic", parent_link_path='root', child_link_path='Arm_2:1')

        builder = KinematicTreeBuilder(nodes, [j1, j2], naming_pattern='{type}_c{chain}_l{level}')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "revolute_c1_l1")
        self.assertEqual(joints[1].name, "prismatic_c2_l1")

    def test_type_chain_level_numbers_preset(self):
        """Test {type}_{chain}_{level} preset."""
        root = MockNode('root', 'root', depth=0)
        arm1 = MockNode('Arm_1:1', 'Arm_1:1', depth=1, parent=root)
        nodes = {'root': root, 'Arm_1:1': arm1}
        j1 = JointInfo(name="j1", joint_type="revolute", parent_link_path='root', child_link_path='Arm_1:1')

        builder = KinematicTreeBuilder(nodes, [j1], naming_pattern='{type}_{chain}_{level}')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "revolute_1_1")

    def test_joint_c_l_preset(self):
        """Test joint_c{chain}_l{level} preset."""
        root = MockNode('root', 'root', depth=0)
        arm1 = MockNode('Arm_1:1', 'Arm_1:1', depth=1, parent=root)
        nodes = {'root': root, 'Arm_1:1': arm1}
        j1 = JointInfo(name="j1", joint_type="revolute", parent_link_path='root', child_link_path='Arm_1:1')

        builder = KinematicTreeBuilder(nodes, [j1], naming_pattern='joint_c{chain}_l{level}')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "joint_c1_l1")

    def test_branch_joint_level_preset(self):
        """Test {branch_name}_joint_{level} preset."""
        root = MockNode('root', 'root', depth=0)
        leg = MockNode('Leg_1:1', 'Leg_1:1', depth=1, parent=root)
        nodes = {'root': root, 'Leg_1:1': leg}
        j1 = JointInfo(name="j1", joint_type="revolute", parent_link_path='root', child_link_path='Leg_1:1')

        builder = KinematicTreeBuilder(nodes, [j1], naming_pattern='{branch_name}_joint_{level}')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "leg_1_joint_1")

    def test_bracket_typo_tolerance(self):
        """Test tolerance for mismatched bracket typos like {branch_name]_c{chain}_l{level)."""
        root = MockNode('root', 'root', depth=0)
        leg = MockNode('Leg_1:1', 'Leg_1:1', depth=1, parent=root)
        nodes = {'root': root, 'Leg_1:1': leg}
        j1 = JointInfo(name="j1", joint_type="revolute", parent_link_path='root', child_link_path='Leg_1:1')

        builder = KinematicTreeBuilder(nodes, [j1], naming_pattern='{branch_name]_c{chain}_l{level)')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "leg_1_c1_l1")

    def test_parallel_branches_at_same_level(self):
        """Test parallel fingers at same level in a chain receive disambiguation suffixes (a, b)."""
        root = MockNode('root', 'root', depth=0)
        arm = MockNode('Arm:1', 'Arm:1', depth=1, parent=root)
        fingerA = MockNode('FingerA:1', 'Arm:1/FingerA:1', depth=2, parent=arm)
        fingerB = MockNode('FingerB:1', 'Arm:1/FingerB:1', depth=2, parent=arm)

        nodes = {
            'root': root,
            'Arm:1': arm,
            'Arm:1/FingerA:1': fingerA,
            'Arm:1/FingerB:1': fingerB,
        }

        j_arm = JointInfo(name="j_arm", joint_type="revolute", parent_link_path='root', child_link_path='Arm:1')
        j_fa = JointInfo(name="j_fa", joint_type="revolute", parent_link_path='Arm:1', child_link_path='Arm:1/FingerA:1')
        j_fb = JointInfo(name="j_fb", joint_type="revolute", parent_link_path='Arm:1', child_link_path='Arm:1/FingerB:1')

        builder = KinematicTreeBuilder(nodes, [j_arm, j_fa, j_fb])
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "arm_c1_l1")
        self.assertEqual(joints[1].name, "arm_c1_l2a")
        self.assertEqual(joints[2].name, "arm_c1_l2b")

    def test_legacy_sequential_naming(self):
        """Test legacy sequential naming preset {type}_{level}."""
        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/link1': MockNode('link1:1', 'root/link1', depth=1),
            'root/link1/link2': MockNode('link2:1', 'root/link1/link2', depth=2),
            'root/link1/link2/link3': MockNode('link3:1', 'root/link1/link2/link3', depth=3),
        }

        j1 = JointInfo(name="u1", joint_type="revolute", parent_link_path='root', child_link_path='root/link1')
        j2 = JointInfo(name="u2", joint_type="revolute", parent_link_path='root/link1', child_link_path='root/link1/link2')
        j3 = JointInfo(name="u3", joint_type="revolute", parent_link_path='root/link1/link2', child_link_path='root/link1/link2/link3')

        builder = KinematicTreeBuilder(nodes, [j1, j2, j3], naming_pattern='{type}_{level}')
        links, joints = builder.build()

        self.assertEqual(joints[0].name, "revolute_1")
        self.assertEqual(joints[1].name, "revolute_2")
        self.assertEqual(joints[2].name, "revolute_3")


if __name__ == '__main__':
    unittest.main()
