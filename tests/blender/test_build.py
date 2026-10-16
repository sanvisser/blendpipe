"""Models, skinned models, clips, checks and export inside Blender."""
import os
import sys
import tempfile
import unittest

import bpy

import blendpipe as bp
from blendpipe import anim, biped, checks, export, geo, rig, runner, scene, tools
from blendpipe.errors import BuildError
from blendpipe.skin import Chain, swap_sides, top4


def fresh():
    scene.reset()
    bp.materials.finishes(wood=dict(rough=0.7), glow=dict(emit="#ffffff", strength=2.0))


class Materials(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_same_name_same_settings_is_the_same_material(self):
        a = bp.material("t-a", "#336699", finish="wood")
        self.assertIs(a, bp.material("t-a", "#336699", finish="wood"))

    def test_same_name_other_settings_fails(self):
        bp.material("t-b", "#336699", finish="wood")
        with self.assertRaises(BuildError):
            bp.material("t-b", "#336698", finish="wood")

    def test_unknown_finish_fails(self):
        with self.assertRaises(BuildError):
            bp.material("t-c", "#336699", finish="velvet")

    def test_tint_and_extras(self):
        m = bp.material("t-d", "#ffffff", tint="team", layer="cloth")
        self.assertEqual((m["tint"], m["layer"]), ("team", "cloth"))
        self.assertEqual(bp.materials.colour_of(m), "#ffffff")


class Models(unittest.TestCase):
    def setUp(self):
        fresh()

    def _crate(self, join=False):
        m = bp.Model("box", {"sockets": ["top"], "tris": 100})
        wood = bp.material("box-wood", "#8a6a4a", finish="wood")
        m.part("body", wood).add(geo.box((1, 1, 1), (0, 0, 0.5)))
        m.part("lid", wood, group="lid").add(geo.box((1, 1, 0.1), (0, 0, 1.05)))
        m.socket("top", (0, 0, 1.1))
        m.finish(join=join)
        return m

    def test_parts_become_meshes_that_face_outwards(self):
        m = self._crate()
        self.assertEqual(sorted(o["part"] for o in m.meshes()), ["body", "lid"])
        for o in m.meshes():
            self.assertGreater(checks.closed_volume(o), 0)
        p = checks.Problems()
        checks.model(m, p)
        self.assertEqual(p.items, [])

    def test_join_merges_each_group(self):
        m = self._crate(join=True)
        self.assertEqual(sorted(o["part"] for o in m.meshes()), ["body", "lid"])
        lid = next(o for o in m.meshes() if o["part"] == "lid")
        self.assertEqual(lid.parent["group"], "lid")

    def test_checks_catch_budgets_ground_and_sockets(self):
        m = bp.Model("floaty", {"sockets": ["top"], "tris": 4})
        m.part("p", bp.material("floaty-m", "#888888")).add(geo.box((1, 1, 1), (0, 0, 2)))
        m.finish()
        p = checks.Problems()
        checks.model(m, p)
        text = "\n".join(p.items)
        self.assertIn("12 triangles, at most 4", text)
        self.assertIn("lowest point", text)
        self.assertIn("sockets", text)

    def test_inside_out_is_caught(self):
        m = bp.Model("inv", {})
        g = geo.box((1, 1, 1), (0, 0, 0.5))
        g.faces = [tuple(reversed(f)) for f in g.faces]
        m.part("p", bp.material("inv-m", "#888888")).add(g)
        m.finish()
        p = checks.Problems()
        checks.model(m, p)
        self.assertTrue(any("inside out" in x for x in p.items), p.items)

    def test_two_nodes_of_one_name_fail(self):
        m = bp.Model("dup", {})
        m.socket("hand", (0, 0, 0))
        with self.assertRaises(BuildError):
            m.socket("hand", (0, 0, 1))

    def test_bevel_rounds_the_edges(self):
        m = bp.Model("bev", {})
        m.part("p", bp.material("bev-m", "#888888"), bevel=0.05).add(geo.box((1, 1, 1), (0, 0, 0.5)))
        m.finish()
        self.assertGreater(scene.triangles(m.meshes()), 12)
        self.assertGreater(checks.closed_volume(m.meshes()[0]), 0)


class Settings(unittest.TestCase):
    def project(self, project_py=None):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "models"))
            if project_py is not None:
                with open(os.path.join(tmp, "project.py"), "w") as f:
                    f.write(project_py)
            try:
                return runner.Project(tmp)
            finally:
                sys.path.remove(tmp)

    def test_a_tile_is_one_metre_unless_the_project_says_so(self):
        self.assertEqual(self.project().tile, 1.0)
        self.assertEqual(self.project("DEFAULTS = {}\n").tile, 1.0)
        self.assertEqual(self.project("TILE = 2.5\n").tile, 2.5)

    def test_a_tile_has_a_size(self):
        for tile in ("0", "-1", "float('nan')"):
            with self.subTest(tile), self.assertRaises(BuildError):
                self.project(f"TILE = {tile}\n")


class Skinning(unittest.TestCase):
    def test_top4_normalises_and_orders(self):
        w = top4({"a": 1, "b": 1, "c": 2, "d": 0.5, "e": 0.1})
        self.assertEqual(sorted(w), ["a", "b", "c", "d"])
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_chain_blends_across_the_joint(self):
        c = Chain([(0, 0, 0), (0, 0, 1), (0, 0, 2)], ["lo", "hi"], [0.2])
        self.assertEqual(c((0, 0, 0.3)), {"lo": 1.0})
        mid = c((0, 0, 1.0))
        self.assertAlmostEqual(mid["lo"], 0.5)
        self.assertAlmostEqual(mid["hi"], 0.5)
        self.assertEqual(c((0, 0, 1.7)), {"hi": 1.0})

    def test_swap_sides(self):
        self.assertEqual(swap_sides({"hand.L": 0.5, "hand.R": 0.25, "head": 0.25}),
                         {"hand.R": 0.5, "hand.L": 0.25, "head": 0.25})


class Characters(unittest.TestCase):
    """A small skinned humanoid with a walk: weights, loops, contact and the written file."""

    @classmethod
    def setUpClass(cls):
        fresh()
        spec = dict(skinned=True, rig="humanoid", variants=["a", "b"], tris=2000, sockets=["hand.R"],
                    clips={"idle": {"loop": True, "contact": True},
                           "walk": {"loop": True, "speed": 1.4, "contact": True},
                           "run": {"loop": True, "speed": 3.0, "contact": 0.4}})
        m = bp.SkinModel("figure", spec)
        m.arm, m.rig = rig.build("figure-rig", biped.HUMANOID, parent=m.root)
        m.objects.append(m.arm)
        cloth = bp.material("figure-cloth", "#ffffff", tint="team")
        legs = Chain([(0.095, 0, 1.0), (0.10, -0.015, 0.50), (0.10, 0.02, 0.085)], ["thigh.L", "shin.L"], [0.05])
        # the toes follow the toe bone, so they stay flat as the heel lifts (all on the foot, they dig in)
        feet = Chain([(0.10, 0.07, 0.04), (0.10, -0.115, 0.04), (0.10, -0.21, 0.04)], ["foot.L", "toe.L"], [0.025])
        for name in m.variants:
            v = m.variant(name)
            v.add(geo.cylinder(0.15, 0.6, 8, loc=(0, 0, 1.2)), cloth, {"spine": 1.0}, 0.9)
            v.add_both(geo.tube([(0.1, 0, 0.95), (0.1, -0.015, 0.5), (0.1, 0.02, 0.1)], 0.05, 6), cloth, legs, 0.5)
            v.add_both(geo.tube([(0.1, 0.06, 0.04), (0.1, -0.06, 0.04), (0.1, -0.12, 0.04), (0.1, -0.19, 0.04)],
                                [(0.04, 0.04)] * 4, 8), cloth, feet, 0.3)
            if name == "b":
                v.add(geo.ball(0.1, 8, 4, loc=(0, 0, 1.7)), cloth, {"head": 1.0})
        m.socket("hand.R", (-0.24, -0.02, 0.81), bone="hand.R")
        m.finish()
        biped.idle(m)
        biped.walk(m)
        biped.run(m)
        anim.rest(m)
        cls.m = m

    def test_the_rules_hold(self):
        p = checks.Problems()
        checks.model(self.m, p)
        self.assertEqual(p.items, [])

    def test_weights_are_mirrored(self):
        o = self.m.meshes()[0]
        names = {vg.name for vg in o.vertex_groups}
        self.assertIn("thigh.R", names)
        right = o.vertex_groups["shin.R"].index
        self.assertTrue(any(g.group == right and g.weight > 0.99 for v in o.data.vertices for g in v.groups))

    def test_a_foot_off_the_ground_is_caught(self):
        m = self.m
        bad = dict(m.spec)
        bad["clips"] = {**m.spec["clips"], "idle": {"loop": True, "contact": True, "contact_tolerance": -0.5}}
        saved = m.spec
        m.spec = bad
        try:
            p = checks.Problems()
            checks.model(m, p)
        finally:
            m.spec = saved
        self.assertTrue(any("leaves the ground" in x for x in p.items), p.items)

    def test_the_export_keeps_what_the_app_reads(self):
        cmd = tools.find_gltfpack(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "figure.glb")
            p = checks.Problems()
            export.export_model(self.m, path, gltfpack_cmd=cmd, check_raw=lambda d: checks.raw_export(self.m, d, p))
            checks.file(self.m, path, p)
            self.assertEqual(p.items, [])
            doc, _ = export.read_glb(path)
            self.assertEqual(sorted(a["name"] for a in doc["animations"]), ["idle", "run", "walk"])
            joints = [doc["nodes"][j]["name"] for j in doc["skins"][0]["joints"]]
            self.assertIn("upper_arm_L", joints)
            if cmd:
                self.assertIn("EXT_meshopt_compression", doc["extensionsUsed"])
        self.assertTrue(all(a.name.startswith("figure@") for a in self.m.clips.values()))


class Leaks(unittest.TestCase):
    def test_one_models_clips_stay_out_of_anothers_file(self):
        fresh()
        made = []
        for mid in ("one", "two"):
            m = bp.Model(mid, {"rig": "humanoid", "clips": {"idle": {"loop": True}}})
            m.arm, m.rig = rig.build(f"{mid}-rig", biped.HUMANOID, parent=m.root)
            m.objects.append(m.arm)
            m.part("torso", bp.material(f"{mid}-m", "#888888"), bone="chest").add(
                geo.box((0.3, 0.2, 0.4), (0, 0, 1.3)))
            m.finish()
            biped.idle(m, frames=10)
            made.append(m)
        with tempfile.TemporaryDirectory() as tmp:
            for m in made:
                p = checks.Problems()
                export.export_model(m, os.path.join(tmp, f"{m.id}.glb"),
                                    check_raw=lambda d, m=m: checks.raw_export(m, d, p))
                self.assertEqual(p.items, [])
        self.assertEqual(len(bpy.data.actions), 2)
