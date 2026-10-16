"""A wooden crate with a lid the app can open: planks, a bevelled frame, a lid in its own group, a socket on top.

Shows: parts joined into one mesh per group (join=True), bevel, a group with extras, a socket.
"""
import blendpipe as bp
from blendpipe import geo

SPEC = dict(folder="props", tris=900, kb=25, materials=2, sockets=["top"], join=True)

W, D, H = 0.6, 0.45, 0.42       # outside size, metres
PLANK, GAP = 0.09, 0.012


def build(m):
    wood = bp.material("crate-wood", "#9a7350", finish="wood")
    dark = bp.material("crate-frame", bp.shade("#9a7350", 0.62), finish="wood")

    planks = m.part("planks", wood)
    rows = int(H // (PLANK + GAP))
    for i in range(rows):
        z = GAP + i * (PLANK + GAP) + PLANK / 2
        planks.add(geo.box((W - 0.04, D - 0.04, PLANK), (0, 0, z)))
    planks.add(geo.box((W - 0.05, D - 0.05, 0.02), (0, 0, 0.01)))          # the floor

    # the frame's posts, rounded off a little (a bevelled box weighs about five plain ones)
    frame = m.part("frame", dark, bevel=0.006)
    for sx in (-1, 1):
        for sy in (-1, 1):
            frame.add(geo.box((0.045, 0.045, H), (sx * (W / 2 - 0.0225), sy * (D / 2 - 0.0225), H / 2)))

    # the lid: its own group, so the app can show it open or closed
    m.group("lid", opens=True, hinge=[0.0, D / 2, H])
    lid = m.part("lid-boards", wood, group="lid")
    for i in range(5):
        y = -D / 2 + (i + 0.5) * D / 5
        lid.add(geo.box((W, D / 5 - 0.006, 0.022), (0, y, H + 0.011)))
    m.part("lid-battens", dark, group="lid").add(geo.box((0.05, D - 0.02, 0.016), (-W / 3, 0, H + 0.03))) \
        .add(geo.box((0.05, D - 0.02, 0.016), (W / 3, 0, H + 0.03)))

    m.socket("top", (0, 0, H + 0.038))
