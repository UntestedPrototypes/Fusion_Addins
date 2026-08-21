"""
URDF Builder module for Fusion 360 Kinematics Exporter.
"""

import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import Tuple

from . import RobotModel, LinkData, JointData

def _fmt(value: float, precision: int = 6) -> str:
    """Format float with specified decimal places, strip trailing zeros but keep at least one decimal."""
    formatted = f"{value:.{precision}f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0')
        if formatted.endswith('.'):
            formatted += '0'
    return formatted

def _fmt_xyz(xyz: Tuple[float, float, float], precision: int = 6) -> str:
    """Format a 3-tuple as space-separated string: 'x y z'."""
    return f"{_fmt(xyz[0], precision)} {_fmt(xyz[1], precision)} {_fmt(xyz[2], precision)}"

def _pretty_xml(root: ET.Element) -> str:
    """Use xml.dom.minidom to add proper indentation and return clean XML string."""
    xml_string = ET.tostring(root, encoding='unicode')
    dom = xml.dom.minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent="  ")
    # Remove extra blank lines
    return '\n'.join([line for line in pretty_xml.split('\n') if line.strip()])

def _build_link_element(link: LinkData, include_mesh: bool) -> ET.Element:
    """Build URDF link element."""
    link_el = ET.Element('link', name=link.name)

    # Inertial
    inertial = ET.SubElement(link_el, 'inertial')
    ET.SubElement(inertial, 'origin', xyz=_fmt_xyz(link.center_of_mass), rpy="0 0 0")
    ET.SubElement(inertial, 'mass', value=_fmt(link.mass))
    ET.SubElement(inertial, 'inertia', 
                  ixx=_fmt(link.inertia.get('ixx', 1e-6)), ixy=_fmt(link.inertia.get('ixy', 0.0)), ixz=_fmt(link.inertia.get('ixz', 0.0)),
                  iyy=_fmt(link.inertia.get('iyy', 1e-6)), iyz=_fmt(link.inertia.get('iyz', 0.0)), izz=_fmt(link.inertia.get('izz', 1e-6)))

    if include_mesh and link.stl_filename:
        visual = ET.SubElement(link_el, 'visual')
        ET.SubElement(visual, 'origin', xyz=_fmt_xyz(link.visual_origin_xyz), rpy=_fmt_xyz(link.visual_origin_rpy))
        geom_v = ET.SubElement(visual, 'geometry')
        ET.SubElement(geom_v, 'mesh', filename=f"meshes/{link.stl_filename}", scale="0.001 0.001 0.001")
        
        mat = ET.SubElement(visual, 'material', name=f"mat_{link.name}")
        ET.SubElement(mat, 'color', rgba=_fmt_xyz(link.visual_color[:3]) + f" {_fmt(link.visual_color[3])}")

    # Collision
    collision = ET.SubElement(link_el, 'collision')
    ET.SubElement(collision, 'origin', xyz=_fmt_xyz(link.center_of_mass), rpy="0 0 0")
    geom_c = ET.SubElement(collision, 'geometry')
    ET.SubElement(geom_c, 'box', size=_fmt_xyz(link.bounding_box))

    return link_el

def _build_joint_element(joint: JointData) -> ET.Element:
    """Build URDF joint element."""
    joint_el = ET.Element('joint', name=joint.name, type=joint.joint_type)
    ET.SubElement(joint_el, 'parent', link=joint.parent_link)
    ET.SubElement(joint_el, 'child', link=joint.child_link)
    ET.SubElement(joint_el, 'origin', xyz=_fmt_xyz(joint.origin_xyz), rpy=_fmt_xyz(joint.origin_rpy))
    ET.SubElement(joint_el, 'axis', xyz=_fmt_xyz(joint.axis))
    
    if joint.joint_type in ('revolute', 'prismatic'):
        ET.SubElement(joint_el, 'limit', 
                      lower=_fmt(joint.limit_lower), 
                      upper=_fmt(joint.limit_upper), 
                      effort=_fmt(joint.limit_effort), 
                      velocity=_fmt(joint.limit_velocity))
        
    ET.SubElement(joint_el, 'dynamics', damping="0.1", friction="0.05")
    
    return joint_el

def build_urdf(robot_model: RobotModel, include_meshes: bool = True) -> str:
    """Generate URDF XML from the parsed RobotModel."""
    robot_el = ET.Element('robot', name=robot_model.name)
    
    for link_name, link in robot_model.links.items():
        link_el = _build_link_element(link, include_meshes)
        robot_el.append(link_el)
        
    for joint in robot_model.joints:
        joint_el = _build_joint_element(joint)
        robot_el.append(joint_el)
        
    return _pretty_xml(robot_el)

def save_urdf(xml_string: str, filepath: str) -> None:
    """Write the URDF XML string to file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(xml_string)
