"""A rock: a jittered lump, flat underneath so it sits on the ground.

Shows: seeded randomness (random.Random(<number>) only, so a rebuild is the same), a looser ground rule.
"""
import random

import blendpipe as bp
from blendpipe import geo

SPEC = dict(folder="props", tris=200, kb=25, ground=(-0.02, 0.01))

R, SQUASH = 0.32, (1.0, 0.8, 0.62)


def build(m):
    stone = bp.material("rock-stone", "#7d7a73", finish="matte")
    rng = random.Random(11)
    flat = -0.45
    lift = -flat * R * SQUASH[2]                # stands the flat bottom on z 0
    m.part("stone", stone, smooth=0).add(geo.lump(R, loc=(0, 0, lift), scale=SQUASH, rng=rng, jitter=0.18, subdiv=1,
                                                  flat_bottom=flat))
