"""Runs an export of several groups: plans the files, asks for the folder
and overwrites once, exports with a progress dialog and shows one summary.
Shared by the Bodies Exporter and the Quick Bodies Exporter."""
import os

import adsk.core

from .common import ui, _do_events, _safe_name
from .doc_state import _read_state, _write_state
from .export_combined import _gather_group_bodies, _export_combined_file
from .export_separate import _plan_separate, _export_separate_body
from .flat_pattern_export import _sheet_metal_components, _export_flat_pattern, _dxf_options
from .folders import _pick_output_folder
from .naming import _resolve_affixes
from .step_post import _split_step_bodies
from .temp_doc_export import _needs_temp_doc, _export_bodies_via_temp_doc

SEPARATE = "Separate"
COMBINED = "Combined"
MODES    = (SEPARATE, COMBINED)

# label -> (extension, exporter key)
FORMAT_INFO = {
    "3MF":  (".3mf",  "3mf"),
    "STEP": (".step", "step"),
    "STL":  (".stl",  "stl"),
    "OBJ":  (".obj",  "obj"),
    "IGES": (".iges", "iges"),
    "SAT":  (".sat",  "sat"),
    "DXF":  (".dxf",  "dxf"),   # sheet-metal flat pattern, one per component
}
# Combined output needs a format that holds several bodies and the assembly;
# DXF flat patterns are always one file per sheet-metal component
MODE_FORMATS = {
    SEPARATE: ("3MF", "STEP", "STL", "OBJ", "IGES", "SAT", "DXF"),
    COMBINED: ("STEP", "IGES", "SAT"),
}
DEFAULT_FORMAT = "STEP"


def _run_export(inputs, design, specs):
    """Export specs [(name, mode, format label, subfolder, entities)] using the
    shared Body Types / Export Options / Naming Options inputs."""
    want_solid   = inputs.itemById("chk_solid").value
    want_surf    = inputs.itemById("chk_surface").value
    want_sm      = inputs.itemById("chk_sheetmetal").value
    visible_only = inputs.itemById("chk_visible_only").value
    inc_comp     = inputs.itemById("chk_compname").value
    recurse      = inputs.itemById("chk_recurse").value
    split_bodies = inputs.itemById("chk_split_bodies").value
    dxf_opts     = _dxf_options(inputs)

    prefix, suffix = _resolve_affixes(inputs)

    # jobs: dicts with group, kind, rel_dir, base, ext, fmt and the
    # payload for that kind ("keep" bodies or a separate body)
    jobs    = []
    skipped = []
    for group_name, mode, fmt_label, subfolder, entities in specs:
        ext, fmt = FORMAT_INFO[fmt_label]
        if mode == COMBINED:
            keep, g_skipped, comp_names = _gather_group_bodies(
                entities, want_solid, want_surf, want_sm, visible_only, recurse)
            skipped.extend("[{}] {}".format(group_name, s) for s in g_skipped)
            if not keep:
                skipped.append("[{}] no bodies matched the filters".format(group_name))
                continue
            base = _safe_name(group_name)
            if inc_comp and comp_names:
                base = "_".join(_safe_name(n) for n in comp_names) + "_" + base
            if prefix:
                base = prefix + "_" + base
            if suffix:
                base = base + "_" + suffix
            jobs.append({"group": group_name, "kind": COMBINED, "keep": keep,
                         "rel_dir": "", "base": base, "ext": ext, "fmt": fmt})
        elif fmt == "dxf":
            # Flat patterns: one DXF per sheet-metal component, named after it
            comps, g_skipped = _sheet_metal_components(entities, recurse)
            skipped.extend("[{}] {}".format(group_name, s) for s in g_skipped)
            if not comps:
                skipped.append("[{}] no sheet-metal components".format(group_name))
                continue
            rel_dir = _safe_name(group_name) if subfolder else ""
            for comp in comps:
                base = _safe_name(comp.name).strip("_")
                if prefix:
                    base = prefix + "_" + base
                if suffix:
                    base = base + "_" + suffix
                jobs.append({"group": group_name, "kind": "flat", "comp": comp,
                             "rel_dir": rel_dir, "base": base, "ext": ext, "fmt": fmt})
        else:
            plan, g_skipped = _plan_separate(
                entities, want_solid, want_surf, want_sm, visible_only, recurse,
                inc_comp, prefix, suffix)
            skipped.extend("[{}] {}".format(group_name, s) for s in g_skipped)
            if not plan:
                skipped.append("[{}] no bodies matched the filters".format(group_name))
                continue
            rel_dir = _safe_name(group_name) if subfolder else ""
            for comp, body_idx, body_name, base in plan:
                jobs.append({"group": group_name, "kind": SEPARATE, "comp": comp,
                             "body_idx": body_idx, "body_name": body_name,
                             "rel_dir": rel_dir, "base": base, "ext": ext, "fmt": fmt})

    if not jobs:
        msg_parts = ["Nothing to export: no bodies (or sheet-metal components for DXF) "
                     "matched the selected filters."]
        if skipped:
            msg_parts.append("Skipped:\n" + "\n".join("  " + s for s in skipped))
        ui.messageBox("\n\n".join(msg_parts))
        return

    # Keep every output path unique
    used = set()
    for job in jobs:
        base, n = job["base"], 2
        while (job["rel_dir"].lower(), (base + job["ext"]).lower()) in used:
            base = "{}_{}".format(job["base"], n)
            n += 1
        used.add((job["rel_dir"].lower(), (base + job["ext"]).lower()))
        job["base"] = base

    folder = _pick_output_folder(_read_state(design).get("folder", ""))
    if not folder:
        return
    try:
        _write_state(design, {"folder": folder})
    except Exception:
        pass

    for job in jobs:
        job["path"] = os.path.join(folder, job["rel_dir"], job["base"] + job["ext"])

    conflicts = [j for j in jobs if os.path.exists(j["path"])]
    overwrite = True
    if conflicts:
        conflict_names = "\n".join(
            "  " + os.path.relpath(j["path"], folder) for j in conflicts[:40])
        if len(conflicts) > 40:
            conflict_names += "\n  ... and {} more".format(len(conflicts) - 40)
        answer = ui.messageBox(
            "{} file(s) already exist:\n{}\n\nOverwrite all?".format(
                len(conflicts), conflict_names),
            "Overwrite?",
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
            adsk.core.MessageBoxIconTypes.QuestionIconType
        )
        overwrite = (answer == adsk.core.DialogResults.DialogYes)

    exported = {}      # group name -> [relative file paths]
    errors   = []
    cancelled = False
    total = len(jobs)

    progress = None
    try:
        progress = ui.createProgressDialog()
        if progress:
            progress.isCancelButtonShown = True
            progress.show("Exporting Bodies", "Preparing export...", 0, total, 0)
            _do_events()
    except Exception:
        progress = None

    try:
        for idx, job in enumerate(jobs):
            _do_events()
            if progress and progress.wasCancelled:
                cancelled = True
                break

            path = job["path"]
            rel  = os.path.relpath(path, folder)
            if progress:
                progress.progressValue = idx
                progress.message = "[{}] file {} of {}:\n{}".format(
                    job["group"], idx + 1, total, rel)
            _do_events()

            if os.path.exists(path):
                if not overwrite:
                    skipped.append("{} (not overwritten)".format(rel))
                    continue
                try:
                    os.remove(path)
                except Exception as exc:
                    errors.append("{}: could not remove: {}".format(rel, exc))
                    continue
            else:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                except Exception as exc:
                    errors.append("{}: could not create folder: {}".format(rel, exc))
                    continue

            try:
                via_temp_doc = _needs_temp_doc(design, job["fmt"])
                if job["kind"] == COMBINED:
                    if via_temp_doc:
                        ok = _export_bodies_via_temp_doc(job["keep"], path, job["fmt"], job["base"])
                    else:
                        ok = _export_combined_file(design, job["keep"], path, job["fmt"])
                elif job["kind"] == "flat":
                    ok = _export_flat_pattern(design.exportManager, job["comp"], path, *dxf_opts)
                elif via_temp_doc:
                    body = job["comp"].bRepBodies.item(job["body_idx"])
                    ok = _export_bodies_via_temp_doc([body], path, job["fmt"], job["body_name"])
                else:
                    ok = _export_separate_body(design.exportManager, job["comp"],
                                               job["body_idx"], path, job["fmt"])
                if ok and not os.path.exists(path):
                    # Seen when exporting from inside a flat pattern: execute()
                    # returns True but nothing is written
                    errors.append("{}: Fusion reported success but wrote no file".format(rel))
                elif ok:
                    exported.setdefault(job["group"], []).append(rel)
                    if split_bodies and job["fmt"] == "step":
                        if progress:
                            progress.message = "Naming bodies in {}...".format(rel)
                        _do_events()
                        try:
                            _split_step_bodies(path, force=(job["kind"] == SEPARATE))
                        except Exception as exc:
                            errors.append("{}: exported, but body naming failed: {}".format(
                                rel, exc))
                else:
                    errors.append("{}: execute() returned False".format(rel))
            except Exception as exc:
                errors.append("{}: {}".format(rel, exc))
            _do_events()

            if progress:
                progress.progressValue = idx + 1
    finally:
        if progress:
            try:
                progress.hide()
            except Exception:
                pass
            progress = None
        _do_events()

    parts = []
    if cancelled:
        parts.append("Export cancelled by user.")
    if exported:
        n_files = sum(len(v) for v in exported.values())
        lines = []
        for group_name, files in exported.items():
            lines.append("{} ({} file{}):".format(
                group_name, len(files), "" if len(files) == 1 else "s"))
            lines.extend("  " + f for f in files[:25])
            if len(files) > 25:
                lines.append("  ... and {} more".format(len(files) - 25))
        parts.append("Exported {} file(s) to:\n{}\n\n{}".format(
            n_files, folder, "\n".join(lines)))
    if skipped:
        parts.append("Skipped {}:\n{}".format(
            len(skipped), "\n".join("  " + s for s in skipped)))
    if errors:
        parts.append("Errors:\n" + "\n".join("  " + e for e in errors))
    ui.messageBox("\n\n".join(parts) or "Nothing exported.")

