"""URDF XML Generator for Fusion 360 models."""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from config.defaults import JOINT_TYPE_REVOLUTE, JOINT_TYPE_PRISMATIC


class URDFWriter:
    """Generates clean, schema-compliant URDF XML string."""
    def __init__(self, robot_name, links, joints):
        self.robot_name = robot_name
        self.links = links
        self.joints = joints

    def generate(self):
        """Construct the XML tree and return pretty-printed string."""
        robot = ET.Element('robot', name=self.robot_name)

        # 1. Add Links
        for link in self.links:
            self._add_link_element(robot, link)

        # 2. Add Joints
        for joint in self.joints:
            self._add_joint_element(robot, joint)

        raw_xml = ET.tostring(robot, encoding='utf-8')
        dom = minidom.parseString(raw_xml)
        pretty_xml = dom.toprettyxml(indent='  ', encoding='utf-8').decode('utf-8')

        # Clean extra blank lines produced by minidom
        cleaned_lines = [line for line in pretty_xml.splitlines() if line.strip()]
        return '\n'.join(cleaned_lines) + '\n'

    def _add_link_element(self, parent_elem, link):
        link_elem = ET.SubElement(parent_elem, 'link', name=link.name)

        # Inertial block (omit for virtual / end-effector links)
        if not getattr(link, 'is_virtual', False):
            inertial = ET.SubElement(link_elem, 'inertial')
            ET.SubElement(
                inertial, 'origin',
                xyz=f"{link.com[0]:.6f} {link.com[1]:.6f} {link.com[2]:.6f}",
                rpy="0.000000 0.000000 0.000000"
            )
            ET.SubElement(inertial, 'mass', value=f"{link.mass:.6f}")
            ET.SubElement(
                inertial, 'inertia',
                ixx=f"{link.inertia['ixx']:.8f}",
                ixy=f"{link.inertia['ixy']:.8f}",
                ixz=f"{link.inertia['ixz']:.8f}",
                iyy=f"{link.inertia['iyy']:.8f}",
                iyz=f"{link.inertia['iyz']:.8f}",
                izz=f"{link.inertia['izz']:.8f}"
            )

        # Visual block
        if link.visual_mesh_path:
            visual = ET.SubElement(link_elem, 'visual', name=f"{link.name}_visual")
            ET.SubElement(visual, 'origin', xyz="0 0 0", rpy="0 0 0")
            geom = ET.SubElement(visual, 'geometry')
            ET.SubElement(geom, 'mesh', filename=link.visual_mesh_path)
            # Default silver/metallic visual material
            mat = ET.SubElement(visual, 'material', name=f"{link.name}_mat")
            ET.SubElement(mat, 'color', rgba="0.75 0.75 0.75 1.0")

        # Collision block
        if link.collision_mesh_path:
            collision = ET.SubElement(link_elem, 'collision', name=f"{link.name}_collision")
            ET.SubElement(collision, 'origin', xyz="0 0 0", rpy="0 0 0")
            geom = ET.SubElement(collision, 'geometry')
            ET.SubElement(geom, 'mesh', filename=link.collision_mesh_path)

    def _add_joint_element(self, parent_elem, joint):
        joint_elem = ET.SubElement(
            parent_elem, 'joint',
            name=joint.name,
            type=joint.joint_type
        )

        ET.SubElement(joint_elem, 'parent', link=joint.parent_link)
        ET.SubElement(joint_elem, 'child', link=joint.child_link)

        ET.SubElement(
            joint_elem, 'origin',
            xyz=f"{joint.origin_xyz[0]:.6f} {joint.origin_xyz[1]:.6f} {joint.origin_xyz[2]:.6f}",
            rpy=f"{joint.origin_rpy[0]:.6f} {joint.origin_rpy[1]:.6f} {joint.origin_rpy[2]:.6f}"
        )

        ET.SubElement(
            joint_elem, 'axis',
            xyz=f"{joint.axis[0]:.4f} {joint.axis[1]:.4f} {joint.axis[2]:.4f}"
        )

        # Limits for revolute and prismatic joints
        if joint.joint_type in (JOINT_TYPE_REVOLUTE, JOINT_TYPE_PRISMATIC):
            lims = joint.limits
            ET.SubElement(
                joint_elem, 'limit',
                lower=f"{lims.get('lower', -3.14159):.6f}",
                upper=f"{lims.get('upper', 3.14159):.6f}",
                effort=f"{lims.get('effort', 100.0):.1f}",
                velocity=f"{lims.get('velocity', 1.0):.1f}"
            )
            # Damping & friction
            ET.SubElement(joint_elem, 'dynamics', damping="0.1", friction="0.0")
        elif joint.joint_type == 'continuous':
            lims = joint.limits
            ET.SubElement(
                joint_elem, 'limit',
                effort=f"{lims.get('effort', 100.0):.1f}",
                velocity=f"{lims.get('velocity', 1.0):.1f}"
            )
            ET.SubElement(joint_elem, 'dynamics', damping="0.1", friction="0.0")
