"""STEP post-processing: one product per body so slicers show body names."""
import os
import re


def _add_split_bodies_input(grp_export):
    chk_split = grp_export.children.addBoolValueInput(
        "chk_split_bodies", "Name every body in STEP (slicer friendly)", True, "", True
    )
    chk_split.tooltip = (
        "Puts each body into its own STEP part named after the body (Component_Body "
        "inside sub-components), so slicers like Bambu Studio show body names instead "
        "of Component-SOLID-1. STEP only."
    )


# ---------------------------------------------------------------------------
# STEP post-processing: one product per body so slicers show body names
# ---------------------------------------------------------------------------
# Fusion writes every component as a PRODUCT whose shape holds all of that
# component's bodies. Slicers such as Bambu Studio name parts after the
# PRODUCT and number the rest ("Robotanics_Layer1-SOLID-1"), ignoring the
# body names Fusion puts on the solids. So every body of a component that has
# several bodies (or also has sub-components) is moved into its own child
# PRODUCT with an identity placement. Geometry is left untouched.
#
# Chain in the file:
#   solid -> ADVANCED_BREP_SHAPE_REPRESENTATION (items)
#         -> SHAPE_REPRESENTATION_RELATIONSHIP -> component SHAPE_REPRESENTATION
#         -> SHAPE_DEFINITION_REPRESENTATION -> PRODUCT_DEFINITION_SHAPE
#         -> PRODUCT_DEFINITION -> PRODUCT_DEFINITION_FORMATION -> PRODUCT
_STR  = r"(?:'(?:[^']|'')*'|\$)"   # a STEP string or $
_SEP  = r"\s*,\s*"
_STEP_SOLID_RE = re.compile(
    r"^#(\d+)\s*=\s*(?:MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS|SHELL_BASED_SURFACE_MODEL|FACETED_BREP)"
    r"\s*\(\s*'((?:[^']|'')*)'", re.M)
_STEP_ITEMS_REP_RE = re.compile(
    r"^#(\d+)\s*=\s*(\w*SHAPE_REPRESENTATION)\s*\(\s*" + _STR + _SEP
    + r"\(([^)]*)\)" + _SEP + r"#(\d+)\s*\)\s*;", re.M)
_STEP_SRR_RE = re.compile(
    r"^#(\d+)\s*=\s*SHAPE_REPRESENTATION_RELATIONSHIP\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)" + _SEP + r"#(\d+)\s*\)\s*;", re.M)
_STEP_SDR_RE = re.compile(
    r"^#\d+\s*=\s*SHAPE_DEFINITION_REPRESENTATION\s*\(\s*#(\d+)" + _SEP + r"#(\d+)\s*\)", re.M)
_STEP_PDS_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION_SHAPE\s*\(\s*" + _STR + _SEP + _STR + _SEP + r"#(\d+)", re.M)
_STEP_PD_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)" + _SEP + r"#(\d+)", re.M)
_STEP_PDF_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT_DEFINITION_FORMATION\w*\s*\(\s*" + _STR + _SEP + _STR + _SEP
    + r"#(\d+)", re.M)
_STEP_PRODUCT_RE = re.compile(
    r"^#(\d+)\s*=\s*PRODUCT\s*\(\s*" + _STR + _SEP + r"'((?:[^']|'')*)'" + _SEP + _STR + _SEP
    + r"(\([^)]*\))", re.M)
_STEP_NAUO_RE = re.compile(
    r"^#\d+\s*=\s*NEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(\s*" + _STR + _SEP + _STR + _SEP + _STR
    + _SEP + r"#(\d+)" + _SEP + r"#(\d+)", re.M)
_STEP_PLACEMENT_RE = re.compile(r"^#(\d+)\s*=\s*AXIS2_PLACEMENT_3D\s*\(", re.M)
_STEP_ID_RE = re.compile(r"^#(\d+)\s*=", re.M)


def _split_step_bodies(filepath, force=False):
    """Give every body of a multi-body component its own PRODUCT, named
    "<Component>_<Body>" (just "<Body>" for bodies of the top-level component).
    With force, single-body components are split too (used for one-body files,
    so the part shows the body name instead of the component name).
    Names are copied as already-encoded STEP strings, so non-ASCII names stay
    intact. Returns the number of bodies split out.
    """
    # latin-1 maps every byte 1:1, so untouched content round-trips unchanged
    with open(filepath, "r", encoding="latin-1", newline="") as f:
        text = f.read()

    solid_name = {m.group(1): m.group(2) for m in _STEP_SOLID_RE.finditer(text)}
    if not solid_name or (len(solid_name) < 2 and not force):
        return 0

    reps = {}            # rep id -> (match, keyword, [item ids], context id)
    for m in _STEP_ITEMS_REP_RE.finditer(text):
        reps[m.group(1)] = (m, m.group(2), re.findall(r"#(\d+)", m.group(3)), m.group(4))
    srr_by_child = {}    # brep rep id -> (match, component shape rep id)
    for m in _STEP_SRR_RE.finditer(text):
        srr_by_child[m.group(3)] = (m, m.group(2))
    rep_pds   = {m.group(2): m.group(1) for m in _STEP_SDR_RE.finditer(text)}
    pds_pd    = {m.group(1): m.group(2) for m in _STEP_PDS_RE.finditer(text)}
    pd_info   = {m.group(1): (m.group(2), m.group(3)) for m in _STEP_PD_RE.finditer(text)}
    pdf_prod  = {m.group(1): m.group(2) for m in _STEP_PDF_RE.finditer(text)}
    prod_info = {m.group(1): (m.group(2), m.group(3)) for m in _STEP_PRODUCT_RE.finditer(text)}
    placements = {m.group(1) for m in _STEP_PLACEMENT_RE.finditer(text)}
    nauo = [(m.group(1), m.group(2)) for m in _STEP_NAUO_RE.finditer(text)]
    child_pds  = {c for _, c in nauo}
    parent_pds = {p for p, _ in nauo}

    # Group brep reps by the component shape rep they belong to
    by_comp = {}         # component shape rep id -> [brep rep id]
    for rep_id, (_, _, items, _) in reps.items():
        if rep_id in srr_by_child and any(i in solid_name for i in items):
            by_comp.setdefault(srr_by_child[rep_id][1], []).append(rep_id)

    edits    = []        # (start, end, replacement) on the original text
    new_recs = []
    next_id  = [max(int(i) for i in _STEP_ID_RE.findall(text)) + 1]

    def new(record):
        rid = next_id[0]
        next_id[0] += 1
        new_recs.append("#{}={};".format(rid, record))
        return "#{}".format(rid)

    split = 0
    for comp_rep, brep_reps in by_comp.items():
        pd = pds_pd.get(rep_pds.get(comp_rep))
        if pd not in pd_info or comp_rep not in reps:
            continue
        pdf, pd_ctx = pd_info[pd]
        prod = pdf_prod.get(pdf)
        if prod not in prod_info:
            continue
        comp_name, prod_ctx = prod_info[prod]
        is_root = pd not in child_pds

        solids = [s for r in brep_reps for s in reps[r][2] if s in solid_name]
        if len(solids) < 2 and pd not in parent_pds and not force:
            continue          # single body, no sub-components: already named well

        comp_items = reps[comp_rep][2]
        origin = next((i for i in comp_items if i in placements), None)
        if origin is None:
            continue

        for brep_rep in brep_reps:
            m_rep, keyword, items, ctx = reps[brep_rep]
            rep_solids = [i for i in items if i in solid_name]
            for solid in rep_solids:
                body = solid_name[solid]
                name = body if is_root else ("{}_{}".format(comp_name, body) if body else comp_name)
                p     = new("PRODUCT('{0}','{0}',$,{1})".format(name, prod_ctx))
                p_pdf = new("PRODUCT_DEFINITION_FORMATION('',$,{})".format(p))
                p_pd  = new("PRODUCT_DEFINITION('{0}','{0}',{1},#{2})".format(name, p_pdf, pd_ctx))
                p_pds = new("PRODUCT_DEFINITION_SHAPE('',$,{})".format(p_pd))
                p_sr  = new("SHAPE_REPRESENTATION('',(#{}),#{})".format(origin, ctx))
                new("SHAPE_DEFINITION_REPRESENTATION({},{})".format(p_pds, p_sr))
                p_br  = new("{}('',(#{}),#{})".format(keyword, solid, ctx))
                new("SHAPE_REPRESENTATION_RELATIONSHIP('SRR','None',{},{})".format(p_sr, p_br))
                occ   = new("NEXT_ASSEMBLY_USAGE_OCCURRENCE('{0}','{0}','',#{1},{2},$)".format(
                    name, pd, p_pd))
                o_pds = new("PRODUCT_DEFINITION_SHAPE($,$,{})".format(occ))
                xf    = new("ITEM_DEFINED_TRANSFORMATION($,$,#{0},#{0})".format(origin))
                rr    = new("(REPRESENTATION_RELATIONSHIP($,$,{},#{})"
                            "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({})"
                            "SHAPE_REPRESENTATION_RELATIONSHIP())".format(p_sr, comp_rep, xf))
                new("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({},{})".format(rr, o_pds))
                split += 1

            # The component's own brep rep no longer holds these solids. A rep
            # cannot be empty, so drop it (and its link) when nothing is left.
            remaining = [i for i in items if i not in solid_name]
            if remaining:
                start, end = m_rep.span(3)
                edits.append((start, end, ",".join("#" + i for i in remaining)))
            else:
                edits.append((m_rep.start(), m_rep.end(), ""))
                m_srr = srr_by_child[brep_rep][0]
                edits.append((m_srr.start(), m_srr.end(), ""))

    if not split:
        return 0

    # Apply edits back to front, then add the new records before DATA's ENDSEC
    for start, end, repl in sorted(edits, reverse=True):
        text = text[:start] + repl + text[end:]
    data_end = text.rfind("ENDSEC;")
    text = text[:data_end] + "\n".join(new_recs) + "\n" + text[data_end:]

    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    os.replace(tmp, filepath)
    return split
