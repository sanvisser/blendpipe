"""Small textures made from numbers, written as PNG by hand so a rebuild writes the same bytes.

Make an image as a numpy uint8 array (h, w), (h, w, 3) or (h, w, 4), register it with `image(name, array)`, and give
it to a material with `texture(mat, colour=..., normal=..., uv=...)`. The PNG is packed into the blend file, and the
glTF exporter embeds a packed, unmodified PNG's own bytes, so the glb carries exactly what `png()` wrote.

UV layouts (how the mesh builder lays out a textured material's UVs):
  "box"    each face is projected onto the axis plane it faces most, in tiles of `tile` metres: tileable patterns
           (mail, bricks, planks, quilting) over any shape.
  "front"  faces turned forwards (-y) inside rect (x0, x1, z0, z1) map that rectangle onto the image: a face, a
           label, a painted sign. Other faces take the image's corner (keep it plain).
Normal maps are linear, OpenGL style (+x right, +y up the image), as glTF wants.
"""
import hashlib
import os
import struct
import tempfile
import zlib

import bpy
import numpy as np

from .errors import BuildError

_images = {}            # name -> (image, sha1 of the png)


def png(arr):
    """PNG bytes of a uint8 array (h, w) or (h, w, 3|4), row 0 at the top, every row filtered 'up'."""
    a = np.ascontiguousarray(arr, dtype=np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    kind = {1: 0, 3: 2, 4: 6}[c]
    up = a.astype(np.int16)
    up[1:] -= a[:-1].astype(np.int16)
    rows = (up % 256).astype(np.uint8).reshape(h, w * c)
    raw = b"".join(bytes([2 if i else 0]) + (rows[i].tobytes() if i else a[0].reshape(-1).tobytes())
                   for i in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, kind, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def to8(x):
    """Floats 0..1 as uint8."""
    return np.clip(np.round(np.asarray(x) * 255.0), 0, 255).astype(np.uint8)


def normal_from_height(height, strength=2.0):
    """A tileable normal map (uint8, h x w x 3) from a height field (floats), wrapping round the edges."""
    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5
    gy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5      # rows run down the image
    nx, ny, nz = -gx * strength, gy * strength, np.ones_like(height)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    return to8(np.stack([nx / ln, ny / ln, nz / ln], axis=2) * 0.5 + 0.5)


def image(name, arr=None, linear=None):
    """The packed image called name: made from arr (a uint8 array) on the first call, looked up after.
    linear: stored as non-colour data (default: when the name ends in 'normal')."""
    if arr is None:
        if name not in _images:
            raise BuildError(f"image {name} was never made")
        return _images[name][0]
    data = png(arr)
    digest = hashlib.sha1(data).hexdigest()
    if name in _images:
        if _images[name][1] != digest:
            raise BuildError(f"image {name} is made twice, with different pixels")
        return _images[name][0]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"{name}.png")
        with open(path, "wb") as f:
            f.write(data)
        img = bpy.data.images.load(path)
        img.pack()
    img.name = name
    is_linear = name.endswith("normal") if linear is None else linear
    img.colorspace_settings.name = "Non-Color" if is_linear else "sRGB"
    _images[name] = (img, digest)
    return img


def texture(mat, colour=None, normal=None, strength=1.0, uv="box", tile=0.1, rect=None):
    """Gives a material a colour texture (multiplied into its base colour) and/or a normal map, by image name, laid
    out by uv ("box" with tiles of tile metres, or "front" over rect = (x0, x1, z0, z1))."""
    if uv not in ("box", "front"):
        raise BuildError(f"material {mat.name}: uv {uv!r} is none of box, front")
    if uv == "front" and rect is None:
        raise BuildError(f"material {mat.name}: a front texture needs its rect (x0, x1, z0, z1)")
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    if colour:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = image(colour)
        t.interpolation = "Linear"
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    if normal:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = image(normal)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = strength
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    mat["uv"] = uv
    mat["uv_tile"] = float(tile)
    if rect is not None:
        mat["uv_rect"] = [float(c) for c in rect]
    return mat


def is_textured(mat):
    return "uv" in mat


def reset():
    _images.clear()
