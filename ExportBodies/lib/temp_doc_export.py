"""STEP/IGES/SAT export of bodies through a temporary document.

Inside a flat pattern (FlatPatternProduct) Fusion's STEP, IGES and SAT exports
report success but write no file; STL, 3MF and OBJ work. For those formats the
bodies are copied into a temporary direct-modelling design, exported from
there, and the temporary document is closed without saving.
"""
import os

import adsk.core
import adsk.fusion

from .common import app

TEMP_DOC_FORMATS = ("step", "iges", "sat")


def _needs_temp_doc(design, fmt):
    return fmt in TEMP_DOC_FORMATS and adsk.fusion.FlatPatternProduct.cast(design) is not None


def _step_string(text):
    """text as a STEP string literal body: quotes doubled, non-ASCII as \\X2\\."""
    out = []
    for ch in text:
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("\\X2\\{}\\X0\\".format(ch.encode("utf-16-be").hex().upper()))
    return "".join(out)


def _rename_unsaved_root(filepath, root_name):
    """The temporary document's root is written as '(Unsaved)'; use root_name."""
    with open(filepath, "r", encoding="latin-1", newline="") as f:
        text = f.read()
    if "'(Unsaved)'" not in text:
        return
    text = text.replace("'(Unsaved)'", "'{}'".format(_step_string(root_name)))
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    os.replace(tmp, filepath)


def _export_bodies_via_temp_doc(bodies, filepath, fmt, root_name):
    """Export copies of bodies to one file. Returns export_mgr.execute()'s result."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    copies = [(body.name, tbm.copy(body)) for body in bodies]

    original = app.activeDocument
    tmp_doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    try:
        design = adsk.fusion.Design.cast(tmp_doc.products.itemByProductType("DesignProductType"))
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        root = design.rootComponent
        for name, copy in copies:
            new_body = root.bRepBodies.add(copy)
            new_body.name = name
        export_mgr = design.exportManager
        if fmt == "step":
            opts = export_mgr.createSTEPExportOptions(filepath, root)
        elif fmt == "iges":
            opts = export_mgr.createIGESExportOptions(filepath, root)
        else:
            opts = export_mgr.createSATExportOptions(filepath, root)
        ok = export_mgr.execute(opts)
    finally:
        tmp_doc.close(False)
        if original:
            original.activate()

    if ok and fmt == "step" and os.path.exists(filepath):
        _rename_unsaved_root(filepath, root_name)
    return ok
