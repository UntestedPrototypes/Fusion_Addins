"""Geometry and contact detection for Autodesk Fusion 360 models.

Analyzes selected B-Rep bodies, faces, and edges to determine plate thicknesses,
contact seams, orientations, and coordinate frames.
"""

import math
from typing import Optional, Tuple, NamedTuple, List
from .geometry_math import Vec3

try:
    import adsk.core
    import adsk.fusion
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


class JointGeometryContext(NamedTuple):
    """Context holding the 3D vectors and dimensions for joint generation."""
    tab_body: object
    slot_body: object
    joint_length: float
    start_point: Vec3
    end_point: Vec3
    edge_dir: Vec3
    thickness_dir: Vec3
    penetration_dir: Vec3
    tab_thickness: float
    slot_thickness: float


def point3d_to_vec3(pt) -> Vec3:
    """Converts a Fusion Point3D into our Vec3."""
    return Vec3(pt.x, pt.y, pt.z)


def vector3d_to_vec3(vec) -> Vec3:
    """Converts a Fusion Vector3D into our Vec3."""
    return Vec3(vec.x, vec.y, vec.z)


def vec3_to_point3d(v: Vec3):
    """Converts Vec3 to Fusion Point3D."""
    if not HAS_ADSK:
        return None
    return adsk.core.Point3D.create(v.x, v.y, v.z)


def vec3_to_vector3d(v: Vec3):
    """Converts Vec3 to Fusion Vector3D."""
    if not HAS_ADSK:
        return None
    return adsk.core.Vector3D.create(v.x, v.y, v.z)


def detect_body_thickness(body) -> float:
    """Estimates the sheet plate thickness of a B-Rep body.

    Finds the minimum distance between opposing parallel planar faces.
    Returns thickness in centimeters (Fusion standard unit).
    Default fallback is 0.3 cm (3.0 mm).
    """
    if not HAS_ADSK or not body or not hasattr(body, "faces"):
        return 0.3

    planar_faces = []
    for face in body.faces:
        if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
            planar_faces.append(face)

    min_dist = float("inf")

    # Compare pairs of planar faces
    for i in range(len(planar_faces)):
        plane_i = planar_faces[i].geometry
        n_i = vector3d_to_vec3(plane_i.normal)

        for j in range(i + 1, len(planar_faces)):
            plane_j = planar_faces[j].geometry
            n_j = vector3d_to_vec3(plane_j.normal)

            # Check if opposing (normals pointing in opposite directions)
            if n_i.is_parallel(n_j) and n_i.dot(n_j) < -0.9:
                p_i = point3d_to_vec3(plane_i.origin)
                p_j = point3d_to_vec3(plane_j.origin)
                # Distance along normal
                dist = abs((p_j - p_i).dot(n_i))
                # Plate thickness is typically 0.1cm (1mm) to 2.5cm (25mm)
                if 0.05 < dist < 3.0 and dist < min_dist:
                    min_dist = dist

    if min_dist < float("inf"):
        return min_dist

    # Fallback to bounding box minimum dimension
    try:
        bb = body.boundingBox
        dx = bb.maxPoint.x - bb.minPoint.x
        dy = bb.maxPoint.y - bb.minPoint.y
        dz = bb.maxPoint.z - bb.minPoint.z
        dims = sorted([dx, dy, dz])
        if dims[0] > 0.05:
            return dims[0]
    except Exception:
        pass

    return 0.3  # 3 mm fallback


def analyze_edge_and_face(edge, face) -> Optional[JointGeometryContext]:
    """Analyzes a selected tab edge and mating slot face to extract 3D vectors."""
    if not HAS_ADSK or not edge or not face:
        return None

    try:
        # Edge geometry
        geom = edge.geometry
        if geom.curveType != adsk.core.Curve3DTypes.Line3DCurveType:
            # Add-in currently supports linear edges for laser-cut joints
            return None

        p_start = point3d_to_vec3(edge.startVertex.geometry)
        p_end = point3d_to_vec3(edge.endVertex.geometry)
        edge_vec = p_end - p_start
        length = edge_vec.length()
        if length < 1e-4:
            return None
        edge_dir = edge_vec.normalized()

        # Face geometry (mating face)
        if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
            return None

        plane = face.geometry
        face_normal = vector3d_to_vec3(plane.normal)

        # Penetration direction: into the slot body
        # Check face normal direction relative to slot body
        # Usually, the mating face faces towards the tab body, so penetrating the slot body is -face_normal
        penetration_dir = (-face_normal).normalized()

        # Check if tab edge is perpendicular or at an angle; thickness_dir is orthogonal to both
        thickness_dir = edge_dir.cross(penetration_dir).normalized()
        if thickness_dir.length() < 1e-4:
            # Fallback if edge is collinear with normal
            thickness_dir = Vec3(0, 1, 0) if abs(edge_dir.y) < 0.9 else Vec3(1, 0, 0)
            thickness_dir = edge_dir.cross(thickness_dir).normalized()

        tab_body = edge.body
        slot_body = face.body

        t_tab = detect_body_thickness(tab_body)
        t_slot = detect_body_thickness(slot_body)

        return JointGeometryContext(
            tab_body=tab_body,
            slot_body=slot_body,
            joint_length=length,
            start_point=p_start,
            end_point=p_end,
            edge_dir=edge_dir,
            thickness_dir=thickness_dir,
            penetration_dir=penetration_dir,
            tab_thickness=t_tab,
            slot_thickness=t_slot
        )
    except Exception:
        return None


def analyze_bodies_contact(body1, body2) -> Optional[JointGeometryContext]:
    """Analyzes two bodies to detect their contact seam or intersection."""
    if not HAS_ADSK or not body1 or not body2:
        return None

    try:
        # Inspect faces of body1 that touch or are nearest to faces of body2
        app = adsk.core.Application.get()
        measure_mgr = app.measureManager

        best_edge = None
        best_face = None
        min_dist = float("inf")

        for face1 in body1.faces:
            for face2 in body2.faces:
                try:
                    res = measure_mgr.measureMinimumDistance(face1, face2)
                    if res and res.value < min_dist:
                        min_dist = res.value
                        if min_dist < 1e-3:
                            # Contact found! Find linear edges on face1
                            for e in face1.edges:
                                if e.geometry.curveType == adsk.core.Curve3DTypes.Line3DCurveType:
                                    best_edge = e
                                    best_face = face2
                                    break
                            if best_edge:
                                break
                except Exception:
                    continue
            if best_edge:
                break

        if best_edge and best_face:
            return analyze_edge_and_face(best_edge, best_face)

        return None
    except Exception:
        return None
