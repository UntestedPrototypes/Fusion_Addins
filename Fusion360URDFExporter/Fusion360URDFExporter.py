"""Fusion 360 URDF Exporter Add-In

Main entry point for Autodesk Fusion 360.
Registers UI command, collects user export options, and executes the URDF pipeline.
"""

import os
import sys
import traceback
import re

# Ensure add-in root directory is on Python search path
ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
if ADDIN_DIR not in sys.path:
    sys.path.insert(0, ADDIN_DIR)

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False
    class _MockBase:
        pass
    class _MockDynamic:
        def __getattr__(self, name):
            return _MockBase
    adsk = _MockDynamic()
    adsk.core = _MockDynamic()
    adsk.fusion = _MockDynamic()

import importlib
from config import defaults
from core import tree_walker, rigid_resolver, joint_analyzer, kinematic_builder, mesh_exporter, inertial_calc, urdf_writer, transform_utils

def reload_exporter_modules():
    """Reloads all add-in modules from disk so edits take effect immediately without restarting Fusion 360."""
    modules = [
        'config.defaults',
        'core.transform_utils',
        'core.tree_walker',
        'core.rigid_resolver',
        'core.joint_analyzer',
        'core.kinematic_builder',
        'core.mesh_exporter',
        'core.inertial_calc',
        'core.urdf_writer',
        'core.diagnostics',
    ]
    for mod_name in modules:
        if mod_name in sys.modules:
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass

reload_exporter_modules()

from config.defaults import (
    MESH_QUALITIES,
    DEFAULT_MESH_QUALITY,
    DEFAULT_SKIP_INVISIBLE,
    DEFAULT_INERTIA_VISIBLE_ONLY,
    JOINT_NAMING_PRESETS,
    DEFAULT_JOINT_NAMING_PATTERN
)
from core.tree_walker import AssemblyTreeWalker
from core.rigid_resolver import RigidGroupResolver
from core.joint_analyzer import JointAnalyzer
from core.kinematic_builder import KinematicTreeBuilder
from core.mesh_exporter import MeshExporter
from core.inertial_calc import InertialCalculator
from core.urdf_writer import URDFWriter
from core.transform_utils import get_world_transform

CMD_ID = 'Fusion360URDFExporter_Cmd'
CMD_NAME = 'Export URDF'
CMD_DESCRIPTION = 'Exports current assembly and sub-assemblies to a URDF model.'
WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidScriptsAddinsPanel'

# Persistent collection to prevent garbage collection of event handlers
handlers = []


class URDFCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Initializes the export dialog inputs when the user clicks the toolbar button."""
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            reload_exporter_modules()
            cmd = args.command
            cmd.isPositionDependent = True

            # Register execute handler
            onExecute = URDFCommandExecuteHandler()
            cmd.execute.add(onExecute)
            handlers.append(onExecute)

            # Register input changed handler for Browse in Explorer button
            onInputChanged = URDFCommandInputChangedHandler()
            cmd.inputChanged.add(onInputChanged)
            handlers.append(onInputChanged)

            # Register destroy handler for cleanup
            onDestroy = URDFCommandDestroyHandler()
            cmd.destroy.add(onDestroy)
            handlers.append(onDestroy)

            inputs = cmd.commandInputs

            # 1. Robot / Model Name
            app = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)
            raw_name = design.rootComponent.name if design else 'robot'
            clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', raw_name).strip('_').lower()
            inputs.addStringValueInput('robotName', 'Robot Name', clean_name)

            # 2. Root Component / Link Selection (Optional)
            root_comp_input = inputs.addSelectionInput('rootComponentSelect', 'Root Component', 'Select the root component or base link')
            root_comp_input.addSelectionFilter('Occurrences')
            root_comp_input.setSelectionLimits(0, 1)
            root_comp_input.tooltip = 'Select the occurrence that acts as the robot base link (optional; defaults to grounded occurrence or assembly root)'

            # 3. Base Joint Origin Selection (Optional)
            base_origin_input = inputs.addSelectionInput('baseOriginSelect', 'URDF Base Origin', 'Select Joint Origin for URDF origin')
            base_origin_input.addSelectionFilter('JointOrigins')
            base_origin_input.setSelectionLimits(0, 1)
            base_origin_input.tooltip = 'Select a Joint Origin to serve as (0,0,0) and orientation for the URDF base link (optional)'

            # 4. Output Directory
            default_out = os.path.join(os.path.expanduser('~'), 'Desktop')
            dir_input = inputs.addStringValueInput('outputDir', 'Export Directory', default_out)
            dir_input.tooltip = 'Target folder where the robot package will be created'

            # 5. Browse Button (aligned in the input column directly below directory path)
            browse_btn = inputs.addBoolValueInput('browseBtn', ' ', False, '', False)
            browse_btn.text = 'Browse...'
            browse_btn.isFullWidth = False
            browse_btn.tooltip = 'Select export destination folder'

            # 4. Mesh Refinement Quality Dropdown
            quality_dropdown = inputs.addDropDownCommandInput(
                'meshQuality', 'Visual Mesh Quality',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            quality_dropdown.tooltip = 'Triangle refinement level for visual STL meshes'
            for q in MESH_QUALITIES:
                is_selected = (q == DEFAULT_MESH_QUALITY)
                quality_dropdown.listItems.add(q, is_selected)

            # 5. Joint Naming Preset Dropdown
            naming_dropdown = inputs.addDropDownCommandInput(
                'jointNamingPreset', 'Joint Naming Convention',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            naming_dropdown.tooltip = 'Select joint naming convention (chain & level) or choose Custom to specify your own pattern'
            for pat, label in JOINT_NAMING_PRESETS:
                is_selected = (pat == DEFAULT_JOINT_NAMING_PATTERN)
                naming_dropdown.listItems.add(label, is_selected)

            # 6. Joint Naming Pattern Template String Input
            naming_pattern_input = inputs.addStringValueInput(
                'jointNamingPattern', 'Naming Template',
                DEFAULT_JOINT_NAMING_PATTERN
            )
            naming_pattern_input.tooltip = (
                'Joint naming template pattern.\n'
                'Placeholders: {branch_name}, {chain}, {level}, {type}, {child_link}\n'
                'Default: {branch_name}_c{chain}_l{level} (e.g. leg_1_c1_l1)'
            )

            # 7. Skip Invisible Meshes Checkbox (Default: True)
            skip_inv_chk = inputs.addBoolValueInput('skipInvisibleMeshes', 'Skip Invisible Meshes', True, '', DEFAULT_SKIP_INVISIBLE)
            skip_inv_chk.tooltip = 'Skip STL mesh export for hidden or invisible components to enable fast testing while preserving all joints and kinematic tree'

            # 7b. Inertia from Visible Bodies Only Checkbox (Default: False)
            inertia_vis_chk = inputs.addBoolValueInput('inertiaVisibleOnly', 'Inertia From Visible Bodies Only', True, '', DEFAULT_INERTIA_VISIBLE_ONLY)
            inertia_vis_chk.tooltip = (
                'When checked, mass, center of mass and inertia are computed only from visible bodies.\n'
                'When unchecked, all bodies (including hidden ones) contribute to the inertial values.'
            )

            # 8. Option to open the exported package in Explorer when finished
            open_chk = inputs.addBoolValueInput('openExplorerOnFinish', 'Open in Explorer', True, '', True)
            open_chk.tooltip = 'Open Windows Explorer at the export folder after export completes'

            # 9. Assembly & Modeling Guidelines (Collapsible Help Section)
            guide_grp = inputs.addGroupCommandInput('guidelinesGroup', 'Assembly & Modeling Guidelines (Help)')
            guide_grp.isExpanded = False
            guide_grp.isEnabledCheckBoxDisplayed = False

            guidelines_html = (
                '<div style="font-size: 11px; line-height: 1.35;">'
                '<b>1. Assembly Structure with Sub-Assemblies:</b><br/>'
                '• <b>Base Link:</b> Ground your robot base occurrence or pick it in the <i>Root Component</i> field above.<br/>'
                '• <b>Chains / Limbs:</b> Group each limb (e.g. <code>Leg_1</code>, <code>Arm_Right</code>) as a top-level sub-assembly. '
                'The add-on automatically uses this name as the <code>{branch_name}</code> for joint naming.<br/>'
                '• <b>Links:</b> Nest moving segments within each limb and connect them sequentially with motion joints.<br/><br/>'
                '<b>2. Joint Origins Rule & Motion Orientation:</b><br/>'
                '• <b>TWO Joint Origins Required:</b> A joint is <b>ONLY created if it is made between two Joint Origins</b> '
                '(joints defined via faces/edges are ignored).<br/>'
                '• <b>Rigid Joints Included:</b> Rigid joints made between two Joint Origins <b>ARE exported as fixed joints</b> in URDF.<br/>'
                '• <b>Z-Axis is Motion Axis:</b> In URDF, the <b>Z-axis is always the motion axis</b>! '
                'Orient each Joint Origin so its blue Z-axis arrow aligns with the desired axis of rotation (Revolute) or sliding (Prismatic).<br/>'
                '• The Joint Origin anchor point defines the joint origin (xyz) in the URDF.<br/><br/>'
                '<b>3. End-Effectors & Reference Frames:</b><br/>'
                '• Any <b>Joint Origin not part of a joint</b> is automatically exported as a <b>fixed joint & virtual child link</b> '
                'to serve as an end-effector, tool center point (TCP), or reference frame.<br/>'
                '• <b>Exclusion Rule:</b> Any Joint Origin whose name ends with <code>_exclude</code> (case-insensitive, e.g. <code>Ref_exclude</code>) '
                'is skipped from export.<br/><br/>'
                '<b>4. Rigid Groups:</b><br/>'
                '• <b>Rigid Groups</b> merge components and bodies into a single rigid link (combining meshes, mass, and inertia).<br/>'
                '• Rigid joints NOT made between two Joint Origins also merge parts into their parent link.'
                '</div>'
            )
            guide_box = guide_grp.children.addTextBoxCommandInput('guidelinesText', '', guidelines_html, 18, True)
            guide_box.isFullWidth = True

        except:
            if HAS_ADSK:
                app = adsk.core.Application.get()
                app.log(f'Failed in CommandCreated:\n{traceback.format_exc()}')


class URDFCommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    """Handles button clicks in the dialog, launching the Windows Explorer folder picker."""
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            changed_input = args.input
            if changed_input.id == 'browseBtn':
                app = adsk.core.Application.get()
                ui = app.userInterface

                # Open native Windows Explorer folder selection dialog
                folder_dlg = ui.createFolderDialog()
                folder_dlg.title = 'Select URDF Export Folder'

                cmd_inputs = args.inputs
                out_input = cmd_inputs.itemById('outputDir')
                if out_input and out_input.value and os.path.exists(out_input.value):
                    folder_dlg.initialDirectory = out_input.value

                res = folder_dlg.showDialog()
                if res == adsk.core.DialogResults.DialogOK:
                    if out_input:
                        out_input.value = folder_dlg.folder
            elif changed_input.id == 'jointNamingPreset':
                cmd_inputs = args.inputs
                pattern_input = cmd_inputs.itemById('jointNamingPattern')
                if pattern_input and getattr(changed_input, 'selectedItem', None):
                    selected_label = changed_input.selectedItem.name
                    for pat, label in JOINT_NAMING_PRESETS:
                        if label == selected_label:
                            if pat != 'Custom':
                                pattern_input.value = pat
                            break
        except:
            if HAS_ADSK:
                app = adsk.core.Application.get()
                app.log(f'Failed in InputChanged:\n{traceback.format_exc()}')


class ExportProgressDialog:
    """Manages an adsk.core.ProgressDialog to provide a real-time progress bar during export."""
    def __init__(self, ui, title="Exporting URDF Package"):
        self.ui = ui
        self.dialog = None
        if ui:
            try:
                self.dialog = ui.createProgressDialog()
                self.dialog.isCancelButtonShown = True
                self.dialog.show(title, "Initializing export pipeline...", 0, 100, 0)
            except Exception:
                self.dialog = None
        self._pump()

    def update(self, message=None, progress_val=None):
        if self.dialog:
            try:
                if message is not None:
                    self.dialog.message = str(message)
                if progress_val is not None:
                    self.dialog.progressValue = int(min(max(0, progress_val), 100))
            except Exception:
                pass
        self._pump()

    def _pump(self):
        try:
            import adsk
            if hasattr(adsk, 'doEvents'):
                adsk.doEvents()
        except Exception:
            pass

    @property
    def was_cancelled(self):
        if self.dialog:
            try:
                return self.dialog.wasCancelled
            except Exception:
                return False
        return False

    def hide(self):
        if self.dialog:
            try:
                self.dialog.hide()
            except Exception:
                pass
            self.dialog = None


class URDFCommandExecuteHandler(adsk.core.CommandEventHandler):
    """Executes the export pipeline upon user confirmation."""
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandEventArgs):
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)

        if not design:
            ui.messageBox('No active Fusion 360 design found.')
            return

        progress = None
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            # Read user inputs
            robot_name_input = inputs.itemById('robotName')
            output_dir_input = inputs.itemById('outputDir')
            quality_input = inputs.itemById('meshQuality')
            skip_inv_input = inputs.itemById('skipInvisibleMeshes')
            root_comp_input = inputs.itemById('rootComponentSelect')
            base_origin_input = inputs.itemById('baseOriginSelect')

            robot_name = robot_name_input.value if robot_name_input else 'robot'
            robot_name = re.sub(r'[^a-zA-Z0-9_]', '_', robot_name).strip('_').lower() or 'robot'
            skip_invisible = skip_inv_input.value if skip_inv_input else DEFAULT_SKIP_INVISIBLE
            inertia_vis_input = inputs.itemById('inertiaVisibleOnly')
            inertia_visible_only = inertia_vis_input.value if inertia_vis_input else DEFAULT_INERTIA_VISIBLE_ONLY

            pattern_input = inputs.itemById('jointNamingPattern')
            naming_pattern = pattern_input.value.strip() if pattern_input and pattern_input.value.strip() else DEFAULT_JOINT_NAMING_PATTERN

            selected_root_occ = None
            if root_comp_input and root_comp_input.selectionCount > 0:
                try:
                    selected_root_occ = root_comp_input.selection(0).entity
                except Exception:
                    selected_root_occ = None

            selected_base_jo = None
            if base_origin_input and base_origin_input.selectionCount > 0:
                try:
                    selected_base_jo = base_origin_input.selection(0).entity
                except Exception:
                    selected_base_jo = None

            base_output_dir = output_dir_input.value if output_dir_input else ''
            if not base_output_dir or not os.path.exists(base_output_dir):
                # Prompt user to choose folder via Explorer if not already chosen
                folder_dlg = ui.createFolderDialog()
                folder_dlg.title = 'Select URDF Export Folder'
                res = folder_dlg.showDialog()
                if res == adsk.core.DialogResults.DialogOK:
                    base_output_dir = folder_dlg.folder
                else:
                    return

            mesh_quality = quality_input.selectedItem.name if quality_input and quality_input.selectedItem else DEFAULT_MESH_QUALITY

            pkg_dir = os.path.join(base_output_dir, robot_name)
            os.makedirs(pkg_dir, exist_ok=True)

            root = design.rootComponent

            # -------------------------------------------------------------
            # Pipeline Execution with Real-Time Progress Dialog
            # -------------------------------------------------------------
            progress = ExportProgressDialog(ui, title=f"Exporting '{robot_name}' URDF")

            # Force reload of all modules on execution to ensure latest edits on disk are run
            progress.update("Step 1/7: Initializing modules and scanning assembly...", 5)
            reload_exporter_modules()
            import core.tree_walker
            import core.rigid_resolver
            import core.joint_analyzer
            import core.kinematic_builder
            import core.mesh_exporter
            import core.inertial_calc
            import core.urdf_writer
            import core.transform_utils

            AssemblyTreeWalker = core.tree_walker.AssemblyTreeWalker
            RigidGroupResolver = core.rigid_resolver.RigidGroupResolver
            JointAnalyzer = core.joint_analyzer.JointAnalyzer
            KinematicTreeBuilder = core.kinematic_builder.KinematicTreeBuilder
            MeshExporter = core.mesh_exporter.MeshExporter
            InertialCalculator = core.inertial_calc.InertialCalculator
            URDFWriter = core.urdf_writer.URDFWriter
            get_world_transform = core.transform_utils.get_world_transform
            get_world_transform_as_list = core.transform_utils.get_world_transform_as_list
            extract_joint_origin_world_frame = core.transform_utils.extract_joint_origin_world_frame

            app.log(f"Starting URDF export for '{robot_name}'...")

            # Extract 4x4 base frame (cm) if custom origin or root component selected
            base_origin_world_frame = None
            if selected_base_jo:
                base_origin_world_frame = extract_joint_origin_world_frame(selected_base_jo, selected_root_occ)
            elif selected_root_occ:
                base_origin_world_frame = get_world_transform_as_list(selected_root_occ)

            # 1. Walk assembly tree (anchoring base to selected occurrence if provided)
            progress.update("Step 1/7: Scanning assembly structure and occurrences...", 8)
            walker = AssemblyTreeWalker(root, selected_base_occ=selected_root_occ)
            walker.walk()

            if progress.was_cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # 2. Analyze kinematic joints
            progress.update("Step 2/7: Analyzing joints and kinematic motion...", 16)
            analyzer = JointAnalyzer(root, tree_nodes=walker.all_nodes)
            joint_infos = analyzer.analyze_all(selected_base_origin=selected_base_jo)

            if progress.was_cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # Collect protected kinematic link paths (moving children of revolute/prismatic joints)
            protected_paths = set()
            for ji in joint_infos:
                if ji.child_link_path:
                    protected_paths.add(ji.child_link_path)

            # 3. Resolve rigid groups and rigid joints (protecting kinematic links and base_node)
            progress.update("Step 3/7: Resolving rigid groups and rigid joints...", 24)
            resolver = RigidGroupResolver(
                root,
                walker.all_nodes,
                base_node=walker.base_node,
                protected_paths=protected_paths
            )
            resolver.resolve()

            if progress.was_cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # 4. Build kinematic tree with ordered naming convention
            progress.update("Step 4/7: Building kinematic tree and coordinate frames...", 32)
            builder = KinematicTreeBuilder(
                walker.all_nodes,
                joint_infos,
                base_node=walker.base_node,
                base_origin_world_frame=base_origin_world_frame,
                naming_pattern=naming_pattern
            )
            links, joints = builder.build()

            # Generate diagnostic report in the export directory
            try:
                import core.diagnostics
                core.diagnostics.generate_diagnostic_report(
                    design, selected_root_occ, walker, resolver, analyzer, builder, pkg_dir
                )
            except Exception as e:
                app.log(f"Warning: Failed to write diagnostic report: {e}")

            if progress.was_cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # Map link names to occurrence nodes for transform lookup
            link_to_node = {}
            for path, node in walker.all_nodes.items():
                if not node.is_merged:
                    l = builder._link_map.get(path)
                    if l:
                        link_to_node[l.name] = node
            if walker.base_node:
                link_to_node['base_link'] = walker.base_node

            # 5. Export Meshes (Visual and Collision)
            progress.update("Step 5/7: Exporting STL meshes...", 35)
            mesh_exporter = MeshExporter(
                design,
                pkg_dir,
                visual_quality=mesh_quality,
                skip_invisible=skip_invisible
            )
            num_links = max(1, len(links))
            cancelled = False

            for i, link in enumerate(links):
                if progress.was_cancelled:
                    cancelled = True
                    break

                link_start_pct = 35 + int(45 * (i / num_links))
                link_end_pct = 35 + int(45 * ((i + 1) / num_links))

                def make_mesh_cb(l_name, start_p, end_p, link_idx, total_l):
                    def cb(b_idx, total_b, b_name, mesh_t):
                        if progress.was_cancelled:
                            return False
                        sub_pct = start_p + int((end_p - start_p) * (b_idx / max(1, total_b)))
                        msg = (
                            f"Step 5/7: Exporting {mesh_t} mesh for '{l_name}' ({link_idx}/{total_l})\n"
                            f"Component/Body {b_idx}/{total_b}: {b_name}"
                        )
                        progress.update(msg, sub_pct)
                        return True
                    return cb

                progress.update(
                    f"Step 5/7: Exporting meshes for '{link.name}' ({i + 1}/{num_links})...",
                    link_start_pct
                )

                frame_transform = link.frame_world_transform
                if frame_transform is None:
                    occ_node = link_to_node.get(link.name)
                    if occ_node and occ_node.occurrence:
                        frame_transform = get_world_transform(occ_node.occurrence)

                res = mesh_exporter.export_link_meshes(
                    link,
                    frame_transform,
                    progress_callback=make_mesh_cb(link.name, link_start_pct, link_end_pct, i + 1, num_links)
                )
                if res is False or progress.was_cancelled:
                    cancelled = True
                    break

            if cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # 6. Compute Physical Inertia Properties
            progress.update("Step 6/7: Computing link inertial properties...", 82)
            inertial_calc = InertialCalculator(visible_only=inertia_visible_only)
            for i, link in enumerate(links):
                if progress.was_cancelled:
                    cancelled = True
                    break

                pct = 82 + int(12 * ((i + 1) / num_links))
                progress.update(f"Step 6/7: Computing inertia for '{link.name}' ({i + 1}/{num_links})...", pct)

                frame_transform = link.frame_world_transform
                if frame_transform is None:
                    occ_node = link_to_node.get(link.name)
                    if occ_node and occ_node.occurrence:
                        frame_transform = get_world_transform(occ_node.occurrence)
                inertial_calc.compute_link_inertial(link, frame_transform)

            if cancelled:
                progress.hide()
                ui.messageBox("URDF export was cancelled by user.", "Export Cancelled")
                return

            # 7. Write URDF XML
            progress.update("Step 7/7: Writing URDF XML package...", 96)
            writer = URDFWriter(robot_name, links, joints)
            urdf_content = writer.generate()
            urdf_file_path = os.path.join(pkg_dir, f"{robot_name}.urdf")
            with open(urdf_file_path, 'w', encoding='utf-8') as f:
                f.write(urdf_content)

            progress.update("Export complete!", 100)

            # Close progress dialog before displaying summary dialog
            progress.hide()

            # 8. Open exported folder in Windows Explorer if enabled
            open_exp_input = inputs.itemById('openExplorerOnFinish')
            if open_exp_input and open_exp_input.value:
                try:
                    os.startfile(pkg_dir)
                except:
                    pass

            root_comp_name = selected_root_occ.name if selected_root_occ else "(Assembly Root)"
            base_origin_desc = selected_base_jo.name if selected_base_jo else "(Default Component Origin)"

            summary_msg = (
                f"URDF Export Complete!\n\n"
                f"Model Name: {robot_name}\n"
                f"Root Component: {root_comp_name}\n"
                f"URDF Origin: {base_origin_desc}\n"
                f"Links: {len(links)}\n"
                f"Joints: {len(joints)}\n"
                f"Joint Naming: {naming_pattern}\n"
                f"Visual Quality: {mesh_quality}\n"
                f"Inertia From: {'Visible bodies only' if inertia_visible_only else 'All bodies'}\n"
                f"Output Location:\n{urdf_file_path}"
            )
            ui.messageBox(summary_msg, "Export Succeeded")

        except:
            if progress:
                progress.hide()
            err_msg = f"URDF Export Failed:\n{traceback.format_exc()}"
            app.log(err_msg)
            ui.messageBox(err_msg, "Export Error")


class URDFCommandDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        pass


def run(context):
    """Add-in entry point called by Fusion 360 on start/load."""
    if not HAS_ADSK:
        return

    app = adsk.core.Application.get()
    ui = app.userInterface

    try:
        # Create command definition
        cmd_defs = ui.commandDefinitions
        cmd_def = cmd_defs.itemById(CMD_ID)
        if not cmd_def:
            icon_folder = os.path.join(ADDIN_DIR, 'resources')
            cmd_def = cmd_defs.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_DESCRIPTION, icon_folder
            )

        # Attach commandCreated listener
        onCommandCreated = URDFCommandCreatedHandler()
        cmd_def.commandCreated.add(onCommandCreated)
        handlers.append(onCommandCreated)

        # Add to toolbar panel
        workspace = ui.workspaces.itemById(WORKSPACE_ID)
        if workspace:
            panel = workspace.toolbarPanels.itemById(PANEL_ID)
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if not ctrl:
                    ctrl = panel.controls.addCommand(cmd_def)
                    ctrl.isPromoted = True
                    ctrl.isVisible = True

        app.log(f"Add-in '{CMD_NAME}' loaded successfully.")

    except:
        app.log(f"Failed to load add-in '{CMD_NAME}':\n{traceback.format_exc()}")


def stop(context):
    """Add-in exit point called by Fusion 360 on unload."""
    if not HAS_ADSK:
        return

    app = adsk.core.Application.get()
    ui = app.userInterface

    try:
        # Remove toolbar button
        workspace = ui.workspaces.itemById(WORKSPACE_ID)
        if workspace:
            panel = workspace.toolbarPanels.itemById(PANEL_ID)
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()

        # Remove command definition
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        handlers.clear()
        app.log(f"Add-in '{CMD_NAME}' unloaded successfully.")

    except:
        app.log(f"Failed to stop add-in '{CMD_NAME}':\n{traceback.format_exc()}")
