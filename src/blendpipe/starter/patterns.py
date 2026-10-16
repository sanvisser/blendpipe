"""Textures made from numbers: a project helper module. Model modules may import it (helpers sit beside project.py);
unlike a model module it may use numpy.

Keep textures for what geometry can't carry (a weave, rivets, a face); flat colour does the rest.
"""
import numpy as np

import blendpipe as bp

WEAVE_TILE = 0.08           # metres one tile of the weave spans on the model (box-projected)


def weave():
    """A tileable cloth weave: a colour multiplier and its normal map, registered as 'weave' and 'weave-normal'."""
    n = 64
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    over = np.sin(xx / n * np.pi * 8) * np.sin(yy / n * np.pi * 8)
    height = 0.5 + 0.5 * np.sign(over) * np.abs(over) ** 0.5
    colour = np.repeat(bp.textures.to8(0.82 + 0.18 * height)[:, :, None], 3, axis=2)
    bp.image("weave", colour)
    bp.image("weave-normal", bp.textures.normal_from_height(height, strength=1.5))
