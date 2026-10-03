"""Coordinate transformation utilities for Fusion 360 to URDF conversion."""

import math

try:
    import adsk.core
    HAS_ADSK = True
except ImportError:
    HAS_ADSK = False


def pure_matrix_to_rpy(r00, r01, r02,
                       r10, r11, r12,
                       r20, r21, r22):
    """Convert a 3x3 rotation matrix to Roll-Pitch-Yaw (extrinsic XYZ / intrinsic ZYX) in radians.
    
    R = Rz(yaw) * Ry(pitch) * Rx(roll)
    """
    sy = math.sqrt(r00 * r00 + r10 * r10)
    pitch = math.atan2(-r20, sy)

    if sy > 1e-6:
        roll = math.atan2(r21, r22)
        yaw = math.atan2(r10, r00)
    else:
        # Gimbal lock: pitch is near +/- pi/2
        roll = 0.0
        yaw = math.atan2(-r01, r11)

    return [roll, pitch, yaw]


def pure_matrix_multiply(m1, m2):
    """Multiply two 4x4 row-major matrices represented as 16-element lists or 4x4 lists."""
    if isinstance(m1[0], (int, float)):
        # 16-element flat
        res = [0.0] * 16
        for row in range(4):
            for col in range(4):
                val = 0.0
                for k in range(4):
                    val += m1[row * 4 + k] * m2[k * 4 + col]
                res[row * 4 + col] = val
        return res
    else:
        # 4x4 nested list
        res = [[0.0] * 4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                res[i][j] = sum(m1[i][k] * m2[k][j] for k in range(4))
        return res


def pure_matrix_invert(m):
    """Invert a 4x4 affine rigid transform matrix (3x3 rotation + translation).
    
    m is a 16-element flat list in row-major order:
    [R00, R01, R02, Tx,
     R10, R11, R12, Ty,
     R20, R21, R22, Tz,
       0,   0,   0,  1]
    
    Inverse:
    R_inv = R^T
    T_inv = -R^T * T
    """
    r00, r01, r02, tx = m[0], m[1], m[2], m[3]
    r10, r11, r12, ty = m[4], m[5], m[6], m[7]
    r20, r21, r22, tz = m[8], m[9], m[10], m[11]

    # Transposed rotation
    inv_r00, inv_r01, inv_r02 = r00, r10, r20
    inv_r10, inv_r11, inv_r12 = r01, r11, r21
    inv_r20, inv_r21, inv_r22 = r02, r12, r22

    # Inverted translation = -R^T * T
    inv_tx = -(inv_r00 * tx + inv_r01 * ty + inv_r02 * tz)
    inv_ty = -(inv_r10 * tx + inv_r11 * ty + inv_r12 * tz)
    inv_tz = -(inv_r20 * tx + inv_r21 * ty + inv_r22 * tz)

    return [
        inv_r00, inv_r01, inv_r02, inv_tx,
        inv_r10, inv_r11, inv_r12, inv_ty,
        inv_r20, inv_r21, inv_r22, inv_tz,
        0.0,     0.0,     0.0,     1.0
    ]


def matrix3d_to_rpy(matrix):
    """Extract Roll-Pitch-Yaw in radians from an adsk.core.Matrix3D."""
    r00 = matrix.getCell(0, 0)
    r01 = matrix.getCell(0, 1)
    r02 = matrix.getCell(0, 2)
    r10 = matrix.getCell(1, 0)
    r11 = matrix.getCell(1, 1)
    r12 = matrix.getCell(1, 2)
    r20 = matrix.getCell(2, 0)
    r21 = matrix.getCell(2, 1)
    r22 = matrix.getCell(2, 2)

    return pure_matrix_to_rpy(r00, r01, r02, r10, r11, r12, r20, r21, r22)


def matrix3d_to_xyz(matrix):
    """Extract translation from adsk.core.Matrix3D, converting cm to meters."""
    if hasattr(matrix, 'translation'):
        # Matrix3D in Fusion API
        return [
            matrix.translation.x * 0.01,
            matrix.translation.y * 0.01,
            matrix.translation.z * 0.01
        ]
    else:
        # Fallback to row-major list [Tx, Ty, Tz at index 3, 7, 11]
        return [matrix[3] * 0.01, matrix[7] * 0.01, matrix[11] * 0.01]


def axes_vectors_to_rpy(x_axis_vec, z_axis_vec):
    """Compute RPY from X and Z direction vectors (right-hand coordinate system).
    
    Y = Z cross X
    """
    # Normalize Z
    len_z = math.sqrt(z_axis_vec.x**2 + z_axis_vec.y**2 + z_axis_vec.z**2)
    zx = z_axis_vec.x / len_z if len_z > 0 else 0.0
    zy = z_axis_vec.y / len_z if len_z > 0 else 0.0
    zz = z_axis_vec.z / len_z if len_z > 0 else 1.0

    # Cross product Y = Z x X
    yx = zy * x_axis_vec.z - zz * x_axis_vec.y
    yy = zz * x_axis_vec.x - zx * x_axis_vec.z
    yz = zx * x_axis_vec.y - zy * x_axis_vec.x

    len_y = math.sqrt(yx**2 + yy**2 + yz**2)
    if len_y > 0:
        yx /= len_y
        yy /= len_y
        yz /= len_y
    else:
        yx, yy, yz = 0.0, 1.0, 0.0

    # Recompute orthonormal X = Y x Z
    xx = yy * zz - yz * zy
    xy = yz * zx - yx * zz
    xz = yx * zy - yy * zx

    return pure_matrix_to_rpy(
        xx, yx, zx,
        xy, yy, zy,
        xz, yz, zz
    )


IDENTITY_16 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0
]


def to_flat_matrix(m):
    """Convert an adsk.core.Matrix3D or 16-element sequence to a 16-element flat list."""
    if m is None:
        return list(IDENTITY_16)
    if isinstance(m, (list, tuple)) and len(m) == 16:
        return [float(x) for x in m]
    if hasattr(m, 'asArray'):
        try:
            return [float(x) for x in m.asArray()]
        except Exception:
            pass
    if hasattr(m, 'getCell'):
        try:
            return [float(m.getCell(r, c)) for r in range(4) for c in range(4)]
        except Exception:
            pass
    return list(IDENTITY_16)


def make_frame_4x4(p, z_vec, x_vec=None):
    """Construct an orthonormal 4x4 row-major matrix from origin p, Z axis, and optional X axis.
    
    p: [px, py, pz]
    z_vec: [zx, zy, zz] (primary axis)
    x_vec: [xx, xy, xz] (secondary axis, optional)
    
    Returns 16-element flat row-major list:
    [Xx, Yx, Zx, Px,
     Xy, Yy, Zy, Py,
     Xz, Yz, Zz, Pz,
      0,  0,  0,  1]
    """
    # Normalize Z
    len_z = math.sqrt(z_vec[0]**2 + z_vec[1]**2 + z_vec[2]**2)
    if len_z > 1e-9:
        zx, zy, zz = z_vec[0] / len_z, z_vec[1] / len_z, z_vec[2] / len_z
    else:
        zx, zy, zz = 0.0, 0.0, 1.0

    # Cross product to find Y = Z x X
    yx, yy, yz = 0.0, 1.0, 0.0
    if x_vec is not None:
        cx = zy * x_vec[2] - zz * x_vec[1]
        cy = zz * x_vec[0] - zx * x_vec[2]
        cz = zx * x_vec[1] - zy * x_vec[0]
        len_c = math.sqrt(cx**2 + cy**2 + cz**2)
        if len_c > 1e-6:
            yx, yy, yz = cx / len_c, cy / len_c, cz / len_c
        else:
            x_vec = None

    if x_vec is None:
        # Fallback reference vector
        ref = (1.0, 0.0, 0.0) if abs(zx) < 0.9 else (0.0, 1.0, 0.0)
        cx = zy * ref[2] - zz * ref[1]
        cy = zz * ref[0] - zx * ref[2]
        cz = zx * ref[1] - zy * ref[0]
        len_c = math.sqrt(cx**2 + cy**2 + cz**2)
        if len_c > 1e-6:
            yx, yy, yz = cx / len_c, cy / len_c, cz / len_c

    # Recompute orthonormal X = Y x Z
    xx = yy * zz - yz * zy
    xy = yz * zx - yx * zz
    xz = yx * zy - yy * zx
    len_x = math.sqrt(xx**2 + xy**2 + xz**2)
    if len_x > 1e-9:
        xx, xy, xz = xx / len_x, xy / len_x, xz / len_x

    return [
        xx, yx, zx, float(p[0]),
        xy, yy, zy, float(p[1]),
        xz, yz, zz, float(p[2]),
        0.0, 0.0, 0.0, 1.0
    ]


def get_world_transform(occ):
    """Compute absolute world transform for an occurrence.
    
    In Fusion 360, occ.transform2 is already defined relative to the root component.
    """
    if not HAS_ADSK or occ is None:
        return None
    try:
        if hasattr(occ, 'transform2') and occ.transform2 is not None:
            return occ.transform2.copy()
        if hasattr(occ, 'transform') and occ.transform is not None:
            return occ.transform.copy()
    except Exception:
        pass
    return None


def get_world_transform_as_list(occ):
    """Get absolute world transform of an occurrence as a 16-element flat list."""
    if occ is None:
        return list(IDENTITY_16)
    mat = get_world_transform(occ)
    if mat is not None:
        return to_flat_matrix(mat)
    if hasattr(occ, 'transform') and occ.transform:
        return to_flat_matrix(occ.transform)
    return list(IDENTITY_16)


def extract_joint_origin_world_frame(jo, occ=None):
    """Extract the 4x4 world coordinate frame (in cm) from a JointOrigin object."""
    if jo is None:
        return None
    try:
        if hasattr(jo, 'transform') and jo.transform is not None:
            mat = to_flat_matrix(jo.transform)
            is_proxy = getattr(jo, 'assemblyContext', None) is not None
            if not is_proxy:
                target_occ = occ or getattr(jo, 'assemblyContext', None)
                if target_occ is not None:
                    occ_mat = get_world_transform_as_list(target_occ)
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
                p_cm = (pt.x, pt.y, pt.z)
                z_vec = (z_axis.x, z_axis.y, z_axis.z) if z_axis else None
                x_vec = (x_axis.x, x_axis.y, x_axis.z) if x_axis else None
                mat = make_frame_4x4(p_cm, z_vec, x_vec)
                is_proxy = getattr(jo, 'assemblyContext', None) is not None
                if not is_proxy:
                    target_occ = occ or getattr(jo, 'assemblyContext', None)
                    if target_occ is not None:
                        occ_mat = get_world_transform_as_list(target_occ)
                        mat = pure_matrix_multiply(occ_mat, mat)
                return mat
    except Exception:
        pass

    return None
