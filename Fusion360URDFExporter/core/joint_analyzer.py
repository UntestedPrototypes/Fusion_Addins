"""Joint analyzer for Fusion 360 assemblies.

Extracts kinematic properties, axis, limits, and handles direct, sketch,
and joint-origin based joint geometries.
"""

import math
from config.defaults import (
    CM_TO_M, M_TO_CM,
    DEFAULT_REVOLUTE_LIMITS,
    DEFAULT_PRISMATIC_LIMITS,
    DEFAULT_EFFORT,
    DEFAULT_VELOCITY,
    JOINT_TYPE_REVOLUTE,
    JOINT_TYPE_CONTINUOUS,
    JOINT_TYPE_PRISMATIC,
    JOINT_TYPE_FIXED,
    JOINT_TYPE_PLANAR
)
from .transform_utils import (
    matrix3d_to_rpy,
    axes_vectors_to_rpy,
    get_world_transform,
    get_world_transform_as_list,
    to_flat_matrix,
    make_frame_4x4,
    pure_matrix_to_rpy,
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


class JointInfo:
    """Encapsulates analyzed kinematic joint data ready for URDF generation."""
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', "")
        self.joint_type = kwargs.get('joint_type', JOINT_TYPE_FIXED)
        self.parent_link_path = kwargs.get('parent_link_path', "root")
        self.child_link_path = kwargs.get('child_link_path', "")
        self.origin_xyz = list(kwargs.get('origin_xyz', [0.0, 0.0, 0.0]))  # meters, relative to parent link
        self.origin_rpy = list(kwargs.get('origin_rpy', [0.0, 0.0, 0.0]))  # radians, relative to parent link
        self.axis = list(kwargs.get('axis', [0.0, 0.0, 1.0]))        # 3D unit vector
        self.world_frame_cm = kwargs.get('world_frame_cm', None)         # 16-element flat list (4x4 world matrix in cm)
        self.limit_lower = kwargs.get('limit_lower', 0.0)
        self.limit_upper = kwargs.get('limit_upper', 0.0)
        self.limit_effort = kwargs.get('limit_effort', DEFAULT_EFFORT)
        self.limit_velocity = kwargs.get('limit_velocity', DEFAULT_VELOCITY)
        self.geometry_source = kwargs.get('geometry_source', "direct")     # 'direct' | 'sketch' | 'joint_origin' | 'as_built'
        self.depth = kwargs.get('depth', 0)

    def __repr__(self):
        return f"<JointInfo '{self.name}' type={self.joint_type} parent='{self.parent_link_path}' child='{self.child_link_path}'>"


class JointAnalyzer:
    """Analyzes Fusion 360 joints and maps them to URDF joint representations."""
    def __init__(self, root_component):
        self.root = root_component
        self.warnings = []

    def analyze_all(self):
        """Analyze all non-rigid standard joints and as-built joints."""
        joints_info = []

        all_joints = []
        has_assembly_joints = False
        try:
            j_all = getattr(self.root, 'allJoints', None)
            if j_all is not None:
                all_joints.extend(list(j_all))
                has_assembly_joints = True
        except (RuntimeError, Exception):
            pass

        if not has_assembly_joints:
            try:
                j_root = getattr(self.root, 'joints', None)
                if j_root is not None:
                    all_joints.extend(list(j_root))
            except (RuntimeError, Exception):
                pass

        try:
            abj_all = getattr(self.root, 'allAsBuiltJoints', None)
            if abj_all is not None:
                all_joints.extend(list(abj_all))
        except (RuntimeError, Exception):
            pass

        try:
            abj_root = getattr(self.root, 'asBuiltJoints', None)
            if abj_root is not None:
                all_joints.extend(list(abj_root))
        except (RuntimeError, Exception):
            pass

        for joint in all_joints:
            # Safely check if joint is suppressed, catching Fusion C++ InternalValidationErrors
            try:
                if joint.isSuppressed:
                    continue
            except (RuntimeError, Exception):
                continue

            # Only create a joint if the joint is made between two joint origins (including rigid joints)
            if not self._is_between_two_joint_origins(joint):
                continue

            try:
                motion = getattr(joint, 'jointMotion', None)
            except (RuntimeError, Exception):
                motion = None
            if motion is None:
                continue

            try:
                info = self._extract_joint(joint)
                if info:
                    joints_info.append(info)
            except (RuntimeError, Exception):
                pass

        return joints_info

    def _is_rigid_joint(self, motion):
        if HAS_ADSK and hasattr(adsk.fusion, 'JointTypes'):
            try:
                if motion.jointType == adsk.fusion.JointTypes.RigidJointType:
                    return True
            except (RuntimeError, Exception):
                pass
        jtype_str = str(getattr(motion, 'jointType', '')).lower()
        return ('rigid' in jtype_str or jtype_str in ('0', 'rigidjointtype'))

    def _extract_joint(self, joint):
        info = JointInfo()
        try:
            motion = joint.jointMotion
        except (RuntimeError, Exception):
            return None

        # 1. Determine URDF Joint Type
        info.joint_type = self._classify_joint_type(motion)

        # 2. Resolve Parent and Child
        # occurrenceOne: component that moves (child link)
        # occurrenceTwo: component that stays (parent link). If None, parent is root assembly.
        try:
            child_occ = getattr(joint, 'occurrenceOne', None)
        except (RuntimeError, Exception):
            child_occ = None

        try:
            parent_occ = getattr(joint, 'occurrenceTwo', None)
        except (RuntimeError, Exception):
            parent_occ = None

        if child_occ is None:
            # Cannot form a kinematic chain without a child
            return None

        try:
            info.child_link_path = child_occ.fullPathName
        except (RuntimeError, Exception):
            return None

        try:
            info.parent_link_path = parent_occ.fullPathName if parent_occ else 'root'
        except (RuntimeError, Exception):
            info.parent_link_path = 'root'

        # 3. Extract Joint Coordinate Frame in World Coordinates (cm)
        world_frame_cm = self._extract_joint_world_frame(joint, child_occ, parent_occ)
        info.world_frame_cm = world_frame_cm

        if self._is_motion_flipped(joint):
            info.axis = [0.0, 0.0, -1.0]
        else:
            info.axis = [0.0, 0.0, 1.0]

        # Compute relative transform for parent occurrence
        self._compute_relative_transform(world_frame_cm, parent_occ, info)

        # 4. Extract Motion Limits
        self._extract_limits(motion, info)

        return info

    def _classify_joint_type(self, motion):
        """Map Fusion 360 joint motion to URDF joint type."""
        m_type = getattr(motion, 'jointType', None)

        if HAS_ADSK and hasattr(adsk.fusion, 'JointTypes'):
            JT = adsk.fusion.JointTypes
            if m_type == JT.RevoluteJointType:
                rev_motion = adsk.fusion.RevoluteJointMotion.cast(motion)
                if rev_motion and hasattr(rev_motion, 'rotationLimits'):
                    lims = rev_motion.rotationLimits
                    if lims is not None and not self._is_min_limit_enabled(lims) and not self._is_max_limit_enabled(lims):
                        return JOINT_TYPE_CONTINUOUS
                return JOINT_TYPE_REVOLUTE
            elif m_type == JT.SliderJointType:
                return JOINT_TYPE_PRISMATIC
            elif m_type in (JT.CylindricalJointType, JT.PinSlotJointType):
                return JOINT_TYPE_REVOLUTE
            elif m_type == JT.PlanarJointType:
                return JOINT_TYPE_PLANAR
            else:
                return JOINT_TYPE_FIXED
        else:
            # String or mock fallback
            if str(m_type) in ('RevoluteJointType', '1', 'revolute'):
                return JOINT_TYPE_REVOLUTE
            elif str(m_type) in ('SliderJointType', '2', 'prismatic', 'slider'):
                return JOINT_TYPE_PRISMATIC
            return JOINT_TYPE_FIXED

    def _is_joint_origin(self, ref):
        if ref is None:
            return False
        if HAS_ADSK and hasattr(adsk.fusion, 'JointOrigin'):
            try:
                if isinstance(ref, adsk.fusion.JointOrigin):
                    return True
            except Exception:
                pass
        type_name = type(ref).__name__
        if 'JointOrigin' in type_name:
            return True
        try:
            native = getattr(ref, 'nativeObject', None)
            if native and self._is_joint_origin(native):
                return True
        except Exception:
            pass
        try:
            ent = getattr(ref, 'entityOne', None)
            if ent and self._is_joint_origin(ent):
                return True
        except Exception:
            pass
        return False

    def _is_between_two_joint_origins(self, joint):
        """Check if a joint connects two JointOrigin features."""
        try:
            ref_one = getattr(joint, 'geometryOrOriginOne', None)
            ref_two = getattr(joint, 'geometryOrOriginTwo', None)
        except Exception:
            return False

        if ref_one is None or ref_two is None:
            return False

        return self._is_joint_origin(ref_one) and self._is_joint_origin(ref_two)

    def _is_sketch_based(self, ref):
        if ref is None:
            return False
        try:
            if hasattr(ref, 'entityOne') and ref.entityOne:
                entity = ref.entityOne
                if HAS_ADSK:
                    return (isinstance(entity, adsk.fusion.SketchPoint) or
                            isinstance(entity, adsk.fusion.SketchCurve))
                return 'Sketch' in type(entity).__name__
        except:
            pass
        return False

    def _extract_joint_world_frame(self, joint, child_occ, parent_occ):
        """Extract the 4x4 world coordinate frame (in cm) for the joint.
        
        Prioritizes JointOrigin features mated between components.
        """
        ref_one = None
        ref_two = None
        if HAS_ADSK and hasattr(adsk.fusion, 'Joint') and isinstance(joint, adsk.fusion.Joint):
            try:
                ref_one = joint.geometryOrOriginOne
            except Exception:
                pass
            try:
                ref_two = getattr(joint, 'geometryOrOriginTwo', None)
            except Exception:
                pass
        else:
            try:
                ref_one = getattr(joint, 'geometryOrOriginOne', None)
                ref_two = getattr(joint, 'geometryOrOriginTwo', None)
            except Exception:
                pass

        # Check for JointOrigin on child (occurrenceOne) or parent (occurrenceTwo)
        jo_target = None
        target_occ = None
        if self._is_joint_origin(ref_one):
            jo_target = ref_one
            target_occ = child_occ
        elif self._is_joint_origin(ref_two):
            jo_target = ref_two
            target_occ = parent_occ

        if jo_target is not None:
            frame = self._frame_from_joint_origin(jo_target, target_occ)
            if frame:
                return frame

        # Check for JointGeometry
        jg_target = ref_one if ref_one else ref_two
        if jg_target is not None:
            target_occ = child_occ if (jg_target == ref_one) else parent_occ
            frame = self._frame_from_joint_geometry(jg_target, target_occ, joint)
            if frame:
                return frame

        # As-Built joint or fallback geometry
        if hasattr(joint, 'geometry') and joint.geometry:
            frame = self._frame_from_joint_geometry(joint.geometry, child_occ, joint)
            if frame:
                return frame

        # Fallback: child occurrence world transform
        return get_world_transform_as_list(child_occ)

    def _frame_from_joint_origin(self, jo, occ):
        """Extract 4x4 world frame from a JointOrigin object."""
        try:
            if hasattr(jo, 'transform') and jo.transform is not None:
                mat = to_flat_matrix(jo.transform)
                is_proxy = getattr(jo, 'assemblyContext', None) is not None
                if not is_proxy and occ is not None:
                    occ_mat = get_world_transform_as_list(occ)
                    mat = pure_matrix_multiply(occ_mat, mat)
                return mat
        except Exception:
            pass

        try:
            if hasattr(jo, 'geometry') and jo.geometry:
                jg = jo.geometry
                pt = getattr(jg, 'origin', None)
                if pt is not None:
                    z_axis = getattr(jg, 'primaryAxisVector', None)
                    x_axis = getattr(jg, 'secondaryAxisVector', None)
                    return self._build_world_frame_from_points(pt, z_axis, x_axis, jo, occ)
        except Exception:
            pass
        return None

    def _frame_from_joint_geometry(self, jg, occ, joint):
        try:
            pt = getattr(jg, 'origin', None)
            if pt is not None:
                z_axis = getattr(jg, 'primaryAxisVector', None)
                if z_axis is None and hasattr(joint, 'jointMotion'):
                    m_vec = self._get_motion_axis_vector(joint.jointMotion)
                    if m_vec:
                        z_axis = m_vec
                x_axis = getattr(jg, 'secondaryAxisVector', None)
                return self._build_world_frame_from_points(pt, z_axis, x_axis, jg, occ)
        except Exception:
            pass
        return None

    def _build_world_frame_from_points(self, pt, z_axis, x_axis, source_obj, occ):
        p = [float(pt.x), float(pt.y), float(pt.z)]
        if hasattr(z_axis, 'x'):
            z = [float(z_axis.x), float(z_axis.y), float(z_axis.z)]
        elif isinstance(z_axis, (list, tuple)):
            z = [float(z_axis[0]), float(z_axis[1]), float(z_axis[2])]
        else:
            z = [0.0, 0.0, 1.0]

        if hasattr(x_axis, 'x'):
            x = [float(x_axis.x), float(x_axis.y), float(x_axis.z)]
        elif isinstance(x_axis, (list, tuple)):
            x = [float(x_axis[0]), float(x_axis[1]), float(x_axis[2])]
        else:
            x = None

        is_proxy = getattr(source_obj, 'assemblyContext', None) is not None
        if not is_proxy and occ is not None:
            occ_mat = get_world_transform_as_list(occ)
            px = occ_mat[0] * p[0] + occ_mat[1] * p[1] + occ_mat[2] * p[2] + occ_mat[3]
            py = occ_mat[4] * p[0] + occ_mat[5] * p[1] + occ_mat[6] * p[2] + occ_mat[7]
            pz = occ_mat[8] * p[0] + occ_mat[9] * p[1] + occ_mat[10] * p[2] + occ_mat[11]
            p = [px, py, pz]

            zx = occ_mat[0] * z[0] + occ_mat[1] * z[1] + occ_mat[2] * z[2]
            zy = occ_mat[4] * z[0] + occ_mat[5] * z[1] + occ_mat[6] * z[2]
            zz = occ_mat[8] * z[0] + occ_mat[9] * z[1] + occ_mat[10] * z[2]
            z = [zx, zy, zz]

            if x is not None:
                xx = occ_mat[0] * x[0] + occ_mat[1] * x[1] + occ_mat[2] * x[2]
                xy = occ_mat[4] * x[0] + occ_mat[5] * x[1] + occ_mat[6] * x[2]
                xz = occ_mat[8] * x[0] + occ_mat[9] * x[1] + occ_mat[10] * x[2]
                x = [xx, xy, xz]

        return make_frame_4x4(p, z, x)

    def _is_motion_flipped(self, joint):
        try:
            motion = getattr(joint, 'jointMotion', None)
            if motion and hasattr(motion, 'isFlipped') and motion.isFlipped:
                return True
        except Exception:
            pass
        return False

    def _get_motion_axis_vector(self, motion):
        """Read 3D unit vector from RevoluteJointMotion or SliderJointMotion."""
        if hasattr(motion, 'rotationAxisVector') and motion.rotationAxisVector:
            v = motion.rotationAxisVector
            norm = math.sqrt(v.x**2 + v.y**2 + v.z**2)
            if norm > 1e-6:
                return [v.x / norm, v.y / norm, v.z / norm]
        if hasattr(motion, 'slideDirectionVector') and motion.slideDirectionVector:
            v = motion.slideDirectionVector
            norm = math.sqrt(v.x**2 + v.y**2 + v.z**2)
            if norm > 1e-6:
                return [v.x / norm, v.y / norm, v.z / norm]
        return None

    def _compute_relative_transform(self, world_frame_cm, parent_occ, info):
        """Transform world joint coordinates to coordinates relative to parent occurrence."""
        if world_frame_cm is None:
            return

        if parent_occ is None:
            info.origin_xyz = [
                world_frame_cm[3] * CM_TO_M,
                world_frame_cm[7] * CM_TO_M,
                world_frame_cm[11] * CM_TO_M
            ]
            info.origin_rpy = pure_matrix_to_rpy(
                world_frame_cm[0], world_frame_cm[1], world_frame_cm[2],
                world_frame_cm[4], world_frame_cm[5], world_frame_cm[6],
                world_frame_cm[8], world_frame_cm[9], world_frame_cm[10]
            )
            return

        parent_mat = get_world_transform_as_list(parent_occ)
        parent_inv = pure_matrix_invert(parent_mat)
        rel_mat = pure_matrix_multiply(parent_inv, world_frame_cm)

        info.origin_xyz = [
            rel_mat[3] * CM_TO_M,
            rel_mat[7] * CM_TO_M,
            rel_mat[11] * CM_TO_M
        ]
        info.origin_rpy = pure_matrix_to_rpy(
            rel_mat[0], rel_mat[1], rel_mat[2],
            rel_mat[4], rel_mat[5], rel_mat[6],
            rel_mat[8], rel_mat[9], rel_mat[10]
        )

    def _is_min_limit_enabled(self, lims):
        """Check if minimum limit is enabled on JointLimits object."""
        try:
            return bool(lims.isMinimumValueEnabled)
        except Exception:
            return False

    def _is_max_limit_enabled(self, lims):
        """Check if maximum limit is enabled on JointLimits object."""
        try:
            return bool(lims.isMaximumValueEnabled)
        except Exception:
            return False

    def _extract_limits(self, motion, info):
        """Extract min/max limits for revolute and slider joints."""
        if info.joint_type in (JOINT_TYPE_REVOLUTE, JOINT_TYPE_CONTINUOUS):
            if hasattr(motion, 'rotationLimits') and motion.rotationLimits is not None:
                lims = motion.rotationLimits
                min_enabled = self._is_min_limit_enabled(lims)
                max_enabled = self._is_max_limit_enabled(lims)
                info.limit_lower = lims.minimumValue if min_enabled else DEFAULT_REVOLUTE_LIMITS['lower']
                info.limit_upper = lims.maximumValue if max_enabled else DEFAULT_REVOLUTE_LIMITS['upper']
            else:
                info.limit_lower = DEFAULT_REVOLUTE_LIMITS['lower']
                info.limit_upper = DEFAULT_REVOLUTE_LIMITS['upper']
            info.limit_effort = DEFAULT_REVOLUTE_LIMITS['effort']
            info.limit_velocity = DEFAULT_REVOLUTE_LIMITS['velocity']

        elif info.joint_type == JOINT_TYPE_PRISMATIC:
            if hasattr(motion, 'slideLimits') and motion.slideLimits is not None:
                lims = motion.slideLimits
                min_enabled = self._is_min_limit_enabled(lims)
                max_enabled = self._is_max_limit_enabled(lims)
                # Fusion lengths are in cm -> convert to m
                info.limit_lower = (lims.minimumValue * CM_TO_M) if min_enabled else DEFAULT_PRISMATIC_LIMITS['lower']
                info.limit_upper = (lims.maximumValue * CM_TO_M) if max_enabled else DEFAULT_PRISMATIC_LIMITS['upper']
            else:
                info.limit_lower = DEFAULT_PRISMATIC_LIMITS['lower']
                info.limit_upper = DEFAULT_PRISMATIC_LIMITS['upper']
            info.limit_effort = DEFAULT_PRISMATIC_LIMITS['effort']
            info.limit_velocity = DEFAULT_PRISMATIC_LIMITS['velocity']
