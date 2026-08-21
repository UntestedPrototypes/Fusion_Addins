"""
Fusion 360 Kinematics Exporter — Main Add-In Entry Point

Registers a toolbar button in the Solid environment that opens a dialog
to export the active assembly as URDF + DH parameters.
"""

import adsk.core
import adsk.fusion
import traceback
import os
import sys

# --- Global handler list (prevents garbage collection of event handlers) ---
_handlers = []

# --- Constants ---
COMMAND_ID = 'f360KinematicsExporter'
COMMAND_NAME = 'Export Kinematics'
COMMAND_DESC = ('Export assembly joints as URDF (for simulation) and '
                'DH parameters (for ESP32 kinematics).')
TOOLBAR_PANEL_ID = 'SolidScriptsAddinsPanel'

# Resolved at module load time (safe — no Fusion API calls)
_ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
_RESOURCE_DIR = ''  # Empty = use Fusion default icon (avoids PNG format issues)


def _ensure_imports():
    """Lazy-import core modules. Called once inside run() after sys.path is set."""
    if _ADDIN_DIR not in sys.path:
        sys.path.insert(0, _ADDIN_DIR)
    # Force re-import to pick up any edits during development
    import importlib
    import core
    importlib.reload(core)
    from core import assembly_parser, urdf_builder, dh_calculator, stl_exporter, esp_header_generator
    return core, assembly_parser, urdf_builder, dh_calculator, stl_exporter, esp_header_generator


# ============================================================
# Event Handlers
# ============================================================

class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface
            cmd = args.command

            # --- Wire up sub-handlers ---
            on_execute = _CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            on_input_changed = _InputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)

            on_destroy = _CommandDestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)

            # --- Build dialog inputs ---
            inputs = cmd.commandInputs

            # Derive default name from active design
            root_comp_name = 'Robot'
            design = app.activeProduct
            if design:
                try:
                    root = adsk.fusion.Design.cast(design).rootComponent
                    root_comp_name = root.name.split(' v')[0]
                except:
                    pass

            inputs.addStringValueInput('robot_name', 'Robot Name', root_comp_name)

            # --- Output directory ---
            out_group = inputs.addGroupCommandInput('grp_output', 'Output Directory')
            out_group.isExpanded = True
            out_children = out_group.children
            out_children.addStringValueInput('output_dir', 'Path',
                                             os.path.join(os.path.expanduser('~'), 'Desktop'))
            out_children.addBoolValueInput('browse_btn', 'Browse...', False, '', False)

            # --- Export options ---
            exp_group = inputs.addGroupCommandInput('grp_export', 'Export Options')
            exp_group.isExpanded = True
            exp = exp_group.children

            exp.addBoolValueInput('export_urdf', 'Export URDF', True, '', True)
            exp.addBoolValueInput('export_stl', 'Export STL Meshes', True, '', True)

            mesh_dd = exp.addDropDownCommandInput(
                'mesh_quality', 'Mesh Quality',
                adsk.core.DropDownStyles.TextListDropDownStyle)
            mesh_dd.listItems.add('High', True)
            mesh_dd.listItems.add('Medium', False)
            mesh_dd.listItems.add('Low', False)

            exp.addBoolValueInput('export_dh', 'Export DH Parameters', True, '', True)
            exp.addBoolValueInput('export_esp', 'Generate ESP32 C Header', True, '', True)

            # --- Naming configuration ---
            name_group = inputs.addGroupCommandInput('grp_naming', 'Naming Configuration')
            name_group.isExpanded = False
            nc = name_group.children

            nc.addStringValueInput('base_link_name', 'Base Link Name', 'base_link')
            nc.addStringValueInput('link_prefix', 'Link Prefix', '')
            nc.addStringValueInput('link_suffix', 'Link Suffix', '')
            nc.addStringValueInput('joint_prefix', 'Joint Prefix', '')
            nc.addStringValueInput('joint_suffix', 'Joint Suffix', '')
            nc.addStringValueInput('chain_prefix', 'Chain Prefix', 'leg_')
            nc.addBoolValueInput('auto_sanitize', 'Auto-sanitize Names', True, '', True)

        except:
            app = adsk.core.Application.get()
            app.userInterface.messageBox(
                'Command Created Failed:\n{}'.format(traceback.format_exc()))


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            changed = args.input
            all_inputs = args.inputs

            if changed.id == 'browse_btn':
                app = adsk.core.Application.get()
                ui = app.userInterface
                dlg = ui.createFolderDialog()
                dlg.title = 'Select Output Directory'
                if dlg.showDialog() == adsk.core.DialogResults.DialogOK:
                    path_input = all_inputs.itemById('output_dir')
                    if path_input:
                        path_input.value = dlg.folder

            elif changed.id == 'export_urdf':
                stl_input = all_inputs.itemById('export_stl')
                qual_input = all_inputs.itemById('mesh_quality')
                if stl_input:
                    stl_input.isVisible = changed.value
                if qual_input:
                    qual_input.isVisible = changed.value and stl_input.value

            elif changed.id == 'export_stl':
                qual_input = all_inputs.itemById('mesh_quality')
                if qual_input:
                    qual_input.isVisible = changed.value

            elif changed.id == 'export_dh':
                esp_input = all_inputs.itemById('export_esp')
                if esp_input:
                    esp_input.isVisible = changed.value

        except:
            pass  # Swallow input-change errors silently


class _CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandEventArgs):
        app = adsk.core.Application.get()
        ui = app.userInterface
        progress = None

        try:
            # --- Lazy-import core modules ---
            core, assembly_parser, urdf_builder, dh_calculator, \
                stl_exporter, esp_header_generator = _ensure_imports()
            from core import NamingConfig

            inputs = args.command.commandInputs

            # --- Read all inputs ---
            robot_name = inputs.itemById('robot_name').value
            output_dir = inputs.itemById('output_dir').value

            do_urdf = inputs.itemById('export_urdf').value
            do_stl = inputs.itemById('export_stl').value and do_urdf
            mesh_quality = inputs.itemById('mesh_quality').selectedItem.name

            do_dh = inputs.itemById('export_dh').value
            do_esp = inputs.itemById('export_esp').value and do_dh

            base_link = inputs.itemById('base_link_name').value
            link_pre = inputs.itemById('link_prefix').value
            link_suf = inputs.itemById('link_suffix').value
            joint_pre = inputs.itemById('joint_prefix').value
            joint_suf = inputs.itemById('joint_suffix').value
            chain_pre = inputs.itemById('chain_prefix').value
            auto_san = inputs.itemById('auto_sanitize').value

            # --- Build config ---
            naming = NamingConfig(
                base_link_name=base_link,
                link_prefix=link_pre, link_suffix=link_suf,
                joint_prefix=joint_pre, joint_suffix=joint_suf,
                chain_prefix=chain_pre, auto_sanitize=auto_san
            )

            os.makedirs(output_dir, exist_ok=True)

            # --- Progress dialog ---
            progress = ui.createProgressDialog()
            progress.cancelButtonText = 'Cancel'
            progress.isBackgroundDependent = False
            progress.isCancelButtonShown = True
            progress.show('Exporting Kinematics', 'Starting...', 0, 100)

            # --- Step 1: Parse assembly ---
            progress.message = 'Parsing assembly...'
            progress.progressValue = 5
            adsk.doEvents()

            robot_model = assembly_parser.parse_assembly(naming)
            if robot_model is None:
                ui.messageBox('No active Fusion design found. Please open an assembly first.',
                              'Export Error')
                progress.hide()
                return

            robot_model.name = robot_name

            num_links = len(robot_model.links)
            num_joints = len(robot_model.joints)
            num_chains = len(robot_model.chains)

            progress.message = 'Found {} links, {} joints, {} chains'.format(
                num_links, num_joints, num_chains)
            progress.progressValue = 20
            adsk.doEvents()

            if progress.wasCancelled:
                return

            # --- Step 2: Compute DH parameters ---
            if do_dh and num_chains > 0:
                progress.message = 'Computing DH parameters for {} chains...'.format(num_chains)
                progress.progressValue = 30
                adsk.doEvents()

                for chain in robot_model.chains:
                    chain.dh_standard = dh_calculator.compute_standard_dh(robot_model, chain)
                    chain.dh_modified = dh_calculator.compute_modified_dh(robot_model, chain)

            if progress.wasCancelled:
                return

            # --- Step 3: Export STL meshes ---
            if do_stl:
                progress.message = 'Exporting STL meshes...'
                progress.progressValue = 45
                adsk.doEvents()

                stl_exporter.export_stl_meshes(
                    robot_model, output_dir, mesh_quality, naming)

            if progress.wasCancelled:
                return

            # --- Step 4: Generate URDF ---
            if do_urdf:
                progress.message = 'Generating URDF...'
                progress.progressValue = 70
                adsk.doEvents()

                urdf_xml = urdf_builder.build_urdf(robot_model, include_meshes=do_stl)
                urdf_path = os.path.join(output_dir, robot_name + '.urdf')
                urdf_builder.save_urdf(urdf_xml, urdf_path)

            if progress.wasCancelled:
                return

            # --- Step 5: Generate ESP32 C header ---
            if do_esp:
                progress.message = 'Generating ESP32 C header...'
                progress.progressValue = 90
                adsk.doEvents()

                header_path = os.path.join(output_dir, 'robot_kinematics.h')
                esp_header_generator.generate_header(robot_model, header_path)

            progress.progressValue = 100
            progress.hide()

            # --- Summary ---
            summary_lines = ['Export complete!\n',
                             'Output: {}\n'.format(output_dir)]
            if do_urdf:
                summary_lines.append('  - {}.urdf'.format(robot_name))
            if do_stl:
                summary_lines.append('  - meshes/ ({} STL files)'.format(num_links))
            if do_dh:
                summary_lines.append('  - DH params: {} chains computed'.format(num_chains))
            if do_esp:
                summary_lines.append('  - robot_kinematics.h')

            summary_lines.append('\nLinks: {}  |  Joints: {}  |  Chains: {}'.format(
                num_links, num_joints, num_chains))

            ui.messageBox('\n'.join(summary_lines), 'Export Success')

        except:
            if progress:
                try:
                    progress.hide()
                except:
                    pass
            ui.messageBox('Export Failed:\n{}'.format(traceback.format_exc()),
                          'Export Error')


class _CommandDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        # Clean up handlers after command dialog closes
        adsk.terminate()


# ============================================================
# Add-In Lifecycle
# ============================================================

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface

    try:
        # Ensure our modules are importable
        if _ADDIN_DIR not in sys.path:
            sys.path.insert(0, _ADDIN_DIR)

        # Create or retrieve command definition
        cmd_def = ui.commandDefinitions.itemById(COMMAND_ID)
        if cmd_def:
            cmd_def.deleteMe()

        cmd_def = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            COMMAND_NAME,
            COMMAND_DESC,
            _RESOURCE_DIR  # Folder containing 16x16.png, 32x32.png, 64x64.png
        )

        on_created = _CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        # Add button to Solid > Utilities panel
        workspace = ui.workspaces.itemById('FusionSolidEnvironment')
        if workspace:
            panel = workspace.toolbarPanels.itemById(TOOLBAR_PANEL_ID)
            if panel:
                existing = panel.controls.itemById(COMMAND_ID)
                if existing:
                    existing.deleteMe()
                panel.controls.addCommand(cmd_def)

    except:
        ui.messageBox('Add-In run() failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    app = adsk.core.Application.get()
    ui = app.userInterface

    try:
        # Remove toolbar button
        workspace = ui.workspaces.itemById('FusionSolidEnvironment')
        if workspace:
            panel = workspace.toolbarPanels.itemById(TOOLBAR_PANEL_ID)
            if panel:
                ctrl = panel.controls.itemById(COMMAND_ID)
                if ctrl:
                    ctrl.deleteMe()

        # Remove command definition
        cmd_def = ui.commandDefinitions.itemById(COMMAND_ID)
        if cmd_def:
            cmd_def.deleteMe()

        _handlers.clear()

    except:
        ui.messageBox('Add-In stop() failed:\n{}'.format(traceback.format_exc()))
