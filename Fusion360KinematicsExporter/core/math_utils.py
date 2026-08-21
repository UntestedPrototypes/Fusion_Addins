import math

def matrix3d_to_4x4(matrix3d_array: list) -> list:
    """
    Convert Fusion's Matrix3D.asArray() (16 floats row-major: 
    [R00,R01,R02,Tx, R10,R11,R12,Ty, R20,R21,R22,Tz, 0,0,0,1]) to 4x4 list-of-lists.
    """
    return [
        [matrix3d_array[0], matrix3d_array[1], matrix3d_array[2], matrix3d_array[3]],
        [matrix3d_array[4], matrix3d_array[5], matrix3d_array[6], matrix3d_array[7]],
        [matrix3d_array[8], matrix3d_array[9], matrix3d_array[10], matrix3d_array[11]],
        [matrix3d_array[12], matrix3d_array[13], matrix3d_array[14], matrix3d_array[15]]
    ]

def identity_4x4() -> list:
    """Return a 4x4 identity matrix."""
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0]
    ]

def extract_rotation_3x3(m4x4: list) -> list:
    """Get the 3x3 rotation submatrix from a 4x4 transformation matrix."""
    return [
        [m4x4[0][0], m4x4[0][1], m4x4[0][2]],
        [m4x4[1][0], m4x4[1][1], m4x4[1][2]],
        [m4x4[2][0], m4x4[2][1], m4x4[2][2]]
    ]

def extract_translation(m4x4: list) -> tuple:
    """Get the (tx, ty, tz) translation from a 4x4 transformation matrix."""
    return (m4x4[0][3], m4x4[1][3], m4x4[2][3])

def transpose_3x3(r: list) -> list:
    """Return the transpose of a 3x3 matrix."""
    return [
        [r[0][0], r[1][0], r[2][0]],
        [r[0][1], r[1][1], r[2][1]],
        [r[0][2], r[1][2], r[2][2]]
    ]

def multiply_4x4(a: list, b: list) -> list:
    """Multiply two 4x4 matrices: a * b."""
    result = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            for k in range(4):
                result[i][j] += a[i][k] * b[k][j]
    return result

def invert_4x4(m: list) -> list:
    """
    Compute the inverse of a 4x4 affine transformation matrix.
    Assumes the bottom row is [0, 0, 0, 1].
    """
    R = extract_rotation_3x3(m)
    t = extract_translation(m)
    Rt = transpose_3x3(R)
    
    # -R^T * t
    tx = -(Rt[0][0]*t[0] + Rt[0][1]*t[1] + Rt[0][2]*t[2])
    ty = -(Rt[1][0]*t[0] + Rt[1][1]*t[1] + Rt[1][2]*t[2])
    tz = -(Rt[2][0]*t[0] + Rt[2][1]*t[1] + Rt[2][2]*t[2])
    
    return [
        [Rt[0][0], Rt[0][1], Rt[0][2], tx],
        [Rt[1][0], Rt[1][1], Rt[1][2], ty],
        [Rt[2][0], Rt[2][1], Rt[2][2], tz],
        [0.0, 0.0, 0.0, 1.0]
    ]

def rotation_to_rpy(R: list) -> tuple:
    """
    Convert a 3x3 rotation matrix to (roll, pitch, yaw) angles using the 
    extrinsic XYZ convention (standard for URDF).
    Handles gimbal lock when pitch is close to +/- pi/2.
    """
    sy = math.sqrt(R[0][0] * R[0][0] + R[1][0] * R[1][0])
    singular = sy < 1e-6
    
    if not singular:
        x = math.atan2(R[2][1], R[2][2])
        y = math.atan2(-R[2][0], sy)
        z = math.atan2(R[1][0], R[0][0])
    else:
        x = math.atan2(-R[1][2], R[1][1])
        y = math.atan2(-R[2][0], sy)
        z = 0.0
        
    return (x, y, z)

def rpy_to_rotation(roll: float, pitch: float, yaw: float) -> list:
    """Convert (roll, pitch, yaw) using extrinsic XYZ to a 3x3 rotation matrix."""
    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)
    
    Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    
    def matmul3(a, b):
        res = [[0.0]*3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    res[i][j] += a[i][k] * b[k][j]
        return res
    
    return matmul3(matmul3(Rz, Ry), Rx)

def cross(a: tuple, b: tuple) -> tuple:
    """Compute the cross product of two 3D vectors."""
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    )

def dot(a: tuple, b: tuple) -> float:
    """Compute the dot product of two 3D vectors."""
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def magnitude(v: tuple) -> float:
    """Compute the magnitude (length) of a 3D vector."""
    return math.sqrt(dot(v, v))

def normalize(v: tuple) -> tuple:
    """Return a normalized (unit) vector. Returns (0,0,0) if magnitude is 0."""
    mag = magnitude(v)
    if mag < 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0]/mag, v[1]/mag, v[2]/mag)

def vec_sub(a: tuple, b: tuple) -> tuple:
    """Subtract vector b from vector a: a - b."""
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def vec_add(a: tuple, b: tuple) -> tuple:
    """Add vector a and vector b: a + b."""
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

def vec_scale(v: tuple, s: float) -> tuple:
    """Scale a vector by a scalar: v * s."""
    return (v[0]*s, v[1]*s, v[2]*s)

def transform_point(T: list, p: tuple) -> tuple:
    """Apply a 4x4 transformation matrix to a 3D point."""
    return (
        T[0][0]*p[0] + T[0][1]*p[1] + T[0][2]*p[2] + T[0][3],
        T[1][0]*p[0] + T[1][1]*p[1] + T[1][2]*p[2] + T[1][3],
        T[2][0]*p[0] + T[2][1]*p[1] + T[2][2]*p[2] + T[2][3]
    )

def transform_vector(T: list, v: tuple) -> tuple:
    """Apply the rotation part of a 4x4 matrix to a 3D direction vector."""
    return (
        T[0][0]*v[0] + T[0][1]*v[1] + T[0][2]*v[2],
        T[1][0]*v[0] + T[1][1]*v[1] + T[1][2]*v[2],
        T[2][0]*v[0] + T[2][1]*v[1] + T[2][2]*v[2]
    )

def make_transform(R: list, t: tuple) -> list:
    """Compose a 3x3 rotation matrix and a translation tuple into a 4x4 matrix."""
    return [
        [R[0][0], R[0][1], R[0][2], t[0]],
        [R[1][0], R[1][1], R[1][2], t[1]],
        [R[2][0], R[2][1], R[2][2], t[2]],
        [0.0, 0.0, 0.0, 1.0]
    ]

def cm_to_m(val: float) -> float:
    """Convert centimeters to meters (multiply by 0.01)."""
    return val * 0.01

def cm_to_m_tuple(t: tuple) -> tuple:
    """Convert a 3D tuple from centimeters to meters."""
    return (t[0]*0.01, t[1]*0.01, t[2]*0.01)

def clamp_inertia(val: float, minimum: float = 1e-6) -> float:
    """Clamp small inertia values to a minimum threshold."""
    return val if val > minimum else minimum
