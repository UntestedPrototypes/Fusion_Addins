"""Unit tests for joint limits relative to the exported (current/rest) joint position."""

import math
import unittest
from types import SimpleNamespace
from core.joint_analyzer import JointAnalyzer, JointInfo
from config.defaults import DEFAULT_REVOLUTE_LIMITS, JOINT_TYPE_REVOLUTE, JOINT_TYPE_PRISMATIC


def make_limits(min_val=None, max_val=None):
    return SimpleNamespace(
        isMinimumValueEnabled=min_val is not None,
        isMaximumValueEnabled=max_val is not None,
        minimumValue=min_val or 0.0,
        maximumValue=max_val or 0.0,
    )


class TestJointLimitsRestPose(unittest.TestCase):
    def setUp(self):
        self.analyzer = JointAnalyzer(None)

    def _revolute(self, lims, rotation_value):
        info = JointInfo()
        info.joint_type = JOINT_TYPE_REVOLUTE
        motion = SimpleNamespace(rotationLimits=lims, rotationValue=rotation_value)
        self.analyzer._extract_limits(motion, info)
        return info

    def test_revolute_at_zero_unchanged(self):
        info = self._revolute(make_limits(-math.pi / 2, math.pi / 2), 0.0)
        self.assertAlmostEqual(info.limit_lower, -math.pi / 2)
        self.assertAlmostEqual(info.limit_upper, math.pi / 2)

    def test_revolute_shifted_by_rest_angle(self):
        # Fusion range [-90, 90] deg, joint exported at rest angle 30 deg -> URDF [-120, 60] deg
        info = self._revolute(make_limits(-math.pi / 2, math.pi / 2), math.radians(30))
        self.assertAlmostEqual(info.limit_lower, math.radians(-120))
        self.assertAlmostEqual(info.limit_upper, math.radians(60))

    def test_revolute_disabled_side_uses_default(self):
        info = self._revolute(make_limits(None, math.pi / 2), math.radians(30))
        self.assertAlmostEqual(info.limit_lower, DEFAULT_REVOLUTE_LIMITS['lower'])
        self.assertAlmostEqual(info.limit_upper, math.radians(60))

    def test_prismatic_shifted_and_converted_to_meters(self):
        # Fusion range [0, 10] cm, joint exported at 4 cm -> URDF [-0.04, 0.06] m
        info = JointInfo()
        info.joint_type = JOINT_TYPE_PRISMATIC
        motion = SimpleNamespace(slideLimits=make_limits(0.0, 10.0), slideValue=4.0)
        motion.slideLimits.isMinimumValueEnabled = True
        self.analyzer._extract_limits(motion, info)
        self.assertAlmostEqual(info.limit_lower, -0.04)
        self.assertAlmostEqual(info.limit_upper, 0.06)


if __name__ == '__main__':
    unittest.main()
