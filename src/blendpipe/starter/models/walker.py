"""A walking figure on the built-in humanoid rig, in two variants (bare-headed and hatted) sharing one skeleton,
socket and clips.

Shows: a skinned model (one mesh per variant), lofted sections and tubes, weights by Chain (smooth across joints)
and by dict, left pieces mirrored with add_both, vertex colours, tint roles, a box-projected texture from a helper
module, a socket on a bone, and the biped's idle and walk cycles (planted feet stay put at the clip's speed).
"""
import blendpipe as bp
from blendpipe import biped, geo
from blendpipe.skin import Chain

import patterns

SPEC = dict(
    folder="units", skinned=True, rig="humanoid", variants=["bare", "hatted"], tris=3000, tris_min=600, kb=200,
    materials=5, sockets=["hand.R"],
    far=(0.3, 0.02),        # also write walker-far.glb: about 30% of the triangles, for the camera far away
    clips={"idle": {"loop": True, "contact": True}, "walk": {"loop": True, "speed": 1.4, "contact": True}},
)

TUNIC, TROUSERS = 0.92, 0.55        # greys the team colour multiplies


def _sections(g, rows, n=10):
    """A loft of horizontal sections (z, half width, front, back) from the bottom up."""
    rings = [geo.ring((0, 0, z), (1, 0, 0), (0, 1, 0), geo.section(n, hx, f, b, power=2.3)) for z, hx, f, b in rows]
    return g.add(geo.loft(rings, cap_start=True, cap_end=True))


def build(m):
    patterns.weave()
    skin = bp.material("walker-skin", "#ffffff", finish="matte", tint="skin")
    cloth = bp.material("walker-cloth", "#ffffff", finish="matte", tint="team")
    bp.texture(cloth, colour="weave", normal="weave-normal", uv="box", tile=patterns.WEAVE_TILE, strength=0.6)
    leather = bp.material("walker-leather", "#5a3e2b", finish="matte")
    hair = bp.material("walker-hair", "#3a2a20", finish="matte")
    hat = bp.material("walker-hat", "#ffffff", finish="matte", tint="accent")

    torso_w = Chain([(0, 0, 0.85), (0, 0, 1.06), (0, 0, 1.22), (0, 0, 1.47)], ["hips", "spine", "chest"], [0.06, 0.07])
    leg_w = Chain([(0.095, 0, 1.02), (0.095, 0, 0.93), (0.10, -0.015, 0.50), (0.10, 0.02, 0.085)],
                  ["hips", "thigh.L", "shin.L"], [0.04, 0.05])
    arm_w = Chain([(0.03, 0, 1.42), (0.185, 0, 1.43), (0.215, 0.02, 1.13), (0.235, -0.005, 0.87)],
                  ["shoulder.L", "upper_arm.L", "forearm.L"], [0.04, 0.05])
    foot_w = Chain([(0.10, 0.07, 0.05), (0.10, -0.115, 0.04), (0.105, -0.21, 0.03)], ["foot.L", "toe.L"], [0.025])
    shaft_w = Chain([(0.10, 0.02, 0.0), (0.10, 0.02, 0.085), (0.10, 0.02, 0.5)], ["foot.L", "shin.L"], [0.04])
    neck_w = Chain([(0, 0, 1.40), (0, 0.005, 1.46), (0, -0.005, 1.585), (0, -0.005, 1.70)], ["chest", "neck", "head"],
                   [0.03, 0.03])

    for name in m.variants:
        v = m.variant(name)
        torso = _sections(geo.Geo(), [(0.88, 0.15, 0.09, 0.09), (0.97, 0.165, 0.10, 0.10), (1.10, 0.15, 0.095, 0.09),
                                      (1.25, 0.17, 0.11, 0.10), (1.37, 0.175, 0.10, 0.095), (1.44, 0.145, 0.085, 0.08),
                                      (1.48, 0.07, 0.055, 0.055)])
        v.add(torso, cloth, torso_w, TUNIC)
        belt = [geo.ring((0, 0, z), (1, 0, 0), (0, 1, 0), geo.section(10, hx + 0.007, f + 0.007, b + 0.007, power=2.3))
                for z, hx, f, b in ((1.00, 0.161, 0.099, 0.098), (1.05, 0.157, 0.097, 0.095))]
        v.add(geo.loft(belt), leather, torso_w)

        leg = geo.tube([(0.095, 0, 0.95), (0.10, -0.012, 0.72), (0.10, -0.015, 0.50), (0.10, 0.0, 0.30),
                        (0.10, 0.02, 0.14)], [0.085, 0.07, 0.056, 0.05, 0.043], 8)
        v.add_both(leg, cloth, leg_w, TROUSERS)
        boot = geo.tube([(0.10, 0.06, 0.05), (0.10, 0.0, 0.05), (0.10, -0.115, 0.04), (0.105, -0.195, 0.032)],
                        [(0.05, 0.045), (0.05, 0.05), (0.04, 0.048), (0.032, 0.04)], 8)
        v.add_both(boot, leather, foot_w)
        v.add_both(geo.tube([(0.10, 0.02, 0.05), (0.10, 0.02, 0.21)], [0.05, 0.047], 8), leather, shaft_w)

        # from inside the torso, over the shoulder, down to the wrist
        sleeve = geo.tube([(0.11, 0.0, 1.425), (0.175, 0.0, 1.415), (0.205, 0.01, 1.30), (0.215, 0.02, 1.13),
                           (0.225, 0.01, 1.0), (0.235, -0.005, 0.89)], [0.055, 0.058, 0.05, 0.045, 0.04, 0.035], 8)
        v.add_both(sleeve, cloth, arm_w, TUNIC)
        v.add_both(geo.ball(0.042, 8, 4, loc=(0.24, -0.012, 0.83), scale=(0.8, 1.0, 1.15)), skin, {"hand.L": 1.0})

        v.add(geo.limb((0, 0, 1.42), (0, 0, 1.61), 0.05, 0.048, 8), skin, neck_w)
        v.add(geo.ball(0.105, 12, 8, loc=(0, -0.01, 1.69), scale=(0.9, 1.0, 1.1)), skin, {"head": 1.0})
        v.add(geo.limb((0, -0.104, 1.675), (0, -0.13, 1.655), 0.015, 0.007, 5), skin, {"head": 1.0})
        # eyes: the skin material in a dark vertex colour (multiplied with the skin tone), no extra material
        v.add_both(geo.ball(0.011, 6, 3, loc=(0.033, -0.104, 1.70), scale=(1, 0.6, 1)), skin, {"head": 1.0},
                   "#2a2220")
        if name == "bare":
            # a dome over the scalp, tipped back so it runs from the forehead down to the nape
            dome = geo.lathe([(0.102, 0.0), (0.1, 0.035), (0.09, 0.072), (0.068, 0.104), (0.037, 0.126), (0, 0.135)],
                             12, loc=(0, -0.004, 1.685), rot=(-28, 0, 0), ry=1.12)
            v.add(dome, hair, {"head": 1.0})
        else:
            v.add(geo.cylinder(0.165, 0.012, 16, loc=(0, 0, 1.775)), hat, {"head": 1.0}, sharp=40)
            v.add(geo.cylinder(0.09, 0.10, 16, loc=(0, 0, 1.83), r_top=0.08), hat, {"head": 1.0}, sharp=40)

    m.socket("hand.R", (-0.24, -0.02, 0.81), bone="hand.R")


def animate(m):
    biped.idle(m)
    biped.walk(m)
