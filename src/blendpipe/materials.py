"""Materials: one flat Principled BSDF per name, made once, with optional finishes, tint roles and extras.

A material is identified by its name. Asking for the same name with the same settings returns the first material;
asking with other settings fails the build, so two models can never silently share a name and get each other's
colour.

Finishes are named presets of (rough, metal, emit, strength) a project declares once (`finishes(...)`), so a whole
set of models shares the same few looks: `material("crate-wood", "#8a6a4a", finish="wood")`.

A tint role (`tint="team"`) marks a material the app recolours at runtime (an army's colour, a skin tone): build it
as a grey and the app multiplies it by the role's colour. The role is exported in the material's glTF extras, and
review sheets preview it with the project's TINTS. Any other `extras` are exported the same way.
"""
import bpy

from .colour import srgb, to_hex
from .errors import BuildError

_made = {}          # name -> (material, settings)
_finishes = {}      # name -> (rough, metal, emit, strength)

BUILD_ONLY = ("uv", "uv_tile", "uv_rect")      # material properties the build reads and the export drops


def finishes(**table):
    """Declares the finishes a project's materials may use: finishes(wood=dict(rough=0.7), brass=dict(rough=0.3,
    metal=1.0), lamp=dict(rough=0.5, emit="#ffd9a0", strength=4.0)). Later calls add to or replace earlier ones."""
    for name, spec in table.items():
        unknown = set(spec) - {"rough", "metal", "emit", "strength"}
        if unknown:
            raise BuildError(f"finish {name}: unknown settings {sorted(unknown)}")
        _finishes[name] = (float(spec.get("rough", 0.8)), float(spec.get("metal", 0.0)), spec.get("emit"),
                           float(spec.get("strength", 0.0)))


def finish_names():
    return sorted(_finishes)


def material(name, colour, *, finish=None, rough=0.8, metal=0.0, emit=None, strength=0.0, alpha=1.0,
             double=False, tint=None, **extras):
    """The material called name, in colour ('#rrggbb'); made on the first call.

    finish: one of the declared finishes (it sets rough, metal, emit and strength).
    emit/strength: an emission colour and strength (glowing parts: bulbs, flames, screens).
    alpha below 1: see-through (glass, water), drawn blended.
    double: both sides show (cloth that hangs open, a flag); otherwise back faces are culled.
    tint: the role the app recolours it by (exported as the material's extras "tint").
    extras: anything else the app should read from the material.
    """
    if finish is not None:
        if finish not in _finishes:
            raise BuildError(f"material {name}: no finish {finish!r}; the finishes are {finish_names()}")
        rough, metal, emit, strength = _finishes[finish]
    settings = (colour.lower(), finish, float(rough), float(metal), emit, float(strength), float(alpha),
                bool(double), tint, tuple(sorted(extras.items())))
    if name in _made:
        mat, before = _made[name]
        if before != settings:
            raise BuildError(f"material {name} is made twice, as {before} and as {settings}")
        return mat
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = srgb(colour)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emit:
        bsdf.inputs["Emission Color"].default_value = srgb(emit)
        bsdf.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        bsdf.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    m.diffuse_color = srgb(colour)
    m.use_backface_culling = not double
    if tint is not None:
        m["tint"] = tint
    for key, value in extras.items():
        m[key] = value
    _made[name] = (m, settings)
    return m


def tint_of(mat):
    """A material's tint role, or None."""
    return mat.get("tint")


def colour_of(mat):
    """The '#rrggbb' a material was made in."""
    if mat.name in _made:
        return _made[mat.name][1][0]
    return to_hex(mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value)


def finish_of(mat):
    """The finish a material was made in, or None."""
    return _made[mat.name][1][1] if mat.name in _made else None


def is_clear(mat):
    """Whether a material lets light through (alpha below 1)."""
    return mat.name in _made and _made[mat.name][1][6] < 1


def all_materials():
    return [m for m, _ in _made.values()]


def reset():
    """Forgets every material made (the build's scene reset calls it)."""
    _made.clear()
