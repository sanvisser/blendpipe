"""blendpipe: procedural, deterministic low-poly assets built headless in Blender, checked against budgets and
rules, exported as compressed glTF (glb), and rendered as review sheets.

Inside Blender:

    import blendpipe as bp

    def build(m):
        wood = bp.material("crate-wood", "#8a6a4a", rough=0.7)
        m.part("body", wood).add(bp.geo.box((0.5, 0.5, 0.5), (0, 0, 0.25)))

Outside Blender only the command line (`blendpipe build ...`, see blendpipe.cli) is available.
"""
__version__ = "0.1.0"

from .errors import BuildError

__all__ = ["BuildError", "__version__"]

try:
    import bpy
except ImportError:         # outside Blender: the CLI only
    bpy = None

if bpy is not None:
    from . import anim, biped, checks, export, geo, materials, mesh, render, rig, scene, skin, textures
    from .colour import grey, mix, shade, srgb
    from .geo import Geo, xf
    from .materials import finishes, material
    from .model import Model
    from .rig import Pose, rot
    from .skin import Chain, SkinModel
    from .textures import image, texture

    __all__ += ["anim", "biped", "checks", "export", "geo", "materials", "mesh", "render", "rig", "scene", "skin",
                "textures", "grey", "mix", "shade", "srgb", "Geo", "xf", "finishes", "material", "Model", "Pose",
                "rot", "Chain", "SkinModel", "image", "texture"]
