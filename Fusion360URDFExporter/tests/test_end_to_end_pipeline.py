"""End-to-end integration test simulating a multi-DOF robot with rigid groups and subassemblies."""

import unittest
import os
import tempfile
import xml.etree.ElementTree as ET
from core.tree_walker import OccurrenceNode
from core.rigid_resolver import RigidGroupResolver
from core.joint_analyzer import JointInfo
from core.kinematic_builder import KinematicTreeBuilder
from core.inertial_calc import InertialCalculator
from core.urdf_writer import URDFWriter


class MockOccurrence:
    def __init__(self, name, fullPathName, depth=0, parent=None, isGrounded=False):
        self.name = name
        self.fullPathName = fullPathName
        self.depth = depth
        self.parent = parent
        self.isGrounded = isGrounded
        self.component = None


class MockBodySim:
    def __init__(self, name, mass=1.0, com=None, inertia=None):
        self.name = name
        self.mass = mass
        self.com = com or [0.0, 0.0, 0.0]
        self.inertia = inertia or {
            'ixx': 0.001, 'ixy': 0.0, 'ixz': 0.0,
            'iyy': 0.001, 'iyz': 0.0, 'izz': 0.001
        }


class TestEndToEndPipeline(unittest.TestCase):
    def test_complete_robot_export_pipeline(self):
        """Simulate a robot arm with:
        - Base
        - Shoulder (revolute joint from base)
        - Upper arm (revolute joint from shoulder)
          - Rigid group: sensor_mount and motor_bracket merged into upper arm
        - Forearm (revolute joint from upper arm)
          - Two parallel gripper fingers at same level: finger_a and finger_b
        """
        # 1. Setup OccurrenceNodes
        base_node = OccurrenceNode(None, None, depth=0)
        base_node.name = 'base_link'
        base_node.full_path = 'root'
        base_node.bodies = [MockBodySim('base_body', mass=10.0)]

        shoulder_node = OccurrenceNode(None, base_node, depth=1)
        shoulder_node.name = 'shoulder:1'
        shoulder_node.full_path = 'root/shoulder:1'
        shoulder_node.bodies = [MockBodySim('shoulder_body', mass=3.0)]

        upper_arm_node = OccurrenceNode(None, shoulder_node, depth=2)
        upper_arm_node.name = 'upper_arm:1'
        upper_arm_node.full_path = 'root/shoulder:1/upper_arm:1'
        upper_arm_node.bodies = [MockBodySim('upper_arm_body', mass=2.5)]

        # Rigid group children under upper arm
        sensor_node = OccurrenceNode(None, upper_arm_node, depth=3)
        sensor_node.name = 'sensor_mount:1'
        sensor_node.full_path = 'root/shoulder:1/upper_arm:1/sensor_mount:1'
        sensor_node.bodies = [MockBodySim('sensor_body', mass=0.2)]

        bracket_node = OccurrenceNode(None, upper_arm_node, depth=3)
        bracket_node.name = 'bracket:1'
        bracket_node.full_path = 'root/shoulder:1/upper_arm:1/bracket:1'
        bracket_node.bodies = [MockBodySim('bracket_body', mass=0.3)]

        # Forearm
        forearm_node = OccurrenceNode(None, upper_arm_node, depth=3)
        forearm_node.name = 'forearm:1'
        forearm_node.full_path = 'root/shoulder:1/upper_arm:1/forearm:1'
        forearm_node.bodies = [MockBodySim('forearm_body', mass=1.5)]

        # Two gripper fingers at depth 4
        finger_a_node = OccurrenceNode(None, forearm_node, depth=4)
        finger_a_node.name = 'finger_a:1'
        finger_a_node.full_path = 'root/shoulder:1/upper_arm:1/forearm:1/finger_a:1'
        finger_a_node.bodies = [MockBodySim('finger_a_body', mass=0.1)]

        finger_b_node = OccurrenceNode(None, forearm_node, depth=4)
        finger_b_node.name = 'finger_b:1'
        finger_b_node.full_path = 'root/shoulder:1/upper_arm:1/forearm:1/finger_b:1'
        finger_b_node.bodies = [MockBodySim('finger_b_body', mass=0.1)]

        nodes = {
            'root': base_node,
            shoulder_node.full_path: shoulder_node,
            upper_arm_node.full_path: upper_arm_node,
            sensor_node.full_path: sensor_node,
            bracket_node.full_path: bracket_node,
            forearm_node.full_path: forearm_node,
            finger_a_node.full_path: finger_a_node,
            finger_b_node.full_path: finger_b_node
        }

        # 2. Run RigidGroupResolver: Merge sensor and bracket into upper_arm
        class MockCompSim:
            def __init__(self, rgs):
                self.rigidGroups = rgs

        class MockRGSim:
            def __init__(self, occ_paths):
                self.isSuppressed = False
                self.occurrences = [MockOccurrence(p.split('/')[-1], p) for p in occ_paths]

        # Rigid group defined in upper_arm containing upper_arm, sensor, bracket
        rg = MockRGSim([upper_arm_node.full_path, sensor_node.full_path, bracket_node.full_path])
        upper_arm_node.component = MockCompSim([rg])

        resolver = RigidGroupResolver(MockCompSim([]), nodes)
        resolver.resolve()

        self.assertTrue(sensor_node.is_merged)
        self.assertTrue(bracket_node.is_merged)
        self.assertFalse(upper_arm_node.is_merged)
        # Upper arm now contains 3 bodies (its own + sensor + bracket)
        self.assertEqual(len(upper_arm_node.bodies), 3)

        # 3. Setup Joints
        # Joint 1: base -> shoulder (revolute)
        j1 = JointInfo()
        j1.joint_type = 'revolute'
        j1.parent_link_path = 'root'
        j1.child_link_path = shoulder_node.full_path
        j1.origin_xyz = [0, 0, 0.1]
        j1.axis = [0, 0, 1]

        # Joint 2: shoulder -> upper_arm (revolute)
        j2 = JointInfo()
        j2.joint_type = 'revolute'
        j2.parent_link_path = shoulder_node.full_path
        j2.child_link_path = upper_arm_node.full_path
        j2.origin_xyz = [0, 0.1, 0.2]
        j2.axis = [0, 1, 0]

        # Joint 3: upper_arm -> forearm (revolute)
        j3 = JointInfo()
        j3.joint_type = 'revolute'
        j3.parent_link_path = upper_arm_node.full_path
        j3.child_link_path = forearm_node.full_path
        j3.origin_xyz = [0, 0, 0.3]
        j3.axis = [0, 1, 0]

        # Parallel finger joints at depth 4: forearm -> finger_a and forearm -> finger_b
        j4a = JointInfo()
        j4a.joint_type = 'revolute'
        j4a.parent_link_path = forearm_node.full_path
        j4a.child_link_path = finger_a_node.full_path
        j4a.origin_xyz = [0.05, 0, 0.1]
        j4a.axis = [1, 0, 0]

        j4b = JointInfo()
        j4b.joint_type = 'revolute'
        j4b.parent_link_path = forearm_node.full_path
        j4b.child_link_path = finger_b_node.full_path
        j4b.origin_xyz = [-0.05, 0, 0.1]
        j4b.axis = [1, 0, 0]

        all_joint_infos = [j1, j2, j3, j4a, j4b]

        # 4. Build Kinematic Tree
        builder = KinematicTreeBuilder(nodes, all_joint_infos, naming_pattern='{type}_{level}')
        links, joints = builder.build()

        # Check links count: 8 initial - 2 merged (sensor & bracket) = 6 links
        self.assertEqual(len(links), 6)
        link_names = [l.name for l in links]
        self.assertIn('base_link', link_names)
        self.assertIn('shoulder_link', link_names)
        self.assertIn('upper_arm_link', link_names)
        self.assertIn('forearm_link', link_names)
        self.assertIn('finger_a_link', link_names)
        self.assertIn('finger_b_link', link_names)

        # Check joint naming
        # Serial: revolute_1, revolute_2, revolute_3
        # Parallel at finger level: revolute_4A, revolute_4B
        joint_names = [j.name for j in joints]
        self.assertEqual(joint_names, [
            'revolute_1',
            'revolute_2',
            'revolute_3',
            'revolute_4A',
            'revolute_4B'
        ])

        # 5. Compute Inertia
        calc = InertialCalculator()
        for link in links:
            calc.compute_link_inertial(link)

        upper_arm_link = next(l for l in links if l.name == 'upper_arm_link')
        # Mass = 2.5 + 0.2 + 0.3 = 3.0 kg
        self.assertAlmostEqual(upper_arm_link.mass, 3.0)

        # Assign dummy mesh paths
        for link in links:
            link.visual_mesh_path = f"meshes/visual/{link.name}.stl"
            link.collision_mesh_path = f"meshes/collision/{link.name}.stl"

        # 6. Generate URDF
        writer = URDFWriter('simulated_arm', links, joints)
        urdf_xml = writer.generate()

        # 7. Validate XML
        root = ET.fromstring(urdf_xml)
        self.assertEqual(root.attrib['name'], 'simulated_arm')
        self.assertEqual(len(root.findall('link')), 6)
        self.assertEqual(len(root.findall('joint')), 5)

    def test_pentapod_base_and_coxa_isolation_pipeline(self):
        """Test realistic robot model like Penta_Assembly_Export where:
        - Selected base is Penta_Body:1 with child sheet metal plates
        - Leg_1:1 contains PENTA_Leg_Coxa:1 (4 bodies)
        - Coxa has a revolute joint to Penta_Body
        - CAD contains rigid joints (grounding to root, bearing between coxa and body)
        - Verify: Coxa bodies NEVER merge into base_link!
        """
        root_node = OccurrenceNode(None, None, depth=0)
        root_node.name = 'root'
        root_node.full_path = 'root'

        # Base node: Penta_Body:1
        base_node = OccurrenceNode(None, root_node, depth=1)
        base_node.name = 'Penta_Body:1'
        base_node.full_path = 'Penta_Body:1'
        base_bodies = [MockBodySim(f'body_b{i}') for i in range(20)]
        base_node.bodies = list(base_bodies)

        # Sheet plate under base node
        sheet_node = OccurrenceNode(None, base_node, depth=2)
        sheet_node.name = 'PENTA_Body_Sheet_MidPlate:1'
        sheet_node.full_path = 'Penta_Body:1+PENTA_Body_Sheet_MidPlate:1'
        sheet_body = MockBodySim('sheet_mid')
        sheet_node.bodies = [sheet_body]

        # Leg 1 assembly container (0 bodies)
        leg1_node = OccurrenceNode(None, root_node, depth=1)
        leg1_node.name = 'Leg_1:1'
        leg1_node.full_path = 'Leg_1:1'

        # Coxa under Leg 1 (4 bodies)
        coxa_node = OccurrenceNode(None, leg1_node, depth=2)
        coxa_node.name = 'PENTA_Leg_Coxa:1'
        coxa_node.full_path = 'Leg_1:1+PENTA_Leg_Coxa:1'
        coxa_bodies = [
            MockBodySim('PENTA_Leg_Coxa_A'),
            MockBodySim('PENTA_Leg_Coxa_B'),
            MockBodySim('PENTA_Leg_Coxa_Rotator_A'),
            MockBodySim('PENTA_Leg_Coxa_Rotator_B')
        ]
        coxa_node.bodies = list(coxa_bodies)

        nodes = {
            'root': root_node,
            base_node.full_path: base_node,
            sheet_node.full_path: sheet_node,
            leg1_node.full_path: leg1_node,
            coxa_node.full_path: coxa_node
        }

        # Step 2: Kinematic Joints Analyzed First
        j_coxa = JointInfo()
        j_coxa.name = 'revolute_coxa'
        j_coxa.joint_type = 'revolute'
        j_coxa.parent_link_path = base_node.full_path
        j_coxa.child_link_path = coxa_node.full_path
        j_coxa.origin_xyz = [0.1, 0.0, 0.05]
        j_coxa.axis = [0.0, 0.0, 1.0]
        joint_infos = [j_coxa]

        protected_paths = {ji.child_link_path for ji in joint_infos if ji.child_link_path}

        # Step 3: Rigid Group and Joint Resolution
        class MockCompPenta:
            def __init__(self, rgs=None):
                self.rigidGroups = rgs or []

        class MockJointSim:
            def __init__(self, p1, p2, is_rigid=True):
                self.isSuppressed = False
                class M:
                    jointType = 'RigidJointType' if is_rigid else 'RevoluteJointType'
                self.jointMotion = M()
                self.occurrenceOne = MockOccurrence(p1.split('+')[-1], p1) if p1 else None
                self.occurrenceTwo = MockOccurrence(p2.split('+')[-1], p2) if p2 else None

        class MockRootAssembly:
            def __init__(self, joints, rgs):
                self.joints = joints
                self.rigidGroups = rgs
                self.asBuiltJoints = []

        # CAD relationships:
        # 1. Base plate rigidly grouped to Penta_Body
        class MockRG:
            isSuppressed = False
            occurrences = [
                MockOccurrence(base_node.name, base_node.full_path),
                MockOccurrence(sheet_node.name, sheet_node.full_path)
            ]
        rg_base = MockRG()
        base_node.component = MockCompPenta([rg_base])

        # 2. Base grounded to root (Rigid joint)
        j_ground = MockJointSim(base_node.full_path, None, is_rigid=True)
        # 3. Rigid joint between Coxa bearing and base mount
        j_bearing = MockJointSim(coxa_node.full_path, base_node.full_path, is_rigid=True)

        root_comp = MockRootAssembly(joints=[j_ground, j_bearing], rgs=[])

        resolver = RigidGroupResolver(
            root_comp,
            nodes,
            base_node=base_node,
            protected_paths=protected_paths
        )
        resolver.resolve()

        # Verifications on occurrence nodes:
        # - Base node must NOT be merged into root
        self.assertFalse(base_node.is_merged)
        # - Sheet plate MUST be merged into base node
        self.assertTrue(sheet_node.is_merged)
        # - Coxa must NOT be merged into base node or root!
        self.assertFalse(coxa_node.is_merged)
        # - Base node bodies = 20 direct + 1 sheet = 21 bodies
        self.assertEqual(len(base_node.bodies), 21)
        # - Coxa bodies = exactly 4 bodies
        self.assertEqual(len(coxa_node.bodies), 4)

        # Step 4: Kinematic Tree Builder
        builder = KinematicTreeBuilder(
            nodes,
            joint_infos,
            base_node=base_node
        )
        links, joints = builder.build()

        base_link = next(l for l in links if l.name == 'base_link')
        coxa_link = next(l for l in links if 'coxa' in l.name)

        # Base link has ONLY the 21 base bodies
        self.assertEqual(len(base_link.bodies), 21)
        self.assertIn(sheet_body, base_link.bodies)
        for cb in coxa_bodies:
            self.assertNotIn(cb, base_link.bodies)

        # Coxa link has ALL 4 coxa bodies!
        self.assertEqual(len(coxa_link.bodies), 4)
        for cb in coxa_bodies:
            self.assertIn(cb, coxa_link.bodies)

        # Joint connects base_link -> coxa_link
        self.assertEqual(len(joints), 1)
        self.assertEqual(joints[0].parent_link, 'base_link')
        self.assertEqual(joints[0].child_link, coxa_link.name)
        self.assertEqual(joints[0].name, 'leg_1_c1_l1')
        self.assertEqual(joints[0].chain, 1)
        self.assertEqual(joints[0].level, 1)


if __name__ == '__main__':
    unittest.main()
