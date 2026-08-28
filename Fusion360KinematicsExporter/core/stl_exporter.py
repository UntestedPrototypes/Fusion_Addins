import adsk.core, adsk.fusion
import os
from . import RobotModel, NamingConfig

def find_occurrence_by_name(root_component, link_name: str, naming_config: NamingConfig) -> adsk.fusion.Occurrence:
    root_formatted = naming_config.format_link_name(root_component.name) if naming_config else root_component.name
    if link_name == root_formatted:
        return None
        
    for occ in root_component.allOccurrences:
        occ_formatted = naming_config.format_link_name(occ.name) if naming_config else occ.name
        if link_name == occ_formatted:
            return occ
    return None

import struct

def merge_stls(input_filepaths, output_filepath):
    total_triangles = 0
    all_triangles_data = bytearray()
    
    for filepath in input_filepaths:
        try:
            with open(filepath, 'rb') as f:
                header = f.read(80)
                count_data = f.read(4)
                if not count_data:
                    continue
                count = struct.unpack('<I', count_data)[0]
                total_triangles += count
                triangle_data = f.read(count * 50)
                all_triangles_data.extend(triangle_data)
        except:
            pass
            
    with open(output_filepath, 'wb') as f:
        f.write(b'\x00' * 80)
        f.write(struct.pack('<I', total_triangles))
        f.write(all_triangles_data)

def is_inside(bb_inner, bb_outer):
    tol = 1e-5
    return (bb_inner.minPoint.x >= bb_outer.minPoint.x - tol and
            bb_inner.minPoint.y >= bb_outer.minPoint.y - tol and
            bb_inner.minPoint.z >= bb_outer.minPoint.z - tol and
            bb_inner.maxPoint.x <= bb_outer.maxPoint.x + tol and
            bb_inner.maxPoint.y <= bb_outer.maxPoint.y + tol and
            bb_inner.maxPoint.z <= bb_outer.maxPoint.z + tol)

def export_stl_meshes(robot_model: RobotModel, output_dir: str, mesh_quality: str = 'high', use_mesh_collision: bool = True, naming_config=None) -> dict:
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        return {}
        
    root = design.rootComponent
    export_mgr = design.exportManager
    
    mesh_dir = os.path.join(output_dir, 'meshes')
    os.makedirs(mesh_dir, exist_ok=True)
    
    results = {}
    
    for link_name, link_data in robot_model.links.items():
        try:
            occ = find_occurrence_by_name(root, link_name, naming_config)
            
            target = occ if occ is not None else root
            
            if target:
                comp = target.component if occ else target
                if comp.bRepBodies.count == 0:
                    continue
                    
                # 1. Export Full Visual Mesh
                filename = f"{link_name}.stl"
                filepath = os.path.join(mesh_dir, filename)
                
                stl_options = export_mgr.createSTLExportOptions(comp, filepath)
                stl_options.isBinaryFormat = True
                
                if mesh_quality.lower() == 'high':
                    stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
                elif mesh_quality.lower() == 'medium':
                    stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
                else:
                    stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementLow
                    
                if export_mgr.execute(stl_options):
                    link_data.stl_filename = filename
                    results[link_name] = filepath
                    
                # 2. Export Filtered Collision Mesh (Low Poly)
                if use_mesh_collision:
                    bodies = [b for b in comp.bRepBodies]
                    filtered_bodies = []
                    for i, b1 in enumerate(bodies):
                        bb1 = b1.boundingBox
                        inside_another = False
                        for j, b2 in enumerate(bodies):
                            if i != j:
                                bb2 = b2.boundingBox
                                # Check if b1 is strictly inside b2
                                if is_inside(bb1, bb2):
                                    # If they have exact same bounding box, keep the first one
                                    if is_inside(bb2, bb1) and i > j:
                                        pass # Let the earlier one be kept, this one is dropped
                                    else:
                                        inside_another = True
                                        break
                        if not inside_another:
                            filtered_bodies.append(b1)
                    
                    temp_files = []
                    for i, b in enumerate(filtered_bodies):
                        temp_file = os.path.join(mesh_dir, f"temp_{link_name}_{i}.stl")
                        opt = export_mgr.createSTLExportOptions(b, temp_file)
                        opt.isBinaryFormat = True
                        opt.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementLow
                        if export_mgr.execute(opt):
                            temp_files.append(temp_file)
                            
                    if temp_files:
                        col_filename = f"{link_name}_col.stl"
                        col_filepath = os.path.join(mesh_dir, col_filename)
                        merge_stls(temp_files, col_filepath)
                        link_data.col_stl_filename = col_filename
                        for tf in temp_files:
                            try:
                                os.remove(tf)
                            except:
                                pass
                    
        except Exception as e:
            # We ignore failure for a specific occurrence to allow exporting the rest
            pass
            
    return results

