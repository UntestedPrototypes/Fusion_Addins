"""STEP/IGES/SAT export through one temporary document per export run.

Fusion's STEP/IGES/SAT translator processes the whole component or design it
is given - hidden parts included - so exporting one body of a large assembly
took ~14 s. Copying just the needed bodies into a small temporary
direct-modelling design and exporting that takes a fraction of a second.
(Inside a flat pattern these formats even write no file at all otherwise.)

One temporary document is opened for the run, reused for every file, and
closed without saving at the end.
"""
import os

import adsk.core
import adsk.fusion

from .common import app

TEMP_DOC_FORMATS = ("step", "iges", "sat")

# A placed copy's vertices must match the original's within this (cm)
_PLACEMENT_TOL = 1e-3


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


# ---------------------------------------------------------------------------
# Copies of bodies
# ---------------------------------------------------------------------------
def _same_place(copy, body):
    """Is the copy where the original body is? Compares vertex positions (the
    original's bounding box is loose for rotated, nested parts, so it can't be
    compared directly). Bodies without vertices (spheres, tori) fall back to
    the copy's tight box lying inside the original's box."""
    n = min(3, body.vertices.count)
    if n and copy.vertices.count >= n:
        for i in range(n):
            if copy.vertices.item(i).geometry.distanceTo(body.vertices.item(i).geometry) > _PLACEMENT_TOL:
                return False
        return True
    a, b = copy.boundingBox, body.boundingBox
    t = _PLACEMENT_TOL
    return (a.minPoint.x >= b.minPoint.x - t and a.minPoint.y >= b.minPoint.y - t and
            a.minPoint.z >= b.minPoint.z - t and a.maxPoint.x <= b.maxPoint.x + t and
            a.maxPoint.y <= b.maxPoint.y + t and a.maxPoint.z <= b.maxPoint.z + t)


def _chain_transform(occ):
    """World transform of an occurrence, composed from each level's own
    placement in its parent (leaf first)."""
    m = adsk.core.Matrix3D.create()
    while occ:
        native = occ.nativeObject or occ
        m.transformBy(native.transform2)
        occ = occ.assemblyContext
    return m


def _local_copy(body):
    """Copy of a body in its own component's coordinates (Separate output)."""
    native = body.nativeObject if body.assemblyContext else body
    return adsk.fusion.TemporaryBRepManager.get().copy(native)


def _world_matrix(body):
    """Placement of a body's occurrence in the design, verified on the body:
    the composed occurrence chain or the occurrence's own transform, whichever
    puts a copy of the native body exactly onto the original. None if neither
    matches (or for bodies of the top level, which need no placement)."""
    ctx = body.assemblyContext
    if not ctx:
        return None
    tbm = adsk.fusion.TemporaryBRepManager.get()
    for make in (lambda: _chain_transform(ctx), lambda: ctx.transform2):
        try:
            matrix = make()
            copy = tbm.copy(body.nativeObject)
            tbm.transform(copy, matrix)
        except Exception:
            continue
        if _same_place(copy, body):
            return matrix
    return None


def _world_copy(body):
    """Copy of a body in design coordinates, for when no verified placement
    exists. Returns (copy, verified)."""
    copy = adsk.fusion.TemporaryBRepManager.get().copy(body)
    return copy, _same_place(copy, body)


# ---------------------------------------------------------------------------
# The temporary document
# ---------------------------------------------------------------------------
class _TempDocSession:
    """Opened on first use, reused for every file of the run, closed at the end."""

    def __init__(self):
        self.doc = None
        self.design = None
        self.original = None
        self._retired = 0

    def _open(self):
        if self.doc:
            return
        self.original = app.activeDocument
        self.doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        self.design = adsk.fusion.Design.cast(self.doc.products.itemByProductType("DesignProductType"))
        self.design.designType = adsk.fusion.DesignTypes.DirectDesignType

    def _clear(self):
        root = self.design.rootComponent
        for i in range(root.occurrences.count - 1, -1, -1):
            occ = root.occurrences.item(i)
            # Rename first so the next file can reuse the component name
            self._retired += 1
            try:
                occ.component.name = "_retired_{}".format(self._retired)
            except Exception:
                pass
            occ.deleteMe()
        for i in range(root.bRepBodies.count - 1, -1, -1):
            root.bRepBodies.item(i).deleteMe()

    def export(self, items, filepath, fmt, root_name):
        """items: [(component name or None, [(body name, copy)], [placements])].
        With a component name the bodies go into one component (in its own
        coordinates) that is placed once per matrix - repeated instances share
        it, like in the design. Without one they go into the root as they are.
        Returns export_mgr.execute()'s result."""
        self._open()
        self._clear()
        root = self.design.rootComponent
        for comp_name, bodies, placements in items:
            if comp_name is None:
                for body_name, copy in bodies:
                    root.bRepBodies.add(copy).name = body_name
                continue
            # Build the component at the origin first, then place each
            # instance: giving the matrix while creating the occurrence moved
            # the bodies added to it afterwards
            occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            comp = occ.component
            comp.name = comp_name
            for body_name, copy in bodies:
                comp.bRepBodies.add(copy).name = body_name
            occs = [occ] + [root.occurrences.addExistingComponent(comp, adsk.core.Matrix3D.create())
                            for _ in placements[1:]]
            for placed, matrix in zip(occs, placements):
                placed.transform2 = matrix.copy()

        export_mgr = self.design.exportManager
        if fmt == "step":
            opts = export_mgr.createSTEPExportOptions(filepath, root)
        elif fmt == "iges":
            opts = export_mgr.createIGESExportOptions(filepath, root)
        elif fmt == "sat":
            opts = export_mgr.createSATExportOptions(filepath, root)
        else:
            raise ValueError("format {} is not exported through a temporary document".format(fmt))
        ok = export_mgr.execute(opts)

        if ok and fmt == "step" and os.path.exists(filepath):
            _rename_unsaved_root(filepath, root_name)
        return ok

    def close(self):
        if self.doc:
            try:
                self.doc.close(False)
            finally:
                self.doc = None
                self.design = None
                if self.original:
                    try:
                        self.original.activate()
                    except Exception:
                        pass
