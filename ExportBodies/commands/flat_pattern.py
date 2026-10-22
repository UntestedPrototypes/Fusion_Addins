"""Quick Flat Pattern Exporter - exports sheet-metal flat patterns of the
selected components (DXF), or the components themselves (IGES/STEP/SAT).
For flat patterns as part of export groups, use the Bodies Exporter's DXF format."""
import os
import traceback

import adsk.core
import adsk.fusion

from ..lib.common import app, ui, _handlers, _disable_ghosting, _safe_name
from ..lib.flat_pattern_export import (_add_dxf_inputs, _dxf_options, _sheet_metal_components,
                                       _ensure_file_writable, _export_flat_pattern)
from ..lib.folders import _pick_output_folder
from ..lib.naming import _add_naming_inputs, _resolve_affixes

CMD_ID        = "ExportFlatPatternsCmd"
CMD_NAME      = "Quick Flat Pattern Exporter"
CMD_TOOLTIP   = "Quickly export sheet-metal flat patterns (DXF) for the selected components."
CMD_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "resources", "flat_pattern")

FORMATS = ("DXF", "IGES", "STEP", "SAT")


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

            _add_dxf_inputs(inputs)

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
class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            _disable_ghosting()
            inputs = args.command.commandInputs

            sel_input = inputs.itemById("comp_selection")
            recurse   = inputs.itemById("recurse").value
            fmt       = inputs.itemById("format").selectedItem.name
            dxf_opts  = _dxf_options(inputs)

            prefix, suffix = _resolve_affixes(inputs)

            entities = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
            sm_components, _ = _sheet_metal_components(entities, recurse)

            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox("No active Fusion design found.")
                return
            export_mgr = design.exportManager

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

            # ---- Build export queue -----------------------------------------
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
                export_queue.append((comp, out_file))

            # ---- Overwrite warning ------------------------------------------
            existing_files = [f for _, f in export_queue if os.path.exists(f)]
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

            for comp, out_file in export_queue:
                try:
                    _ensure_file_writable(out_file)
                except RuntimeError as lock_err:
                    skipped.append("{}: {}".format(comp.name, lock_err))
                    continue

                try:
                    if fmt == "DXF":
                        ok = _export_flat_pattern(export_mgr, comp, out_file, *dxf_opts)
                    else:
                        if fmt == "IGES":
                            opts = export_mgr.createIGESExportOptions(out_file, comp)
                        elif fmt == "STEP":
                            opts = export_mgr.createSTEPExportOptions(out_file, comp)
                        else:
                            opts = export_mgr.createSATExportOptions(out_file, comp)
                        ok = export_mgr.execute(opts)

                    if ok:
                        exported.append(os.path.basename(out_file))
                    else:
                        skipped.append("{}: execute() returned False".format(comp.name))
                except Exception as ex:
                    skipped.append("{}: {}".format(comp.name, ex))

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
