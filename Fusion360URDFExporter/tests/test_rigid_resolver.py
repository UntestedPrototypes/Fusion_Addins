"""Tests for rigid group and joint merging resolution."""

import unittest
from core.tree_walker import OccurrenceNode
from core.rigid_resolver import RigidGroupResolver


class MockBody:
    def __init__(self, name):
        self.name = name


class MockNode(OccurrenceNode):
    def __init__(self, name, full_path, depth=0, parent=None):
        super().__init__(None, parent, depth)
        self.name = name
        self.full_path = full_path
        self.depth = depth


class MockRigidGroup:
    def __init__(self, occurrences, isSuppressed=False):
        self.occurrences = occurrences
        self.isSuppressed = isSuppressed


class MockOcc:
    def __init__(self, fullPathName):
        self.fullPathName = fullPathName


class MockComp:
    def __init__(self, rigidGroups=None):
        self.rigidGroups = rigidGroups or []


class TestRigidResolver(unittest.TestCase):
    def test_child_merged_into_parent(self):
        """Test child occurrences in a rigid group defined in parent are merged into parent."""
        parent_node = MockNode('parent', 'root/parent', depth=1)
        child1_node = MockNode('child1', 'root/parent/child1', depth=2, parent=parent_node)
        child2_node = MockNode('child2', 'root/parent/child2', depth=2, parent=parent_node)

        b_parent = MockBody('b_parent')
        b_c1 = MockBody('b_c1')
        b_c2 = MockBody('b_c2')

        parent_node.bodies.append(b_parent)
        child1_node.bodies.append(b_c1)
        child2_node.bodies.append(b_c2)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/parent': parent_node,
            'root/parent/child1': child1_node,
            'root/parent/child2': child2_node
        }

        # Rigid group defined in parent component grouping child1 and child2
        rg = MockRigidGroup([MockOcc('root/parent/child1'), MockOcc('root/parent/child2')])
        parent_comp = MockComp([rg])
        parent_node.component = parent_comp

        root_comp = MockComp([])

        resolver = RigidGroupResolver(root_comp, nodes)
        resolver.resolve()

        self.assertTrue(child1_node.is_merged)
        self.assertTrue(child2_node.is_merged)
        self.assertFalse(parent_node.is_merged)

        # Bodies must be merged into parent
        self.assertIn(b_parent, parent_node.bodies)
        self.assertIn(b_c1, parent_node.bodies)
        self.assertIn(b_c2, parent_node.bodies)

    def test_transitive_merge(self):
        """Test transitive merge chain A -> B -> C."""
        node_a = MockNode('a', 'root/a', depth=1)
        node_b = MockNode('b', 'root/a/b', depth=2, parent=node_a)
        node_c = MockNode('c', 'root/a/b/c', depth=3, parent=node_b)

        body_c = MockBody('body_c')
        node_c.bodies.append(body_c)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/a': node_a,
            'root/a/b': node_b,
            'root/a/b/c': node_c
        }

        resolver = RigidGroupResolver(MockComp(), nodes)
        # Register c -> b, and b -> a
        resolver._register_merge('root/a/b/c', 'root/a/b')
        resolver._register_merge('root/a/b', 'root/a')
        resolver._apply_merges()

        self.assertTrue(node_c.is_merged)
        self.assertTrue(node_b.is_merged)
        self.assertFalse(node_a.is_merged)
        self.assertIn(body_c, node_a.bodies)

    def test_rigid_joint_merges_child_into_parent(self):
        """Test that a rigid joint merges child occurrence into parent and transfers bodies."""
        parent_node = MockNode('link1', 'root/link1', depth=1)
        child_node = MockNode('bracket', 'root/link1/bracket', depth=2, parent=parent_node)

        body_parent = MockBody('body_parent')
        body_bracket = MockBody('body_bracket')
        parent_node.bodies.append(body_parent)
        child_node.bodies.append(body_bracket)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/link1': parent_node,
            'root/link1/bracket': child_node
        }

        class MockMotion:
            jointType = 'RigidJointType'

        class MockJoint:
            isSuppressed = False
            jointMotion = MockMotion()
            occurrenceOne = MockOcc('root/link1/bracket')
            occurrenceTwo = MockOcc('root/link1')

        class MockRootWithJoints:
            rigidGroups = []
            joints = [MockJoint()]
            asBuiltJoints = []

        resolver = RigidGroupResolver(MockRootWithJoints(), nodes)
        resolver.resolve()

        self.assertTrue(child_node.is_merged)
        self.assertFalse(parent_node.is_merged)
        self.assertIn(body_bracket, parent_node.bodies)
        self.assertIn(body_parent, parent_node.bodies)

    def test_base_node_locked_cannot_merge_into_root(self):
        """Test that the designated base_node is never merged into root even with a rigid joint."""
        base_node = MockNode('base_part', 'root/base_part', depth=1)
        root_node = MockNode('root', 'root', depth=0)
        body_base = MockBody('body_base')
        base_node.bodies.append(body_base)

        nodes = {
            'root': root_node,
            'root/base_part': base_node
        }

        class MockMotion:
            jointType = 'RigidJointType'

        class MockJoint:
            isSuppressed = False
            jointMotion = MockMotion()
            occurrenceOne = MockOcc('root/base_part')
            occurrenceTwo = None  # Joint to root assembly

        class MockRootWithJoints:
            rigidGroups = []
            joints = [MockJoint()]
            asBuiltJoints = []

        resolver = RigidGroupResolver(MockRootWithJoints(), nodes, base_node=base_node)
        resolver.resolve()

        self.assertFalse(base_node.is_merged)
        self.assertNotIn(body_base, root_node.bodies)
        self.assertIn(body_base, base_node.bodies)

    def test_kinematic_child_link_protected_from_merging_into_base(self):
        """Test that a moving kinematic child link (e.g. Coxa) is never merged into base link."""
        base_node = MockNode('base_part', 'root/base_part', depth=1)
        leg1_node = MockNode('leg1', 'root/leg1', depth=1)
        coxa_node = MockNode('coxa', 'root/leg1/coxa', depth=2, parent=leg1_node)

        body_base = MockBody('body_base')
        body_coxa = MockBody('body_coxa')
        base_node.bodies.append(body_base)
        coxa_node.bodies.append(body_coxa)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/base_part': base_node,
            'root/leg1': leg1_node,
            'root/leg1/coxa': coxa_node
        }

        class MockMotion:
            jointType = 'RigidJointType'

        # Simulate a rigid joint between coxa and base (e.g. bearing/bracket in CAD)
        class MockJoint:
            isSuppressed = False
            jointMotion = MockMotion()
            occurrenceOne = MockOcc('root/leg1/coxa')
            occurrenceTwo = MockOcc('root/base_part')

        class MockRootWithJoints:
            rigidGroups = []
            joints = [MockJoint()]
            asBuiltJoints = []

        # coxa is registered as an active kinematic child link
        protected_paths = {'root/leg1/coxa'}

        resolver = RigidGroupResolver(
            MockRootWithJoints(),
            nodes,
            base_node=base_node,
            protected_paths=protected_paths
        )
        resolver.resolve()

        # Coxa must NOT be merged into base_part!
        self.assertFalse(coxa_node.is_merged)
        self.assertNotIn(body_coxa, base_node.bodies)
        self.assertIn(body_coxa, coxa_node.bodies)

    def test_kinematic_child_descendant_cannot_merge_into_base(self):
        """Test that a component inside a kinematic link (e.g. bearing in coxa) cannot merge into base."""
        base_node = MockNode('base_part', 'root/base_part', depth=1)
        leg1_node = MockNode('leg1', 'root/leg1', depth=1)
        coxa_node = MockNode('coxa', 'root/leg1/coxa', depth=2, parent=leg1_node)
        bearing_node = MockNode('bearing', 'root/leg1/coxa/bearing', depth=3, parent=coxa_node)

        body_base = MockBody('body_base')
        body_bearing = MockBody('body_bearing')
        base_node.bodies.append(body_base)
        bearing_node.bodies.append(body_bearing)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/base_part': base_node,
            'root/leg1': leg1_node,
            'root/leg1/coxa': coxa_node,
            'root/leg1/coxa/bearing': bearing_node
        }

        class MockMotion:
            jointType = 'RigidJointType'

        # Rigid joint connecting bearing to base
        class MockJoint:
            isSuppressed = False
            jointMotion = MockMotion()
            occurrenceOne = MockOcc('root/leg1/coxa/bearing')
            occurrenceTwo = MockOcc('root/base_part')

        class MockRootWithJoints:
            rigidGroups = []
            joints = [MockJoint()]
            asBuiltJoints = []

        protected_paths = {'root/leg1/coxa'}

        resolver = RigidGroupResolver(
            MockRootWithJoints(),
            nodes,
            base_node=base_node,
            protected_paths=protected_paths
        )
        resolver.resolve()

        # Bearing must NOT merge into base across the kinematic boundary!
        self.assertFalse(bearing_node.is_merged)
        self.assertNotIn(body_bearing, base_node.bodies)

    def test_internal_part_of_kinematic_child_still_merges_into_child(self):
        """Test that internal parts inside a kinematic link (e.g. servo bracket inside coxa) DO merge into coxa."""
        base_node = MockNode('base_part', 'root/base_part', depth=1)
        leg1_node = MockNode('leg1', 'root/leg1', depth=1)
        coxa_node = MockNode('coxa', 'root/leg1/coxa', depth=2, parent=leg1_node)
        servo_node = MockNode('servo', 'root/leg1/coxa/servo', depth=3, parent=coxa_node)

        body_coxa = MockBody('body_coxa')
        body_servo = MockBody('body_servo')
        coxa_node.bodies.append(body_coxa)
        servo_node.bodies.append(body_servo)

        nodes = {
            'root': MockNode('root', 'root', depth=0),
            'root/base_part': base_node,
            'root/leg1': leg1_node,
            'root/leg1/coxa': coxa_node,
            'root/leg1/coxa/servo': servo_node
        }

        class MockMotion:
            jointType = 'RigidJointType'

        # Rigid joint connecting servo to coxa (internal to the coxa link)
        class MockJoint:
            isSuppressed = False
            jointMotion = MockMotion()
            occurrenceOne = MockOcc('root/leg1/coxa/servo')
            occurrenceTwo = MockOcc('root/leg1/coxa')

        class MockRootWithJoints:
            rigidGroups = []
            joints = [MockJoint()]
            asBuiltJoints = []

        protected_paths = {'root/leg1/coxa'}

        resolver = RigidGroupResolver(
            MockRootWithJoints(),
            nodes,
            base_node=base_node,
            protected_paths=protected_paths
        )
        resolver.resolve()

        # Servo SHOULD merge into coxa!
        self.assertTrue(servo_node.is_merged)
        self.assertIn(body_servo, coxa_node.bodies)
        self.assertNotIn(body_servo, base_node.bodies)


if __name__ == '__main__':
    unittest.main()
