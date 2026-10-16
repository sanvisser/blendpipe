"""Geometry: closed shapes face outwards, open ones stay open, placement and mirroring keep faces outwards."""
import random
import unittest

from blendpipe import geo


CLOSED = {
    "box": lambda: geo.box((1, 2, 3), (1, 0, 0), (10, 20, 30)),
    "box_taper": lambda: geo.box((1, 1, 1), taper=(0.5, 0.7)),
    "box_between": lambda: geo.box_between((0, 0, 0), (1, 2, 3)),
    "lathe": lambda: geo.lathe([(0, 0), (1, 0), (1, 1), (0.5, 1.5), (0, 1.6)], 10),
    "lathe_oval_square": lambda: geo.lathe([(1, 0), (1, 1)], 12, ry=0.5, power=4),
    "cylinder": lambda: geo.cylinder(0.5, 2, 12, loc=(1, 2, 3), rot=(90, 0, 0)),
    "frustum": lambda: geo.cylinder(0.5, 2, 12, r_top=0.2),
    "cone": lambda: geo.cone(1, 2, 8),
    "ball": lambda: geo.ball(1, 10, 6, scale=(1, 2, 0.5)),
    "torus": lambda: geo.torus(1, 0.2, 12, 6, rot=(30, 0, 0)),
    "limb": lambda: geo.limb((0, 0, 0), (0.3, 0.2, 1), 0.1, 0.05, 6),
    "limb_oval": lambda: geo.limb((0, 0, 0), (0, -1, 0), 0.1, 0.05, 8, rya=0.5, ryb=1.5),
    "lump": lambda: geo.lump(1, rng=random.Random(3), jitter=0.2, subdiv=1, flat_bottom=-0.5),
    "slab": lambda: geo.slab([(-1, 0), (1, 0), (1, 1), (0, 1.5), (-1, 1)], 0.1, bevel=0.2),
    "fin": lambda: geo.fin([(0, 0), (1, 0), (0.5, 1)], 0.01),
    "strip": lambda: geo.strip([(0, 0, 0), (1, 0, 0.2), (2, 0, 0)], 0.1, 0.02),
    "tube": lambda: geo.tube(geo.smooth_path([(0, 0, 0), (0, 0, 1), (1, 0, 2)], 4), [0.1] * 9, 8),
    "tube_oval": lambda: geo.tube([(0, 0, 0), (0, -1, 0)], [(0.1, 0.2), (0.05, 0.1)], 8),
    "loft": lambda: geo.loft([geo.ring((0, 0, z), (1, 0, 0), (0, 1, 0), geo.section(10, 0.2, 0.1, 0.12))
                              for z in (0, 0.5, 1)], cap_start=True, cap_end=True),
    "loft_fans": lambda: geo.loft_fans([geo.ring((0, 0, z), (1, 0, 0), (0, 1, 0), geo.section(6, 0.2, 0.1, 0.1))
                                        for z in (0, 1)], top=(0, 0, 1.3), bottom=(0, 0, -0.3)),
}


class Closed(unittest.TestCase):
    def test_closed_shapes_face_outwards(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                g = make()
                self.assertTrue(g.is_closed(), f"{name} is not closed")
                self.assertGreater(g.volume(), 0, f"{name} is inside out")

    def test_mirroring_keeps_them_outwards(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                self.assertGreater(make().mirrored_x().volume(), 0)

    def test_offset_surface_grows_a_closed_shape(self):
        g = geo.ball(1, 10, 6)
        self.assertGreater(geo.offset_surface(g, 0.1).volume(), g.volume())


class Shapes(unittest.TestCase):
    def test_box_volume_and_bounds(self):
        g = geo.box((1, 2, 3), (1, 0, 0))
        self.assertAlmostEqual(g.volume(), 6.0, places=6)
        self.assertEqual(g.bounds(), ((0.5, -1.0, -1.5), (1.5, 1.0, 1.5)))

    def test_band_is_open(self):
        g = geo.band([(1, 0), (0.8, 0.5)], 8)
        self.assertFalse(g.is_closed())
        self.assertEqual(g.tris(), 16)

    def test_disc_faces_up(self):
        g = geo.disc(1, 8, loc=(0, 0, 2))
        self.assertEqual(len(g.faces), 1)
        self.assertTrue(all(abs(v[2] - 2) < 1e-9 for v in g.verts))

    def test_torus_triangles(self):
        self.assertEqual(geo.torus(1, 0.1, 16, 6).tris(), 2 * 16 * 6)

    def test_lump_is_the_same_for_the_same_seed(self):
        a = geo.lump(1, rng=random.Random(5), jitter=0.3)
        b = geo.lump(1, rng=random.Random(5), jitter=0.3)
        self.assertEqual(a.verts, b.verts)

    def test_lump_flat_bottom(self):
        g = geo.lump(2, rng=random.Random(1), jitter=0.2, flat_bottom=-0.4)
        self.assertAlmostEqual(min(v[2] for v in g.verts), -0.8)

    def test_smooth_path_passes_through_its_points(self):
        pts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (2, 1, 1)]
        path = geo.smooth_path(pts, 5)
        for p in pts:
            self.assertTrue(any(sum((a - b) ** 2 for a, b in zip(p, q)) < 1e-12 for q in path))

    def test_basis_refuses_a_mirror(self):
        with self.assertRaises(ValueError):
            geo.basis((-1, 0, 0), (0, 1, 0), (0, 0, 1))

    def test_add_with_a_matrix(self):
        g = geo.Geo().add(geo.box((1, 1, 1)), geo.xf((0, 0, 5)))
        self.assertAlmostEqual(g.bounds()[0][2], 4.5)
