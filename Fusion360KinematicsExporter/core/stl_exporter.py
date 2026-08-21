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

def export_stl_meshes(robot_model: RobotModel, output_dir: str, mesh_quality: str = 'high', naming_config=None) -> dict:
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
                # Need to check bodies at the component level
                comp = target.component if occ else target
                if comp.bRepBodies.count == 0:
                    continue
                    
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
                    
                success = export_mgr.execute(stl_options)
                
                if success:
                    link_data.stl_filename = filename
                    results[link_name] = filepath
                    
        except Exception as e:
            # We ignore failure for a specific occurrence to allow exporting the rest
            pass
            
    return results

