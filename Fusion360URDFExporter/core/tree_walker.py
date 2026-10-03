"""Assembly tree walker for Fusion 360 models."""

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


class OccurrenceNode:
    """Represents a component/occurrence in the assembly tree."""
    def __init__(self, occurrence=None, parent=None, depth=0):
        self.occurrence = occurrence
        self.parent = parent
        self.children = []
        self.depth = depth
        self.bodies = []
        self.is_merged = False
        self.merged_children = []

        if occurrence is not None:
            self.component = occurrence.component
            self.name = occurrence.name
            self.full_path = occurrence.fullPathName
            self.transform = getattr(occurrence, 'transform2', None)
            self.is_grounded = getattr(occurrence, 'isGrounded', False)
        else:
            self.component = None
            self.name = 'base_link'
            self.full_path = 'root'
            self.transform = None
            self.is_grounded = True

    def __repr__(self):
        return f"<OccurrenceNode name='{self.name}' path='{self.full_path}' depth={self.depth} merged={self.is_merged}>"


class AssemblyTreeWalker:
    """Traverses the Fusion 360 occurrence hierarchy."""
    def __init__(self, root_component, selected_base_occ=None):
        self.root = root_component
        self.selected_base_occ = selected_base_occ
        self.all_nodes = {}  # full_path -> OccurrenceNode
        self.base_node = None

    def walk(self):
        """Build the full occurrence tree starting from rootComponent."""
        root_node = OccurrenceNode(occurrence=None, parent=None, depth=0)
        root_node.component = self.root
        root_node.name = 'base_link'
        root_node.full_path = 'root'

        # Collect root component's own bodies (if any)
        if hasattr(self.root, 'bRepBodies'):
            for body in self.root.bRepBodies:
                try:
                    body._source_occ = None
                except Exception:
                    pass
                root_node.bodies.append(body)

        self.all_nodes['root'] = root_node

        if hasattr(self.root, 'occurrences'):
            self._walk_recursive(self.root.occurrences, root_node, depth=1)

        # Resolve base_node from selected occurrence, or grounded occurrence, or fallback to root
        if self.selected_base_occ is not None:
            for node in self.all_nodes.values():
                if node.occurrence == self.selected_base_occ:
                    self.base_node = node
                    break
                try:
                    if hasattr(node.occurrence, 'entityToken') and hasattr(self.selected_base_occ, 'entityToken'):
                        if node.occurrence.entityToken == self.selected_base_occ.entityToken:
                            self.base_node = node
                            break
                except Exception:
                    pass
                try:
                    node_path = getattr(node.occurrence, 'fullPathName', None)
                    target_path = getattr(self.selected_base_occ, 'fullPathName', None)
                    if node_path and target_path and node_path == target_path:
                        self.base_node = node
                        break
                except Exception:
                    pass

        if self.base_node is None:
            for node in self.all_nodes.values():
                if node.is_grounded and node.full_path != 'root':
                    self.base_node = node
                    break

        if self.base_node is None:
            for node in self.all_nodes.values():
                if node.full_path != 'root' and node.name.lower() in ('base', 'base_link', 'base_part', 'baselink'):
                    self.base_node = node
                    break

        if self.base_node is None:
            self.base_node = root_node

        return root_node

    def _walk_recursive(self, occurrences, parent_node, depth):
        for occ in occurrences:
            node = OccurrenceNode(occurrence=occ, parent=parent_node, depth=depth)

            # Collect bodies via occurrence proxy
            if hasattr(occ, 'bRepBodies'):
                for body in occ.bRepBodies:
                    try:
                        body._source_occ = occ
                    except Exception:
                        pass
                    node.bodies.append(body)

            parent_node.children.append(node)
            self.all_nodes[occ.fullPathName] = node

            # Recursively traverse nested child occurrences
            child_occs = getattr(occ, 'childOccurrences', None)
            if child_occs is not None:
                child_count = len(child_occs) if isinstance(child_occs, (list, tuple)) else getattr(child_occs, 'count', 0)
                if child_count > 0:
                    self._walk_recursive(child_occs, node, depth + 1)
