
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
def _safe_name(name):
    bad = set('/ \\:|*?"<>')
    return ''.join('_' if ch in bad else ch for ch in name).strip()


# ---------------------------------------------------------------------------
def _collect_components_recursive(root_comp, seen):
    result = []
    if root_comp.id in seen:
        return result
    seen.add(root_comp.id)
    result.append(root_comp)
    for occ in root_comp.occurrences:
        child_comp = occ.component
        result.extend(_collect_components_recursive(child_comp, seen))
    return result


# ---------------------------------------------------------------------------
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False

            onExec     = CommandExecuteHandler()
            onInput    = InputChangedHandler()
            onValidate = CommandValidateHandler()
            cmd.execute.add(onExec)
            cmd.inputChanged.add(onInput)
            cmd.validateInputs.add(onValidate)
            _handlers.extend([onExec, onInput, onValidate])

            i = cmd.commandInputs

            # 1. COMPONENT SELECTION
            sel = i.addSelectionInput(
                'comp_selection',
                'Components to export',
                'Select one or more components whose flat patterns to export'
            )
            sel.addSelectionFilter('Occurrences')
            sel.setSelectionLimits(1, 0)

            # 2. RECURSIVE SUB-COMPONENTS
            i.addBoolValueInput(
                'recurse',
                'Include sub-components (recursive)',
                True, '', True
            )

            # 3. FILE FORMAT
            fmt = i.addDropDownCommandInput(
                'format', 'File format',
                adsk.core.DropDownStyles.TextListDropDownStyle)
            fmt.listItems.add('DXF',  True)
            fmt.listItems.add('IGES', False)
            fmt.listItems.add('STEP', False)
            fmt.listItems.add('SAT',  False)

            # 4. DXF OPTIONS
            grp = i.addGroupCommandInput('dxf_opts', 'DXF options')
            grp.isExpanded = True
            gi = grp.children
            gi.addBoolValueInput('bend_lines',  'Include bend lines',           True, '', True)
            gi.addBoolValueInput('ext_lines',   'Include extent lines',         True, '', True)
            gi.addBoolValueInput('spline_poly', 'Convert splines to polylines', True, '', False)

            # 5. PREFIX / SUFFIX
            i.addStringValueInput('prefix', 'Filename Prefix', '')
            i.addStringValueInput('suffix', 'Filename Suffix', '')

        except:
            ui.messageBox('CommandCreated error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
class CommandValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            inputs = args.firingEvent.sender.commandInputs
            sel = inputs.itemById('comp_selection')
            args.areInputsValid = sel is not None and sel.selectionCount > 0
        except:
            args.areInputsValid = False


# ---------------------------------------------------------------------------
class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            root_inputs = args.firingEvent.sender.commandInputs
            fmt_input = root_inputs.itemById('format')
            dxf_grp   = root_inputs.itemById('dxf_opts')
            if fmt_input and dxf_grp:
                dxf_grp.isVisible = (fmt_input.selectedItem.name == 'DXF')
        except:
            ui.messageBox('InputChanged error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
def _ensure_file_writable(filepath):
    import stat
    if not os.path.exists(filepath):
        return
    try:
        os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        with open(filepath, 'r+b'):
            pass
    except OSError as e:
        raise RuntimeError(
            f'Cannot overwrite "{os.path.basename(filepath)}" because it is '
            f'locked by another program.\n\nSystem message: {e}\n\n'
            f'Please close the file and try again.'
        )
    try:
        os.remove(filepath)
    except OSError as e:
        raise RuntimeError(
            f'Cannot delete existing file "{os.path.basename(filepath)}":\n{e}'
        )


# ---------------------------------------------------------------------------
class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            root_inputs = args.firingEvent.sender.commandInputs

            # ---- Read inputs ------------------------------------------------
            sel_input   = root_inputs.itemById('comp_selection')
            recurse     = root_inputs.itemById('recurse').value
            fmt         = root_inputs.itemById('format').selectedItem.name
            bend_lines  = root_inputs.itemById('bend_lines').value
            ext_lines   = root_inputs.itemById('ext_lines').value
            spline_poly = root_inputs.itemById('spline_poly').value

            raw_prefix = _safe_name(root_inputs.itemById('prefix').value.strip())
            raw_suffix = _safe_name(root_inputs.itemById('suffix').value.strip())
            prefix = raw_prefix.strip('_')
            suffix = raw_suffix.strip('_')

            # ---- Resolve directly-selected components -----------------------
            seen      = set()
            top_level = []
            for idx in range(sel_input.selectionCount):
                entity = sel_input.selection(idx).entity
                if hasattr(entity, 'component'):
                    comp = entity.component
                elif hasattr(entity, 'parentComponent'):
                    comp = entity.parentComponent
                else:
                    comp = entity
                if comp.id not in seen:
                    seen.add(comp.id)
                    top_level.append(comp)

            # ---- Optionally expand to sub-components ------------------------
            if recurse:
                recurse_seen = set()
                components   = []
                for comp in top_level:
                    components.extend(
                        _collect_components_recursive(comp, recurse_seen)
                    )
            else:
                components = top_level

            # ---- Ask for export folder --------------------------------------
            dlg = ui.createFolderDialog()
            dlg.title = 'Select export folder'
            if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
                return
            export_path = dlg.folder

            if not export_path or not os.path.isdir(export_path):
                ui.messageBox('Invalid export folder. Export cancelled.')
                return

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox('No active Fusion design found.')
                return

            export_mgr = design.exportManager


            # ---- Build export queue -----------------------------------------
            export_queue = []
            name_count   = {}
            for comp in components:
                sm_bodies = [b for b in comp.bRepBodies if b.isSheetMetal]
                if not sm_bodies:
                    continue

                # Build base name: sanitise component name
                base_name = _safe_name(comp.name).strip('_')

                # Apply prefix / suffix
                if prefix:
                    base_name = prefix + '_' + base_name
                if suffix:
                    base_name = base_name + '_' + suffix

                # Deduplicate when two components produce the same base_name
                if base_name in name_count:
                    name_count[base_name] += 1
                    base_name = f'{base_name}_{name_count[base_name]}'
                else:
                    name_count[base_name] = 0

                out_file = os.path.join(export_path, f'{base_name}.{fmt.lower()}')
                export_queue.append((comp, base_name, out_file))

            if not export_queue:
                msg = ('None of the selected components (or their sub-components) '
                       'contain sheet-metal bodies.'
                       if recurse else
                       'None of the selected components contain sheet-metal bodies.')
                ui.messageBox(msg, 'Flat Pattern Export')
                return

            # ---- Overwrite warning ------------------------------------------
            existing_files = [f for _, _, f in export_queue if os.path.exists(f)]
            if existing_files:
                names_list = '\n'.join(
                    f'  • {os.path.basename(f)}' for f in existing_files)
                answer = ui.messageBox(
                    f'⚠️  The following {len(existing_files)} file(s) already '
                    f'exist and will be overwritten:\n\n{names_list}\n\n'
                    f'Do you want to continue?',
                    'Overwrite warning',
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                    adsk.core.MessageBoxIconTypes.WarningIconType)
                if answer != adsk.core.DialogResults.DialogYes:
                    return

            # ---- Export -----------------------------------------------------
            exported = []
            skipped  = []

            for comp, base_name, out_file in export_queue:
                sm_bodies = [b for b in comp.bRepBodies if b.isSheetMetal]

                try:
                    _ensure_file_writable(out_file)
                except RuntimeError as lock_err:
                    skipped.append(f'{comp.name}   ✗  {lock_err}')
                    continue

                fp = comp.flatPattern

                if fp is None:
                    station_face = _find_stationary_face(sm_bodies[0])
                    if station_face is None:
                        skipped.append(
                            f'{comp.name}   -  no flat pattern and no '
                            f'top/bottom face found to create one')
                        continue
                    try:
                        fp = comp.createFlatPattern(station_face)
                    except Exception:
                        pass
                    if fp is None:
                        skipped.append(
                            f'{comp.name}   -  flat pattern could not be '
                            f'created automatically; please create it manually '
                            f'in the Sheet Metal workspace.')
                        continue


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

            # ---- Summary ----------------------------------------------------
            msg = f'Exported {len(exported)} file(s) to:\n{export_path}\n'
            if exported:
                msg += '\nFiles:\n' + '\n'.join(f'  * {f}' for f in exported)
            if skipped:
                msg += ('\n\nSkipped / warnings:\n' +
                        '\n'.join(f'  ! {s}' for s in skipped))
            if not exported and not skipped:
                msg += '\nNo sheet-metal components were found.'
            ui.messageBox(msg, 'Flat Pattern Export')

        except:
            ui.messageBox('Execute error:\n' + traceback.format_exc())


# ---------------------------------------------------------------------------
def _find_stationary_face(body):
    best_by_axis    = None
    best_large      = None
    best_large_area = 0.0

    for face in body.faces:
        if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            continue
        ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
        if not ok:
            continue
        az = abs(normal.z)
        if az < 0.15:
            continue
        if az > 0.985 and best_by_axis is None:
            best_by_axis = face
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
            'Export sheet-metal flat patterns for selected components.',
            './resources/cmd')

        cc = CommandCreatedHandler()
        _btn_def.commandCreated.add(cc)
        _handlers.append(cc)

        panel = ui.allToolbarPanels.itemById('UtilityPanel')
        if panel is None:
            panel = ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')

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
