"""FusionLaserJoints Add-In for Autodesk Fusion.

Automatically generates interlocking tabs and slots (Mortise & Tenon, Finger/Box Joints,
and Cross/Halving Joints) for laser-cut and CNC sheet manufacturing.
"""

import os
import sys
import traceback
import importlib

# Ensure add-in root directory is in sys.path
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


def reload_modules():
    """Hot-reloads add-in submodules during iterative development."""
    mods = [
        "config.defaults",
        "core.geometry_math",
        "core.detection",
        "core.feature_builder",
        "core.tab_slot_generator",
        "core.finger_joint_generator",
        "core.cross_joint_generator",
    ]
    for m in mods:
        if m in sys.modules:
            try:
                importlib.reload(sys.modules[m])
            except Exception:
                pass


reload_modules()

from config.defaults import (
    JOINT_TYPE_TAB_SLOT,
    JOINT_TYPE_FINGER,
    JOINT_TYPE_CROSS,
    JOINT_TYPES,
    JOINT_TYPE_LABELS,
    SELECT_MODE_EDGE_FACE,
    SELECT_MODE_BODIES,
    SELECT_MODE_LABELS,
    DIST_BY_COUNT,
    DIST_BY_LENGTH,
    DEFAULT_JOINT_TYPE,
    DEFAULT_SELECT_MODE,
    DEFAULT_DIST_MODE,
    DEFAULT_TAB_COUNT,
    DEFAULT_TAB_LENGTH_MM,
    DEFAULT_MARGIN_MM,
    DEFAULT_CLEARANCE_MM,
    DEFAULT_PROTRUSION_MM,
    DEFAULT_ENABLE_CHAMFER,
    DEFAULT_CHAMFER_MM,
    DEFAULT_INVERT_ORDER,
    MM_TO_CM,
    CM_TO_MM,
    OVERSHOOT_MM
)
from core.detection import analyze_edge_and_face, analyze_bodies_contact
from core.tab_slot_generator import generate_tab_and_slot
from core.finger_joint_generator import generate_finger_joint
from core.cross_joint_generator import generate_cross_joint

CMD_ID = "FusionLaserJoints_Cmd"
CMD_NAME = "Laser Cut Joints"
CMD_DESCRIPTION = "Generate interlocking Tab & Slot, Finger, and Cross joints for laser cutting."
WORKSPACE_ID = "FusionSolidEnvironment"
PANEL_ID = "SolidModifyPanel"

# Keep handlers referenced to avoid premature garbage collection
handlers = []


class LaserJointsCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Initializes command dialog inputs when user launches Laser Cut Joints."""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            reload_modules()
            cmd = args.command
            cmd.isPositionDependent = True

            # Register lifecycle handlers
            on_execute = LaserJointsCommandExecuteHandler()
            cmd.execute.add(on_execute)
            handlers.append(on_execute)

            on_input_changed = LaserJointsCommandInputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            handlers.append(on_input_changed)

            on_destroy = LaserJointsCommandDestroyHandler()
            cmd.destroy.add(on_destroy)
            handlers.append(on_destroy)

            inputs = cmd.commandInputs

            # 1. Joint Type Dropdown
            joint_drop = inputs.addDropDownCommandInput(
                "input_joint_type", "Joint Style", adsk.core.DropDownStyles.LabeledIconDropDownStyle
            )
            for jt in JOINT_TYPES:
                joint_drop.listItems.add(JOINT_TYPE_LABELS[jt], jt == DEFAULT_JOINT_TYPE)

            # 2. Selection Mode Dropdown
            mode_drop = inputs.addDropDownCommandInput(
                "input_select_mode", "Selection Mode", adsk.core.DropDownStyles.LabeledIconDropDownStyle
            )
            mode_drop.listItems.add(SELECT_MODE_LABELS[SELECT_MODE_EDGE_FACE], True)
            mode_drop.listItems.add(SELECT_MODE_LABELS[SELECT_MODE_BODIES], False)

            # 3. Geometry Selection Group
            sel_group = inputs.addGroupCommandInput("group_selection", "Geometry Selection")
            sel_group.isExpanded = True
            sel_inputs = sel_group.children

            # Edge & Face Selection inputs
            sel_edge = sel_inputs.addSelectionInput("input_sel_edge", "Tab Edge", "Select linear mating edge")
            sel_edge.addSelectionFilter(adsk.core.SelectionFilters.SolidEdges)
            sel_edge.setSelectionLimits(1, 1)

            sel_face = sel_inputs.addSelectionInput("input_sel_face", "Mating Face", "Select planar mating face")
            sel_face.addSelectionFilter(adsk.core.SelectionFilters.PlanarFaces)
            sel_face.setSelectionLimits(1, 1)

            # Body-to-Body inputs
            sel_body1 = sel_inputs.addSelectionInput("input_sel_body1", "Plate 1", "Select first body")
            sel_body1.addSelectionFilter(adsk.core.SelectionFilters.SolidBodies)
            sel_body1.setSelectionLimits(1, 1)
            sel_body1.isVisible = False

            sel_body2 = sel_inputs.addSelectionInput("input_sel_body2", "Plate 2", "Select second body")
            sel_body2.addSelectionFilter(adsk.core.SelectionFilters.SolidBodies)
            sel_body2.setSelectionLimits(1, 1)
            sel_body2.isVisible = False

            # 4. Joint Parameters Group
            param_group = inputs.addGroupCommandInput("group_params", "Layout & Dimensions")
            param_group.isExpanded = True
            p_inputs = param_group.children

            # Distribution Mode
            dist_drop = p_inputs.addDropDownCommandInput(
                "input_dist_mode", "Tab Distribution", adsk.core.DropDownStyles.LabeledIconDropDownStyle
            )
            dist_drop.listItems.add("By Tab Count", True)
            dist_drop.listItems.add("By Target Length", False)

            # Count & Length
            val_count = adsk.core.ValueInput.createByReal(float(DEFAULT_TAB_COUNT))
            p_inputs.addValueInput("input_count", "Count", "", val_count)

            val_len = adsk.core.ValueInput.createByString(f"{DEFAULT_TAB_LENGTH_MM} mm")
            input_len = p_inputs.addValueInput("input_tab_len", "Tab Length", "mm", val_len)
            input_len.isVisible = False

            # Edge Margin / Inset
            val_margin = adsk.core.ValueInput.createByString(f"{DEFAULT_MARGIN_MM} mm")
            p_inputs.addValueInput("input_margin", "Edge Margin", "mm", val_margin)

            # 5. Laser Fit & Manufacturing Group
            fit_group = inputs.addGroupCommandInput("group_laser_fit", "Laser Fit & Tolerance")
            fit_group.isExpanded = True
            f_inputs = fit_group.children

            # Kerf / Clearance
            val_clearance = adsk.core.ValueInput.createByString(f"{DEFAULT_CLEARANCE_MM} mm")
            f_inputs.addValueInput("input_clearance", "Clearance / Kerf", "mm", val_clearance)

            # Tab Protrusion (Flush vs Protruding)
            val_protrusion = adsk.core.ValueInput.createByString(f"{DEFAULT_PROTRUSION_MM} mm")
            f_inputs.addValueInput("input_protrusion", "Tab Protrusion", "mm", val_protrusion)

            # Lead-in Chamfer for easy assembly
            f_inputs.addBoolValueCommandInput(
                "input_chamfer_enable", "Lead-in Chamfers (Easy Assembly)", True, "", DEFAULT_ENABLE_CHAMFER
            )
            val_chamfer = adsk.core.ValueInput.createByString(f"{DEFAULT_CHAMFER_MM} mm")
            f_inputs.addValueInput("input_chamfer_size", "Chamfer Size", "mm", val_chamfer)

            # Invert Alternation (for Finger joints)
            input_invert = f_inputs.addBoolValueCommandInput(
                "input_invert", "Invert Finger Parity", True, "", DEFAULT_INVERT_ORDER
            )
            input_invert.isVisible = False

        except Exception:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(f"Error initializing command dialog:\n{traceback.format_exc()}")


class LaserJointsCommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    """Dynamically adapts UI controls when selections or settings change."""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            inputs = args.inputs
            changed = args.input

            # Get key dropdowns
            joint_input = inputs.itemById("input_joint_type")
            sel_mode_input = inputs.itemById("input_select_mode")
            dist_mode_input = inputs.itemById("input_dist_mode")

            is_finger = (joint_input.selectedItem.name == JOINT_TYPE_LABELS[JOINT_TYPE_FINGER]) if joint_input else False
            is_cross = (joint_input.selectedItem.name == JOINT_TYPE_LABELS[JOINT_TYPE_CROSS]) if joint_input else False
            is_bodies_mode = (sel_mode_input.selectedItem.name == SELECT_MODE_LABELS[SELECT_MODE_BODIES]) if sel_mode_input else False
            is_by_length = (dist_mode_input.selectedItem.name == "By Target Length") if dist_mode_input else False

            # Toggle Selection Inputs
            sel_edge = inputs.itemById("input_sel_edge")
            sel_face = inputs.itemById("input_sel_face")
            sel_b1 = inputs.itemById("input_sel_body1")
            sel_b2 = inputs.itemById("input_sel_body2")

            if sel_edge:
                sel_edge.isVisible = not is_bodies_mode
            if sel_face:
                sel_face.isVisible = not is_bodies_mode
            if sel_b1:
                sel_b1.isVisible = is_bodies_mode
            if sel_b2:
                sel_b2.isVisible = is_bodies_mode

            # Toggle Distribution Inputs
            cnt_input = inputs.itemById("input_count")
            len_input = inputs.itemById("input_tab_len")
            margin_input = inputs.itemById("input_margin")
            protrusion_input = inputs.itemById("input_protrusion")
            chamfer_en = inputs.itemById("input_chamfer_enable")
            chamfer_sz = inputs.itemById("input_chamfer_size")
            invert_input = inputs.itemById("input_invert")

            if is_cross:
                if dist_mode_input: dist_mode_input.isVisible = False
                if cnt_input: cnt_input.isVisible = False
                if len_input: len_input.isVisible = False
                if margin_input: margin_input.isVisible = False
                if protrusion_input: protrusion_input.isVisible = False
                if chamfer_en: chamfer_en.isVisible = False
                if chamfer_sz: chamfer_sz.isVisible = False
                if invert_input: invert_input.isVisible = False
            elif is_finger:
                if dist_mode_input: dist_mode_input.isVisible = False
                if cnt_input:
                    cnt_input.isVisible = True
                    cnt_input.name = "Finger Count"
                if len_input: len_input.isVisible = False
                if margin_input: margin_input.isVisible = False
                if protrusion_input: protrusion_input.isVisible = False
                if chamfer_en: chamfer_en.isVisible = False
                if chamfer_sz: chamfer_sz.isVisible = False
                if invert_input: invert_input.isVisible = True
            else:
                # Tab & Slot
                if dist_mode_input: dist_mode_input.isVisible = True
                if cnt_input:
                    cnt_input.name = "Tab Count"
                    cnt_input.isVisible = not is_by_length
                if len_input: len_input.isVisible = is_by_length
                if margin_input: margin_input.isVisible = True
                if protrusion_input: protrusion_input.isVisible = True
                if chamfer_en: chamfer_en.isVisible = True
                if chamfer_sz: chamfer_sz.isVisible = chamfer_en.value if chamfer_en else True
                if invert_input: invert_input.isVisible = False

        except Exception:
            pass


class LaserJointsCommandExecuteHandler(adsk.core.CommandExecuteEventHandler):
    """Executes joint generation when user confirms dialog with OK."""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandEventArgs):
        app = adsk.core.Application.get()
        ui = app.userInterface

        try:
            inputs = args.command.commandInputs

            # 1. Read configuration
            joint_item = inputs.itemById("input_joint_type").selectedItem
            joint_type = JOINT_TYPE_TAB_SLOT
            if joint_item.name == JOINT_TYPE_LABELS[JOINT_TYPE_FINGER]:
                joint_type = JOINT_TYPE_FINGER
            elif joint_item.name == JOINT_TYPE_LABELS[JOINT_TYPE_CROSS]:
                joint_type = JOINT_TYPE_CROSS

            is_bodies_mode = (inputs.itemById("input_select_mode").selectedItem.name == SELECT_MODE_LABELS[SELECT_MODE_BODIES])

            # 2. Extract geometry context
            context = None
            if is_bodies_mode:
                b1_input = inputs.itemById("input_sel_body1")
                b2_input = inputs.itemById("input_sel_body2")
                if b1_input.selectionCount == 0 or b2_input.selectionCount == 0:
                    ui.messageBox("Please select both bodies.")
                    return
                body1 = b1_input.selection(0).entity
                body2 = b2_input.selection(0).entity
                context = analyze_bodies_contact(body1, body2)
            else:
                edge_input = inputs.itemById("input_sel_edge")
                face_input = inputs.itemById("input_sel_face")
                if edge_input.selectionCount == 0 or face_input.selectionCount == 0:
                    ui.messageBox("Please select both a tab edge and a mating slot face.")
                    return
                edge = edge_input.selection(0).entity
                face = face_input.selection(0).entity
                context = analyze_edge_and_face(edge, face)

            if not context:
                ui.messageBox("Could not compute joint alignment. Please verify that the edge touches or faces the mating plate.")
                return

            # Read parameters
            dist_is_len = (inputs.itemById("input_dist_mode").selectedItem.name == "By Target Length") if inputs.itemById("input_dist_mode") else False
            dist_mode = DIST_BY_LENGTH if dist_is_len else DIST_BY_COUNT

            count_val = int(inputs.itemById("input_count").value) if inputs.itemById("input_count") else DEFAULT_TAB_COUNT
            len_cm = inputs.itemById("input_tab_len").value if inputs.itemById("input_tab_len") else (DEFAULT_TAB_LENGTH_MM * MM_TO_CM)
            margin_cm = inputs.itemById("input_margin").value if inputs.itemById("input_margin") else (DEFAULT_MARGIN_MM * MM_TO_CM)
            clearance_cm = inputs.itemById("input_clearance").value if inputs.itemById("input_clearance") else (DEFAULT_CLEARANCE_MM * MM_TO_CM)
            protrusion_cm = inputs.itemById("input_protrusion").value if inputs.itemById("input_protrusion") else 0.0
            chamfer_en = inputs.itemById("input_chamfer_enable").value if inputs.itemById("input_chamfer_enable") else False
            chamfer_cm = inputs.itemById("input_chamfer_size").value if inputs.itemById("input_chamfer_size") else (DEFAULT_CHAMFER_MM * MM_TO_CM)
            invert = inputs.itemById("input_invert").value if inputs.itemById("input_invert") else False

            overshoot_cm = OVERSHOOT_MM * MM_TO_CM

            # 3. Execute joint generator
            if joint_type == JOINT_TYPE_TAB_SLOT:
                result = generate_tab_and_slot(
                    context=context,
                    dist_mode=dist_mode,
                    tab_count=count_val,
                    tab_length_cm=len_cm,
                    margin_cm=margin_cm,
                    clearance_cm=clearance_cm,
                    protrusion_cm=protrusion_cm,
                    enable_chamfer=chamfer_en,
                    chamfer_cm=chamfer_cm,
                    overshoot_cm=overshoot_cm
                )
                if result.get("success"):
                    ui.messageBox(
                        f"Tab & Slot Joint Created Successfully!\n"
                        f"- Tabs Created: {result.get('tab_count')}\n"
                        f"- Slots Cut: {result.get('slot_count')}\n"
                        f"- Clearance Offset: {clearance_cm * CM_TO_MM:.2f} mm\n"
                        f"- Lead-in Chamfers: {'Applied' if result.get('chamfer_applied') else 'None'}",
                        "FusionLaserJoints"
                    )
                else:
                    ui.messageBox(f"Error creating Tab & Slot:\n{result.get('error')}", "FusionLaserJoints Error")

            elif joint_type == JOINT_TYPE_FINGER:
                result = generate_finger_joint(
                    context=context,
                    finger_count=count_val,
                    clearance_cm=clearance_cm,
                    invert=invert,
                    overshoot_cm=overshoot_cm
                )
                if result.get("success"):
                    ui.messageBox(
                        f"Finger Joint Created Successfully!\n"
                        f"- Plate 1 Fingers: {result.get('body1_fingers')}\n"
                        f"- Plate 2 Fingers: {result.get('body2_fingers')}\n"
                        f"- Clearance Offset: {clearance_cm * CM_TO_MM:.2f} mm",
                        "FusionLaserJoints"
                    )
                else:
                    ui.messageBox(f"Error creating Finger Joint:\n{result.get('error')}", "FusionLaserJoints Error")

            elif joint_type == JOINT_TYPE_CROSS:
                result = generate_cross_joint(
                    context=context,
                    clearance_cm=clearance_cm,
                    overshoot_cm=overshoot_cm
                )
                if result.get("success"):
                    ui.messageBox(
                        f"Cross / Halving Joint Created Successfully!\n"
                        f"- Both half-depth slots cut with {clearance_cm * CM_TO_MM:.2f} mm clearance.",
                        "FusionLaserJoints"
                    )
                else:
                    ui.messageBox(f"Error creating Cross Joint:\n{result.get('error')}", "FusionLaserJoints Error")

        except Exception:
            ui.messageBox(f"Execution failed:\n{traceback.format_exc()}", "FusionLaserJoints Error")


class LaserJointsCommandDestroyHandler(adsk.core.CommandEventHandler):
    """Cleans up event handlers on dialog closure."""

    def __init__(self):
        super().__init__()

    def notify(self, args: adsk.core.CommandEventArgs):
        pass


def run(context):
    """Entry point when Add-In or Script is launched in Autodesk Fusion."""
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # Remove pre-existing instance if present
        existing_cmd = ui.commandDefinitions.itemById(CMD_ID)
        if existing_cmd:
            existing_cmd.deleteMe()

        # Create button definition
        resources_dir = os.path.join(ADDIN_DIR, "resources")
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID,
            CMD_NAME,
            CMD_DESCRIPTION,
            resources_dir if os.path.exists(resources_dir) else ""
        )

        # Attach CommandCreated handler
        on_created = LaserJointsCommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        handlers.append(on_created)

        # Add button to Solid Modify Panel and Utilities Panel
        panels = [
            ui.allToolbarPanels.itemById(PANEL_ID),
            ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel"),
            ui.allToolbarPanels.itemById("SolidMakePanel"),
        ]

        added = False
        for panel in panels:
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
                panel.controls.addCommand(cmd_def)
                added = True
                break

        # If executed directly as script, trigger command immediately
        if context is None or (isinstance(context, dict) and context.get("IsScript", False)):
            cmd_def.execute()
        elif not added:
            cmd_def.execute()

    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(f"Failed to start FusionLaserJoints:\n{traceback.format_exc()}")


def stop(context):
    """Cleanup entry point when Add-In is stopped or unloaded."""
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # Remove toolbar controls
        panels = [
            ui.allToolbarPanels.itemById(PANEL_ID),
            ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel"),
            ui.allToolbarPanels.itemById("SolidMakePanel"),
        ]
        for panel in panels:
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()

        # Remove command definition
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

    except Exception:
        pass
