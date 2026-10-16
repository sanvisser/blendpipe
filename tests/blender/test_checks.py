"""The code rules (a model module builds from the kit, never from Blender, with seeded randomness only) and the
building checks (footprint, height, fill, floating)."""
import os
import tempfile
import textwrap
import unittest

import blendpipe as bp
from blendpipe import checks, geo, scene


def problems_of(source, allowed=()):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "model.py")
        with open(path, "w") as f:
            f.write(textwrap.dedent(source))
        p = checks.Problems()
        checks.code(path, p, allowed)
        return p.items


class Code(unittest.TestCase):
    def test_a_clean_module_passes(self):
        self.assertEqual(problems_of("""
            import math
            import random
            from random import Random
            import blendpipe as bp
            from blendpipe import geo
            from mathutils import Vector
            import helpers
            def build(m):
                rng = random.Random(4)
                rng2 = Random(5)
                return math.pi, rng.uniform(0, 1), Vector((0, 0, 0)), helpers
            """, allowed={"helpers"}), [])

    def test_blender_itself_is_refused(self):
        found = problems_of("""
            import bpy
            from bmesh import ops
            import blendpipe as bp
            def build(m):
                bp.materials.bpy.context.scene
            """)
        self.assertTrue(any("imports bpy" in p for p in found))
        self.assertTrue(any("from bmesh" in p for p in found))
        self.assertTrue(any(".bpy" in p or ".context" in p for p in found))

    def test_unseeded_randomness_is_refused(self):
        found = problems_of("""
            import random
            from random import randint
            def build(m, n):
                random.random()
                random.Random()
                random.Random(n)
            """)
        self.assertEqual(len(found), 4, found)

    def test_files_and_eval_are_refused(self):
        found = problems_of("""
            import os
            def build(m):
                open("x")
                eval("1")
            """)
        self.assertEqual(len(found), 3, found)

    def test_the_noise_generators_shared_state_is_refused(self):
        found = problems_of("""
            import mathutils
            import mathutils as mu
            import mathutils.noise as gen
            from mathutils import noise
            from mathutils import noise as nz
            from mathutils.noise import seed_set, random_unit_vector, noise as value
            def build(m):
                noise.seed_set(3)
                noise.random()
                nz.random_vector()
                mathutils.noise.random_unit_vector()
                mu.noise.random()
                gen.seed_set(1)
            """)
        self.assertEqual(len(found), 8, found)
        self.assertEqual(sum("mathutils.noise.seed_set" in p for p in found), 3, found)
        self.assertEqual(sum("mathutils.noise.random" in p for p in found), 5, found)
        self.assertTrue(all("use random.Random(<number>)" in p for p in found), found)

    def test_the_rest_of_the_noise_module_is_fine(self):
        self.assertEqual(problems_of("""
            import mathutils.noise
            from mathutils import Vector, noise
            from mathutils.noise import turbulence
            def build(m):
                at = Vector((1, 2, 3))
                return (noise.noise(at), noise.noise_vector(at), noise.cell(at), turbulence(at, 3, False),
                        noise.fractal(at, 1.0, 2.0, 3, noise.types.STDPERLIN), mathutils.noise.voronoi(at))
            """), [])


def box(lo, hi):
    return geo.box_between(lo, hi)


def checked(spec, *parts, join=False, **kw):
    """The problems checks.model finds in a model "hut" of that spec. Each of parts is a list of shapes, added to a
    part of its own."""
    scene.reset()
    m = bp.Model("hut", spec)
    for i, shapes in enumerate(parts):
        part = m.part(f"p{i}", bp.material(f"hut-{i}", "#888888"))
        for shape in shapes:
            part.add(shape)
    m.finish(join=join)
    found = checks.Problems()
    checks.model(m, found, **kw)
    return found.items


class Unchanged(unittest.TestCase):
    def test_a_project_without_the_keys_gets_no_new_problems(self):
        # far past any tile, tall, with a piece hanging in the air: only the rules the spec asks for speak
        hut = [box((-9, -9, 0), (9, 9, 5)), box((0, 0, 7), (1, 1, 8))]
        self.assertEqual(checked({}, hut), [])
        self.assertEqual(checked(dict(tris=4, sockets=["top"]), hut),
                         ["hut: 24 triangles, at most 4", "hut: sockets [], the spec says ['top']"])
        self.assertEqual(checked({}, [box((0, 0, 3), (1, 1, 4))]),
                         ["hut: its lowest point is at 3.000 m; it must stand on the ground "
                          "(between -0.01 and 0.01)"])

    def test_a_key_set_to_none_is_off(self):
        spec = dict(footprint=None, overhang=None, height=None, fill=None, floating=None)
        self.assertEqual(checked(spec, [box((-9, -9, 0), (9, 9, 5)), box((0, 0, 7), (1, 1, 8))]), [])


class Footprint(unittest.TestCase):
    PAST = [box((-1.015, -0.5, 0), (1.0, 0.5, 1))]

    def test_a_box_past_the_tile_fails_and_says_by_how_much(self):
        self.assertEqual(checked(dict(footprint=(2, 2)), self.PAST),
                         ["hut: footprint: vertex at x = -1.015 is 0.015 past the tile edge (1.000)"])

    def test_the_worst_vertex_of_each_side_is_named(self):
        found = checked(dict(footprint=(1, 1)), [box((-0.6, -0.7, 0), (0.55, 0.52, 1))])
        self.assertEqual(found, [
            "hut: footprint: vertex at x = -0.600 is 0.100 past the tile edge (0.500)",
            "hut: footprint: vertex at x = 0.550 is 0.050 past the tile edge (0.500)",
            "hut: footprint: vertex at y = -0.700 is 0.200 past the tile edge (0.500)",
            "hut: footprint: vertex at y = 0.520 is 0.020 past the tile edge (0.500)"])

    def test_the_edge_itself_is_inside(self):
        self.assertEqual(checked(dict(footprint=(2, 2)), [box((-1, -1, 0), (1, 1, 1))]), [])

    def test_an_overhang_allows_it(self):
        self.assertEqual(checked(dict(footprint=(2, 2), overhang=0.02), self.PAST), [])
        self.assertEqual(checked(dict(footprint=(2, 2), overhang=0.01), self.PAST),
                         ["hut: footprint: vertex at x = -1.015 is 0.005 past the tile edge plus overhang (1.010)"])

    def test_the_tile_is_a_setting_and_the_footprint_may_be_longer_one_way(self):
        long_house = [box((-1, -2, 0), (1, 2, 1))]
        self.assertEqual(checked(dict(footprint=(1, 2)), long_house, tile=2.0), [])
        self.assertEqual(len(checked(dict(footprint=(1, 2)), long_house)), 4)

    def test_half_a_millimetre_is_rounding(self):
        self.assertEqual(checked(dict(footprint=(1, 1)), [box((-0.5004, -0.5, 0), (0.5, 0.5, 1))]), [])
        self.assertEqual(len(checked(dict(footprint=(1, 1)), [box((-0.5006, -0.5, 0), (0.5, 0.5, 1))])), 1)

    def test_a_part_hung_from_a_bone_is_measured_where_it_stands(self):
        from blendpipe import rig
        scene.reset()
        m = bp.Model("mill", dict(footprint=(1, 1)))
        m.arm, m.rig = rig.build("mill-rig", [("base", None, (0, 0, 0), (0, 0, 0.5))], parent=m.root, loc=(0.9, 0, 0))
        m.objects.append(m.arm)
        m.part("body", bp.material("mill-m", "#888888"), bone="base").add(box((-0.2, -0.2, 0), (0.2, 0.2, 1)))
        m.finish()
        found = checks.Problems()
        checks.model(m, found)
        self.assertEqual(found.items, ["mill: footprint: vertex at x = 1.100 is 0.600 past the tile edge (0.500)"])


class Height(unittest.TestCase):
    TALL = [box((-0.5, -0.5, 0), (0.5, 0.5, 2.0))]

    def test_the_limit_itself_passes_and_more_fails_by_the_amount(self):
        self.assertEqual(checked(dict(height=2.0), self.TALL), [])
        self.assertEqual(checked(dict(height=1.99), self.TALL),
                         ["hut: height: the highest point is at z = 2.000, 0.010 over the limit (1.990)"])

    def test_half_a_millimetre_is_rounding(self):
        self.assertEqual(checked(dict(height=1.9996), self.TALL), [])
        self.assertEqual(len(checked(dict(height=1.9994), self.TALL)), 1)


class Fill(unittest.TestCase):
    SPEC = dict(footprint=(2, 2))

    @staticmethod
    def plan(w, d):
        return [box((-w / 2, -d / 2, 0), (w / 2, d / 2, 1))]

    def test_the_lower_boundary(self):
        self.assertEqual(checked(dict(self.SPEC, fill=(0.75, 0.95)), self.plan(1.5, 1.5)), [])
        self.assertEqual(checked(dict(self.SPEC, fill=(0.76, 0.95)), self.plan(1.5, 1.5)), [
            "hut: fill: the plan along x spans 1.500 m, 0.75 of the footprint (2.000 m); the range is 0.76 to 0.95 "
            "(1.520 to 1.900 m)",
            "hut: fill: the plan along y spans 1.500 m, 0.75 of the footprint (2.000 m); the range is 0.76 to 0.95 "
            "(1.520 to 1.900 m)"])

    def test_the_upper_boundary(self):
        self.assertEqual(checked(dict(self.SPEC, fill=(0.5, 0.75)), self.plan(1.5, 1.5)), [])
        found = checked(dict(self.SPEC, fill=(0.5, 0.74)), self.plan(1.5, 1.2))
        self.assertEqual(found, ["hut: fill: the plan along x spans 1.500 m, 0.75 of the footprint (2.000 m); "
                                 "the range is 0.5 to 0.74 (1.000 to 1.480 m)"])

    def test_each_axis_has_its_own_share(self):
        self.assertEqual(checked(dict(self.SPEC, fill=(0.5, 0.95)), self.plan(1.9, 1.0)), [])
        found = checked(dict(self.SPEC, fill=(0.5, 0.95)), self.plan(1.9, 0.5))
        self.assertEqual(len(found), 1, found)
        self.assertIn("along y spans 0.500 m, 0.25 of the footprint", found[0])

    def test_the_share_is_of_the_footprint_without_the_overhang(self):
        found = checked(dict(self.SPEC, overhang=0.5, fill=(0.8, 0.95)), self.plan(1.5, 1.5))
        self.assertEqual(len(found), 2, found)

    def test_the_plan_is_every_part_together(self):
        two = [[box((-0.9, -0.9, 0), (0, 0.9, 1))], [box((0, -0.9, 0), (0.9, 0.9, 1))]]
        self.assertEqual(checked(dict(self.SPEC, fill=(0.9, 0.95)), *two), [])


class Floating(unittest.TestCase):
    BASE = box((-0.5, -0.5, 0), (0.5, 0.5, 0.5))
    HOVER = box((-0.1, -0.1, 0.7), (0.1, 0.1, 0.9))

    def test_a_box_in_the_air_is_caught_and_the_amount_named(self):
        self.assertEqual(checked(dict(floating=0.005), [self.BASE], [self.HOVER]), [
            "hut: floating: a piece of part p1 around (0.000, 0.000, 0.800) is 0.200 m clear of the ground and of "
            "every other piece, at most 0.005 m allowed"])

    def test_a_box_that_touches_passes(self):
        on_top = box((-0.1, -0.1, 0.5), (0.1, 0.1, 0.7))
        beside = box((0.5, -0.1, 0.2), (0.8, 0.1, 0.4))
        far_on_the_ground = box((3, 3, 0), (4, 4, 1))
        self.assertEqual(checked(dict(floating=0.005), [self.BASE], [on_top, beside], [far_on_the_ground]), [])

    def test_the_ground_rule_alone_does_not_see_it(self):
        self.assertEqual(checked({}, [self.BASE], [self.HOVER]), [])

    def test_the_gap_is_compared_with_the_tolerance(self):
        gap = box((-0.1, -0.1, 0.75), (0.1, 0.1, 1.0))      # 0.25 above the base, exactly
        self.assertEqual(checked(dict(floating=0.25), [self.BASE, gap]), [])
        self.assertEqual(len(checked(dict(floating=0.24), [self.BASE, gap])), 1)
        close = box((-0.1, -0.1, 0.503), (0.1, 0.1, 0.8))
        self.assertEqual(checked(dict(floating=0.005), [self.BASE, close]), [])
        self.assertEqual(len(checked(dict(floating=0.002), [self.BASE, close])), 1)

    def test_pieces_are_found_inside_one_part_and_inside_one_joined_mesh(self):
        for name, found in (("one part", checked(dict(floating=0.005), [self.BASE, self.HOVER])),
                            ("joined", checked(dict(floating=0.005), [self.BASE], [self.HOVER], join=True)),
                            ("bevelled", self._bevelled())):
            with self.subTest(name):
                self.assertEqual(len(found), 1, found)
                self.assertIn("is 0.200 m clear", found[0])

    def _bevelled(self):
        scene.reset()
        m = bp.Model("hut", dict(floating=0.005))
        m.part("p0", bp.material("hut-0", "#888888"), bevel=0.02).add(self.BASE).add(self.HOVER)
        m.finish()
        found = checks.Problems()
        checks.model(m, found)
        return found.items

    def test_a_slanted_piece_is_one_piece(self):
        post = geo.limb((0, 0, 0.0), (0.1, 0, 0.6), 0.03, 0.03, 6)
        roof = geo.box((0.6, 0.6, 0.05), (0.1, 0, 0.625))
        self.assertEqual(checked(dict(floating=0.005), [post, roof]), [])


class Misuse(unittest.TestCase):
    ON_GROUND = [box((-0.5, -0.5, 0), (0.5, 0.5, 1))]

    def test_fill_and_overhang_need_a_footprint(self):
        self.assertEqual(checked(dict(overhang=0.1), self.ON_GROUND), ["hut: overhang is set without a footprint"])
        self.assertEqual(checked(dict(fill=(0.5, 0.9)), self.ON_GROUND), ["hut: fill is set without a footprint"])

    def test_values_that_are_not_what_they_should_be_are_named(self):
        for spec in (dict(footprint=(1,)), dict(footprint=(1, 0)), dict(footprint="ab"),
                     dict(footprint=(1, 1), fill=(0.9, 0.5)), dict(height=-1), dict(height="tall"),
                     dict(floating=True), dict(footprint=(1, 1), overhang=-0.1)):
            with self.subTest(spec):
                found = checked(spec, self.ON_GROUND)
                self.assertEqual(len(found), 1, found)
                self.assertIn("must be", found[0])
