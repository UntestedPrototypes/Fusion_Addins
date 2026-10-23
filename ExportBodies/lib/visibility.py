"""Run-wide visibility safety net: snapshot every light bulb before an export
run and put back anything still different afterwards - also when the run is
cancelled or fails part-way through isolating bodies."""


def _snapshot_all(design):
    """Light bulb states of all bodies, body folders and occurrences."""
    root = design.rootComponent
    comps = [design.allComponents.item(i) for i in range(design.allComponents.count)]
    if not any(c.id == root.id for c in comps):
        comps.append(root)       # flat pattern root may be missing from allComponents

    snapshot = {"occs": [], "folders": [], "bodies": []}
    for comp in comps:
        if hasattr(comp, "isBodiesFolderLightBulbOn"):
            snapshot["folders"].append((comp, comp.isBodiesFolderLightBulbOn))
        bodies = comp.bRepBodies
        for i in range(bodies.count):
            body = bodies.item(i)
            snapshot["bodies"].append((body, body.isLightBulbOn))
        # Occurrences in their component's context (what Separate isolation hides)
        occs = getattr(comp, "occurrences", None)
        for i in range(occs.count if occs else 0):
            occ = occs.item(i)
            snapshot["occs"].append((occ, occ.isLightBulbOn))
    # ...and every instance in the root context (what Combined isolation hides)
    all_occs = getattr(root, "allOccurrences", None)
    for i in range(all_occs.count if all_occs else 0):
        occ = all_occs.item(i)
        snapshot["occs"].append((occ, occ.isLightBulbOn))
    return snapshot


def _restore_all(snapshot):
    """Set back every light bulb that differs from the snapshot. Returns the
    number of items that could not be restored."""
    failed = 0
    for key, attr in (("occs", "isLightBulbOn"),
                      ("folders", "isBodiesFolderLightBulbOn"),
                      ("bodies", "isLightBulbOn")):
        for obj, state in snapshot[key]:
            try:
                if getattr(obj, attr) != state:
                    setattr(obj, attr, state)
            except Exception:
                failed += 1
    return failed
