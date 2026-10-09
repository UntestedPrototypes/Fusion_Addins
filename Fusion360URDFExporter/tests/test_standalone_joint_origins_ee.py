"""Unit tests for exporting standalone JointOrigins as fixed end-effectors with _exclude filter."""

import unittest
import xml.etree.ElementTree as ET

from core.joint_analyzer import JointAnalyzer, JointInfo
from core.tree_walker import OccurrenceNode
from core.kinematic_builder import KinematicTreeBuilder
from core.urdf_writer import URDFWriter


class MockPt:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class MockGeometry:
    def __init__(self, origin=(0.0, 0.0, 0.0)):
        self.origin = MockPt(origin[0], origin[1], origin[2])
        self.primaryAxisVector = MockPt(0.0, 0.0, 1.0)
        self.secondaryAxisVector = MockPt(1.0, 0.0, 0.0)


class MockJointOrigin:
    __hash__ = None  # Simulate Fusion 360 C++ object unhashability

    def __init__(self, name="JO", origin=(0.0, 0.0, 0.0), assembly_context=None, entity_token=None):
        self.name = name
        self.geometry = MockGeometry(origin)
        self.transform = None
        self.assemblyContext = assembly_context
        self.entityToken = entity_token or name


class MockOccurrence:
    def __init__(self, name, full_path):
        self.name = name
        self.fullPathName = full_path
        self.component = None


class MockJoint:
    def __init__(self, name, jtype, ref_one, ref_two, occ_one, occ_two):
        self.name = name
        self.isSuppressed = False
        self.geometryOrOriginOne = ref_one
        self.geometryOrOriginTwo = ref_two
        self.occurrenceOne = occ_one
        self.occurrenceTwo = occ_two

        class Motion:
            pass
        m = Motion()
        m.jointType = jtype
        self.jointMotion = m


class MockRootComponent:
    def __init__(self, name="AssemblyRoot"):
        self.name = name
        self.allJoints = []
        self.allJointOrigins = []
        self.jointOrigins = []


class TestStandaloneJointOriginsEndEffectors(unittest.TestCase):
    def setUp(self):
        self.root = MockRootComponent()
        self.occ_arm = MockOccurrence("Arm:1", "Arm:1")
        self.occ_gripper = MockOccurrence("Gripper:1", "Arm:1+Gripper:1")

        # Kinematic joint between Arm and Gripper using two JointOrigins
        self.jo_arm_joint = MockJointOrigin("Arm_Mating_Origin", origin=(0.0, 0.0, 10.0), assembly_context=self.occ_arm)
        self.jo_grip_joint = MockJointOrigin("Grip_Mating_Origin", origin=(0.0, 0.0, 10.0), assembly_context=self.occ_gripper)
        self.kinematic_joint = MockJoint(
            "Arm_to_Gripper", "RevoluteJointType",
            self.jo_grip_joint, self.jo_arm_joint,
            self.occ_gripper, self.occ_arm
        )
        self.root.allJoints = [self.kinematic_joint]

        # Standalone JointOrigins:
        # 1. Valid End-Effector on Gripper
        self.jo_tcp = MockJointOrigin("TCP", origin=(5.0, 0.0, 15.0), assembly_context=self.occ_gripper)
        # 2. Another valid End-Effector on Gripper
        self.jo_camera = MockJointOrigin("Camera_Frame", origin=(2.0, 3.0, 12.0), assembly_context=self.occ_gripper)
        # 3. Excluded origin ending with _exclude
        self.jo_exclude1 = MockJointOrigin("WorkPoint_exclude", origin=(0.0, 0.0, 5.0), assembly_context=self.occ_gripper)
        # 4. Excluded origin ending with _EXCLUDE (case-insensitive)
        self.jo_exclude2 = MockJointOrigin("Helper_Origin_EXCLUDE", origin=(1.0, 1.0, 1.0), assembly_context=self.occ_arm)
        # 5. Base origin (to be passed as selected_base_origin)
        self.jo_base = MockJointOrigin("Base_Origin", origin=(0.0, 0.0, 0.0), assembly_context=None)

        self.root.allJointOrigins = [
            self.jo_arm_joint,
            self.jo_grip_joint,
            self.jo_tcp,
            self.jo_camera,
            self.jo_exclude1,
            self.jo_exclude2,
            self.jo_base
        ]

    def test_standalone_joint_origins_discovery_and_filtering(self):
        """Verify that only un-jointed, non-excluded JointOrigins are exported as fixed joints."""
        analyzer = JointAnalyzer(self.root)
        results = analyzer.analyze_all(selected_base_origin=self.jo_base)

        # Expect:
        # 1. Kinematic revolute joint (Arm_to_Gripper)
        # 2. Standalone fixed joint for TCP
        # 3. Standalone fixed joint for Camera_Frame
        # Note: jo_arm_joint & jo_grip_joint are in a joint -> skipped as standalone
        # jo_exclude1 & jo_exclude2 end with _exclude -> skipped
        # jo_base is selected_base_origin -> skipped

        joint_names = [j.name for j in results]
        self.assertEqual(len(results), 3, f"Expected 3 joints, got {len(results)}: {joint_names}")

        tcp_info = next((j for j in results if 'tcp' in j.name), None)
        self.assertIsNotNone(tcp_info, "TCP end-effector joint was not found")
        self.assertTrue(tcp_info.is_end_effector)
        self.assertEqual(tcp_info.joint_type, 'fixed')
        self.assertEqual(tcp_info.parent_link_path, self.occ_gripper.fullPathName)

        camera_info = next((j for j in results if 'camera' in j.name), None)
        self.assertIsNotNone(camera_info, "Camera_Frame end-effector joint was not found")
        self.assertTrue(camera_info.is_end_effector)
        self.assertEqual(camera_info.joint_type, 'fixed')

        # Verify excluded origins are NOT present
        for j in results:
            self.assertFalse('exclude' in j.name.lower())
            self.assertFalse('base_origin' in j.name.lower())

    def test_kinematic_tree_and_virtual_link_creation(self):
        """Verify KinematicTreeBuilder creates virtual links and fixed joints for end-effectors."""
        analyzer = JointAnalyzer(self.root)
        joint_infos = analyzer.analyze_all(selected_base_origin=self.jo_base)

        # Mock OccurrenceNodes
        node_root = OccurrenceNode(None, None, depth=0)
        node_root.name = 'root'
        node_root.full_path = 'root'

        node_arm = OccurrenceNode(None, node_root, depth=1)
        node_arm.name = 'Arm:1'
        node_arm.full_path = 'Arm:1'
        node_arm.parent = node_root

        node_grip = OccurrenceNode(None, node_arm, depth=2)
        node_grip.name = 'Gripper:1'
        node_grip.full_path = 'Arm:1+Gripper:1'
        node_grip.parent = node_arm

        nodes = {
            'root': node_root,
            'Arm:1': node_arm,
            'Arm:1+Gripper:1': node_grip
        }

        builder = KinematicTreeBuilder(nodes, joint_infos, base_node=node_root)
        links, joints = builder.build()

        # Check links
        link_names = [l.name for l in links]
        self.assertIn('tcp_link', link_names)
        self.assertIn('camera_frame_link', link_names)

        tcp_link = next(l for l in links if l.name == 'tcp_link')
        self.assertTrue(getattr(tcp_link, 'is_virtual', False))
        self.assertEqual(len(tcp_link.bodies), 0)

        # Check joints
        tcp_joint = next((j for j in joints if 'tcp' in j.name), None)
        self.assertIsNotNone(tcp_joint)
        self.assertEqual(tcp_joint.joint_type, 'fixed')
        self.assertEqual(tcp_joint.child_link, 'tcp_link')
        self.assertEqual(tcp_joint.parent_link, 'gripper_link')
        self.assertEqual(tcp_joint.name, 'tcp_joint')  # Name preserved!

    def test_urdf_writer_virtual_link_clean_xml(self):
        """Verify URDFWriter omits <inertial> for virtual links and generates valid URDF XML."""
        analyzer = JointAnalyzer(self.root)
        joint_infos = analyzer.analyze_all(selected_base_origin=self.jo_base)

        node_root = OccurrenceNode(None, None, depth=0)
        node_root.name = 'root'
        node_root.full_path = 'root'

        node_arm = OccurrenceNode(None, node_root, depth=1)
        node_arm.name = 'Arm:1'
        node_arm.full_path = 'Arm:1'
        node_arm.parent = node_root

        node_grip = OccurrenceNode(None, node_arm, depth=2)
        node_grip.name = 'Gripper:1'
        node_grip.full_path = 'Arm:1+Gripper:1'
        node_grip.parent = node_arm

        nodes = {
            'root': node_root,
            'Arm:1': node_arm,
            'Arm:1+Gripper:1': node_grip
        }

        builder = KinematicTreeBuilder(nodes, joint_infos, base_node=node_root)
        links, joints = builder.build()

        writer = URDFWriter('test_robot', links, joints)
        urdf_xml = writer.generate()

        root_elem = ET.fromstring(urdf_xml)

        # Find tcp_link
        tcp_elem = None
        for link in root_elem.findall('link'):
            if link.get('name') == 'tcp_link':
                tcp_elem = link
                break

        self.assertIsNotNone(tcp_elem, "tcp_link not found in URDF XML")
        # Ensure virtual link has no inertial, visual, or collision elements
        self.assertIsNone(tcp_elem.find('inertial'), "Virtual link must not have <inertial>")
        self.assertIsNone(tcp_elem.find('visual'), "Virtual link must not have <visual>")
        self.assertIsNone(tcp_elem.find('collision'), "Virtual link must not have <collision>")

        # Find tcp_joint
        tcp_joint_elem = None
        for joint in root_elem.findall('joint'):
            if joint.get('name') == 'tcp_joint':
                tcp_joint_elem = joint
                break

        self.assertIsNotNone(tcp_joint_elem, "tcp_joint not found in URDF XML")
        self.assertEqual(tcp_joint_elem.get('type'), 'fixed')
        self.assertEqual(tcp_joint_elem.find('parent').get('link'), 'gripper_link')
        self.assertEqual(tcp_joint_elem.find('child').get('link'), 'tcp_link')

    def test_robustness_against_internal_validation_error(self):
        """Verify that joints throwing InternalValidationError on geometryOrOriginTwo do not crash export."""
        class MockBrokenJoint:
            def __init__(self, name="BrokenAsBuiltJoint"):
                self.name = name
                self.isSuppressed = False

            @property
            def geometryOrOriginTwo(self):
                raise RuntimeError("2 : InternalValidationError : targetObj")

            @property
            def geometryOrOriginOne(self):
                return None

        self.root.allJoints.append(MockBrokenJoint())
        analyzer = JointAnalyzer(self.root)
        # Must not raise RuntimeError!
        results = analyzer.analyze_all(selected_base_origin=self.jo_base)
        self.assertEqual(len(results), 3)


if __name__ == '__main__':
    unittest.main()
