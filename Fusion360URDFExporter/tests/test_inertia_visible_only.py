"""Unit tests for the 'inertia from visible bodies only' option."""

import unittest
from types import SimpleNamespace
from core.inertial_calc import InertialCalculator
from core.kinematic_builder import URDFLink


def make_body(name, mass, com, visible=True):
    return SimpleNamespace(name=name, mass=mass, com=com, isLightBulbOn=visible, _source_occ=None)


class TestInertiaVisibleOnly(unittest.TestCase):
    def setUp(self):
        self.link = URDFLink('link')
        self.link.bodies = [
            make_body('visible', 1.0, [0.0, 0.0, 0.0]),
            make_body('hidden', 1.0, [1.0, 0.0, 0.0], visible=False),
        ]

    def test_all_bodies_by_default(self):
        InertialCalculator().compute_link_inertial(self.link)
        self.assertAlmostEqual(self.link.mass, 2.0)
        self.assertAlmostEqual(self.link.com[0], 0.5)

    def test_visible_only_excludes_hidden_bodies(self):
        InertialCalculator(visible_only=True).compute_link_inertial(self.link)
        self.assertAlmostEqual(self.link.mass, 1.0)
        self.assertAlmostEqual(self.link.com[0], 0.0)

    def test_hidden_parent_component_excluded(self):
        self.link.bodies[0]._source_occ = SimpleNamespace(isLightBulbOn=False)
        InertialCalculator(visible_only=True).compute_link_inertial(self.link)
        # No visible bodies left -> placeholder massless link
        self.assertAlmostEqual(self.link.mass, 0.001)


if __name__ == '__main__':
    unittest.main()
