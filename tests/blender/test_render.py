"""The review renderer: which engine it picks, and that the Cycles fallback (no GPU needed) renders."""
import os
import tempfile
import unittest

import bpy

import blendpipe as bp
from blendpipe import geo, render, scene
from blendpipe.errors import BuildError


def crate():
    scene.reset()
    m = bp.Model("box", {"tris": 100})
    m.part("body", bp.material("render-wood", "#8a6a4a")).add(geo.box((1, 1, 1), (0, 0, 0.5)))
    m.finish()
    return m


class Choosing(unittest.TestCase):
    def test_asking_for_an_engine_gets_it(self):
        self.assertEqual(render.choose_renderer("cycles"), "cycles")
        self.assertEqual(render.choose_renderer("eevee"), "eevee")

    def test_an_unknown_engine_fails(self):
        with self.assertRaises(BuildError):
            render.choose_renderer("luxrender")

    def test_auto_picks_one_of_the_two(self):
        self.assertIn(render.choose_renderer("auto"), ("eevee", "cycles"))

    def test_the_probe_answers_without_taking_this_blender_down(self):
        gpu = render.probe_gpu()
        self.assertTrue(gpu is None or isinstance(gpu, str))


class Cycles(unittest.TestCase):
    def test_a_shot_shows_the_model_against_the_ground(self):
        m = crate()
        st = render.Stage(None, "cycles")
        self.assertEqual(bpy.context.scene.render.engine, "CYCLES")
        render.aim(st.cam, 18, 32)
        render.frame(st.cam, render.points(m.tree()), 64, 64)
        with tempfile.TemporaryDirectory() as tmp:
            a = st.shot(m.tree(), os.path.join(tmp, "shot.png"), 64, 64, 16)
        self.assertEqual(a.shape, (64, 64, 4))
        centre, corner = a[32, 32], a[2, 2]
        self.assertGreater(centre[0], centre[2])        # the wood is warm
        self.assertGreater(corner[1], corner[0])        # the ground is green
        self.assertEqual(bpy.context.scene.cycles.samples, round(16 * render.CYCLES_SAMPLES))

    def test_thumbnails_are_written(self):
        m = crate()
        st = render.Stage(None, "cycles")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "box.webp")
            render.thumbnails([m], [path], 32, stage=st)
            self.assertGreater(os.path.getsize(path), 0)
