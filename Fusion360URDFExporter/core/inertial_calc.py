"""Inertial properties calculation for URDF links.

Computes combined mass, center of mass, and moments of inertia using
high-accuracy physics evaluation and the parallel axis theorem.
"""

from config.defaults import CM_TO_M, KG_CM2_TO_KG_M2
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


class InertialCalculator:
    """Computes mass properties and aggregates inertia tensors for URDF links."""

    def compute_link_inertial(self, link, link_world_transform=None):
        """Compute aggregate mass, CoM, and 3D inertia tensor for all bodies in a link.
        
        Args:
            link (URDFLink): The link to calculate.
            link_world_transform (sequence or Matrix3D, optional): Transform of the link frame.
        """
        if not link.bodies:
            # Massless / virtual link
            link.mass = 0.001
            link.com = [0.0, 0.0, 0.0]
            link.inertia = {
                'ixx': 1e-6, 'ixy': 0.0, 'ixz': 0.0,
                'iyy': 1e-6, 'iyz': 0.0, 'izz': 1e-6
            }
            return

        body_data = []
        total_mass = 0.0
        weighted_com = [0.0, 0.0, 0.0]

        T_link = to_flat_matrix(link_world_transform)
        T_link_inv = pure_matrix_invert(T_link)

        for body in link.bodies:
            occ = getattr(body, '_source_occ', getattr(body, 'assemblyContext', None))
            body_world = get_world_transform_as_list(occ) if occ else list(IDENTITY_16)

            # Compute relative transform from body local frame to link local frame
            body_to_link = pure_matrix_multiply(T_link_inv, body_world)

            m, com_link, i_tensor = self._get_body_properties(body, body_to_link)
            if m > 0:
                total_mass += m
                weighted_com[0] += m * com_link[0]
                weighted_com[1] += m * com_link[1]
                weighted_com[2] += m * com_link[2]
                body_data.append((m, com_link, i_tensor))

        if total_mass > 1e-9:
            combined_com = [
                weighted_com[0] / total_mass,
                weighted_com[1] / total_mass,
                weighted_com[2] / total_mass
            ]
            link.mass = total_mass
            link.com = combined_com
            link.inertia = self._aggregate_inertia(body_data, combined_com)
        else:
            link.mass = 0.001
            link.com = [0.0, 0.0, 0.0]
            link.inertia = {
                'ixx': 1e-6, 'ixy': 0.0, 'ixz': 0.0,
                'iyy': 1e-6, 'iyz': 0.0, 'izz': 1e-6
            }

    def _get_body_properties(self, body, body_to_link):
        """Extract mass, CoM in link frame, and inertia tensor from a body."""
        if not HAS_ADSK:
            # Mock fallback if called during unit testing
            m = getattr(body, 'mass', 1.0)
            com = getattr(body, 'com', [0.0, 0.0, 0.0])
            inertia = getattr(body, 'inertia', {
                'ixx': 0.001, 'ixy': 0.0, 'ixz': 0.0,
                'iyy': 0.001, 'iyz': 0.0, 'izz': 0.001
            })
            return m, com, inertia

        try:
            acc = adsk.fusion.CalculationAccuracy.HighCalculationAccuracy
            props = body.getPhysicalProperties(acc)

            mass = props.mass  # kg
            raw_com = props.centerOfMass  # Point3D in cm

            m = body_to_link or IDENTITY_16
            is_identity = (m == IDENTITY_16)

            if not is_identity:
                px = m[0] * raw_com.x + m[1] * raw_com.y + m[2] * raw_com.z + m[3]
                py = m[4] * raw_com.x + m[5] * raw_com.y + m[6] * raw_com.z + m[7]
                pz = m[8] * raw_com.x + m[9] * raw_com.y + m[10] * raw_com.z + m[11]
                com_m = [px * CM_TO_M, py * CM_TO_M, pz * CM_TO_M]
            else:
                com_m = [raw_com.x * CM_TO_M, raw_com.y * CM_TO_M, raw_com.z * CM_TO_M]

            # Inertia moments about CoM in kg*cm^2
            res = props.getXYZMomentsOfInertia()
            if len(res) == 7:
                _, ixx, iyy, izz, ixy, iyz, ixz = res
            else:
                ixx, iyy, izz, ixy, iyz, ixz = res

            if not is_identity:
                R = [
                    [m[0], m[1], m[2]],
                    [m[4], m[5], m[6]],
                    [m[8], m[9], m[10]]
                ]
                I_mat = [
                    [ixx * KG_CM2_TO_KG_M2, ixy * KG_CM2_TO_KG_M2, ixz * KG_CM2_TO_KG_M2],
                    [ixy * KG_CM2_TO_KG_M2, iyy * KG_CM2_TO_KG_M2, iyz * KG_CM2_TO_KG_M2],
                    [ixz * KG_CM2_TO_KG_M2, iyz * KG_CM2_TO_KG_M2, izz * KG_CM2_TO_KG_M2]
                ]
                RI = [[sum(R[r][k] * I_mat[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
                I_rot = [[sum(RI[r][k] * R[c][k] for k in range(3)) for c in range(3)] for r in range(3)]
                tensor = {
                    'ixx': max(I_rot[0][0], 1e-9),
                    'iyy': max(I_rot[1][1], 1e-9),
                    'izz': max(I_rot[2][2], 1e-9),
                    'ixy': I_rot[0][1],
                    'iyz': I_rot[1][2],
                    'ixz': I_rot[0][2]
                }
            else:
                tensor = {
                    'ixx': max(ixx * KG_CM2_TO_KG_M2, 1e-9),
                    'iyy': max(iyy * KG_CM2_TO_KG_M2, 1e-9),
                    'izz': max(izz * KG_CM2_TO_KG_M2, 1e-9),
                    'ixy': ixy * KG_CM2_TO_KG_M2,
                    'iyz': iyz * KG_CM2_TO_KG_M2,
                    'ixz': ixz * KG_CM2_TO_KG_M2
                }
            return mass, com_m, tensor

        except:
            return 0.001, [0.0, 0.0, 0.0], {
                'ixx': 1e-6, 'ixy': 0.0, 'ixz': 0.0,
                'iyy': 1e-6, 'iyz': 0.0, 'izz': 1e-6
            }

    def _aggregate_inertia(self, body_data, combined_com):
        """Combine multiple inertia tensors using the parallel axis theorem.
        
        I_comb = sum( I_body + m * ((d.d)*E - d*d^T) )
        where d = com_body - combined_com
        """
        Ixx = Iyy = Izz = 0.0
        Ixy = Iyz = Ixz = 0.0

        for mass, b_com, tensor in body_data:
            dx = b_com[0] - combined_com[0]
            dy = b_com[1] - combined_com[1]
            dz = b_com[2] - combined_com[2]

            Ixx += tensor['ixx'] + mass * (dy * dy + dz * dz)
            Iyy += tensor['iyy'] + mass * (dx * dx + dz * dz)
            Izz += tensor['izz'] + mass * (dx * dx + dy * dy)

            Ixy += tensor['ixy'] - mass * (dx * dy)
            Ixz += tensor['ixz'] - mass * (dx * dz)
            Iyz += tensor['iyz'] - mass * (dy * dz)

        # Enforce physical sanity (positive diagonals)
        Ixx = max(Ixx, 1e-9)
        Iyy = max(Iyy, 1e-9)
        Izz = max(Izz, 1e-9)

        return {
            'ixx': Ixx, 'ixy': Ixy, 'ixz': Ixz,
            'iyy': Iyy, 'iyz': Iyz, 'izz': Izz
        }
