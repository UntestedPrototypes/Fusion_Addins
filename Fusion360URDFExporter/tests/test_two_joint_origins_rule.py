"""Unit tests for the 'two joint origins required' rule and rigid joint inclusion."""

import unittest
from core.joint_analyzer import JointAnalyzer, JointInfo
from core.rigid_resolver import RigidGroupResolver
from core.tree_walker import OccurrenceNode
from core.kinematic_builder import KinematicTreeBuilder
from core.urdf_writer import URDFWriter
import xml.etree.ElementTree as ET


class MockPt:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class MockGeometry:
    def __init__(self, origin=(0.0, 0.0, 0.0)):
        self.origin = MockPt(origin[0], origin[1], origin[2])
        self.primaryAxisVector = MockPt(0.0, 0.0, 1.0)
        self.secondaryAxisVector = MockPt(1.0, 0.0, 0.0)


class MockJointOrigin:
    """Mock representing an adsk.fusion.JointOrigin."""
    def __init__(self, name="JO", origin=(0.0, 0.0, 0.0)):
        self.name = name
        self.geometry = MockGeometry(origin)
        self.transform = None


class MockJointGeometry:
    """Mock representing an adsk.fusion.JointGeometry (face, edge, etc.)."""
    def __init__(self, name="JG"):
        self.name = name
        class G:
            class Pt:
                x, y, z = 0.0, 0.0, 0.0
            origin = Pt()
            primaryAxisVector = Pt()
            secondaryAxisVector = Pt()
        self.geometry = G()


class MockOccurrence:
    def __init__(self, name, full_path):
        self.name = name
        self.fullPathName = full_path
        self.component = None


class MockJoint:
    def __init__(self, name, jtype, ref_one, ref_two, occ_one, occ_two, is_suppressed=False):
        self.name = name
        self.isSuppressed = is_suppressed
        self.geometryOrOriginOne = ref_one
        self.geometryOrOriginTwo = ref_two
        self.occurrenceOne = occ_one
        self.occurrenceTwo = occ_two

        class Motion:
            def __init__(self, t):
                self.jointType = t
                self.isFlipped = False
                self.rotationLimits = None
                self.slideLimits = None
        self.jointMotion = Motion(jtype)


class TestTwoJointOriginsRule(unittest.TestCase):
    def setUp(self):
        self.analyzer = JointAnalyzer(None)

    def test_is_joint_origin_detection(self):
        """Test detection of JointOrigin vs JointGeometry."""
        jo = MockJointOrigin("JO1")
        jg = MockJointGeometry("JG1")
        
        self.assertTrue(self.analyzer._is_joint_origin(jo))
        self.assertFalse(self.analyzer._is_joint_origin(jg))
        self.assertFalse(self.analyzer._is_joint_origin(None))

        # Proxy with nativeObject
        class MockProxy:
            nativeObject = MockJointOrigin("NativeJO")
        self.assertTrue(self.analyzer._is_joint_origin(MockProxy()))

    def test_is_between_two_joint_origins(self):
        """Test check for whether joint connects two JointOrigins."""
        jo1 = MockJointOrigin("JO1")
        jo2 = MockJointOrigin("JO2")
        jg = MockJointGeometry("JG1")
        occ1 = MockOccurrence("child:1", "root/child:1")
        occ2 = MockOccurrence("base:1", "root/base:1")

        # Two JointOrigins -> True
        j_both = MockJoint("j_both", "RevoluteJointType", jo1, jo2, occ1, occ2)
        self.assertTrue(self.analyzer._is_between_two_joint_origins(j_both))

        # One JointOrigin, one JointGeometry -> False
        j_one = MockJoint("j_one", "RevoluteJointType", jo1, jg, occ1, occ2)
        self.assertFalse(self.analyzer._is_between_two_joint_origins(j_one))

        # Two JointGeometries -> False
        j_neither = MockJoint("j_neither", "RevoluteJointType", jg, jg, occ1, occ2)
        self.assertFalse(self.analyzer._is_between_two_joint_origins(j_neither))

        # One None -> False
        j_none = MockJoint("j_none", "RevoluteJointType", jo1, None, occ1, occ2)
        self.assertFalse(self.analyzer._is_between_two_joint_origins(j_none))

    def test_analyze_all_filters_joints_and_includes_rigid(self):
        """Test that analyze_all only includes joints with two JointOrigins, and includes rigid joints as fixed."""
        jo_base = MockJointOrigin("JO_Base", origin=(0.0, 0.0, 0.0))
        jo_coxa = MockJointOrigin("JO_Coxa", origin=(10.0, 0.0, 5.0))
        jo_femur = MockJointOrigin("JO_Femur", origin=(15.0, 0.0, 10.0))
        jg_face = MockJointGeometry("JG_Face")

        occ_base = MockOccurrence("Base:1", "root/Base:1")
        occ_coxa = MockOccurrence("Coxa:1", "root/Base:1/Coxa:1")
        occ_femur = MockOccurrence("Femur:1", "root/Base:1/Coxa:1/Femur:1")
        occ_bracket = MockOccurrence("Bracket:1", "root/Base:1/Bracket:1")

        # 1. Revolute joint between two JointOrigins (Base -> Coxa) -> SHOULD BE INCLUDED
        j_rev = MockJoint("j_coxa", "RevoluteJointType", jo_coxa, jo_base, occ_coxa, occ_base)

        # 2. Rigid joint between two JointOrigins (Coxa -> Femur fixed mount) -> SHOULD BE INCLUDED as fixed!
        j_rigid_origin = MockJoint("j_femur_mount", "RigidJointType", jo_femur, jo_coxa, occ_femur, occ_coxa)

        # 3. Revolute joint defined by faces (no JointOrigins) -> SHOULD BE SKIPPED
        j_rev_faces = MockJoint("j_skip_rev", "RevoluteJointType", jg_face, jg_face, occ_coxa, occ_base)

        # 4. Rigid joint defined by faces -> SHOULD BE SKIPPED by analyzer
        j_rigid_faces = MockJoint("j_bracket", "RigidJointType", jg_face, jg_face, occ_bracket, occ_base)

        class MockRootComp:
            allJoints = [j_rev, j_rigid_origin, j_rev_faces, j_rigid_faces]
            allAsBuiltJoints = []

        analyzer = JointAnalyzer(MockRootComp())
        results = analyzer.analyze_all()

        self.assertEqual(len(results), 2)
        
        # Check first joint is revolute
        self.assertEqual(results[0].joint_type, 'revolute')
        self.assertEqual(results[0].child_link_path, occ_coxa.fullPathName)

        # Check second joint is rigid -> mapped to 'fixed'
        self.assertEqual(results[1].joint_type, 'fixed')
        self.assertEqual(results[1].child_link_path, occ_femur.fullPathName)

    def test_rigid_resolver_does_not_merge_rigid_joint_with_two_origins(self):
        """Test that RigidGroupResolver does NOT merge components if their rigid joint connects two JointOrigins."""
        base_node = OccurrenceNode(None, None, depth=1)
        base_node.name = 'Base:1'
        base_node.full_path = 'root/Base:1'

        sensor_node = OccurrenceNode(None, base_node, depth=2)
        sensor_node.name = 'Sensor:1'
        sensor_node.full_path = 'root/Base:1/Sensor:1'

        cover_node = OccurrenceNode(None, base_node, depth=2)
        cover_node.name = 'Cover:1'
        cover_node.full_path = 'root/Base:1/Cover:1'

        nodes = {
            'root': OccurrenceNode(None, None, depth=0),
            base_node.full_path: base_node,
            sensor_node.full_path: sensor_node,
            cover_node.full_path: cover_node
        }

        jo_base = MockJointOrigin("JO_Base")
        jo_sensor = MockJointOrigin("JO_Sensor")
        jg_face = MockJointGeometry("JG_Face")

        occ_base = MockOccurrence('Base:1', base_node.full_path)
        occ_sensor = MockOccurrence('Sensor:1', sensor_node.full_path)
        occ_cover = MockOccurrence('Cover:1', cover_node.full_path)

        # Rigid joint between two JointOrigins: Base -> Sensor
        j_sensor = MockJoint("j_sensor", "RigidJointType", jo_sensor, jo_base, occ_sensor, occ_base)

        # Rigid joint between faces (not two JointOrigins): Base -> Cover
        j_cover = MockJoint("j_cover", "RigidJointType", jg_face, jg_face, occ_cover, occ_base)

        class MockRootComp:
            allJoints = [j_sensor, j_cover]
            rigidGroups = []
            allRigidGroups = []
            asBuiltJoints = []

        resolver = RigidGroupResolver(MockRootComp(), nodes, base_node=base_node)
        resolver.resolve()

        # Sensor was connected by two JointOrigins -> MUST NOT be merged!
        self.assertFalse(sensor_node.is_merged)

        # Cover was connected by face joint without JointOrigins -> MUST be merged into Base!
        self.assertTrue(cover_node.is_merged)

    def test_end_to_end_fixed_joint_urdf_generation(self):
        """Test full pipeline builds URDF with valid fixed joint when rigid joint has two JointOrigins."""
        base_node = OccurrenceNode(None, None, depth=0)
        base_node.name = 'base_link'
        base_node.full_path = 'root'

        camera_node = OccurrenceNode(None, base_node, depth=1)
        camera_node.name = 'camera_mount:1'
        camera_node.full_path = 'root/camera_mount:1'

        nodes = {
            'root': base_node,
            camera_node.full_path: camera_node
        }

        # Fixed joint info (from rigid joint between two joint origins)
        j_fixed = JointInfo()
        j_fixed.name = 'camera_joint'
        j_fixed.joint_type = 'fixed'
        j_fixed.parent_link_path = 'root'
        j_fixed.child_link_path = camera_node.full_path
        j_fixed.origin_xyz = [0.1, 0.0, 0.2]
        j_fixed.origin_rpy = [0.0, 0.0, 0.0]
        j_fixed.axis = [0.0, 0.0, 1.0]

        builder = KinematicTreeBuilder(nodes, [j_fixed])
        links, joints = builder.build()

        self.assertEqual(len(links), 2)
        self.assertEqual(len(joints), 1)
        self.assertEqual(joints[0].joint_type, 'fixed')

        # Generate URDF XML
        writer = URDFWriter('test_robot', links, joints)
        xml_str = writer.generate()

        # Validate XML structure
        root = ET.fromstring(xml_str)
        joint_elems = root.findall('joint')
        self.assertEqual(len(joint_elems), 1)
        j_elem = joint_elems[0]
        self.assertEqual(j_elem.get('type'), 'fixed')

        parent_elem = j_elem.find('parent')
        self.assertEqual(parent_elem.get('link'), 'base_link')

        child_elem = j_elem.find('child')
        self.assertEqual(child_elem.get('link'), 'camera_mount_link')

        origin_elem = j_elem.find('origin')
        self.assertIsNotNone(origin_elem)

        # Fixed joints must NOT have limits in URDF schema
        limit_elem = j_elem.find('limit')
        self.assertIsNone(limit_elem)


if __name__ == '__main__':
    unittest.main()
