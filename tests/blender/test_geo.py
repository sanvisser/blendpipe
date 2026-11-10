"""Geometry: closed shapes face outwards, open ones stay open, placement and mirroring keep faces outwards."""
import math
import random
import unittest

from mathutils import Vector

from blendpipe import geo
from blendpipe.errors import BuildError


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
    "prism": lambda: geo.prism([(-1, 0), (1, 0), (1, 1), (0, 2), (-1, 1)], 0.5, loc=(1, 2, 3), rot=(10, 20, 30)),
    "prism_concave_x": lambda: geo.prism([(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)], 0.5, axis="x"),
    "prism_floor_plan": lambda: geo.prism([(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)], 0.5, axis="z"),
    "column": lambda: geo.column(0.05, 0.6),
    "column_fluted": lambda: geo.column(0.05, 0.6, flutes=8, loc=(1, 0, 0), rot=(0, 90, 0)),
    "column_straight": lambda: geo.column(0.05, 0.6, 6, entasis=0, top=1),
    "steps": lambda: geo.steps((1.6, 1.8), 3, 0.06, 0.06, rot=(0, 0, 30)),
    "steps_one": lambda: geo.steps((1.6, 1.8), 1, 0.07, 0.0),
    "gable": lambda: geo.gable(1.36, 1.74, 0.34, loc=(0, 0, 1)),
    "gable_no_eave": lambda: geo.gable(1.36, 1.74, 0.34, eave=0),
    "hip": lambda: geo.hip(1.6, 2.0, 0.5),
    "hip_pyramid": lambda: geo.hip(1.6, 2.0, 0.5, ridge=0),
    "hip_with_upright_ends": lambda: geo.hip(1.6, 2.0, 0.5, ridge=1),
    "pediment": lambda: geo.pediment(1.36, 0.34, 0.012, rot=(0, 0, 90)),
    "pediment_flat": lambda: geo.pediment(1.36, 0.34, 0.012, inset=0),
}


def is_manifold(g):
    """Every edge is shared by exactly two faces that run along it in opposite directions, so they agree which side
    is out."""
    runs = {}
    for f in g.faces:
        for a, b in zip(f, f[1:] + f[:1]):
            runs[(a, b)] = runs.get((a, b), 0) + 1
    return all(count == 1 and (b, a) in runs for (a, b), count in runs.items())


class Closed(unittest.TestCase):
    def test_closed_shapes_face_outwards(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                g = make()
                self.assertTrue(g.is_closed(), f"{name} is not closed")
                self.assertGreater(g.volume(), 0, f"{name} is inside out")

    def test_closed_shapes_are_manifold(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                self.assertTrue(is_manifold(make()), f"{name} has an edge its faces disagree about")

    def test_mirroring_keeps_them_outwards(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                self.assertGreater(make().mirrored_x().volume(), 0)

    def test_the_same_call_makes_the_same_mesh(self):
        for name, make in CLOSED.items():
            with self.subTest(name):
                a, b = make(), make()
                self.assertEqual((a.verts, a.faces), (b.verts, b.faces))

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


def radius(v):
    return math.hypot(v[0], v[1])


def ring_at(g, z):
    """The vertices of g at height z."""
    return [v for v in g.verts if abs(v[2] - z) < 1e-9]


def widest_between(g, lo, hi):
    """(height, radius) of the widest ring of g strictly between the heights lo and hi."""
    heights = sorted({v[2] for v in g.verts if lo < v[2] < hi})
    return max(((z, max(radius(v) for v in ring_at(g, z))) for z in heights), key=lambda pair: pair[1])


def distance(x, z, a, b):
    """How far the point (x, z) is from the line through a and b."""
    (x1, z1), (x2, z2) = a, b
    return abs((x2 - x1) * (z1 - z) - (x1 - x) * (z2 - z1)) / math.hypot(x2 - x1, z2 - z1)


class Prisms(unittest.TestCase):
    L = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]            # an L of area 3

    def test_a_prism_is_its_outline_centred_along_its_axis(self):
        for axis, bounds in (("y", ((0, -0.25, 0), (2, 0.25, 2))), ("x", ((-0.25, 0, 0), (0.25, 2, 2))),
                             ("z", ((0, 0, -0.25), (2, 2, 0.25)))):
            with self.subTest(axis):
                g = geo.prism(self.L, 0.5, axis=axis)
                self.assertEqual(g.bounds(), bounds)
                self.assertAlmostEqual(g.volume(), 3 * 0.5, places=6)

    def test_a_prisms_first_face_looks_at_the_side_its_outline_is_read_from(self):
        for axis, want in (("y", (0, -1, 0)), ("x", (1, 0, 0)), ("z", (0, 0, 1))):
            with self.subTest(axis):
                g = geo.prism([(0, 0), (1, 0), (0, 1)], 1, axis=axis)
                a, b, c = (Vector(g.verts[i]) for i in g.faces[0][:3])
                for got, expected in zip((b - a).cross(c - b).normalized(), want):
                    self.assertAlmostEqual(got, expected)

    def test_a_prism_refuses_what_would_not_be_a_solid(self):
        with self.assertRaisesRegex(BuildError, r"area is -0\.5.*counter-clockwise seen from -y"):
            geo.prism([(0, 0), (0, 1), (1, 0)], 1)
        with self.assertRaisesRegex(BuildError, r"has 2 points; it needs at least 3"):
            geo.prism([(0, 0), (1, 0)], 1)
        with self.assertRaisesRegex(BuildError, r"depth is 0; each must be above 0"):
            geo.prism(self.L, 0)
        with self.assertRaisesRegex(BuildError, r"axis is 'w'"):
            geo.prism(self.L, 1, axis="w")


class Columns(unittest.TestCase):
    R, H, BASE, CAPITAL = 0.05, 0.6, 0.025, 0.035

    def test_the_widest_ring_is_a_third_of_the_way_up(self):
        g = geo.column(self.R, self.H)
        z, widest = widest_between(g, self.BASE, self.H - self.CAPITAL)         # the shaft, between base and capital
        self.assertAlmostEqual(z / self.H, 1 / 3, delta=0.02)
        self.assertAlmostEqual(widest, self.R * 1.02)                           # entasis 0.02
        self.assertAlmostEqual(min(radius(v) for v in ring_at(g, self.BASE)), self.R)           # the foot
        self.assertAlmostEqual(min(radius(v) for v in ring_at(g, self.H - self.CAPITAL)), self.R * 0.86)    # the top

    def test_it_stands_on_the_ground_with_a_base_and_a_capital_wider_than_the_shaft(self):
        g = geo.column(self.R, self.H)
        lo, hi = g.bounds()
        self.assertEqual((lo[2], hi[2]), (0, self.H))
        self.assertAlmostEqual(max(radius(v) for v in ring_at(g, 0)), self.R * 1.3)
        self.assertAlmostEqual(max(radius(v) for v in ring_at(g, self.H)), self.R * 2.7 / 2)

    def test_flutes_cut_grooves_into_the_shaft(self):
        g = geo.column(self.R, self.H, flutes=8)
        ring = sorted(radius(v) for v in ring_at(g, self.BASE + (self.H - self.BASE - self.CAPITAL) / 3))
        self.assertEqual(len(ring), 16)
        self.assertAlmostEqual(ring[-1], self.R * 1.02)                          # the arrises keep the shaft's radius
        self.assertAlmostEqual(ring[0], ring[-1] * (1 - 0.5 * math.sin(math.pi / 8)))
        self.assertEqual(sum(1 for r in ring if r < ring[-1] * 0.9), 8)         # eight grooves

    def test_the_triangles_cost_16_n_less_4(self):
        self.assertEqual(geo.column(self.R, self.H, 8).tris(), 16 * 8 - 4)
        self.assertEqual(geo.column(self.R, self.H, flutes=6).tris(), 16 * 12 - 4)

    def test_a_column_refuses_what_leaves_no_shaft_or_no_swell(self):
        with self.assertRaisesRegex(BuildError, r"base \(0\.025\) and capital \(0\.035\) take 0\.060 of h 0\.05, "
                                                r"leaving the shaft -0\.010 high"):
            geo.column(0.05, 0.05)
        with self.assertRaisesRegex(BuildError, r"top is 1\.5; it must be above 0 and at most 1 \+ entasis \(1\.020\)"):
            geo.column(0.05, 0.6, top=1.5)
        with self.assertRaisesRegex(BuildError, r"entasis is -0\.1"):
            geo.column(0.05, 0.6, entasis=-0.1)
        with self.assertRaisesRegex(BuildError, r"flutes is 2"):
            geo.column(0.05, 0.6, flutes=2)
        with self.assertRaisesRegex(BuildError, r"n is 2"):
            geo.column(0.05, 0.6, 2)


class Steps(unittest.TestCase):
    def test_the_top_is_at_n_times_rise_and_each_step_is_inset(self):
        for n in (1, 2, 5):
            with self.subTest(n):
                g = geo.steps((2.0, 3.0), n, 0.07, 0.1)
                lo, hi = g.bounds()
                self.assertEqual((lo[2], hi[2]), (0, n * 0.07))
                top = [v for v in g.verts if v[2] == hi[2]]
                self.assertEqual(len(top), 4)                                   # the top step's own face
                self.assertAlmostEqual(max(v[0] for v in top), 1.0 - 0.1 * (n - 1))
                self.assertAlmostEqual(max(v[1] for v in top), 1.5 - 0.1 * (n - 1))
                blocks = sum((2.0 - 0.2 * i) * (3.0 - 0.2 * i) * 0.07 for i in range(n))
                self.assertAlmostEqual(g.volume(), blocks, places=6)

    def test_steps_refuse_what_would_not_show(self):
        with self.assertRaisesRegex(BuildError, r"5 steps inset 0\.2 take 1\.600 off the smaller side \(1\.000\), "
                                                r"leaving the top step -0\.600 across"):
            geo.steps((1, 1), 5, 0.1, 0.2)
        with self.assertRaisesRegex(BuildError, r"inset is 0; 3 steps need an inset above 0"):
            geo.steps((1, 1), 3, 0.1, 0)
        with self.assertRaisesRegex(BuildError, r"n is 0"):
            geo.steps((1, 1), 0, 0.1, 0.1)


class Roofs(unittest.TestCase):
    def test_a_gables_volume_is_its_section_times_its_length(self):
        w, l, rise, eave = 1.36, 1.74, 0.34, 0.035
        g = geo.gable(w, l, rise, eave=eave)
        section = w * eave + w * (rise - eave) / 2                  # the wall at each side, and the triangle on top
        self.assertAlmostEqual(g.volume(), l * section, delta=1e-5)
        self.assertAlmostEqual(section, w * (rise + eave) / 2)
        self.assertEqual(g.bounds(), ((-w / 2, -l / 2, 0), (w / 2, l / 2, rise)))

    def test_a_hips_volume_follows_the_wedge_formula(self):
        w, l, rise = 1.6, 2.0, 0.5
        for ridge in (0, 0.25, 0.5, 1):             # a pyramid is a third of its box, a gable with no eave half
            with self.subTest(ridge):
                g = geo.hip(w, l, rise, ridge=ridge)
                self.assertAlmostEqual(g.volume(), w * l * rise * (2 + ridge) / 6, delta=1e-5)
                top = [v[1] for v in g.verts if v[2] == rise]
                self.assertAlmostEqual(max(top) - min(top), ridge * l)

    def test_roofs_refuse_what_would_not_stand(self):
        with self.assertRaisesRegex(BuildError, r"rise 0\.02 must be above the eave 0\.035 \(it is 0\.015 short\)"):
            geo.gable(1, 1, 0.02)
        with self.assertRaisesRegex(BuildError, r"w is 0 and l is -1; each must be above 0"):
            geo.gable(0, -1, 0.3)
        with self.assertRaisesRegex(BuildError, r"ridge is 2; it is a share of l"):
            geo.hip(1, 1, 1, ridge=2)


class Pediments(unittest.TestCase):
    def test_a_pediment_is_rise_high_and_t_thick(self):
        for inset in (0, 0.05, 0.11):
            with self.subTest(inset):
                lo, hi = geo.pediment(1.36, 0.34, 0.012, inset=inset).bounds()
                self.assertEqual((lo[2], hi[2]), (0, 0.34))
                self.assertEqual((lo[0], hi[0]), (-1.36 / 2, 1.36 / 2))
                self.assertAlmostEqual(hi[1] - lo[1], 0.012)

    def test_its_field_is_sunk_and_inset_from_every_side(self):
        w, rise, t, inset = 1.36, 0.34, 0.012, 0.05
        g = geo.pediment(w, rise, t, inset=inset)
        field = [v for v in g.verts if v[1] == 0]                               # its floor, half way through
        self.assertEqual(len(field), 3)
        sides = [((-w / 2, 0), (w / 2, 0)), ((w / 2, 0), (0, rise)), ((0, rise), (-w / 2, 0))]
        for x, _, z in field:
            self.assertAlmostEqual(min(distance(x, z, a, b) for a, b in sides), inset)
        xs, zs = [v[0] for v in field], [v[2] for v in field]
        area = (max(xs) - min(xs)) * (max(zs) - min(zs)) / 2
        self.assertAlmostEqual(g.volume(), w * rise / 2 * t - area * t / 2, places=7)       # the field is t / 2 thin

    def test_no_inset_leaves_it_flat(self):
        g = geo.pediment(1.36, 0.34, 0.012, inset=0)
        self.assertAlmostEqual(g.volume(), 1.36 * 0.34 / 2 * 0.012, places=7)
        self.assertEqual(len(g.faces), 5)

    def test_a_pediment_refuses_a_frame_with_no_room_for_a_field(self):
        with self.assertRaisesRegex(BuildError, r"inset is 0\.2; it must be 0 or more and below 0\.161"):
            geo.pediment(1.36, 0.34, 0.012, inset=0.2)


class Placement(unittest.TestCase):
    MAKERS = {
        "prism": lambda **kw: geo.prism([(0, 0), (1, 0), (0, 1)], 1, **kw),
        "column": lambda **kw: geo.column(0.05, 0.6, **kw),
        "steps": lambda **kw: geo.steps((1.6, 1.8), 3, 0.06, 0.06, **kw),
        "gable": lambda **kw: geo.gable(1.36, 1.74, 0.34, **kw),
        "hip": lambda **kw: geo.hip(1.6, 2.0, 0.5, **kw),
        "pediment": lambda **kw: geo.pediment(1.36, 0.34, 0.012, **kw),
    }

    def test_loc_and_m_place_them_like_the_other_primitives(self):
        for name, make in self.MAKERS.items():
            with self.subTest(name):
                for moved, home in zip(make(loc=(1, 2, 3)).bounds(), make().bounds()):
                    for got, was, shift in zip(moved, home, (1, 2, 3)):
                        self.assertAlmostEqual(got - was, shift, places=5)
                self.assertEqual(make(loc=(1, 2, 3)).verts, make(m=geo.xf((1, 2, 3))).verts)
