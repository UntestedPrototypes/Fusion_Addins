"""Mesh exporter for Fusion 360 URDF add-in.

Exports separate visual and collision STL meshes with user-configurable refinement.
Uses Fusion 360's native ExportManager for fast, robust geometry tessellation,
then transforms all mesh vertices into the link's Joint Origin frame in meters.
Handles single and merged multi-body links from rigid groups.
"""

import os
import struct
import math
import tempfile
import uuid
import shutil
from config.defaults import (
    CM_TO_M,
    DEFAULT_MESH_QUALITY,
    COLLISION_MESH_QUALITY,
    DEFAULT_SKIP_INVISIBLE
)
from .transform_utils import (
    get_world_transform,
    get_world_transform_as_list,
    to_flat_matrix,
    pure_matrix_invert,
    pure_matrix_multiply,
    IDENTITY_16
)

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False
    class _MockDynamic:
        def __getattr__(self, name):
            return _MockDynamic()
    adsk = _MockDynamic()
    adsk.core = _MockDynamic()
    adsk.fusion = _MockDynamic()


def get_collection_count(coll):
    """Safely get count from a Fusion 360 collection or standard Python sequence."""
    if coll is None:
        return 0
    cnt = getattr(coll, 'count', None)
    if isinstance(cnt, int):
        return cnt
    if hasattr(coll, '__len__'):
        return len(coll)
    return 0


def get_occ_key(occ):
    """Return a unique, hashable string identifier for an occurrence to avoid TypeError on unhashable C++ objects."""
    if occ is None:
        return "__root__"
    try:
        token = getattr(occ, 'entityToken', None)
        if token:
            return str(token)
    except Exception:
        pass
    try:
        path = getattr(occ, 'fullPathName', None)
        if path:
            return str(path)
    except Exception:
        pass
    try:
        name = getattr(occ, 'name', None)
        if name:
            return f"{name}_{id(occ)}"
    except Exception:
        pass
    return str(id(occ))


class MeshExporter:
    """Exports link bodies to binary STL format in meters, transformed to link local frame."""
    def __init__(self, design, output_dir, visual_quality=DEFAULT_MESH_QUALITY, skip_invisible=DEFAULT_SKIP_INVISIBLE):
        self.design = design
        self.output_dir = output_dir
        self.visual_quality_str = visual_quality
        self.collision_quality_str = COLLISION_MESH_QUALITY
        self.skip_invisible = skip_invisible

    def _is_body_visible(self, body):
        """Check if a body and its parent occurrence are visible in the viewport/browser."""
        if body is None:
            return True
        try:
            if hasattr(body, 'isVisible') and not body.isVisible:
                return False
        except Exception:
            pass
        try:
            if hasattr(body, 'isLightBulbOn') and not body.isLightBulbOn:
                return False
        except Exception:
            pass
        
        occ = getattr(body, '_source_occ', getattr(body, 'assemblyContext', None))
        if occ:
            try:
                if hasattr(occ, 'isVisible') and not occ.isVisible:
                    return False
            except Exception:
                pass
            try:
                if hasattr(occ, 'isLightBulbOn') and not occ.isLightBulbOn:
                    return False
            except Exception:
                pass
        return True

    def _can_batch_export_occurrence(self, occ, occ_bodies):
        """Determine if an occurrence can be exported in one batch STL pass.
        
        Requirements:
        1. Occ is not None and not rootComponent.
        2. Occ is a leaf occurrence (no child occurrences).
        3. Occ's underlying component definition has no occurrences (no sub-components).
        4. Strict body count isolation (always enforced): len(occ_bodies) == len(comp.bRepBodies).
           If the component has any hidden bodies or bodies belonging to other links,
           batch component export is rejected to prevent geometry bleeding.
        """
        if not occ:
            return False
        if HAS_ADSK and self.design and occ == getattr(self.design, 'rootComponent', None):
            return False
        
        try:
            child_occs = getattr(occ, 'childOccurrences', None)
            if get_collection_count(child_occs) > 0:
                return False
        except Exception:
            return False

        comp = getattr(occ, 'component', None)
        if not comp:
            return False

        # Ensure the underlying component definition has no child occurrences
        try:
            comp_occs = getattr(comp, 'occurrences', None)
            if get_collection_count(comp_occs) > 0:
                return False
        except Exception:
            return False

        # Strict body count isolation (always enforced, not just when skip_invisible is enabled):
        # If the component contains more bodies than occ_bodies (e.g. hidden bodies,
        # or bodies assigned to another link), createSTLExportOptions(comp) would export
        # ALL of them, causing mesh bleeding. In that case, fall back to per-body export.
        try:
            b_col = getattr(comp, 'bRepBodies', None)
            total_b_count = get_collection_count(b_col)
            if total_b_count == 0 or len(occ_bodies) != total_b_count:
                return False
        except Exception:
            return False

        return True

    def export_link_meshes(self, link, link_world_transform=None, progress_callback=None):
        """Export separate visual and collision STL files for a URDF link.
        
        Args:
            link (URDFLink): The link containing bodies to export.
            link_world_transform (adsk.core.Matrix3D, optional): World transform of the link frame.
            progress_callback (callable, optional): Callback with signature
                (body_idx, total_bodies, body_name, mesh_type). If it returns False, export aborts.
        """
        if not link.bodies:
            return True

        bodies_to_export = link.bodies
        if self.skip_invisible:
            bodies_to_export = [b for b in link.bodies if self._is_body_visible(b)]
            if not bodies_to_export:
                link.visual_mesh_path = None
                link.collision_mesh_path = None
                return True

        visual_dir = os.path.join(self.output_dir, 'meshes', 'visual')
        collision_dir = os.path.join(self.output_dir, 'meshes', 'collision')
        os.makedirs(visual_dir, exist_ok=True)
        os.makedirs(collision_dir, exist_ok=True)

        filename = f"{link.name}.stl"
        visual_path = os.path.join(visual_dir, filename)
        collision_path = os.path.join(collision_dir, filename)

        # 1. Export Visual Mesh (User-selected quality)
        res_v = self._export_bodies_to_stl(
            bodies=bodies_to_export,
            filepath=visual_path,
            quality_str=self.visual_quality_str,
            link_world_transform=link_world_transform,
            progress_callback=(lambda b, t, n: progress_callback(b, t, n, "visual")) if progress_callback else None
        )
        if res_v is False:
            return False
        link.visual_mesh_path = f"meshes/visual/{filename}"

        # 2. Collision Mesh: Instant copy from visual mesh (avoids redundant C++ meshing pass)
        if progress_callback:
            if progress_callback(1, 1, f"{link.name} (collision)", "collision") is False:
                return False
        shutil.copyfile(visual_path, collision_path)
        link.collision_mesh_path = f"meshes/collision/{filename}"
        return True

    def _export_bodies_to_stl(self, bodies, filepath, quality_str, link_world_transform=None, progress_callback=None):
        """Extract triangle meshes from bodies or leaf occurrences using Fusion 360's native ExportManager,
        transform into link frame, and write binary STL in meters.
        """
        all_triangles = []
        T_link = to_flat_matrix(link_world_transform)
        T_link_inv = pure_matrix_invert(T_link)

        # Determine conversion scale from Fusion document units to centimeters and meters
        units_to_m = 0.001
        if HAS_ADSK and self.design:
            try:
                um = self.design.unitsManager
                units_to_m = um.convert(1.0, um.defaultLengthUnits, 'm')
            except Exception:
                units_to_m = 0.001

        # Scale from document unit (e.g. mm) to cm (for Matrix3D compatibility):
        units_to_cm = units_to_m * 100.0

        # Group bodies by source occurrence using a string key to avoid hashing unhashable C++ objects
        occ_map = {}  # key -> (occ, [bodies])
        for body in bodies:
            occ = getattr(body, '_source_occ', getattr(body, 'assemblyContext', None))
            key = get_occ_key(occ)
            if key not in occ_map:
                occ_map[key] = (occ, [])
            occ_map[key][1].append(body)

        # Build work items: batch leaf occurrences when possible, else per-body
        work_items = []
        for key, (occ, occ_bodies) in occ_map.items():
            if self._can_batch_export_occurrence(occ, occ_bodies):
                work_items.append(('occ', occ, occ_bodies))
            else:
                for b in occ_bodies:
                    work_items.append(('body', b, occ))

        total_items = len(work_items)
        for idx, item in enumerate(work_items):
            item_type = item[0]
            if item_type == 'occ':
                _, occ, occ_bodies = item
                occ_name = getattr(occ, 'name', f"Component {idx+1}")
                if progress_callback:
                    if progress_callback(idx + 1, total_items, occ_name) is False:
                        return False

                occ_world = get_world_transform_as_list(occ)
                occ_to_link = pure_matrix_multiply(T_link_inv, occ_world)
                triangles = self._export_occurrence_triangles(occ, quality_str, occ_to_link, units_to_cm)

                if triangles is not None:
                    all_triangles.extend(triangles)
                else:
                    # Fallback to per-body if occurrence export was not supported or failed
                    for body in occ_bodies:
                        body_triangles = self._export_single_body_triangles(body, quality_str, occ_to_link, units_to_cm)
                        all_triangles.extend(body_triangles)
            else:
                _, body, occ = item
                body_name = getattr(body, 'name', f"Body {idx+1}")
                if progress_callback:
                    if progress_callback(idx + 1, total_items, body_name) is False:
                        return False

                body_world = get_world_transform_as_list(occ) if occ else list(IDENTITY_16)
                body_to_link = pure_matrix_multiply(T_link_inv, body_world)
                triangles = self._export_single_body_triangles(body, quality_str, body_to_link, units_to_cm)
                all_triangles.extend(triangles)

        write_binary_stl(filepath, all_triangles)
        return True

    def _export_occurrence_triangles(self, occ, quality_str, occ_to_link, units_to_cm):
        """Export all bodies of an occurrence in a single native ExportManager pass."""
        if not HAS_ADSK or not self.design:
            if hasattr(occ, 'triangles'):
                return self._transform_triangles(occ.triangles, occ_to_link, units_to_cm)
            comp = getattr(occ, 'component', None)
            if comp and hasattr(comp, 'triangles'):
                return self._transform_triangles(comp.triangles, occ_to_link, units_to_cm)
            return None

        export_mgr = getattr(self.design, 'exportManager', None)
        if not export_mgr:
            return None

        temp_dir = tempfile.gettempdir()
        temp_filename = f"fusion_urdf_temp_{uuid.uuid4().hex}.stl"
        temp_filepath = os.path.join(temp_dir, temp_filename)

        try:
            # In Fusion 360, createSTLExportOptions accepts a Component (comp = occ.component)
            # or a BRepBody. Passing an Occurrence directly is rejected by the API.
            targets = []
            comp = getattr(occ, 'component', None)
            if comp:
                targets.append(comp)
                if hasattr(comp, 'nativeObject') and comp.nativeObject:
                    targets.append(comp.nativeObject)
            targets.append(occ)
            if hasattr(occ, 'nativeObject') and occ.nativeObject:
                targets.append(occ.nativeObject)

            stl_options = None
            for target in targets:
                try:
                    stl_options = export_mgr.createSTLExportOptions(target, temp_filepath)
                    if stl_options:
                        break
                except Exception:
                    pass
                try:
                    stl_options = export_mgr.createSTLExportOptions(target)
                    if stl_options:
                        stl_options.filename = temp_filepath
                        break
                except Exception:
                    pass

            if not stl_options:
                if HAS_ADSK:
                    try:
                        adsk.core.Application.get().log(
                            f"Warning: createSTLExportOptions returned None for component '{getattr(occ, 'name', occ)}' (tried {len(targets)} targets)"
                        )
                    except Exception:
                        pass
                return None

            stl_options.filename = temp_filepath
            stl_options.sendToPrintUtility = False

            if hasattr(adsk.fusion, 'MeshRefinementSettings'):
                MRS = adsk.fusion.MeshRefinementSettings
                if quality_str == 'Low':
                    stl_options.meshRefinement = MRS.MeshRefinementLow
                elif quality_str == 'High':
                    stl_options.meshRefinement = MRS.MeshRefinementHigh
                else:
                    stl_options.meshRefinement = MRS.MeshRefinementMedium

            export_mgr.execute(stl_options)
            if not os.path.exists(temp_filepath) or os.path.getsize(temp_filepath) < 84:
                return None

            raw_triangles = parse_stl_file(temp_filepath)
            return self._transform_triangles(raw_triangles, occ_to_link, units_to_cm)
        except Exception as e:
            if HAS_ADSK:
                try:
                    adsk.core.Application.get().log(f"Warning: Failed to export component mesh: {e}")
                except Exception:
                    pass
            return None
        finally:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass

    def _export_single_body_triangles(self, body, quality_str, body_to_link, units_to_cm):
        """Export a single body to a temporary STL using ExportManager and parse/transform its triangles."""
        if not HAS_ADSK or not self.design:
            # Fallback for mock objects in unit tests
            if hasattr(body, 'triangles'):
                return self._transform_triangles(body.triangles, body_to_link, units_to_cm)
            return []

        export_mgr = getattr(self.design, 'exportManager', None)
        if not export_mgr:
            return []

        # Create temporary file for native STL export
        temp_dir = tempfile.gettempdir()
        temp_filename = f"fusion_urdf_temp_{uuid.uuid4().hex}.stl"
        temp_filepath = os.path.join(temp_dir, temp_filename)
        restore_vis = []

        try:
            # Attempt to export body directly (or its nativeObject if proxy has issues)
            targets = [body]
            if hasattr(body, 'nativeObject') and body.nativeObject:
                targets.append(body.nativeObject)

            stl_options = None
            for target in targets:
                try:
                    stl_options = export_mgr.createSTLExportOptions(target, temp_filepath)
                    if stl_options:
                        break
                except Exception:
                    pass
                try:
                    stl_options = export_mgr.createSTLExportOptions(target)
                    if stl_options:
                        stl_options.filename = temp_filepath
                        break
                except Exception:
                    pass

            # If body export is unsupported or returns None, fall back to component or occurrence
            # while temporarily isolating ONLY this body by hiding all other sibling bodies and child occurrences!
            if not stl_options:
                occ = getattr(body, '_source_occ', getattr(body, 'assemblyContext', None))
                if occ:
                    comp = getattr(occ, 'component', None)
                    if comp:
                        comp_targets = [comp]
                        if hasattr(comp, 'nativeObject') and comp.nativeObject:
                            comp_targets.append(comp.nativeObject)
                        comp_targets.append(occ)
                        for c_tgt in comp_targets:
                            try:
                                stl_options = export_mgr.createSTLExportOptions(c_tgt, temp_filepath)
                                if stl_options:
                                    break
                            except Exception:
                                pass
                            try:
                                stl_options = export_mgr.createSTLExportOptions(c_tgt)
                                if stl_options:
                                    stl_options.filename = temp_filepath
                                    break
                            except Exception:
                                stl_options = None

                        if stl_options:
                            # Hide all other bodies and child occurrences in comp to ensure only this specific body is exported!
                            try:
                                for b in getattr(comp, 'bRepBodies', []):
                                    if b != body and getattr(b, 'isLightBulbOn', True):
                                        b.isLightBulbOn = False
                                        restore_vis.append(b)
                            except Exception:
                                pass
                            try:
                                for o in getattr(comp, 'occurrences', []):
                                    if getattr(o, 'isLightBulbOn', True):
                                        o.isLightBulbOn = False
                                        restore_vis.append(o)
                            except Exception:
                                pass

            if not stl_options:
                return []

            # Ensure output filename is explicitly set
            stl_options.filename = temp_filepath
            stl_options.sendToPrintUtility = False

            # Set mesh refinement
            if hasattr(adsk.fusion, 'MeshRefinementSettings'):
                MRS = adsk.fusion.MeshRefinementSettings
                if quality_str == 'Low':
                    stl_options.meshRefinement = MRS.MeshRefinementLow
                elif quality_str == 'High':
                    stl_options.meshRefinement = MRS.MeshRefinementHigh
                else:
                    stl_options.meshRefinement = MRS.MeshRefinementMedium

            # Execute native export
            export_mgr.execute(stl_options)
            if not os.path.exists(temp_filepath) or os.path.getsize(temp_filepath) < 84:
                return []

            # Parse exported STL triangles
            raw_triangles = parse_stl_file(temp_filepath)
            return self._transform_triangles(raw_triangles, body_to_link, units_to_cm)

        except Exception as e:
            if HAS_ADSK:
                try:
                    adsk.core.Application.get().log(f"Warning: Failed to export body mesh: {e}")
                except Exception:
                    pass
            return []
        finally:
            for item in restore_vis:
                try:
                    item.isLightBulbOn = True
                except Exception:
                    pass
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass

    def _transform_triangles(self, raw_triangles, body_to_link, units_to_cm):
        """Transforms triangles from body component coordinates into link frame and meters.
        
        Args:
            raw_triangles: list of ((nx, ny, nz), (x0, y0, z0), (x1, y1, z1), (x2, y2, z2))
                           where vertices are in document length units.
            body_to_link: 16-element flat matrix (in cm) transforming body local to link local.
            units_to_cm: conversion factor from document length units to centimeters.
        """
        transformed = []
        m = body_to_link or IDENTITY_16

        # Scale factor from cm to meters
        cm_to_m = 0.01

        for norm, p0, p1, p2 in raw_triangles:
            # Step 1: Scale input vertices to centimeters
            p0_cm = (p0[0] * units_to_cm, p0[1] * units_to_cm, p0[2] * units_to_cm)
            p1_cm = (p1[0] * units_to_cm, p1[1] * units_to_cm, p1[2] * units_to_cm)
            p2_cm = (p2[0] * units_to_cm, p2[1] * units_to_cm, p2[2] * units_to_cm)

            # Step 2: Apply 4x4 matrix transformation in cm
            p0_x = m[0] * p0_cm[0] + m[1] * p0_cm[1] + m[2] * p0_cm[2] + m[3]
            p0_y = m[4] * p0_cm[0] + m[5] * p0_cm[1] + m[6] * p0_cm[2] + m[7]
            p0_z = m[8] * p0_cm[0] + m[9] * p0_cm[1] + m[10] * p0_cm[2] + m[11]

            p1_x = m[0] * p1_cm[0] + m[1] * p1_cm[1] + m[2] * p1_cm[2] + m[3]
            p1_y = m[4] * p1_cm[0] + m[5] * p1_cm[1] + m[6] * p1_cm[2] + m[7]
            p1_z = m[8] * p1_cm[0] + m[9] * p1_cm[1] + m[10] * p1_cm[2] + m[11]

            p2_x = m[0] * p2_cm[0] + m[1] * p2_cm[1] + m[2] * p2_cm[2] + m[3]
            p2_y = m[4] * p2_cm[0] + m[5] * p2_cm[1] + m[6] * p2_cm[2] + m[7]
            p2_z = m[8] * p2_cm[0] + m[9] * p2_cm[1] + m[10] * p2_cm[2] + m[11]

            # Step 3: Convert cm to meters for URDF
            v0 = (p0_x * cm_to_m, p0_y * cm_to_m, p0_z * cm_to_m)
            v1 = (p1_x * cm_to_m, p1_y * cm_to_m, p1_z * cm_to_m)
            v2 = (p2_x * cm_to_m, p2_y * cm_to_m, p2_z * cm_to_m)

            # Step 4: Rotate normal vector
            if norm:
                nx = m[0] * norm[0] + m[1] * norm[1] + m[2] * norm[2]
                ny = m[4] * norm[0] + m[5] * norm[1] + m[6] * norm[2]
                nz = m[8] * norm[0] + m[9] * norm[1] + m[10] * norm[2]
                n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
                norm_val = (nx / n_len, ny / n_len, nz / n_len) if n_len > 1e-9 else (0.0, 0.0, 1.0)
            else:
                norm_val = self._compute_normal(v0, v1, v2)

            transformed.append((norm_val, v0, v1, v2))

        return transformed

    def _compute_normal(self, v0, v1, v2):
        """Calculate face normal from 3 vertices."""
        ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
        bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 1e-9:
            return (nx / length, ny / length, nz / length)
        return (0.0, 0.0, 1.0)


def parse_stl_file(filepath):
    """Parses binary or ASCII STL file into list of ((nx,ny,nz), (x0,y0,z0), (x1,y1,z1), (x2,y2,z2))."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 84:
        return []

    file_size = os.path.getsize(filepath)
    with open(filepath, 'rb') as f:
        header = f.read(80)
        count_bytes = f.read(4)
        num_triangles = struct.unpack('<I', count_bytes)[0]
        expected_size = 84 + num_triangles * 50

        # If file size matches or accommodates exact binary STL formula
        if file_size >= expected_size and num_triangles > 0:
            triangles = []
            data = f.read(num_triangles * 50)
            for i in range(num_triangles):
                offset = i * 50
                n = struct.unpack_from('<3f', data, offset)
                v0 = struct.unpack_from('<3f', data, offset + 12)
                v1 = struct.unpack_from('<3f', data, offset + 24)
                v2 = struct.unpack_from('<3f', data, offset + 36)
                triangles.append((n, v0, v1, v2))
            return triangles

    # Fallback: ASCII STL parser
    triangles = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            current_normal = (0.0, 0.0, 1.0)
            current_verts = []
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0].lower() == 'facet' and parts[1].lower() == 'normal' and len(parts) >= 5:
                    current_normal = (float(parts[2]), float(parts[3]), float(parts[4]))
                elif parts[0].lower() == 'vertex' and len(parts) >= 4:
                    current_verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    if len(current_verts) == 3:
                        triangles.append((current_normal, current_verts[0], current_verts[1], current_verts[2]))
                        current_verts = []
    except Exception:
        pass
    return triangles


def write_binary_stl(filepath, triangles):
    """Write list of (normal, v0, v1, v2) triangles as a binary STL file."""
    with open(filepath, 'wb') as f:
        # 80-byte header
        header = b'Exported by Fusion 360 URDF Exporter (units: meters)'.ljust(80, b'\x00')
        f.write(header)

        # 4-byte unsigned int: triangle count
        f.write(struct.pack('<I', len(triangles)))

        # 50 bytes per triangle
        for n, v0, v1, v2 in triangles:
            # Normal
            f.write(struct.pack('<3f', float(n[0]), float(n[1]), float(n[2])))
            # Vertices
            f.write(struct.pack('<3f', float(v0[0]), float(v0[1]), float(v0[2])))
            f.write(struct.pack('<3f', float(v1[0]), float(v1[1]), float(v1[2])))
            f.write(struct.pack('<3f', float(v2[0]), float(v2[1]), float(v2[2])))
            # Attribute byte count (2 bytes)
            f.write(struct.pack('<H', 0))
