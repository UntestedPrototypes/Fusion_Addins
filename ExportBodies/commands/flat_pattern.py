"""Export Flat Patterns - exports sheet-metal flat patterns of the selected
components (DXF), or the components themselves (IGES/STEP/SAT)."""
import os
import stat
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting, _safe_name
from ..lib.folders import _pick_output_folder
from ..lib.naming import _add_naming_inputs, _resolve_affixes

CMD_ID        = "ExportFlatPatternsCmd"
CMD_NAME      = "Export Flat Patterns"
CMD_TOOLTIP   = "Export sheet-metal flat patterns for selected components."
CMD_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "resources", "flat_pattern")

FORMATS = ("DXF", "IGES", "STEP", "SAT")


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
class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs

            grp_sel = inputs.addGroupCommandInput("grp_sel", "Selection")
            sel = grp_sel.children.addSelectionInput(
                "comp_selection", "Components",
                "Select one or more components whose flat patterns to export"
            )
            sel.addSelectionFilter("Occurrences")
            sel.addSelectionFilter("RootComponents")
            sel.setSelectionLimits(1, 0)
            grp_sel.children.addBoolValueInput(
                "recurse", "Include sub-components (recursive)", True, "", True
            )

            grp_export = inputs.addGroupCommandInput("grp_export", "Export Options")
            fmt = grp_export.children.addDropDownCommandInput(
                "format", "File format",
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            for label in FORMATS:
                fmt.listItems.add(label, label == "DXF")

            grp_dxf = inputs.addGroupCommandInput("dxf_opts", "DXF Options")
            grp_dxf.children.addBoolValueInput("bend_lines",  "Include bend lines",           True, "", True)
            grp_dxf.children.addBoolValueInput("ext_lines",   "Include extent lines",         True, "", True)
            grp_dxf.children.addBoolValueInput("spline_poly", "Convert splines to polylines", True, "", False)

            _add_naming_inputs(inputs)

            h_exec = _ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

            h_val = _ValidateHandler()
            cmd.validateInputs.add(h_val)
            _handlers.append(h_val)

            h_in = _InputChangedHandler()
            cmd.inputChanged.add(h_in)
            _handlers.append(h_in)

        except Exception:
            ui.messageBox("Flat pattern exporter commandCreated error:\n" + traceback.format_exc())


# ---------------------------------------------------------------------------
class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            sel = args.inputs.itemById("comp_selection")
            args.areInputsValid = sel is not None and sel.selectionCount > 0
        except Exception:
            args.areInputsValid = False


# ---------------------------------------------------------------------------
class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id == "format":
                inputs = args.input.parentCommand.commandInputs
                inputs.itemById("dxf_opts").isVisible = (args.input.selectedItem.name == "DXF")
        except Exception:
            pass


# ---------------------------------------------------------------------------
def _ensure_file_writable(filepath):
    if not os.path.exists(filepath):
        return
    try:
        os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        with open(filepath, "r+b"):
            pass
    except OSError as e:
        raise RuntimeError(
            'Cannot overwrite "{}" because it is locked by another program.\n\n'
            "System message: {}\n\nPlease close the file and try again.".format(
                os.path.basename(filepath), e)
        )
    try:
        os.remove(filepath)
    except OSError as e:
        raise RuntimeError(
            'Cannot delete existing file "{}":\n{}'.format(os.path.basename(filepath), e)
        )


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
class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs = args.command.commandInputs

            sel_input   = inputs.itemById("comp_selection")
            recurse     = inputs.itemById("recurse").value
            fmt         = inputs.itemById("format").selectedItem.name
            bend_lines  = inputs.itemById("bend_lines").value
            ext_lines   = inputs.itemById("ext_lines").value
            spline_poly = inputs.itemById("spline_poly").value

            prefix, suffix = _resolve_affixes(inputs)

            # ---- Resolve directly-selected components -----------------------
            seen      = set()
            top_level = []
            for idx in range(sel_input.selectionCount):
                entity = sel_input.selection(idx).entity
                occ = adsk.fusion.Occurrence.cast(entity)
                comp = occ.component if occ else adsk.fusion.Component.cast(entity)
                if comp and comp.id not in seen:
                    seen.add(comp.id)
                    top_level.append(comp)

            # ---- Optionally expand to sub-components ------------------------
            if recurse:
                recurse_seen = set()
                components   = []
                for comp in top_level:
                    components.extend(_collect_components_recursive(comp, recurse_seen))
            else:
                components = top_level

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("No active Fusion design found.")
                return
            export_mgr = design.exportManager

            # ---- Build export queue -----------------------------------------
            sm_components = [c for c in components
                             if any(b.isSheetMetal for b in c.bRepBodies)]
            if not sm_components:
                msg = ("None of the selected components (or their sub-components) "
                       "contain sheet-metal bodies."
                       if recurse else
                       "None of the selected components contain sheet-metal bodies.")
                ui.messageBox(msg, "Flat Pattern Export")
                return

            export_path = _pick_output_folder()
            if not export_path:
                return

            export_queue = []
            name_count   = {}
            for comp in sm_components:
                base_name = _safe_name(comp.name).strip("_")
                if prefix:
                    base_name = prefix + "_" + base_name
                if suffix:
                    base_name = base_name + "_" + suffix

                # Deduplicate when two components produce the same base_name
                if base_name in name_count:
                    name_count[base_name] += 1
                    base_name = "{}_{}".format(base_name, name_count[base_name])
                else:
                    name_count[base_name] = 0

                out_file = os.path.join(export_path, "{}.{}".format(base_name, fmt.lower()))
                export_queue.append((comp, base_name, out_file))

            # ---- Overwrite warning ------------------------------------------
            existing_files = [f for _, _, f in export_queue if os.path.exists(f)]
            if existing_files:
                names_list = "\n".join("  " + os.path.basename(f) for f in existing_files)
                answer = ui.messageBox(
                    "{} file(s) already exist:\n{}\n\nOverwrite all?".format(
                        len(existing_files), names_list),
                    "Overwrite?",
                    adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                    adsk.core.MessageBoxIconTypes.QuestionIconType
                )
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
                    skipped.append("{}: {}".format(comp.name, lock_err))
                    continue

                try:
                    if fmt == "DXF":
                        fp = comp.flatPattern
                        if fp is None:
                            station_face = _find_stationary_face(sm_bodies[0])
                            if station_face is None:
                                skipped.append("{}: no flat pattern and no top/bottom face "
                                               "found to create one".format(comp.name))
                                continue
                            try:
                                fp = comp.createFlatPattern(station_face)
                            except Exception:
                                fp = None
                            if fp is None:
                                skipped.append("{}: flat pattern could not be created "
                                               "automatically; please create it manually in "
                                               "the Sheet Metal workspace.".format(comp.name))
                                continue
                        opts = export_mgr.createDXFFlatPatternExportOptions(out_file, fp)
                        opts.isCenterLinesExported       = bend_lines
                        opts.isExtentLinesExported       = ext_lines
                        opts.isSplineConvertedToPolyline = spline_poly
                    elif fmt == "IGES":
                        opts = export_mgr.createIGESExportOptions(out_file, comp)
                    elif fmt == "STEP":
                        opts = export_mgr.createSTEPExportOptions(out_file, comp)
                    else:
                        opts = export_mgr.createSATExportOptions(out_file, comp)

                    if export_mgr.execute(opts):
                        exported.append(os.path.basename(out_file))
                    else:
                        skipped.append("{}: execute() returned False".format(comp.name))
                except Exception as ex:
                    skipped.append("{}: export error: {}".format(comp.name, ex))

            # ---- Summary ----------------------------------------------------
            parts = []
            if exported:
                parts.append("Exported {} file(s) to:\n{}\n\n{}".format(
                    len(exported), export_path, "\n".join("  " + f for f in exported)))
            if skipped:
                parts.append("Skipped {}:\n{}".format(
                    len(skipped), "\n".join("  " + s for s in skipped)))
            ui.messageBox("\n\n".join(parts) or "Nothing exported.", "Flat Pattern Export")

        except Exception:
            ui.messageBox("Flat pattern exporter execute error:\n" + traceback.format_exc())
