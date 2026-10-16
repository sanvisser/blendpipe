"""A lantern: a turned base and cap, glass, a flame that glows, a real light, a bail handle and a ring to hang it by.

Shows: lathe profiles, limbs, torus, a tube along a smooth path, a see-through material, emission, a light with
extras the app can read (a flicker), a tint role (the app colours the cap).
"""
import math

import blendpipe as bp
from blendpipe import geo

SPEC = dict(folder="props", tris=1400, kb=25, materials=4)


def build(m):
    metal = bp.material("lantern-metal", "#3b3d42", finish="metal")
    cap_paint = bp.material("lantern-cap", "#c8c8c8", finish="matte", tint="accent")
    glass = bp.material("lantern-glass", "#dfe9ee", rough=0.05, alpha=0.3, double=True)
    flame = bp.material("lantern-flame", "#ffd27a", finish="flame")

    body = m.part("body", metal)
    body.add(geo.lathe([(0, 0), (0.09, 0), (0.095, 0.012), (0.085, 0.03), (0.07, 0.04), (0.07, 0.05), (0, 0.05)], 16))
    for i in range(4):                                  # four bars round the glass
        a = math.tau * (i + 0.5) / 4
        x, y = 0.072 * math.cos(a), 0.072 * math.sin(a)
        body.add(geo.limb((x, y, 0.045), (x, y, 0.235), 0.006, 0.006, 6))

    m.part("cap", cap_paint).add(geo.lathe([(0, 0.23), (0.085, 0.23), (0.09, 0.24), (0.05, 0.29), (0.02, 0.30),
                                            (0, 0.30)], 16))
    m.part("glass", glass, smooth=60).add(geo.cylinder(0.066, 0.19, 16, loc=(0, 0, 0.14)))
    m.part("flame", flame, smooth=90).add(geo.ball(0.016, 8, 4, loc=(0, 0, 0.11), scale=(1, 1, 2.2)))

    handle = m.part("handle", metal)
    bail = [(-0.075, 0, 0.245), (-0.06, 0, 0.32), (0, 0, 0.36), (0.06, 0, 0.32), (0.075, 0, 0.245)]
    handle.add(geo.tube(geo.smooth_path(bail, 3), 0.004, 6))
    handle.add(geo.torus(0.016, 0.004, 12, 5, loc=(0, 0, 0.376), rot=(90, 0, 0)))

    m.light("flame-light", (0, 0, 0.12), "#ffb347", 3.0, flicker=True)
