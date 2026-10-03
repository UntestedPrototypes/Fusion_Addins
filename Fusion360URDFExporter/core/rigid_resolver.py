"""Rigid group and rigid joint resolver for Fusion 360 assemblies.

Merges rigidly connected components into their highest-level ancestor link.
"""

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


class RigidGroupResolver:
    """Resolves rigid groups and rigid joints, merging children into the highest possible parent."""
    def __init__(self, root_component, tree_nodes, base_node=None, protected_paths=None):
        self.root = root_component
        self.nodes = tree_nodes  # full_path -> OccurrenceNode
        self.base_node = base_node
        self.base_node_path = getattr(base_node, 'full_path', None) if base_node else None
        self.protected_paths = set(protected_paths) if protected_paths else set()
        # merge_targets: child_path -> target_parent_path
        self.merge_map = {}
        self.merge_log = []

    def _is_descendant_of(self, child_path, ancestor_path):
        """Check if child_path is a strict descendant of ancestor_path in the tree."""
        if child_path not in self.nodes or ancestor_path not in self.nodes:
            return False
        curr = self.nodes[child_path].parent
        while curr:
            if curr.full_path == ancestor_path:
                return True
            curr = curr.parent
        return False

    def _crosses_kinematic_boundary(self, child_path, parent_path):
        """Check if merging child_path into parent_path crosses an active kinematic joint boundary."""
        for prot_path in self.protected_paths:
            # If child is the protected kinematic link itself, or a descendant of it
            is_child_in_branch = (child_path == prot_path) or self._is_descendant_of(child_path, prot_path)
            if is_child_in_branch:
                # If parent is outside this kinematic link branch (not the link itself and not in its branch)
                is_parent_in_branch = (parent_path == prot_path) or self._is_descendant_of(parent_path, prot_path)
                if not is_parent_in_branch:
                    return True
        return False

    def _is_joint_origin(self, ref):
        if ref is None:
            return False
        if HAS_ADSK and hasattr(adsk.fusion, 'JointOrigin'):
            try:
                if isinstance(ref, adsk.fusion.JointOrigin):
                    return True
            except Exception:
                pass
        type_name = type(ref).__name__
        if 'JointOrigin' in type_name:
            return True
        try:
            native = getattr(ref, 'nativeObject', None)
            if native and self._is_joint_origin(native):
                return True
        except Exception:
            pass
        try:
            ent = getattr(ref, 'entityOne', None)
            if ent and self._is_joint_origin(ent):
                return True
        except Exception:
            pass
        return False

    def _is_between_two_joint_origins(self, joint):
        """Check if a joint connects two JointOrigin features."""
        try:
            ref_one = getattr(joint, 'geometryOrOriginOne', None)
            ref_two = getattr(joint, 'geometryOrOriginTwo', None)
        except Exception:
            return False

        if ref_one is None or ref_two is None:
            return False

        return self._is_joint_origin(ref_one) and self._is_joint_origin(ref_two)

    def resolve(self):
        """Identify all rigid relationships and perform merges."""
        self._find_rigid_groups()
        self._find_rigid_joints()
        self._apply_merges()

    def _resolve_occ_path(self, occ, parent_node_path=None):
        """Map an occurrence (proxy or native) to a path in self.nodes."""
        if occ is None:
            return None
        # 1. Direct match on fullPathName
        try:
            full_path = occ.fullPathName
        except (RuntimeError, Exception):
            full_path = None
        if full_path and full_path in self.nodes:
            return full_path

        try:
            occ_name = occ.name
        except (RuntimeError, Exception):
            occ_name = ''

        # 2. If parent_node_path is known, try relative paths under parent
        if parent_node_path and parent_node_path != 'root':
            if occ_name:
                cand_plus = f"{parent_node_path}+{occ_name}"
                if cand_plus in self.nodes:
                    return cand_plus
                cand_slash = f"{parent_node_path}/{occ_name}"
                if cand_slash in self.nodes:
                    return cand_slash

            parent_node = self.nodes.get(parent_node_path)
            if parent_node:
                for child in parent_node.children:
                    if child.name == occ_name:
                        return child.full_path
                    try:
                        child_comp = child.occurrence.component if child.occurrence else None
                        occ_comp = occ.component
                        if child_comp and child_comp == occ_comp:
                            return child.full_path
                    except (RuntimeError, Exception):
                        pass

        # 3. Search across all nodes
        for p, n in self.nodes.items():
            try:
                if n.occurrence == occ:
                    return p
            except (RuntimeError, Exception):
                pass
            if occ_name and (n.name == occ_name or n.full_path.endswith(f"+{occ_name}") or n.full_path.endswith(f"/{occ_name}")):
                return p

        return full_path if (full_path and full_path in self.nodes) else None

    def _collect_descendants(self, node, result):
        for child in node.children:
            result.append(child.full_path)
            self._collect_descendants(child, result)

    def _find_rigid_groups(self):
        """Scan rigid groups across all components in the assembly."""
        has_assembly_groups = False

        # 1. Check allRigidGroups on root (returns assembly proxies for all subassemblies)
        try:
            rg_all = getattr(self.root, 'allRigidGroups', None)
            if rg_all is not None:
                self._process_rigid_groups_collection(rg_all, parent_node_path=None)
                has_assembly_groups = True
        except (RuntimeError, Exception):
            pass

        # 2. Check root component direct rigidGroups
        try:
            rg_root = getattr(self.root, 'rigidGroups', None)
            if rg_root is not None:
                self._process_rigid_groups_collection(rg_root, parent_node_path='root')
        except (RuntimeError, Exception):
            pass

        # 3. Check sub-components only if allRigidGroups was not available
        # Note: In Fusion 360, rigid groups belong to Component, never Occurrence.
        if not has_assembly_groups:
            for path, node in self.nodes.items():
                if path == 'root' or not node.component:
                    continue
                try:
                    rg_comp = getattr(node.component, 'rigidGroups', None)
                    if rg_comp is not None:
                        self._process_rigid_groups_collection(rg_comp, parent_node_path=path)
                except (RuntimeError, Exception):
                    pass

    def _process_rigid_groups_collection(self, rigid_groups, parent_node_path):
        if not rigid_groups:
            return

        try:
            rg_list = list(rigid_groups)
        except (RuntimeError, Exception):
            return

        for rg in rg_list:
            try:
                if getattr(rg, 'isSuppressed', False):
                    continue
            except (RuntimeError, Exception):
                continue

            owner_path = parent_node_path
            try:
                parent_comp = getattr(rg, 'parentComponent', None)
            except (RuntimeError, Exception):
                parent_comp = None

            if parent_comp:
                if parent_comp == self.root:
                    owner_path = 'root'
                else:
                    for p, n in self.nodes.items():
                        if n.component == parent_comp:
                            owner_path = p
                            break

            members = []
            try:
                rg_occs = list(rg.occurrences)
            except (RuntimeError, Exception):
                rg_occs = []

            for occ in rg_occs:
                try:
                    path = self._resolve_occ_path(occ, owner_path)
                    if path and path in self.nodes:
                        members.append(path)
                except (RuntimeError, Exception):
                    pass

            if not members:
                continue

            # Include children if flag is enabled
            is_inc = False
            try:
                is_inc = getattr(rg, 'isIncludeChildren', False)
            except (RuntimeError, Exception):
                pass

            if is_inc:
                extra = []
                for m_path in members:
                    m_node = self.nodes.get(m_path)
                    if m_node:
                        self._collect_descendants(m_node, extra)
                for ep in extra:
                    if ep not in members and ep in self.nodes:
                        members.append(ep)

            # Target to merge into:
            # If rigid group is defined in a specific parent component, merge children into it
            if owner_path and owner_path in self.nodes and owner_path != 'root':
                target_path = owner_path
            else:
                if self.base_node_path and self.base_node_path in members:
                    target_path = self.base_node_path
                else:
                    target_path = min(members, key=lambda p: self.nodes[p].depth)

            for member_path in members:
                if member_path != target_path:
                    self._register_merge(child_path=member_path, parent_path=target_path)

    def _find_rigid_joints(self):
        """Scan standard and as-built joints for rigid joints."""
        all_joints = []
        has_assembly_joints = False

        try:
            j_all = getattr(self.root, 'allJoints', None)
            if j_all is not None:
                all_joints.extend(list(j_all))
                has_assembly_joints = True
        except (RuntimeError, Exception):
            pass

        if not has_assembly_joints:
            try:
                j_root = getattr(self.root, 'joints', None)
                if j_root is not None:
                    all_joints.extend(list(j_root))
            except (RuntimeError, Exception):
                pass

        try:
            abj_all = getattr(self.root, 'allAsBuiltJoints', None)
            if abj_all is not None:
                all_joints.extend(list(abj_all))
        except (RuntimeError, Exception):
            pass

        try:
            abj_root = getattr(self.root, 'asBuiltJoints', None)
            if abj_root is not None:
                all_joints.extend(list(abj_root))
        except (RuntimeError, Exception):
            pass

        # Only check sub-components if root has no assembly-level joints collection
        if not has_assembly_joints:
            for path, node in self.nodes.items():
                if path == 'root' or not node.component:
                    continue
                for attr in ('joints', 'asBuiltJoints'):
                    try:
                        j_coll = getattr(node.component, attr, None)
                        if j_coll:
                            for j in j_coll:
                                if j not in all_joints:
                                    all_joints.append(j)
                    except (RuntimeError, Exception):
                        pass

        for joint in all_joints:
            # Safely check if joint is suppressed, catching Fusion C++ InternalValidationErrors
            try:
                if joint.isSuppressed:
                    continue
            except (RuntimeError, Exception):
                # If isSuppressed fails (e.g. missing jointOcc), the joint has no valid assembly occurrence context
                continue

            try:
                motion = joint.jointMotion
            except (RuntimeError, Exception):
                motion = None
            if motion is None:
                continue

            # Check if rigid joint
            is_rigid = False
            if HAS_ADSK and hasattr(adsk.fusion, 'JointTypes'):
                try:
                    if motion.jointType == adsk.fusion.JointTypes.RigidJointType:
                        is_rigid = True
                except (RuntimeError, Exception):
                    pass
            if not is_rigid:
                try:
                    jtype_str = str(getattr(motion, 'jointType', '')).lower()
                    if 'rigid' in jtype_str or jtype_str in ('0', 'rigidjointtype'):
                        is_rigid = True
                except (RuntimeError, Exception):
                    pass

            if not is_rigid:
                continue

            # If this rigid joint is made between two joint origins, it is an explicit kinematic/fixed joint, NOT a merge
            if self._is_between_two_joint_origins(joint):
                continue

            try:
                occ_one = getattr(joint, 'occurrenceOne', None)
            except (RuntimeError, Exception):
                occ_one = None

            try:
                occ_two = getattr(joint, 'occurrenceTwo', None)
            except (RuntimeError, Exception):
                occ_two = None

            path_one = self._resolve_occ_path(occ_one) if occ_one else 'root'
            path_two = self._resolve_occ_path(occ_two) if occ_two else 'root'

            if occ_one and not path_one:
                continue
            if occ_two and not path_two:
                continue
            if not path_one or not path_two:
                continue

            if path_one == path_two:
                continue

            node_one = self.nodes.get(path_one)
            node_two = self.nodes.get(path_two)

            if node_one and node_two:
                # Merge the deeper component into the higher component (highest level possible)
                if node_one.depth > node_two.depth:
                    self._register_merge(child_path=path_one, parent_path=path_two)
                elif node_two.depth > node_one.depth:
                    self._register_merge(child_path=path_two, parent_path=path_one)
                else:
                    self._register_merge(child_path=path_one, parent_path=path_two)

    def _register_merge(self, child_path, parent_path):
        """Record a child -> parent merge relationship."""
        if child_path == parent_path:
            return

        # 1. Base node must never be merged into root or any other node
        if self.base_node_path and child_path == self.base_node_path:
            self.merge_log.append(
                f"[BLOCKED] Base node '{child_path}' cannot be merged into '{parent_path}'"
            )
            return

        # 2. Moving kinematic child links and their descendants must not merge across joint boundaries
        if self._crosses_kinematic_boundary(child_path, parent_path):
            self.merge_log.append(
                f"[BLOCKED] Kinematic boundary: '{child_path}' cannot merge into '{parent_path}'"
            )
            return

        # 3. If parent_path is 'root' but a custom base_node exists:
        # Descendants of base_node should merge into base_node, not into 'root'
        if parent_path == 'root' and self.base_node_path and self.base_node_path != 'root':
            if child_path != self.base_node_path and self._is_descendant_of(child_path, self.base_node_path):
                parent_path = self.base_node_path
            else:
                self.merge_log.append(
                    f"[BLOCKED] Sibling/unrelated node '{child_path}' cannot merge into 'root' when custom base_node is set"
                )
                return

        self.merge_map[child_path] = parent_path
        self.merge_log.append(f"[MERGED] '{child_path}' -> '{parent_path}'")

    def _get_ultimate_target(self, path):
        """Resolve transitive merges (A -> B -> C => C). Avoid cycles."""
        visited = set()
        curr = path
        while curr in self.merge_map:
            if curr in visited:
                break
            visited.add(curr)
            curr = self.merge_map[curr]
        return curr

    def _apply_merges(self):
        """Apply merges to the OccurrenceNodes."""
        # Resolve all ultimate targets
        final_targets = {}
        for child_path in self.merge_map:
            final_targets[child_path] = self._get_ultimate_target(child_path)

        for child_path, target_path in final_targets.items():
            if child_path not in self.nodes or target_path not in self.nodes:
                continue

            child_node = self.nodes[child_path]
            target_node = self.nodes[target_path]

            if child_node == target_node:
                continue

            # Extra safety: do not merge base_node into root or anything else
            if self.base_node_path and child_path == self.base_node_path:
                continue

            # Extra safety: do not merge across kinematic boundary
            if self._crosses_kinematic_boundary(child_path, target_path):
                continue

            child_node.is_merged = True
            if child_node not in target_node.merged_children:
                target_node.merged_children.append(child_node)

            # Transfer child bodies to target node
            for body in child_node.bodies:
                if body not in target_node.bodies:
                    target_node.bodies.append(body)
