"""Tests for body isolation between links and safe mesh export behavior."""

import unittest
import tempfile
from core.tree_walker import OccurrenceNode
from core.joint_analyzer import JointInfo
from core.kinematic_builder import KinematicTreeBuilder, URDFLink
from core.mesh_exporter import MeshExporter


class MockBody:
    def __init__(self, name):
        self.name = name


class MockExportMgr:
    def __init__(self, fail_body=False, fail_occ=False):
        self.fail_body = fail_body
        self.fail_occ = fail_occ
        self.calls = []

    def createSTLExportOptions(self, target, filename=None):
        self.calls.append(target)
        is_comp_or_occ = hasattr(target, 'is_occurrence') or hasattr(target, 'is_component')
        if is_comp_or_occ and self.fail_occ:
            raise RuntimeError("Occ export failed")
        if not is_comp_or_occ and self.fail_body:
            raise RuntimeError("Body export failed")
        
        class MockOptions:
            def __init__(self, fn):
                self.filename = fn
                self.meshRefinement = None
                self.aspectRatio = None
                self.surfaceDeviation = None
                self.normalDeviation = None
                self.maxEdgeLength = None
                self.sendToPrintUtility = None
        return MockOptions(filename)

    def execute(self, options):
        # Write dummy binary STL with 0 triangles
        with open(options.filename, 'wb') as f:
            f.write(b'\x00' * 80)
            f.write((0).to_bytes(4, byteorder='little'))
        return True


class TestBodyIsolationAndMeshExport(unittest.TestCase):
    def test_base_link_body_isolation_when_occurrence_is_base(self):
        """Verify root bodies and other link bodies never bleed into base_link."""
        root_node = OccurrenceNode(None, None, depth=0)
        root_node.name = 'RootComponent'
        root_node.full_path = 'root'
        root_body1 = MockBody('root_body1')
        root_body2 = MockBody('root_body2')
        root_node.bodies = [root_body1, root_body2]

        base_occ_node = OccurrenceNode(None, root_node, depth=1)
        base_occ_node.name = 'Base:1'
        base_occ_node.full_path = 'root/Base:1'
        base_body = MockBody('base_body')
        base_occ_node.bodies = [base_body]

        link1_node = OccurrenceNode(None, root_node, depth=1)
        link1_node.name = 'Link1:1'
        link1_node.full_path = 'root/Link1:1'
        link1_body = MockBody('link1_body')
        link1_node.bodies = [link1_body]

        nodes = {
            'root': root_node,
            base_occ_node.full_path: base_occ_node,
            link1_node.full_path: link1_node,
        }

        j = JointInfo()
        j.joint_type = 'revolute'
        j.parent_link_path = base_occ_node.full_path
        j.child_link_path = link1_node.full_path

        builder = KinematicTreeBuilder(nodes, [j], base_node=base_occ_node)
        links, joints = builder.build()

        base_link = next(l for l in links if l.name == 'base_link')
        self.assertEqual(len(base_link.bodies), 1)
        self.assertIn(base_body, base_link.bodies)
        self.assertNotIn(root_body1, base_link.bodies)
        self.assertNotIn(root_body2, base_link.bodies)
        self.assertNotIn(link1_body, base_link.bodies)

    def test_container_occurrence_promotion(self):
        """Verify selecting a container subassembly promotes the actual root child part to base_link."""
        root_node = OccurrenceNode(None, None, depth=0)
        root_node.name = 'Root'
        root_node.full_path = 'root'

        # Container occurrence selected as base
        robot_container = OccurrenceNode(None, root_node, depth=1)
        robot_container.name = 'RobotArm:1'
        robot_container.full_path = 'root/RobotArm:1'
        robot_container.bodies = []

        base_part = OccurrenceNode(None, robot_container, depth=2)
        base_part.name = 'BasePedestal:1'
        base_part.full_path = 'root/RobotArm:1/BasePedestal:1'
        base_body = MockBody('base_pedestal_body')
        base_part.bodies = [base_body]

        link1 = OccurrenceNode(None, robot_container, depth=2)
        link1.name = 'Link1:1'
        link1.full_path = 'root/RobotArm:1/Link1:1'
        link1_body = MockBody('link1_body')
        link1.bodies = [link1_body]

        nodes = {
            'root': root_node,
            robot_container.full_path: robot_container,
            base_part.full_path: base_part,
            link1.full_path: link1,
        }

        j = JointInfo()
        j.joint_type = 'revolute'
        j.parent_link_path = base_part.full_path
        j.child_link_path = link1.full_path

        builder = KinematicTreeBuilder(nodes, [j], base_node=robot_container)
        links, joints = builder.build()

        link_names = [l.name for l in links]
        self.assertIn('base_link', link_names)
        self.assertIn('link1_link', link_names)
        self.assertNotIn('robotarm_link', link_names)

        base_link = next(l for l in links if l.name == 'base_link')
        self.assertEqual(base_link.bodies, [base_body])
        self.assertEqual(joints[0].parent_link, 'base_link')
        self.assertEqual(joints[0].child_link, 'link1_link')

    def test_mesh_exporter_occurrence_fallback_with_child_isolation(self):
        """Verify fallback to component safely isolates target body by temporarily hiding child occurrences and sibling bodies."""
        from unittest.mock import patch
        from core.transform_utils import IDENTITY_16
        import core.mesh_exporter as me_module

        export_mgr = MockExportMgr(fail_body=True)
        class MockDesign:
            exportManager = export_mgr
        exporter = MeshExporter(MockDesign(), output_dir='dummy_dir')

        class MockChildOcc:
            is_occurrence = True
            isLightBulbOn = True

        child1 = MockChildOcc()
        child2 = MockChildOcc()

        class MockComp:
            is_component = True
            occurrences = [child1, child2]
            bRepBodies = []

        class MockOcc:
            is_occurrence = True
            def __init__(self):
                self.childOccurrences = [child1, child2]
                self.component = MockComp()

        body = MockBody('test_body')
        body._source_occ = MockOcc()
        body._source_occ.component.bRepBodies = [body]

        with patch.object(me_module, 'HAS_ADSK', True):
            triangles = exporter._export_single_body_triangles(body, 'high', IDENTITY_16, 1.0)
            # Component target should be called
            self.assertTrue(any(getattr(c, 'is_component', False) for c in export_mgr.calls))
            # Child occurrences should have their visibility restored after export
            self.assertTrue(child1.isLightBulbOn)
            self.assertTrue(child2.isLightBulbOn)

    def test_mesh_exporter_progress_callback(self):
        """Verify progress_callback is invoked for visual bodies and instant collision copy, and aborts on False."""
        from core.kinematic_builder import URDFLink
        import tempfile

        class MockDesign:
            exportManager = None

        with tempfile.TemporaryDirectory() as td:
            exporter = MeshExporter(MockDesign(), output_dir=td)
            link = URDFLink('test_link')
            b1 = MockBody('BodyA')
            b1.triangles = []
            b2 = MockBody('BodyB')
            b2.triangles = []
            link.bodies = [b1, b2]

            calls = []
            def progress_cb(b_idx, total_b, b_name, mesh_type):
                calls.append((b_idx, total_b, b_name, mesh_type))
                return True

            res = exporter.export_link_meshes(link, progress_callback=progress_cb)
            self.assertTrue(res)
            # 2 visual body calls + 1 instant collision copy call = 3 calls total
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0], (1, 2, 'BodyA', 'visual'))
            self.assertEqual(calls[1], (2, 2, 'BodyB', 'visual'))
            self.assertEqual(calls[2], (1, 1, 'test_link (collision)', 'collision'))

            # Test cancellation / abort during visual
            cancel_calls = []
            def cancel_cb(b_idx, total_b, b_name, mesh_type):
                cancel_calls.append(b_name)
                return False  # Abort immediately

            res_cancel = exporter.export_link_meshes(link, progress_callback=cancel_cb)
            self.assertFalse(res_cancel)
            self.assertEqual(len(cancel_calls), 1)

    def test_instant_collision_mesh_reuse(self):
        """Verify collision STL is created via instant copy of visual STL."""
        from core.kinematic_builder import URDFLink
        import os
        import tempfile

        class MockDesign:
            exportManager = None

        with tempfile.TemporaryDirectory() as td:
            exporter = MeshExporter(MockDesign(), output_dir=td)
            link = URDFLink('arm_link')
            b1 = MockBody('arm_body')
            # Mock single triangle in body
            b1.triangles = [((0, 0, 1), (0, 0, 0), (1, 0, 0), (0, 1, 0))]
            link.bodies = [b1]

            res = exporter.export_link_meshes(link)
            self.assertTrue(res)

            v_path = os.path.join(td, 'meshes', 'visual', 'arm_link.stl')
            c_path = os.path.join(td, 'meshes', 'collision', 'arm_link.stl')

            self.assertTrue(os.path.exists(v_path))
            self.assertTrue(os.path.exists(c_path))
            # Verify collision file is identical to visual file (instant reuse)
            with open(v_path, 'rb') as f_v, open(c_path, 'rb') as f_c:
                self.assertEqual(f_v.read(), f_c.read())

    def test_leaf_occurrence_batch_export(self):
        """Verify leaf occurrences (childOccurrences == 0) are batched in a single export pass."""
        from core.kinematic_builder import URDFLink
        from core.transform_utils import IDENTITY_16
        from unittest.mock import patch
        import core.mesh_exporter as me_module
        import tempfile

        export_mgr = MockExportMgr(fail_body=False, fail_occ=False)
        class MockDesign:
            exportManager = export_mgr
            rootComponent = None

        b1 = MockBody('Bolt1')
        b2 = MockBody('Bolt2')

        class MockComp:
            is_component = True
            bRepBodies = [b1, b2]

        class MockLeafOcc:
            __hash__ = None  # Replicate unhashable C++ wrapper type in Fusion 360 API
            is_occurrence = True
            name = 'LeafComp:1'
            childOccurrences = []
            transform = None
            component = MockComp()

        leaf_occ = MockLeafOcc()
        b1._source_occ = leaf_occ
        b2._source_occ = leaf_occ

        with tempfile.TemporaryDirectory() as td:
            exporter = MeshExporter(MockDesign(), output_dir=td)
            link = URDFLink('bracket_link')
            link.bodies = [b1, b2]

            with patch.object(me_module, 'HAS_ADSK', True):
                res = exporter.export_link_meshes(link)
                self.assertTrue(res)

                # Exactly 1 export call should have occurred for the leaf occurrence/component (not 2 for each body!)
                occ_calls = [c for c in export_mgr.calls if getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False)]
                body_calls = [c for c in export_mgr.calls if not (getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False))]
                self.assertEqual(len(occ_calls), 1)
                self.assertEqual(len(body_calls), 0)

    def test_batch_export_rejected_when_component_has_occurrences(self):
        """Verify batch component export is blocked when component has occurrences, falling back to per-body."""
        from unittest.mock import patch
        import core.mesh_exporter as me_module
        import tempfile

        export_mgr = MockExportMgr(fail_body=False, fail_occ=False)
        class MockDesign:
            exportManager = export_mgr
            rootComponent = None

        class MockComp:
            is_component = True
            occurrences = [MockBody('SubOcc')]
            bRepBodies = []

        b1 = MockBody('Body1')
        MockComp.bRepBodies = [b1]

        class MockOcc:
            is_occurrence = True
            childOccurrences = []
            component = MockComp()

        occ = MockOcc()
        b1._source_occ = occ

        with tempfile.TemporaryDirectory() as td:
            exporter = MeshExporter(MockDesign(), output_dir=td)
            link = URDFLink('test_link')
            link.bodies = [b1]

            with patch.object(me_module, 'HAS_ADSK', True):
                res = exporter.export_link_meshes(link)
                self.assertTrue(res)

                # Should NOT export component (because comp.occurrences > 0); must fall back to per-body
                occ_calls = [c for c in export_mgr.calls if getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False)]
                body_calls = [c for c in export_mgr.calls if not (getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False))]
                self.assertEqual(len(occ_calls), 0)
                self.assertEqual(len(body_calls), 1)

    def test_batch_export_rejected_when_body_count_mismatches(self):
        """Verify batch export is blocked when link only owns a subset of the component's bodies."""
        from unittest.mock import patch
        import core.mesh_exporter as me_module
        import tempfile

        export_mgr = MockExportMgr(fail_body=False, fail_occ=False)
        class MockDesign:
            exportManager = export_mgr
            rootComponent = None

        b1 = MockBody('BaseBody')
        b2_joint = MockBody('JointBody')

        class MockComp:
            is_component = True
            occurrences = []
            bRepBodies = [b1, b2_joint]  # Component contains 2 bodies

        class MockOcc:
            is_occurrence = True
            childOccurrences = []
            component = MockComp()

        occ = MockOcc()
        b1._source_occ = occ
        b2_joint._source_occ = occ

        with tempfile.TemporaryDirectory() as td:
            exporter = MeshExporter(MockDesign(), output_dir=td)
            link = URDFLink('base_link')
            # base_link only owns b1, NOT b2_joint
            link.bodies = [b1]

            with patch.object(me_module, 'HAS_ADSK', True):
                res = exporter.export_link_meshes(link)
                self.assertTrue(res)

                # Batch export of comp must be rejected (2 bodies in comp vs 1 in link.bodies)
                # to prevent JointBody from bleeding into base_link!
                occ_calls = [c for c in export_mgr.calls if getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False)]
                body_calls = [c for c in export_mgr.calls if not (getattr(c, 'is_occurrence', False) or getattr(c, 'is_component', False))]
                self.assertEqual(len(occ_calls), 0)
                self.assertEqual(len(body_calls), 1)

    def test_top_level_sibling_not_merged_into_base_link_when_base_is_occurrence(self):
        """Verify unjointed top-level components under root are not merged into base_link when base_node is an occurrence."""
        root_node = OccurrenceNode(None, None, depth=0)
        root_node.name = 'Root'
        root_node.full_path = 'root'

        base_occ = OccurrenceNode(None, root_node, depth=1)
        base_occ.name = 'Base:1'
        base_occ.full_path = 'root/Base:1'
        base_body = MockBody('base_body')
        base_occ.bodies = [base_body]

        joint_link_occ = OccurrenceNode(None, root_node, depth=1)
        joint_link_occ.name = 'Link1:1'
        joint_link_occ.full_path = 'root/Link1:1'
        link1_body = MockBody('link1_body')
        joint_link_occ.bodies = [link1_body]

        # Sibling unjointed component at root level (e.g. fastener or joint motor casing)
        extra_sibling_occ = OccurrenceNode(None, root_node, depth=1)
        extra_sibling_occ.name = 'Hardware:1'
        extra_sibling_occ.full_path = 'root/Hardware:1'
        hardware_body = MockBody('hardware_body')
        extra_sibling_occ.bodies = [hardware_body]

        nodes = {
            'root': root_node,
            base_occ.full_path: base_occ,
            joint_link_occ.full_path: joint_link_occ,
            extra_sibling_occ.full_path: extra_sibling_occ,
        }

        j = JointInfo()
        j.joint_type = 'revolute'
        j.parent_link_path = base_occ.full_path
        j.child_link_path = joint_link_occ.full_path

        builder = KinematicTreeBuilder(nodes, [j], base_node=base_occ)
        links, joints = builder.build()

        base_link = next(l for l in links if l.name == 'base_link')
        # base_link must ONLY have base_body, not hardware_body!
        self.assertIn(base_body, base_link.bodies)
        self.assertNotIn(hardware_body, base_link.bodies)
        self.assertEqual(len(base_link.bodies), 1)

    def test_unhashable_occurrence_grouping(self):
        """Verify exporter safely handles unhashable adsk.fusion.Occurrence objects."""
        from core.mesh_exporter import get_occ_key

        class UnhashableOcc:
            __hash__ = None
            entityToken = 'token_12345'
            fullPathName = 'Root/Sub/Comp:1'
            name = 'Comp:1'

        occ = UnhashableOcc()
        # Verify get_occ_key returns a valid hashable string
        key = get_occ_key(occ)
        self.assertEqual(key, 'token_12345')
        d = {key: occ}
        self.assertIn(key, d)

    def test_skip_invisible_meshes(self):
        """Verify invisible bodies/occurrences are skipped when skip_invisible=True."""
        from core.kinematic_builder import URDFLink
        import tempfile

        class MockDesign:
            exportManager = None

        with tempfile.TemporaryDirectory() as td:
            # 0. Verify default is True
            from config.defaults import DEFAULT_SKIP_INVISIBLE
            self.assertTrue(DEFAULT_SKIP_INVISIBLE)
            default_exp = MeshExporter(MockDesign(), output_dir=td)
            self.assertTrue(default_exp.skip_invisible)

            # 1. With skip_invisible=True, visible body is exported, hidden body is skipped
            exporter = MeshExporter(MockDesign(), output_dir=td, skip_invisible=True)
            link = URDFLink('mixed_link')
            
            b_vis = MockBody('VisiblePart')
            b_vis.isVisible = True
            b_vis.isLightBulbOn = True
            b_vis.triangles = [((0, 0, 1), (0, 0, 0), (1, 0, 0), (0, 1, 0))]

            b_hid = MockBody('HiddenPart')
            b_hid.isVisible = False
            b_hid.isLightBulbOn = True
            b_hid.triangles = [((0, 0, 1), (1, 1, 1), (2, 1, 1), (1, 2, 1))]

            link.bodies = [b_vis, b_hid]

            res = exporter.export_link_meshes(link)
            self.assertTrue(res)
            self.assertIsNotNone(link.visual_mesh_path)
            self.assertIsNotNone(link.collision_mesh_path)

            # 2. When all bodies in link are invisible, mesh files are skipped completely
            link_hidden = URDFLink('hidden_link')
            b_hid2 = MockBody('HiddenPart2')
            b_hid2.isVisible = False
            link_hidden.bodies = [b_hid2]

            res2 = exporter.export_link_meshes(link_hidden)
            self.assertTrue(res2)
            self.assertIsNone(link_hidden.visual_mesh_path)
            self.assertIsNone(link_hidden.collision_mesh_path)

    def test_export_progress_dialog_mock(self):
        """Verify ExportProgressDialog initializes, updates, and handles cancellation."""
        from Fusion360URDFExporter import ExportProgressDialog

        class MockUIProgress:
            def __init__(self):
                self.isCancelButtonShown = False
                self.title = ''
                self.message = ''
                self.progressValue = 0
                self.maximumValue = 100
                self.minimumValue = 0
                self.wasCancelled = False
                self.is_hidden = False

            def show(self, title, message, min_val, max_val, delay):
                self.title = title
                self.message = message
                self.minimumValue = min_val
                self.maximumValue = max_val

            def hide(self):
                self.is_hidden = True

        class MockUI:
            def __init__(self):
                self.dlg = MockUIProgress()

            def createProgressDialog(self):
                return self.dlg

        mock_ui = MockUI()
        tracker = ExportProgressDialog(mock_ui, title="Testing Export")
        self.assertTrue(mock_ui.dlg.isCancelButtonShown)
        self.assertEqual(mock_ui.dlg.title, "Testing Export")

        tracker.update("Processing step 1...", 25)
        self.assertEqual(mock_ui.dlg.message, "Processing step 1...")
        self.assertEqual(mock_ui.dlg.progressValue, 25)

        self.assertFalse(tracker.was_cancelled)
        mock_ui.dlg.wasCancelled = True
        self.assertTrue(tracker.was_cancelled)

        tracker.hide()
        self.assertTrue(mock_ui.dlg.is_hidden)

    def test_urdf_writer_meshless_link_and_kinematics_preserved(self):
        """Verify links without meshes (skipped invisible) produce valid URDF without visual/collision tags."""
        from core.kinematic_builder import URDFLink, URDFJoint
        from core.urdf_writer import URDFWriter

        l1 = URDFLink('base_link')
        l1.mass = 1.5
        l1.visual_mesh_path = None
        l1.collision_mesh_path = None

        l2 = URDFLink('link1_link')
        l2.mass = 2.0
        l2.visual_mesh_path = 'meshes/visual/link1_link.stl'
        l2.collision_mesh_path = 'meshes/collision/link1_link.stl'

        j1 = URDFJoint('joint1', 'revolute')
        j1.parent_link = 'base_link'
        j1.child_link = 'link1_link'
        j1.origin_xyz = [0, 0, 0.1]
        j1.origin_rpy = [0, 0, 0]
        j1.axis = [0, 0, 1]

        writer = URDFWriter('test_robot', [l1, l2], [j1])
        xml_str = writer.generate()

        # base_link should have inertial and joint references, but NO visual/collision tags
        self.assertIn('<link name="base_link">', xml_str)
        self.assertIn('<mass value="1.500000"/>', xml_str)
        self.assertNotIn('base_link_visual', xml_str)
        self.assertNotIn('base_link_collision', xml_str)

        # link1_link should have visual and collision tags
        self.assertIn('<link name="link1_link">', xml_str)
        self.assertIn('link1_link_visual', xml_str)
        self.assertIn('link1_link_collision', xml_str)

        # Kinematic joint connection must be preserved
        self.assertIn('<joint name="joint1" type="revolute">', xml_str)
        self.assertIn('<parent link="base_link"/>', xml_str)
        self.assertIn('<child link="link1_link"/>', xml_str)


if __name__ == '__main__':
    unittest.main()
