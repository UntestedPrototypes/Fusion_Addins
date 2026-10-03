"""Tests for URDF XML generation and schema validation."""

import unittest
import xml.etree.ElementTree as ET
from core.kinematic_builder import URDFLink, URDFJoint
from core.urdf_writer import URDFWriter


class TestURDFWriter(unittest.TestCase):
    def test_xml_structure_and_tags(self):
        """Test that generated URDF parses cleanly and contains all required tags."""
        l1 = URDFLink('base_link')
        l1.mass = 5.0
        l1.com = [0.0, 0.0, 0.05]
        l1.inertia = {'ixx': 0.01, 'ixy': 0.0, 'ixz': 0.0, 'iyy': 0.01, 'iyz': 0.0, 'izz': 0.02}
        l1.visual_mesh_path = 'meshes/visual/base_link.stl'
        l1.collision_mesh_path = 'meshes/collision/base_link.stl'

        l2 = URDFLink('arm_link')
        l2.mass = 2.5
        l2.com = [0.0, 0.0, 0.15]
        l2.inertia = {'ixx': 0.005, 'ixy': 0.0, 'ixz': 0.0, 'iyy': 0.005, 'iyz': 0.0, 'izz': 0.001}
        l2.visual_mesh_path = 'meshes/visual/arm_link.stl'
        l2.collision_mesh_path = 'meshes/collision/arm_link.stl'

        j1 = URDFJoint('revolute_1', 'revolute')
        j1.parent_link = 'base_link'
        j1.child_link = 'arm_link'
        j1.origin_xyz = [0.0, 0.0, 0.1]
        j1.origin_rpy = [0.0, 0.0, 0.0]
        j1.axis = [0.0, 0.0, 1.0]
        j1.limits = {'lower': -1.57, 'upper': 1.57, 'effort': 50.0, 'velocity': 2.0}

        writer = URDFWriter('test_robot', [l1, l2], [j1])
        xml_str = writer.generate()

        # 1. Must parse as valid XML without exceptions
        root = ET.fromstring(xml_str)
        self.assertEqual(root.tag, 'robot')
        self.assertEqual(root.attrib['name'], 'test_robot')

        # 2. Check Links
        links = root.findall('link')
        self.assertEqual(len(links), 2)
        link_names = [l.attrib['name'] for l in links]
        self.assertIn('base_link', link_names)
        self.assertIn('arm_link', link_names)

        # Check visual mesh paths
        l1_elem = links[0]
        vis_mesh = l1_elem.find('visual/geometry/mesh')
        self.assertIsNotNone(vis_mesh)
        self.assertEqual(vis_mesh.attrib['filename'], 'meshes/visual/base_link.stl')

        col_mesh = l1_elem.find('collision/geometry/mesh')
        self.assertIsNotNone(col_mesh)
        self.assertEqual(col_mesh.attrib['filename'], 'meshes/collision/base_link.stl')

        # 3. Check Joints
        joints = root.findall('joint')
        self.assertEqual(len(joints), 1)
        j_elem = joints[0]
        self.assertEqual(j_elem.attrib['name'], 'revolute_1')
        self.assertEqual(j_elem.attrib['type'], 'revolute')
        self.assertEqual(j_elem.find('parent').attrib['link'], 'base_link')
        self.assertEqual(j_elem.find('child').attrib['link'], 'arm_link')
        self.assertEqual(j_elem.find('axis').attrib['xyz'], '0.0000 0.0000 1.0000')

        limit = j_elem.find('limit')
        self.assertIsNotNone(limit)
        self.assertAlmostEqual(float(limit.attrib['lower']), -1.57, places=2)
        self.assertAlmostEqual(float(limit.attrib['upper']), 1.57, places=2)


if __name__ == '__main__':
    unittest.main()
