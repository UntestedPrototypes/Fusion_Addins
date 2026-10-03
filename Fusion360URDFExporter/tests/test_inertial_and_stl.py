"""Tests for inertial physics calculation, binary STL output, and transform math."""

import unittest
import os
import struct
import tempfile
import math
from core.inertial_calc import InertialCalculator
from core.kinematic_builder import URDFLink
from core.mesh_exporter import write_binary_stl, parse_stl_file, MeshExporter
from core.transform_utils import (
    pure_matrix_to_rpy,
    pure_matrix_invert,
    pure_matrix_multiply
)


class MockBodyPhys:
    def __init__(self, mass, com, inertia):
        self.mass = mass
        self.com = com
        self.inertia = inertia


class TestInertialAndSTL(unittest.TestCase):
    def test_inertial_parallel_axis_aggregation(self):
        """Test parallel axis theorem for two symmetric bodies."""
        # Two identical point-like masses of 1.0 kg at (+0.1, 0, 0) and (-0.1, 0, 0)
        # Combined CoM must be (0, 0, 0)
        # Offset d = 0.1 m along X
        # For point mass along X:
        # Ixx offset = m * (dy^2 + dz^2) = 0
        # Iyy offset = m * (dx^2 + dz^2) = 1.0 * (0.1^2) = 0.01 kg*m^2 per body -> 0.02 total
        # Izz offset = m * (dx^2 + dy^2) = 1.0 * (0.1^2) = 0.01 kg*m^2 per body -> 0.02 total
        b1 = MockBodyPhys(
            mass=1.0,
            com=[0.1, 0.0, 0.0],
            inertia={'ixx': 0.001, 'ixy': 0.0, 'ixz': 0.0, 'iyy': 0.001, 'iyz': 0.0, 'izz': 0.001}
        )
        b2 = MockBodyPhys(
            mass=1.0,
            com=[-0.1, 0.0, 0.0],
            inertia={'ixx': 0.001, 'ixy': 0.0, 'ixz': 0.0, 'iyy': 0.001, 'iyz': 0.0, 'izz': 0.001}
        )

        link = URDFLink('test_link')
        link.bodies = [b1, b2]

        calc = InertialCalculator()
        calc.compute_link_inertial(link)

        self.assertAlmostEqual(link.mass, 2.0)
        self.assertAlmostEqual(link.com[0], 0.0)
        self.assertAlmostEqual(link.com[1], 0.0)
        self.assertAlmostEqual(link.com[2], 0.0)

        # Ixx should be 0.001 + 0.001 = 0.002
        self.assertAlmostEqual(link.inertia['ixx'], 0.002, places=4)
        # Iyy should be 0.002 + 0.02 = 0.022
        self.assertAlmostEqual(link.inertia['iyy'], 0.022, places=4)
        # Izz should be 0.002 + 0.02 = 0.022
        self.assertAlmostEqual(link.inertia['izz'], 0.022, places=4)

    def test_binary_stl_generation(self):
        """Test writing and parsing of binary STL file format."""
        triangles = [
            # ((nx, ny, nz), (v0), (v1), (v2))
            ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        ]

        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            write_binary_stl(tmp_path, triangles)

            file_size = os.path.getsize(tmp_path)
            # Binary STL size formula: 80 bytes header + 4 bytes count + N * 50 bytes
            expected_size = 80 + 4 + len(triangles) * 50
            self.assertEqual(file_size, expected_size)

            with open(tmp_path, 'rb') as f:
                header = f.read(80)
                self.assertEqual(len(header), 80)
                num_triangles = struct.unpack('<I', f.read(4))[0]
                self.assertEqual(num_triangles, 2)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_transform_matrix_invert_and_rpy(self):
        """Test pure matrix invert and RPY extraction."""
        # 90 degrees around Z axis:
        # cos(90) = 0, sin(90) = 1
        r00, r01, r02 = 0.0, -1.0, 0.0
        r10, r11, r12 = 1.0, 0.0, 0.0
        r20, r21, r22 = 0.0, 0.0, 1.0

        roll, pitch, yaw = pure_matrix_to_rpy(r00, r01, r02, r10, r11, r12, r20, r21, r22)
        self.assertAlmostEqual(roll, 0.0)
        self.assertAlmostEqual(pitch, 0.0)
        self.assertAlmostEqual(yaw, math.pi / 2.0, places=5)

        # Invert affine matrix with translation
        mat = [
            1.0, 0.0, 0.0, 10.0,
            0.0, 1.0, 0.0, 20.0,
            0.0, 0.0, 1.0, 30.0,
            0.0, 0.0, 0.0, 1.0
        ]
        inv = pure_matrix_invert(mat)
        self.assertAlmostEqual(inv[3], -10.0)
        self.assertAlmostEqual(inv[7], -20.0)
        self.assertAlmostEqual(inv[11], -30.0)

    def test_stl_parse_and_roundtrip(self):
        """Test parse_stl_file correctly parses binary STL written by write_binary_stl."""
        triangles = [
            ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 1.0, 0.0), (1.0, 1.0, 1.0), (2.0, 1.0, 1.0), (1.0, 2.0, 1.0)),
        ]
        with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            write_binary_stl(tmp_path, triangles)
            parsed = parse_stl_file(tmp_path)
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0][1], (0.0, 0.0, 0.0))
            self.assertEqual(parsed[0][2], (1.0, 0.0, 0.0))
            self.assertEqual(parsed[1][1], (1.0, 1.0, 1.0))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_mesh_triangle_transformation(self):
        """Test _transform_triangles scales mm to meters and applies 4x4 matrix offset."""
        exporter = MeshExporter(design=None, output_dir=tempfile.gettempdir())
        raw_triangles = [
            ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0)),
        ]
        # Body is in mm: units_to_cm = 0.1 (100 mm = 10 cm = 0.1 m)
        # Translation offset in cm: +5.0 cm along X
        # Expected X of (100 mm): (10 cm + 5 cm) = 15 cm = 0.15 m
        body_to_link = [
            1.0, 0.0, 0.0, 5.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0
        ]
        transformed = exporter._transform_triangles(raw_triangles, body_to_link, units_to_cm=0.1)
        self.assertEqual(len(transformed), 1)
        norm, v0, v1, v2 = transformed[0]

        # v0 was (0, 0, 0) -> +5 cm along X = 0.05 m
        self.assertAlmostEqual(v0[0], 0.05, places=5)
        self.assertAlmostEqual(v0[1], 0.0, places=5)
        self.assertAlmostEqual(v0[2], 0.0, places=5)

        # v1 was (100 mm, 0, 0) = 10 cm -> +5 cm = 15 cm = 0.15 m
        self.assertAlmostEqual(v1[0], 0.15, places=5)
        self.assertAlmostEqual(v1[1], 0.0, places=5)
        self.assertAlmostEqual(v1[2], 0.0, places=5)


if __name__ == '__main__':
    unittest.main()
