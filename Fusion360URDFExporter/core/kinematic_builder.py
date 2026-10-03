"""Kinematic tree builder for URDF generation.

Creates URDFLink and URDFJoint structures and applies type-based ordered naming.
"""

import re
from config.defaults import (
    CM_TO_M,
    JOINT_TYPE_REVOLUTE,
    JOINT_TYPE_PRISMATIC,
    DEFAULT_JOINT_NAMING_PATTERN
)
from .transform_utils import (
    pure_matrix_invert,
    pure_matrix_multiply,
    pure_matrix_to_rpy,
    IDENTITY_16
)


class URDFLink:
    """Represents a rigid body link in the URDF."""
    def __init__(self, name):
        self.name = name
        self.visual_mesh_path = ""
        self.collision_mesh_path = ""
        self.mass = 0.0
        self.com = [0.0, 0.0, 0.0]
        self.inertia = {
            'ixx': 0.0, 'ixy': 0.0, 'ixz': 0.0,
            'iyy': 0.0, 'iyz': 0.0, 'izz': 0.0
        }
        self.bodies = []
        self.frame_world_transform = None  # 16-element flat list representing world frame in cm

    def __repr__(self):
        return f"<URDFLink '{self.name}' bodies={len(self.bodies)} mass={self.mass:.4f}>"


class URDFJoint:
    """Represents a kinematic joint in the URDF."""
    def __init__(self, name, joint_type):
        self.name = name
        self.joint_type = joint_type
        self.parent_link = ""
        self.child_link = ""
        self.origin_xyz = [0.0, 0.0, 0.0]
        self.origin_rpy = [0.0, 0.0, 0.0]
        self.axis = [0.0, 0.0, 1.0]
        self.limits = {}
        self.depth = 0
        self.chain = 1
        self.level = 1
        self.branch_name = ""

    def __repr__(self):
        return f"<URDFJoint '{self.name}' ({self.joint_type}): {self.parent_link} -> {self.child_link}>"


class KinematicTreeBuilder:
    """Builds links and joints, redirects merged references, and applies naming rules."""
    def __init__(self, tree_nodes, joint_infos, base_node=None, base_origin_world_frame=None, naming_pattern=None):
        self.nodes = tree_nodes  # full_path -> OccurrenceNode
        self.joint_infos = joint_infos
        self.base_node = base_node or tree_nodes.get('root')
        self.base_origin_world_frame = base_origin_world_frame
        self.naming_pattern = naming_pattern or DEFAULT_JOINT_NAMING_PATTERN
        self.links = []
        self.joints = []
        self._link_map = {}      # path -> URDFLink

    def build(self):
        """Construct links, map joints, and apply naming conventions."""
        self._create_links()
        self._create_joints()
        self._apply_naming_convention()
        return self.links, self.joints

    def _create_links(self):
        """Create URDFLink for every non-merged OccurrenceNode."""
        # 1. Create base_link for self.base_node
        base_node = self.base_node
        if base_node is None:
            base_node = self.nodes.get('root')

        if base_node:
            base_link = URDFLink('base_link')
            base_link.bodies = list(base_node.bodies)
            base_link.frame_world_transform = list(self.base_origin_world_frame or IDENTITY_16)
            self.links.append(base_link)
            self._link_map[base_node.full_path] = base_link
            self._link_map['root'] = base_link
            self._link_map['base_link'] = base_link

        used_names = {l.name for l in self.links}
        for path, node in self.nodes.items():
            if node.is_merged or node == base_node or path == 'root':
                continue

            link_name = self._sanitize_link_name(node.name)
            if link_name == 'base_link':
                link_name = 'base_part_link'

            # Disambiguate if link_name already exists in this assembly
            if link_name in used_names:
                branch_node = self._find_branch_node(node)
                branch_clean = self._clean_branch_name(branch_node.name) if branch_node else ""
                candidate = f"{branch_clean}_{link_name}" if branch_clean and not link_name.startswith(branch_clean) else link_name
                if candidate in used_names:
                    base_str = candidate[:-5] if candidate.endswith('_link') else candidate
                    k = 2
                    while f"{base_str}_{k}_link" in used_names:
                        k += 1
                    link_name = f"{base_str}_{k}_link"
                else:
                    link_name = candidate

            used_names.add(link_name)
            link = URDFLink(link_name)
            link.bodies = list(node.bodies)
            self.links.append(link)
            self._link_map[path] = link

    def _create_joints(self):
        """Map JointInfo into URDFJoint, redirecting merged paths to their survivor link."""
        for ji in self.joint_infos:
            # Resolve actual un-merged parent and child nodes
            parent_node = self._resolve_unmerged_node(ji.parent_link_path)
            child_node = self._resolve_unmerged_node(ji.child_link_path)

            if parent_node is None or child_node is None:
                continue

            # If parent and child were merged into the same link, this joint is internal to a rigid group
            if parent_node == child_node:
                continue

            parent_link = self._link_map.get(parent_node.full_path)
            child_link = self._link_map.get(child_node.full_path)

            if not parent_link or not child_link:
                continue

            # If child_link is base_link, invert parent/child so base_link is parent
            if child_link.name == 'base_link' and parent_link.name != 'base_link':
                parent_link, child_link = child_link, parent_link
                parent_node, child_node = child_node, parent_node

            joint = URDFJoint(name=ji.name, joint_type=ji.joint_type)
            joint.parent_link = parent_link.name
            joint.child_link = child_link.name
            joint.origin_xyz = list(ji.origin_xyz)
            joint.origin_rpy = list(ji.origin_rpy)
            joint.axis = list(ji.axis)
            joint.depth = child_node.depth
            joint.limits = {
                'lower': ji.limit_lower,
                'upper': ji.limit_upper,
                'effort': ji.limit_effort,
                'velocity': ji.limit_velocity
            }
            joint._joint_info = ji

            self.joints.append(joint)

        # Check if base_link participates in joints as parent.
        # If the user selected a container occurrence (e.g. RobotArm) that holds the links,
        # but the kinematic joints originate from an inner base part (e.g. Base), promote that part to base_link!
        base_link_in_joints = any(j.parent_link == 'base_link' for j in self.joints)
        if not base_link_in_joints and self.joints:
            child_link_names = {j.child_link for j in self.joints}
            root_candidates = [j.parent_link for j in self.joints if j.parent_link not in child_link_names]
            if root_candidates:
                true_root_name = root_candidates[0]
                true_root_link = next((l for l in self.links if l.name == true_root_name), None)
                base_link_obj = next((l for l in self.links if l.name == 'base_link'), None)
                if true_root_link and base_link_obj:
                    # Inherit base_origin_world_frame if set
                    if self.base_origin_world_frame:
                        true_root_link.frame_world_transform = list(self.base_origin_world_frame)
                    old_name = true_root_link.name
                    true_root_link.name = 'base_link'
                    for j in self.joints:
                        if j.parent_link == old_name:
                            j.parent_link = 'base_link'
                        if j.child_link == old_name:
                            j.child_link = 'base_link'
                    for p, l in list(self._link_map.items()):
                        if l == true_root_link or l == base_link_obj:
                            self._link_map[p] = true_root_link
                    self.links = [l for l in self.links if l != base_link_obj]

        # Propagate kinematic frames and compute relative joint origins
        self._compute_kinematic_frames()

        # Any link (other than base_link) not connected by a joint must NOT be
        # included in the joint chain/tree; instead, merge its geometry into its parent link
        connected_link_names = {j.child_link for j in self.joints} | {j.parent_link for j in self.joints}
        links_to_remove = set()

        for link in list(self.links):
            if link.name == 'base_link' or link.name in connected_link_names:
                continue

            orig_path = None
            for p, l in self._link_map.items():
                if l == link:
                    orig_path = p
                    break

            target_link = None
            if orig_path and orig_path in self.nodes:
                node = self.nodes[orig_path]
                parent_node = node.parent
                while parent_node and parent_node.is_merged:
                    parent_node = parent_node.parent

                if parent_node:
                    # If base_node is a specific occurrence (not root), do not merge top-level root siblings into base_link!
                    if parent_node.full_path == 'root' and self.base_node and self.base_node.full_path != 'root':
                        target_link = None
                    else:
                        target_link = self._link_map.get(parent_node.full_path)

            if target_link and target_link != link and (target_link.name == 'base_link' or target_link.name in connected_link_names):
                for b in link.bodies:
                    if b not in target_link.bodies:
                        target_link.bodies.append(b)
                links_to_remove.add(link)
            elif target_link is None:
                # Disconnected component without parent in the kinematic tree: omit from URDF links
                links_to_remove.add(link)

        self.links = [l for l in self.links if l not in links_to_remove]

    def _resolve_unmerged_node(self, path):
        """Follow merged relationships to find the surviving parent OccurrenceNode."""
        if path not in self.nodes:
            # Check if path is root or base_link
            if path in ('root', 'base_link'):
                return self.base_node if self.base_node else self.nodes.get('root')
            return None

        node = self.nodes[path]
        if self.base_node and (path == 'root' or node == self.base_node):
            return self.base_node

        visited = set()
        while node.is_merged and node.parent is not None:
            if node in visited:
                break
            visited.add(node)
            node = node.parent

        if self.base_node and (node == self.base_node or node.full_path == 'root'):
            return self.base_node

        return node

    def _natural_sort_key(self, s):
        """Natural alphanumeric sorting key (e.g. Leg_2 before Leg_10)."""
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

    def _clean_branch_name(self, raw_name):
        """Clean an occurrence or link name into a readable branch identifier."""
        if not raw_name or raw_name in ('root', 'base_link'):
            return 'chain'
        # Strip Fusion occurrence instance suffix, e.g. ':1', ':2'
        name = re.sub(r':\d+$', '', str(raw_name))
        # Strip version strings, e.g. ' v1', ' v2'
        name = re.sub(r'\s+v\d+$', '', name)
        # Strip trailing '_link' if present
        name = re.sub(r'_link$', '', name)
        # Replace non-alphanumeric chars with underscore
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_').lower()
        return name or 'chain'

    def _find_branch_node(self, node):
        """Walk up occurrence parent hierarchy to find the top-level limb occurrence directly under root or base_node."""
        if not node:
            return None
        curr = node
        while curr and curr.parent:
            if curr.parent.full_path == 'root' or (self.base_node and curr.parent == self.base_node):
                return curr
            curr = curr.parent
        return curr

    def _get_joint_branch_name(self, joint):
        """Determine branch name for a joint from its child occurrence or link."""
        ji = getattr(joint, '_joint_info', None)
        child_node = None
        if ji and getattr(ji, 'child_link_path', None):
            child_node = self.nodes.get(ji.child_link_path)
        if not child_node:
            for path, link in self._link_map.items():
                if link.name == joint.child_link and path in self.nodes:
                    child_node = self.nodes[path]
                    break
        branch_node = self._find_branch_node(child_node)
        if branch_node:
            return self._clean_branch_name(branch_node.name)
        return self._clean_branch_name(joint.child_link)

    def _apply_naming_convention(self):
        """Apply joint naming convention indicating chain, level, and branch."""
        if not self.joints:
            return

        pattern = (self.naming_pattern or DEFAULT_JOINT_NAMING_PATTERN).strip()
        # Normalize any bracket typos (e.g. {branch_name], {chain), etc.)
        for key in ['branch_name', 'chain', 'level', 'type', 'joint', 'child_link', 'parent_link']:
            pattern = pattern.replace(f'[{key}]', f'{{{key}}}')
            pattern = pattern.replace(f'[{key})', f'{{{key}}}')
            pattern = pattern.replace(f'({key})', f'{{{key}}}')
            pattern = pattern.replace(f'{{{key})', f'{{{key}}}')
            pattern = pattern.replace(f'{{{key}]', f'{{{key}}}')

        # Check if legacy sequential type format is requested
        if pattern in ('{type}_{level}', '{type}_{counter}'):
            self._apply_legacy_naming_convention()
            return

        # -------------------------------------------------------------
        # 1. Topological Chain & Level Discovery
        # -------------------------------------------------------------
        children_joints = {}
        for j in self.joints:
            children_joints.setdefault(j.parent_link, []).append(j)

        child_link_names = {j.child_link for j in self.joints}
        base_link_name = 'base_link' if any(j.parent_link == 'base_link' for j in self.joints) else None
        if not base_link_name:
            candidates = [l for l in children_joints if l not in child_link_names]
            base_link_name = candidates[0] if candidates else None

        root_joints = list(children_joints.get(base_link_name, [])) if base_link_name else []

        # Sort root joints by natural sort order of branch name, then child link name
        root_joints.sort(key=lambda j: (
            self._natural_sort_key(self._get_joint_branch_name(j)),
            self._natural_sort_key(j.child_link)
        ))

        joint_meta = {}
        visited_joints = set()

        for chain_idx, rj in enumerate(root_joints, start=1):
            branch_name = self._get_joint_branch_name(rj)
            queue = [(rj, 1)]  # (joint, level)
            while queue:
                curr_j, level = queue.pop(0)
                if curr_j in visited_joints:
                    continue
                visited_joints.add(curr_j)
                joint_meta[curr_j] = {
                    'chain': chain_idx,
                    'level': level,
                    'branch_name': branch_name
                }
                next_joints = children_joints.get(curr_j.child_link, [])
                next_joints_sorted = sorted(next_joints, key=lambda j: self._natural_sort_key(j.child_link))
                for nj in next_joints_sorted:
                    if nj not in visited_joints:
                        queue.append((nj, level + 1))

        # Handle any remaining unvisited joints
        unvisited = [j for j in self.joints if j not in visited_joints]
        if unvisited:
            next_chain = len(root_joints) + 1
            for j in unvisited:
                branch_name = self._get_joint_branch_name(j)
                joint_meta[j] = {
                    'chain': next_chain,
                    'level': 1,
                    'branch_name': branch_name
                }
                next_chain += 1

        # -------------------------------------------------------------
        # 2. Parallel Branch Disambiguation within each (chain, level)
        # -------------------------------------------------------------
        chain_level_groups = {}
        for j, meta in joint_meta.items():
            key = (meta['chain'], meta['level'])
            chain_level_groups.setdefault(key, []).append(j)

        for key, j_group in chain_level_groups.items():
            if len(j_group) > 1:
                j_group.sort(key=lambda j: self._natural_sort_key(j.child_link))
                for idx, j in enumerate(j_group):
                    joint_meta[j]['disambig'] = chr(ord('a') + idx)
            else:
                joint_meta[j_group[0]]['disambig'] = ''

        # -------------------------------------------------------------
        # 3. Apply Naming Format
        # -------------------------------------------------------------
        used_names = set()
        for joint in self.joints:
            meta = joint_meta.get(joint, {'chain': 1, 'level': 1, 'branch_name': 'chain', 'disambig': ''})
            chain_num = meta['chain']
            level_num = meta['level']
            dis = meta.get('disambig', '')
            branch_name = meta['branch_name']

            joint.chain = chain_num
            joint.level = level_num
            joint.branch_name = branch_name

            level_str = f"{level_num}{dis}"
            clean_child = self._clean_branch_name(joint.child_link)
            clean_parent = self._clean_branch_name(joint.parent_link)

            try:
                name = pattern.format(
                    branch_name=branch_name,
                    chain=chain_num,
                    level=level_str,
                    type=joint.joint_type,
                    joint='joint',
                    child_link=clean_child,
                    parent_link=clean_parent
                )
            except Exception:
                name = f"{branch_name}_c{chain_num}_l{level_str}"

            name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
            name = re.sub(r'_+', '_', name).strip('_').lower()
            if not name:
                name = f"joint_{chain_num}_{level_str}"

            unique_name = name
            k = 2
            while unique_name in used_names:
                unique_name = f"{name}_{k}"
                k += 1
            used_names.add(unique_name)
            joint.name = unique_name

    def _apply_legacy_naming_convention(self):
        """Legacy sequential naming by child link depth: revolute_1, revolute_2, revolute_1A, etc."""
        depth_groups = {}
        for joint in self.joints:
            depth_groups.setdefault(joint.depth, []).append(joint)

        type_counters = {}
        for depth in sorted(depth_groups.keys()):
            joints_at_depth = depth_groups[depth]
            by_type = {}
            for j in joints_at_depth:
                by_type.setdefault(j.joint_type, []).append(j)

            for jtype, jlist in by_type.items():
                counter = type_counters.get(jtype, 0) + 1
                type_counters[jtype] = counter

                if len(jlist) == 1:
                    jlist[0].name = f"{jtype}_{counter}"
                else:
                    for idx, j in enumerate(jlist):
                        suffix = chr(ord('A') + idx)
                        j.name = f"{jtype}_{counter}{suffix}"

    def _sanitize_link_name(self, raw_name):
        """Clean occurrence name into a valid, readable URDF link identifier."""
        if raw_name in ('root', 'base_link'):
            return 'base_link'

        # Strip Fusion occurrence instance suffix, e.g. ':1', ':2'
        name = re.sub(r':\d+$', '', raw_name)
        # Strip version strings, e.g. ' v1', ' v2'
        name = re.sub(r'\s+v\d+$', '', name)
        # Replace non-alphanumeric chars with underscore
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_').lower()

        if not name:
            name = 'link'

        if not name.endswith('_link'):
            name = f"{name}_link"

        return name

    def _compute_kinematic_frames(self):
        """Topologically propagate world frames from base_link down to child links and compute relative joint transforms."""
        name_to_link = {l.name: l for l in self.links}
        base_link = name_to_link.get('base_link')
        if base_link:
            if not base_link.frame_world_transform:
                base_link.frame_world_transform = list(self.base_origin_world_frame or IDENTITY_16)

        # BFS queue starting from base_link
        queue = [base_link] if base_link else [l for l in self.links[:1]]
        visited_links = set(queue)

        while queue:
            curr_link = queue.pop(0)
            if curr_link is None:
                continue
            curr_frame = curr_link.frame_world_transform or list(IDENTITY_16)

            # Find all joints where curr_link is the parent
            for joint in self.joints:
                if joint.parent_link == curr_link.name:
                    child_link = name_to_link.get(joint.child_link)
                    ji = getattr(joint, '_joint_info', None)
                    if ji and ji.world_frame_cm:
                        child_frame = list(ji.world_frame_cm)
                        if child_link:
                            child_link.frame_world_transform = child_frame

                        # T_rel = T_parent^-1 * T_joint
                        parent_inv = pure_matrix_invert(curr_frame)
                        rel_mat = pure_matrix_multiply(parent_inv, child_frame)

                        joint.origin_xyz = [
                            rel_mat[3] * CM_TO_M,
                            rel_mat[7] * CM_TO_M,
                            rel_mat[11] * CM_TO_M
                        ]
                        joint.origin_rpy = pure_matrix_to_rpy(
                            rel_mat[0], rel_mat[1], rel_mat[2],
                            rel_mat[4], rel_mat[5], rel_mat[6],
                            rel_mat[8], rel_mat[9], rel_mat[10]
                        )
                        joint.axis = list(ji.axis)

                    if child_link and child_link not in visited_links:
                        visited_links.add(child_link)
                        queue.append(child_link)
