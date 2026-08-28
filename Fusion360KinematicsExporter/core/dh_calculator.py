import math
from . import math_utils
# Using try/except to gracefully handle partial imports during development
try:
    from . import DHParameter, KinematicChain
except ImportError:
    # Fallbacks in case __init__ does not export these properly or it is run stand-alone
    class DHParameter:
        def __init__(self, joint_name, joint_type, a, alpha, d, theta_offset, limit_min, limit_max):
            self.joint_name = joint_name
            self.joint_type = joint_type
            self.a = a
            self.alpha = alpha
            self.d = d
            self.theta_offset = theta_offset
            self.limit_min = limit_min
            self.limit_max = limit_max
    
    class KinematicChain:
        pass


def _compute_standard_dh_raw(joint_positions: list, joint_axes: list, joint_names: list, joint_types: list, joint_limits: list) -> list:
    """
    Computes Standard Denavit-Hartenberg parameters for a serial kinematic chain.
    Internal function that works with raw lists.
    """
    dh_params = []
    eps = 1e-10
    
    n = len(joint_positions)
    if n < 2:
        # Single joint: return one DH entry with zero geometry
        if n == 1:
            dh = DHParameter(
                joint_name=joint_names[0],
                joint_type=joint_types[0],
                a=0.0, alpha=0.0, d=0.0, theta_offset=0.0,
                limit_min=joint_limits[0][0] if joint_limits[0] else -3.14159,
                limit_max=joint_limits[0][1] if joint_limits[0] else 3.14159
            )
            dh_params.append(dh)
        return dh_params
        
    X_axes = []
    
    # First, we define X_0. Since there's no previous joint for joint 0, we'll arbitrarily pick an orthogonal vector
    Z_0 = math_utils.normalize(joint_axes[0])
    if abs(Z_0[0]) < 0.9:
        X_0 = math_utils.normalize(math_utils.cross(Z_0, (1.0, 0.0, 0.0)))
    else:
        X_0 = math_utils.normalize(math_utils.cross(Z_0, (0.0, 1.0, 0.0)))
    X_axes.append(X_0)
    
    for i in range(1, n):
        Z_prev = math_utils.normalize(joint_axes[i-1])
        Z_curr = math_utils.normalize(joint_axes[i])
        P_prev = joint_positions[i-1]
        P_curr = joint_positions[i]
        
        # a. Common normal
        cross_Z = math_utils.cross(Z_prev, Z_curr)
        mag_cross = math_utils.magnitude(cross_Z)
        
        if mag_cross > eps:
            # d. Intersecting or skew axes
            X_i = math_utils.normalize(cross_Z)
        else:
            # b. Parallel axes or c. Collinear axes
            diff_P = math_utils.vec_sub(P_curr, P_prev)
            dot_diff_Z = math_utils.dot(diff_P, Z_prev)
            proj_P = math_utils.vec_add(P_prev, math_utils.vec_scale(Z_prev, dot_diff_Z))
            vec_to_curr = math_utils.vec_sub(P_curr, proj_P)
            mag_vec = math_utils.magnitude(vec_to_curr)
            
            if mag_vec > eps:
                # Parallel axes
                X_i = math_utils.normalize(vec_to_curr)
            else:
                # Collinear axes
                X_i = X_axes[-1]
                
        X_axes.append(X_i)
        
        # e. Compute a_i
        diff_P_i = math_utils.vec_sub(P_curr, P_prev)
        a_i = math_utils.dot(diff_P_i, X_i)
        
        # f. Compute alpha_i
        cross_Z_prev_curr = math_utils.cross(Z_prev, Z_curr)
        dot_Z_prev_curr = math_utils.dot(Z_prev, Z_curr)
        alpha_i = math.atan2(math_utils.dot(cross_Z_prev_curr, X_i), dot_Z_prev_curr)
        
        # g. Compute d_i
        d_i = math_utils.dot(diff_P_i, Z_prev)
        
        # h. Compute theta_offset_i
        cross_X_prev_curr = math_utils.cross(X_axes[i-1], X_i)
        dot_X_prev_curr = math_utils.dot(X_axes[i-1], X_i)
        theta_offset_i = math.atan2(math_utils.dot(cross_X_prev_curr, Z_prev), dot_X_prev_curr)
        
        dh = DHParameter(
            joint_name=joint_names[i],
            joint_type=joint_types[i],
            a=a_i,
            alpha=alpha_i,
            d=d_i,
            theta_offset=theta_offset_i,
            limit_min=joint_limits[i][0] if joint_limits[i] else -3.14159,
            limit_max=joint_limits[i][1] if joint_limits[i] else 3.14159
        )
        dh_params.append(dh)
        
    return dh_params

def _compute_modified_dh_raw(joint_positions: list, joint_axes: list, joint_names: list, joint_types: list, joint_limits: list) -> list:
    """
    Computes Modified Denavit-Hartenberg parameters (Craig convention).
    Internal function that works with raw lists.
    """
    dh_params = []
    eps = 1e-10
    
    n = len(joint_positions)
    if n < 2:
        return dh_params
        
    X_axes = []
    
    Z_0 = math_utils.normalize(joint_axes[0])
    if abs(Z_0[0]) < 0.9:
        X_0 = math_utils.normalize(math_utils.cross(Z_0, (1.0, 0.0, 0.0)))
    else:
        X_0 = math_utils.normalize(math_utils.cross(Z_0, (0.0, 1.0, 0.0)))
    X_axes.append(X_0)
    
    for i in range(1, n):
        Z_prev = math_utils.normalize(joint_axes[i-1])
        Z_curr = math_utils.normalize(joint_axes[i])
        P_prev = joint_positions[i-1]
        P_curr = joint_positions[i]
        
        cross_Z = math_utils.cross(Z_prev, Z_curr)
        mag_cross = math_utils.magnitude(cross_Z)
        
        if mag_cross > eps:
            X_i = math_utils.normalize(cross_Z)
        else:
            diff_P = math_utils.vec_sub(P_curr, P_prev)
            dot_diff_Z = math_utils.dot(diff_P, Z_prev)
            proj_P = math_utils.vec_add(P_prev, math_utils.vec_scale(Z_prev, dot_diff_Z))
            vec_to_curr = math_utils.vec_sub(P_curr, proj_P)
            mag_vec = math_utils.magnitude(vec_to_curr)
            
            if mag_vec > eps:
                X_i = math_utils.normalize(vec_to_curr)
            else:
                X_i = X_axes[-1]
                
        X_axes.append(X_i)
        
        # Modified DH shifts the parameters
        diff_P_i = math_utils.vec_sub(P_curr, P_prev)
        a_i_minus_1 = math_utils.dot(diff_P_i, X_axes[i-1])
        
        cross_Z_prev_curr = math_utils.cross(Z_prev, Z_curr)
        dot_Z_prev_curr = math_utils.dot(Z_prev, Z_curr)
        alpha_i_minus_1 = math.atan2(math_utils.dot(cross_Z_prev_curr, X_axes[i-1]), dot_Z_prev_curr)
        
        d_i = math_utils.dot(diff_P_i, Z_curr)
        
        cross_X_prev_curr = math_utils.cross(X_axes[i-1], X_i)
        dot_X_prev_curr = math_utils.dot(X_axes[i-1], X_i)
        theta_offset_i = math.atan2(math_utils.dot(cross_X_prev_curr, Z_curr), dot_X_prev_curr)
        
        dh = DHParameter(
            joint_name=joint_names[i],
            joint_type=joint_types[i],
            a=a_i_minus_1,
            alpha=alpha_i_minus_1,
            d=d_i,
            theta_offset=theta_offset_i,
            limit_min=joint_limits[i][0] if joint_limits[i] else 0.0,
            limit_max=joint_limits[i][1] if joint_limits[i] else 0.0
        )
        dh_params.append(dh)
        
    return dh_params


def _extract_chain_data(robot_model, chain):
    """
    Extract joint positions, axes, names, types, and limits from a RobotModel
    and KinematicChain for DH computation.
    """
    joint_positions = []
    joint_axes = []
    joint_names = []
    joint_types = []
    joint_limits = []

    # Build a lookup from joint name to JointData
    joint_lookup = {j.name: j for j in robot_model.joints}

    for jname in chain.joint_names:
        jd = joint_lookup.get(jname)
        if jd is None:
            continue
        # Use the joint origin in parent frame as position proxy (world-space approximation)
        # For DH, we ideally want world-space joint positions.
        # The origin_xyz is in parent frame — we need to accumulate transforms.
        # For now use the child link's world transform origin as the joint position.
        child_link = robot_model.links.get(jd.child_link)
        if child_link and child_link.world_transform:
            pos = math_utils.extract_translation(child_link.world_transform)
            # Convert from cm to m if not already (transforms from Fusion are in cm)
            joint_positions.append((pos[0] * 0.01, pos[1] * 0.01, pos[2] * 0.01))
        else:
            joint_positions.append(jd.origin_xyz)

        joint_axes.append(jd.axis)
        joint_names.append(jd.name)
        joint_types.append(jd.joint_type)
        if jd.has_limits:
            joint_limits.append((jd.limit_lower, jd.limit_upper))
        else:
            joint_limits.append((-3.14159, 3.14159))

    return joint_positions, joint_axes, joint_names, joint_types, joint_limits


def compute_standard_dh(robot_model, chain):
    """
    Compute Standard DH parameters for a kinematic chain.
    
    Args:
        robot_model: RobotModel with links and joints
        chain: KinematicChain identifying which joints form this chain
    
    Returns:
        List of DHParameter objects (Standard convention)
    """
    positions, axes, names, types, limits = _extract_chain_data(robot_model, chain)
    return _compute_standard_dh_raw(positions, axes, names, types, limits)


def compute_modified_dh(robot_model, chain):
    """
    Compute Modified DH (Craig convention) parameters for a kinematic chain.
    
    Args:
        robot_model: RobotModel with links and joints
        chain: KinematicChain identifying which joints form this chain
    
    Returns:
        List of DHParameter objects (Modified convention)
    """
    positions, axes, names, types, limits = _extract_chain_data(robot_model, chain)
    return _compute_modified_dh_raw(positions, axes, names, types, limits)

def compute_dh_transform_standard(dh: DHParameter, q: float = 0.0) -> list:
    """
    Compute the 4x4 homogeneous transform for a single Standard DH parameter row.
    """
    if dh.joint_type == 'prismatic':
        theta = dh.theta_offset
        d = dh.d + q
    else: # revolute or fixed
        theta = dh.theta_offset + q
        d = dh.d
        
    ct = math.cos(theta)
    st = math.sin(theta)
    ca = math.cos(dh.alpha)
    sa = math.sin(dh.alpha)
    a = dh.a
    
    return [
        [ct, -st*ca,  st*sa, a*ct],
        [st,  ct*ca, -ct*sa, a*st],
        [0,   sa,     ca,    d],
        [0,   0,      0,     1]
    ]

def compute_dh_transform_modified(dh: DHParameter, q: float = 0.0) -> list:
    """
    Compute the 4x4 homogeneous transform for a single Modified DH parameter row.
    """
    if dh.joint_type == 'prismatic':
        theta = dh.theta_offset
        d = dh.d + q
    else: # revolute or fixed
        theta = dh.theta_offset + q
        d = dh.d
        
    ct = math.cos(theta)
    st = math.sin(theta)
    ca = math.cos(dh.alpha)
    sa = math.sin(dh.alpha)
    a = dh.a
    
    return [
        [ct,        -st,        0,      a],
        [st*ca,      ct*ca,    -sa,    -d*sa],
        [st*sa,      ct*sa,     ca,     d*ca],
        [0,          0,         0,      1]
    ]

def verify_dh_fk(dh_params: list, joint_positions: list, convention: str = 'standard') -> float:
    """
    Verify the DH parameters by computing forward kinematics and comparing end-effector
    position to actual target position. Returns position error in meters (or whatever unit was passed in).
    """
    if not dh_params or len(joint_positions) < 2:
        return 0.0
        
    T = math_utils.identity_4x4()
    
    for dh in dh_params:
        if convention == 'standard':
            T_i = compute_dh_transform_standard(dh, 0.0)
        else:
            T_i = compute_dh_transform_modified(dh, 0.0)
        T = math_utils.multiply_4x4(T, T_i)
        
    # The start is joint_positions[0], but the DH usually represents transforms starting from the first frame.
    # A full strict evaluation would involve mapping the world frame. 
    # For a simple local check, we just check relative displacement.
    # To properly implement FK error in world space, we'd multiply by an initial root transform.
    # We will approximate this by checking length or if absolute frame is matched.
    
    # Calculate difference between T translation and final joint position.
    final_pos = math_utils.extract_translation(T)
    
    # Calculate distance to last joint position, adjusting for the base offset
    # If the first joint is at origin, then final_pos should match joint_positions[-1].
    # Otherwise, it might be offset.
    
    # Let's do a simple Euclidean distance as error heuristic (might need base transform offset).
    diff = math_utils.vec_sub(final_pos, joint_positions[-1])
    error = math_utils.magnitude(diff)
    
    return error
