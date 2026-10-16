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
