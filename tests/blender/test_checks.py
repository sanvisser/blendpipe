"""The code rules: a model module builds from the kit, never from Blender, with seeded randomness only."""
import os
import tempfile
import textwrap
import unittest

from blendpipe import checks


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
