"""Diagnostic reporting tool for Fusion 360 URDF Exporter.

Dumps the assembly structure, occurrence hierarchy, joints, and link body assignments
to a human-readable text file and to the Fusion 360 log.
"""

import os
import traceback


def generate_diagnostic_report(design, root_occ_selected, walker, resolver, analyzer, builder, output_dir):
    """Generate a comprehensive diagnostic report of the assembly and export pipeline."""
    lines = []
    lines.append("=" * 70)
    lines.append("FUSION 360 URDF EXPORTER - ASSEMBLY DIAGNOSTIC REPORT")
    lines.append("=" * 70)
    lines.append("")

    try:
        # 1. Document & Selection Info
        lines.append("--- 1. DOCUMENT & SELECTION ---")
        root_comp = getattr(design, 'rootComponent', None)
        lines.append(f"Root Component: {getattr(root_comp, 'name', 'None')}")
        if root_occ_selected:
            lines.append(f"Selected Base Occurrence: {getattr(root_occ_selected, 'fullPathName', getattr(root_occ_selected, 'name', str(root_occ_selected)))}")
            comp = getattr(root_occ_selected, 'component', None)
            lines.append(f"  Underlying Component: {getattr(comp, 'name', 'None')}")
            child_occs = getattr(root_occ_selected, 'childOccurrences', [])
            lines.append(f"  Child Occurrences Count: {getattr(child_occs, 'count', len(child_occs))}")
            bodies = getattr(root_occ_selected, 'bRepBodies', [])
            lines.append(f"  Direct Bodies Count: {getattr(bodies, 'count', len(bodies))}")
        else:
            lines.append("Selected Base Occurrence: None (Auto-resolving base)")
        lines.append("")

        # 2. Occurrence Hierarchy
        lines.append("--- 2. OCCURRENCE HIERARCHY ---")
        if walker and hasattr(walker, 'all_nodes'):
            for path, node in walker.all_nodes.items():
                indent = "  " * node.depth
                occ_name = node.name
                comp_name = getattr(node.component, 'name', 'None')
                body_names = [getattr(b, 'name', 'unnamed') for b in node.bodies]
                merged_str = f" [MERGED into parent]" if node.is_merged else ""
                lines.append(f"{indent}- Node: '{occ_name}' (Path: '{path}') | Comp: '{comp_name}'{merged_str}")
                lines.append(f"{indent}  Bodies ({len(body_names)}): {', '.join(body_names) if body_names else 'None'}")
                child_count = len(node.children)
                if child_count > 0:
                    lines.append(f"{indent}  Children count: {child_count}")
        # 2.5 Rigid Merges & Protection
        lines.append("--- 2.5. RIGID RELATIONSHIPS & MERGES ---")
        if resolver and hasattr(resolver, 'merge_log'):
            lines.append(f"Total Rigid Merge Log Entries: {len(resolver.merge_log)}")
            for log_entry in resolver.merge_log:
                lines.append(f"  {log_entry}")
            lines.append(f"Final Merged Occurrences Count: {len(resolver.merge_map)}")
            for c_path, p_path in sorted(resolver.merge_map.items()):
                lines.append(f"  Mapping: '{c_path}' -> '{p_path}'")
        lines.append("")

        # 3. Kinematic Joints Detected
        lines.append("--- 3. JOINTS DETECTED ---")
        if analyzer and hasattr(analyzer, 'root'):
            all_j = getattr(analyzer.root, 'allJoints', getattr(analyzer.root, 'joints', []))
            lines.append(f"Total Fusion Joints in Design: {getattr(all_j, 'count', len(all_j))}")
            for idx, j in enumerate(all_j):
                try:
                    j_name = getattr(j, 'name', f"Joint_{idx}")
                    m_type = getattr(getattr(j, 'jointMotion', None), 'jointType', 'unknown')
                    occ1 = getattr(j, 'occurrenceOne', None)
                    occ2 = getattr(j, 'occurrenceTwo', None)
                    occ1_str = getattr(occ1, 'fullPathName', getattr(occ1, 'name', 'None'))
                    occ2_str = getattr(occ2, 'fullPathName', getattr(occ2, 'name', 'None'))
                    suppr = getattr(j, 'isSuppressed', False)
                    lines.append(f"  Joint '{j_name}': Type={m_type} | Suppressed={suppr}")
                    lines.append(f"    OccurrenceOne (Child): {occ1_str}")
                    lines.append(f"    OccurrenceTwo (Parent): {occ2_str}")
                except Exception as e:
                    lines.append(f"  Joint {idx}: Error reading joint ({e})")
        lines.append("")

        # 4. URDF Kinematic Links & Bodies Assigned
        lines.append("--- 4. URDF LINKS & BODY ASSIGNMENT ---")
        if builder and hasattr(builder, 'links'):
            for link in builder.links:
                lines.append(f"Link: '{link.name}'")
                body_list = []
                for b in link.bodies:
                    b_name = getattr(b, 'name', 'unnamed_body')
                    source_occ = getattr(b, '_source_occ', getattr(b, 'assemblyContext', None))
                    occ_name = getattr(source_occ, 'name', 'root')
                    body_list.append(f"{b_name} (from {occ_name})")
                lines.append(f"  Total Bodies: {len(body_list)}")
                for b_info in body_list:
                    lines.append(f"    - {b_info}")
        lines.append("")

        # 5. URDF Kinematic Tree
        lines.append("--- 5. URDF KINEMATIC TREE JOINTS ---")
        if builder and hasattr(builder, 'naming_pattern'):
            lines.append(f"Naming Pattern: '{builder.naming_pattern}'")
        if builder and hasattr(builder, 'joints'):
            for j in builder.joints:
                lines.append(f"URDF Joint: '{j.name}' ({j.joint_type})")
                lines.append(f"  Parent Link: '{j.parent_link}'")
                lines.append(f"  Child Link:  '{j.child_link}'")
                chain_val = getattr(j, 'chain', '-')
                level_val = getattr(j, 'level', '-')
                branch_val = getattr(j, 'branch_name', '-')
                lines.append(f"  Topology:    Chain {chain_val} | Level {level_val} | Branch '{branch_val}'")
                lines.append(f"  Origin XYZ:  {j.origin_xyz}")
                lines.append(f"  Origin RPY:  {j.origin_rpy}")
                lines.append(f"  Axis:        {j.axis}")
        lines.append("")
        lines.append("=" * 70)
        lines.append("END OF DIAGNOSTIC REPORT")
        lines.append("=" * 70)

    except Exception as e:
        lines.append(f"Error during diagnostic dump: {e}\n{traceback.format_exc()}")

    report_text = "\n".join(lines)

    if output_dir:
        try:
            report_path = os.path.join(output_dir, "urdf_export_diagnostics.txt")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_text)
        except Exception:
            pass

    return report_text
