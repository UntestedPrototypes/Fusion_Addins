"""Naming Options inputs and the filename prefix/suffix they produce."""
import re

from .common import app, _safe_name


def _add_naming_inputs(inputs):
    grp_naming = inputs.addGroupCommandInput("grp_naming", "Naming Options")
    grp_naming.children.addStringValueInput("prefix", "Filename Prefix", "")
    grp_naming.children.addBoolValueInput("chk_filename_prefix", "Use document name as prefix", True, "", False)
    grp_naming.children.addStringValueInput("suffix", "Filename Suffix", "")
    grp_naming.children.addBoolValueInput("chk_milestone_suffix", "Use milestone as suffix (V#)", True, "", False)


def _split_doc_name():
    """Return (document name without version, version number or "")."""
    doc_name = app.activeDocument.name
    match = re.search(r'^(.*?)(?:\s+v(\d+))?$', doc_name, re.IGNORECASE)
    base_doc_name = match.group(1).strip() if match else doc_name
    version_num = match.group(2) if (match and match.group(2)) else ""
    return base_doc_name, version_num


def _resolve_affixes(inputs):
    """Build the filesystem-safe (prefix, suffix) from the Naming Options."""
    custom_prefix = inputs.itemById("prefix").value.strip()
    custom_suffix = inputs.itemById("suffix").value.strip()

    chk_filename_prefix = inputs.itemById("chk_filename_prefix").value
    chk_milestone_suffix = inputs.itemById("chk_milestone_suffix").value

    base_doc_name, version_num = _split_doc_name()

    combined_prefix = custom_prefix
    if chk_filename_prefix:
        if combined_prefix:
            combined_prefix = combined_prefix + "_" + base_doc_name
        else:
            combined_prefix = base_doc_name

    combined_suffix = custom_suffix
    if chk_milestone_suffix:
        ver_str = "V" + version_num if version_num else "V1"
        if combined_suffix:
            combined_suffix = combined_suffix + "_" + ver_str
        else:
            combined_suffix = ver_str

    prefix = _safe_name(combined_prefix) if combined_prefix else ""
    suffix = _safe_name(combined_suffix) if combined_suffix else ""
    return prefix, suffix
