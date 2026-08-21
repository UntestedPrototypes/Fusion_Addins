import adsk.core, adsk.fusion
import traceback
import math
import re
from . import LinkData, JointData, KinematicChain, RobotModel, NamingConfig
from . import math_utils

def _sanitize_name(name: str) -> str:
    """Remove Fusion occurrence suffixes (':1'), spaces, special chars"""
    name = re.sub(r':\d+$', '', name)
    name = re.sub(r'[^a-zA-Z0-9]', '_', name)
    return name

def _get_occ_name(occ, naming_config):
    """Get the formatted name for an occurrence (or root if occ is None)."""
    if occ is None:
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        raw = design.rootComponent.name if design else 'root'
    else:
        raw = occ.name
    return naming_config.format_link_name(raw) if naming_config else raw

def _safe_occ(joint, attr):
    """Safely access joint.occurrenceOne or occurrenceTwo (throws RuntimeError for root)."""
    try:
        return getattr(joint, attr)
    except:
        return None

def _get_joint_origin_world(joint) -> tuple:
    """Extract joint origin point in world coordinates (cm -> m)"""
    try:
        if hasattr(joint, 'geometryOrOriginTwo') and joint.geometryOrOriginTwo:
            origin = joint.geometryOrOriginTwo.origin
        elif hasattr(joint, 'geometryOrOriginOne') and joint.geometryOrOriginOne:
            origin = joint.geometryOrOriginOne.origin
        else:
            origin = adsk.core.Point3D.create(0, 0, 0)
        return (origin.x * 0.01, origin.y * 0.01, origin.z * 0.01)
    except:
        return (0.0, 0.0, 0.0)

def _get_joint_axis_world(joint) -> tuple:
    """Extract joint axis unit vector in world coordinates"""
    try:
        motion = joint.jointMotion
        if motion.jointType == adsk.fusion.JointTypes.RevoluteJointType:
            vec = motion.rotationAxisVector
        elif motion.jointType == adsk.fusion.JointTypes.SliderJointType:
            vec = motion.slideDirectionVector
        else:
            return (0.0, 0.0, 1.0)

        length = math.sqrt(vec.x**2 + vec.y**2 + vec.z**2)
        if length < 1e-6:
            return (0.0, 0.0, 1.0)
        return (vec.x/length, vec.y/length, vec.z/length)
    except:
        return (0.0, 0.0, 1.0)

def _is_rigid_joint(joint) -> bool:
    """Check if a Fusion joint is rigid."""
    try:
        return joint.jointMotion.jointType == adsk.fusion.JointTypes.RigidJointType
    except:
        return True  # Default to rigid if we can't determine

def _get_joint_type_str(joint):
    """Get the URDF joint type string for a Fusion joint."""
    try:
        motion = joint.jointMotion
        if motion.jointType == adsk.fusion.JointTypes.RevoluteJointType:
            if motion.rotationLimits.isMinimumValueEnabled or motion.rotationLimits.isMaximumValueEnabled:
                return 'revolute'
            else:
                return 'continuous'
        elif motion.jointType == adsk.fusion.JointTypes.SliderJointType:
            return 'prismatic'
        elif motion.jointType == adsk.fusion.JointTypes.RigidJointType:
            return 'fixed'
        else:
            return 'fixed'
    except:
        return 'fixed'


def _extract_link_data(occ, naming_config: NamingConfig) -> LinkData:
    """Extract link data from a Fusion occurrence (or root component if occ is None)."""
    app = adsk.core.Application.get()

    if occ is None:
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        name = root.name
        link_name = naming_config.format_link_name(name) if naming_config else name
        link = LinkData(name=link_name)
        link.world_transform = math_utils.identity_4x4()
        comp = root
        bb = root.boundingBox
    else:
        name = occ.name
        link_name = naming_config.format_link_name(name) if naming_config else name
        link = LinkData(name=link_name)
        mat = math_utils.matrix3d_to_4x4(occ.transform2.asArray())
        mat[0][3] *= 0.01
        mat[1][3] *= 0.01
        mat[2][3] *= 0.01
        link.world_transform = mat
        comp = occ.component
        bb = occ.boundingBox

    try:
        if bb:
            size_x = (bb.maxPoint.x - bb.minPoint.x) * 0.01
            size_y = (bb.maxPoint.y - bb.minPoint.y) * 0.01
            size_z = (bb.maxPoint.z - bb.minPoint.z) * 0.01
            link.bounding_box = (size_x, size_y, size_z)
    except:
        link.bounding_box = (0.0, 0.0, 0.0)

    try:
        props = comp.getPhysicalProperties(adsk.fusion.CalculationAccuracy.HighCalculationAccuracy)
        if props:
            link.mass = props.mass
            com = props.centerOfMass
            
            link.center_of_mass = (com.x * 0.01, com.y * 0.01, com.z * 0.01)
            
            (ret, ixx, iyy, izz, ixy, iyz, ixz) = props.getXYZMomentsOfInertia()
            if ret:
                link.inertia = {
                    'ixx': max(ixx * 1e-4, 1e-6),
                    'ixy': ixy * 1e-4,
                    'ixz': ixz * 1e-4,
                    'iyy': max(iyy * 1e-4, 1e-6),
                    'iyz': iyz * 1e-4,
                    'izz': max(izz * 1e-4, 1e-6)
                }

            # Transform center of mass to link-local frame
            if link.world_transform:
                T_inv = math_utils.invert_4x4(link.world_transform)
                link.center_of_mass = math_utils.transform_point(T_inv, link.center_of_mass)
    except Exception as e:
        link.mass = 0.0
        link.center_of_mass = (0.0, 0.0, 0.0)
        link.inertia = {
            'ixx': 1e-6, 'ixy': 0.0, 'ixz': 0.0,
            'iyy': 1e-6, 'iyz': 0.0, 'izz': 1e-6
        }

    try:
        if comp.bRepBodies.count > 0:
            body = comp.bRepBodies.item(0)
            appearance = body.appearance
            if appearance:
                for prop in appearance.appearanceProperties:
                    if prop.id == 'surface_albedo':
                        color = prop.value
                        link.visual_color = (color.red/255.0, color.green/255.0, color.blue/255.0, color.opacity/255.0)
                        break
    except:
        pass

    if not hasattr(link, 'visual_color') or not link.visual_color:
        link.visual_color = (0.8, 0.8, 0.8, 1.0)

    return link


def _extract_joint_data(joint, links_world_transforms: dict, naming_config: NamingConfig) -> JointData:
    """Extract a URDF joint from a Fusion joint. Only called for non-rigid joints."""
    jd = JointData(name=naming_config.format_joint_name(joint.name) if naming_config else joint.name)

    occ_parent = _safe_occ(joint, 'occurrenceTwo')
    occ_child = _safe_occ(joint, 'occurrenceOne')

    jd.parent_link = _get_occ_name(occ_parent, naming_config)
    jd.child_link = _get_occ_name(occ_child, naming_config)

    # Joint type and limits
    jd.joint_type = _get_joint_type_str(joint)
    try:
        motion = joint.jointMotion
        if jd.joint_type == 'revolute':
            jd.has_limits = True
            jd.limit_lower = motion.rotationLimits.minimumValue if motion.rotationLimits.isMinimumValueEnabled else -3.14159
            jd.limit_upper = motion.rotationLimits.maximumValue if motion.rotationLimits.isMaximumValueEnabled else 3.14159
        elif jd.joint_type == 'prismatic':
            jd.has_limits = True
            jd.limit_lower = (motion.slideLimits.minimumValue * 0.01) if motion.slideLimits.isMinimumValueEnabled else -1.0
            jd.limit_upper = (motion.slideLimits.maximumValue * 0.01) if motion.slideLimits.isMaximumValueEnabled else 1.0
    except:
        pass

    jd.axis = _get_joint_axis_world(joint)

    try:
        T_parent_world = links_world_transforms.get(jd.parent_link, math_utils.identity_4x4())
        T_child_world = links_world_transforms.get(jd.child_link, math_utils.identity_4x4())

        T_parent_inv = math_utils.invert_4x4(T_parent_world)
        T_relative = math_utils.multiply_4x4(T_parent_inv, T_child_world)

        jd.origin_xyz = math_utils.extract_translation(T_relative)
        jd.origin_rpy = math_utils.rotation_to_rpy(math_utils.extract_rotation_3x3(T_relative))
    except:
        jd.origin_xyz = (0.0, 0.0, 0.0)
        jd.origin_rpy = (0.0, 0.0, 0.0)

    jd.limit_effort = 100.0
    jd.limit_velocity = 10.0

    return jd


def _detect_chains(robot_model: RobotModel) -> list:
    """Detect serial kinematic chains from the joint graph."""
    chains = []
    graph = {}
    parent_map = {}
    all_links = set(robot_model.links.keys())

    for joint in robot_model.joints:
        if joint.parent_link not in graph:
            graph[joint.parent_link] = []
        graph[joint.parent_link].append((joint.child_link, joint.name))
        parent_map[joint.child_link] = (joint.parent_link, joint.name)

    leaves = [link for link in all_links if link not in graph or len(graph[link]) == 0]

    for idx, leaf in enumerate(leaves):
        # Only trace chains that have at least one joint
        if leaf not in parent_map:
            continue

        chain = KinematicChain(name=f"chain_{idx}")
        chain.link_names = []
        chain.joint_names = []

        curr = leaf
        while curr in parent_map:
            parent, joint_name = parent_map[curr]
            chain.link_names.insert(0, curr)
            chain.joint_names.insert(0, joint_name)

            if len(graph.get(parent, [])) > 1:
                chain.link_names.insert(0, parent)
                break

            curr = parent

        if curr not in chain.link_names:
            chain.link_names.insert(0, curr)

        chains.append(chain)

    return chains


def parse_assembly(naming_config: NamingConfig) -> RobotModel:
    """
    Parse a Fusion 360 assembly into a RobotModel.

    Strategy:
      1. Iterate all Fusion joints to classify them:
         - Rigid joints: child occurrence is merged into parent (no URDF joint/link)
         - Non-rigid joints (revolute, prismatic, etc.): create URDF joint + link
      2. Only occurrences that participate in non-rigid joints become URDF links
      3. All other occurrences are conceptually merged into the base link
    """
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return None

    root = design.rootComponent
    model = RobotModel(name=naming_config.format_link_name(root.name) if naming_config else root.name)

    # --- Step 1: Classify joints ---
    # Sets of occurrence names that participate in non-rigid joints
    articulated_occ_names = set()   # Occurrences that need their own URDF link
    rigid_child_to_parent = {}      # rigid child occ name -> parent occ name

    for joint in root.allJoints:
        try:
            occ_parent = _safe_occ(joint, 'occurrenceTwo')
            occ_child = _safe_occ(joint, 'occurrenceOne')

            parent_name = _get_occ_name(occ_parent, naming_config)
            child_name = _get_occ_name(occ_child, naming_config)

            if _is_rigid_joint(joint):
                # Rigid: merge child into parent (don't create separate link)
                rigid_child_to_parent[child_name] = parent_name
            else:
                # Non-rigid: both parent and child need URDF links
                articulated_occ_names.add(parent_name)
                articulated_occ_names.add(child_name)
        except:
            pass

    # --- Step 2: Build occurrence lookup (name -> occ object) ---
    occ_lookup = {}  # formatted name -> occurrence object (None = root)
    root_link_name = _get_occ_name(None, naming_config)
    occ_lookup[root_link_name] = None

    for occ in root.allOccurrences:
        fname = _get_occ_name(occ, naming_config)
        occ_lookup[fname] = occ

    # --- Step 3: Determine which occurrences become URDF links ---
    # Always include the root/base link
    link_names_to_create = set()
    link_names_to_create.add(root_link_name)

    # Add all occurrences that participate in non-rigid joints
    for name in articulated_occ_names:
        # But skip any that are rigid-children (they got merged into parent)
        if name not in rigid_child_to_parent:
            link_names_to_create.add(name)
        else:
            link_names_to_create.add(name)  # Even rigid children need links if they also have articulated joints

    # Actually: an occurrence needs a URDF link if it's a parent or child of ANY non-rigid joint
    # Rigid merging only applies if an occurrence is ONLY connected by rigid joints
    # Recalculate:
    link_names_to_create = set()
    link_names_to_create.add(root_link_name)
    link_names_to_create.update(articulated_occ_names)

    model.root_link_name = root_link_name

    # --- Step 4: Create LinkData for each URDF link ---
    links_world_transforms = {}
    
    incoming_joint_for_link = {}
    for joint in root.allJoints:
        try:
            if not _is_rigid_joint(joint):
                child_name = _get_occ_name(_safe_occ(joint, 'occurrenceOne'), naming_config)
                incoming_joint_for_link[child_name] = joint
        except:
            pass

    for link_name in link_names_to_create:
        occ = occ_lookup.get(link_name)
        try:
            link_data = _extract_link_data(occ, naming_config)
            
            T_comp_world = link_data.world_transform
            R_comp = math_utils.extract_rotation_3x3(T_comp_world)
            P_comp = math_utils.extract_translation(T_comp_world)
            
            incoming_joint = incoming_joint_for_link.get(link_name)
            
            if incoming_joint:
                P_joint = _get_joint_origin_world(incoming_joint)
                T_link_world = [
                    [R_comp[0][0], R_comp[0][1], R_comp[0][2], P_joint[0]],
                    [R_comp[1][0], R_comp[1][1], R_comp[1][2], P_joint[1]],
                    [R_comp[2][0], R_comp[2][1], R_comp[2][2], P_joint[2]],
                    [0.0,          0.0,          0.0,          1.0]
                ]
            else:
                P_joint = P_comp
                T_link_world = T_comp_world
                
            links_world_transforms[link_name] = T_link_world
            
            # Visual offset: P_vis = R_comp^T * (P_comp - P_joint)
            dx = P_comp[0] - P_joint[0]
            dy = P_comp[1] - P_joint[1]
            dz = P_comp[2] - P_joint[2]
            
            px = R_comp[0][0]*dx + R_comp[1][0]*dy + R_comp[2][0]*dz
            py = R_comp[0][1]*dx + R_comp[1][1]*dy + R_comp[2][1]*dz
            pz = R_comp[0][2]*dx + R_comp[1][2]*dy + R_comp[2][2]*dz
            
            link_data.visual_origin_xyz = (px, py, pz)
            link_data.visual_origin_rpy = (0.0, 0.0, 0.0)
            
            cx, cy, cz = link_data.center_of_mass
            link_data.center_of_mass = (cx + px, cy + py, cz + pz)
            
            model.links[link_name] = link_data
        except Exception:
            pass

    # --- Step 5: Create JointData for non-rigid joints only ---
    for joint in root.allJoints:
        try:
            if _is_rigid_joint(joint):
                continue

            joint_data = _extract_joint_data(joint, links_world_transforms, naming_config)

            if joint_data.parent_link not in model.links or joint_data.child_link not in model.links:
                continue
                
            # Convert world axis to local child frame
            T_child_world = links_world_transforms.get(joint_data.child_link, math_utils.identity_4x4())
            R_child = math_utils.extract_rotation_3x3(T_child_world)
            axis_w = joint_data.axis
            
            ax = R_child[0][0]*axis_w[0] + R_child[1][0]*axis_w[1] + R_child[2][0]*axis_w[2]
            ay = R_child[0][1]*axis_w[0] + R_child[1][1]*axis_w[1] + R_child[2][1]*axis_w[2]
            az = R_child[0][2]*axis_w[0] + R_child[1][2]*axis_w[1] + R_child[2][2]*axis_w[2]
            joint_data.axis = (ax, ay, az)

            model.joints.append(joint_data)
        except Exception:
            pass

    # --- Step 5.5: Anchor floating sub-trees to root ---
    anchored_children = set([j.child_link for j in model.joints])
    for link_name in link_names_to_create:
        if link_name != model.root_link_name and link_name not in anchored_children:
            T_child_world = links_world_transforms.get(link_name, math_utils.identity_4x4())
            T_root_world = links_world_transforms.get(model.root_link_name, math_utils.identity_4x4())
            
            T_root_inv = math_utils.invert_4x4(T_root_world)
            T_rel = math_utils.multiply_4x4(T_root_inv, T_child_world)
            
            fix_j = JointData(name=f"fixed_{link_name}_to_root")
            fix_j.joint_type = 'fixed'
            fix_j.parent_link = model.root_link_name
            fix_j.child_link = link_name
            fix_j.origin_xyz = math_utils.extract_translation(T_rel)
            fix_j.origin_rpy = math_utils.rotation_to_rpy(math_utils.extract_rotation_3x3(T_rel))
            model.joints.append(fix_j)
            

    # --- Step 6: Detect kinematic chains for DH computation ---
    model.chains = _detect_chains(model)

    return model
