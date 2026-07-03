
import adsk.core, adsk.fusion
import os, traceback

app = adsk.core.Application.get()
ui  = app.userInterface

_handlers = []
_btn_def  = None
_ctrl     = None

CMD_ID   = 'FlatPatternExporterCmd'
CMD_NAME = 'Export Flat Patterns'


# ---------------------------------------------------------------------------
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False

            onExec  = CommandExecuteHandler()
            onInput = InputChangedHandler()
            cmd.execute.add(onExec)
            cmd.inputChanged.add(onInput)
            _handlers.extend([onExec, onInput])

            i = cmd.commandInputs
            i.addBoolValueInput('browse_btn', 'Choose export folder...', False, '', False)
            i.addStringValueInput('export_path', 'Export folder', '')

            fmt = i.addDropDownCommandInput(
                'format', 'File format',
                adsk.core.DropDownStyles.TextListDropDownStyle)
            fmt.listItems.add('DXF',  True)
            fmt.listItems.add('IGES', False)
            fmt.listItems.add('STEP', False)
            fmt.listItems.add('SAT',  False)

            grp = i.addGroupCommandInput('dxf_opts', 'DXF options')
            grp.isExpanded = True
            gi = grp.children
            gi.addBoolValueInput('bend_lines',  'Include bend lines',           True, '', True)
            gi.addBoolValueInput('ext_lines',   'Include extent lines',         True, '', True)
            gi.addBoolValueInput('spline_poly', 'Convert splines to polylines', True, '', False)

        except:
            ui.messageBox('CommandCreated error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            changed     = args.input
            root_inputs = args.firingEvent.sender.commandInputs

            if changed.id == 'browse_btn':
                dlg = ui.createFolderDialog()
                dlg.title = 'Select export folder'
                if dlg.showDialog() == adsk.core.DialogResults.DialogOK:
                    root_inputs.itemById('export_path').value = dlg.folder
                changed.value = False

            fmt_input = root_inputs.itemById('format')
            dxf_grp   = root_inputs.itemById('dxf_opts')
            if fmt_input and dxf_grp:
                dxf_grp.isVisible = (fmt_input.selectedItem.name == 'DXF')

        except:
            ui.messageBox('InputChanged error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            root_inputs = args.firingEvent.sender.commandInputs
            export_path = root_inputs.itemById('export_path').value.strip()
            fmt         = root_inputs.itemById('format').selectedItem.name
            bend_lines  = root_inputs.itemById('bend_lines').value
            ext_lines   = root_inputs.itemById('ext_lines').value
            spline_poly = root_inputs.itemById('spline_poly').value

            if not export_path or not os.path.isdir(export_path):
                ui.messageBox('Please choose a valid export folder first.')
                return

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox('No active Fusion design found.')
                return

            export_mgr = design.exportManager

            seen       = set()
            components = []
            for occ in design.rootComponent.allOccurrences:
                c = occ.component
                if c.id not in seen:
                    seen.add(c.id)
                    components.append(c)
            if design.rootComponent.id not in seen:
                components.append(design.rootComponent)

            exported = []
            skipped  = []

            for comp in components:
                sm_bodies = [b for b in comp.bRepBodies if b.isSheetMetal]
                if not sm_bodies:
                    continue

                # ---- check for existing flat pattern ----------------------
                fp = comp.flatPattern

                if fp is None:
                    # No flat pattern exists yet  -  try to create one
                    station_face = _find_stationary_face(sm_bodies[0])

                    if station_face is None:
                        # Could not identify any top/bottom face at all
                        skipped.append(
                            f'{comp.name}   -  no flat pattern exists and no '
                            f'top/bottom face could be found to create one')
                        continue

                    try:
                        fp = comp.createFlatPattern(station_face)
                    except Exception:
                        pass  # fp stays None; handled below

                    if fp is None:
                        # Creation failed (e.g. mirrored / derived component)
                        skipped.append(
                            f'{comp.name}   -  no flat pattern exists and one '
                            f'could not be created automatically. '
                            f'Please open the component and create the flat '
                            f'pattern manually in the Sheet Metal workspace.')
                        continue

                # ---- export -----------------------------------------------
                safe_name = ''.join(
                    c for c in comp.name if c.isalnum() or c in ' _-').strip()
                out_file = os.path.join(export_path, f'{safe_name}.{fmt.lower()}')

                try:
                    if fmt == 'DXF':
                        opts = export_mgr.createDXFFlatPatternExportOptions(out_file, fp)
                        opts.isCenterLinesExported       = bend_lines
                        opts.isExtentLinesExported       = ext_lines
                        opts.isSplineConvertedToPolyline = spline_poly
                        export_mgr.execute(opts)

                    elif fmt == 'IGES':
                        opts = export_mgr.createIGESExportOptions(out_file, comp)
                        export_mgr.execute(opts)

                    elif fmt == 'STEP':
                        opts = export_mgr.createSTEPExportOptions(out_file, comp)
                        export_mgr.execute(opts)

                    elif fmt == 'SAT':
                        opts = export_mgr.createSATExportOptions(out_file, comp)
                        export_mgr.execute(opts)

                    exported.append(os.path.basename(out_file))

                except Exception as ex:
                    skipped.append(f'{comp.name}   -  export error: {ex}')

            # ---- summary --------------------------------------------------
            msg = f'Exported {len(exported)} file(s) to:\n{export_path}\n'
            if exported:
                msg += '\nFiles:\n' + '\n'.join(f'  * {f}' for f in exported)
            if skipped:
                msg += '\n\nSkipped / warnings:\n' + '\n'.join(f'  ! {s}' for s in skipped)
            if not exported and not skipped:
                msg += '\nNo sheet-metal components were found in this design.'
            ui.messageBox(msg, 'Flat Pattern Export')

        except:
            ui.messageBox('Execute error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
def _find_stationary_face(body):
    """
    Return the best planar top/bottom face for flat-pattern creation.

    Strategy (in priority order):
      1. Planar face whose outward normal is within 15 degrees of +/-Z  (true top/bottom)
      2. Planar face whose outward normal is within 15 degrees of +/-X or +/-Y  (top/bottom
         when the part is oriented differently)
      3. The largest planar face (last resort, excludes near-vertical side faces)

    Side faces (normal nearly perpendicular to Z, i.e. |normal.z| < 0.15) are
    explicitly excluded because Fusion rejects them as stationary faces.
    """
    best_by_axis   = None   # priority-1/2 match
    best_large     = None   # priority-3: largest planar, non-side face
    best_large_area = 0.0

    for face in body.faces:
        if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
        if not ok:
            continue

        ax = abs(normal.x)
        ay = abs(normal.y)
        az = abs(normal.z)

        # Skip side faces: normal is nearly horizontal (az very small AND
        # at least one horizontal component dominates)
        is_side_face = (az < 0.15)
        if is_side_face:
            continue

        # Priority 1: near-+/-Z (true top/bottom in default orientation)
        if az > 0.985 and best_by_axis is None:
            best_by_axis = face

        # Priority 3: largest non-side planar face
        try:
            area = face.area
        except Exception:
            area = 0.0
        if area > best_large_area:
            best_large_area = area
            best_large      = face

    return best_by_axis or best_large


# ---------------------------------------------------------------------------
def run(context):
    global _btn_def, _ctrl
    try:
        existing = ui.commandDefinitions.itemById(CMD_ID)
        if existing:
            existing.deleteMe()

        _btn_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME,
            'Export all sheet-metal flat patterns in the active design.',
            './resources/cmd')

        cc = CommandCreatedHandler()
        _btn_def.commandCreated.add(cc)
        _handlers.append(cc)

        panel = ui.allToolbarPanels.itemById('SheetMetalCreatePanel')
        if panel is None:
            panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')  # fallback

        _ctrl = panel.controls.addCommand(_btn_def)
        _ctrl.isPromotedByDefault = False

    except:
        ui.messageBox('run() error:\n' + traceback.format_exc())


def stop(context):
    global _btn_def, _ctrl
    try:
        if _ctrl:    _ctrl.deleteMe()
        if _btn_def: _btn_def.deleteMe()
        _handlers.clear()
    except:
        pass
