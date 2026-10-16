"""Turning vertex and face lists into Blender meshes: materials per face, UVs for textured materials, vertex colours,
smooth shading with hard edges past a per-face angle, and bevels (Blender's modifier, applied and read back)."""
import math

import bpy
from mathutils import Vector

from .geo import Geo

NEUTRAL_UV = (0.02, 0.02)       # where faces a "front" texture doesn't cover sample it: keep that corner plain


def _normal(pts):
    n = Vector()
    for i in range(1, len(pts) - 1):
        n += (pts[i] - pts[0]).cross(pts[i + 1] - pts[0])
    return n.normalized() if n.length > 1e-12 else Vector((0, 0, 1))


def face_uvs(verts, face, mat):
    """The UVs of a face's corners for a textured material (textures.texture's uv layout)."""
    pts = [Vector(verts[i]) for i in face]
    mode = mat.get("uv")
    if mode == "box":
        n = _normal(pts)
        ax = max(range(3), key=lambda k: abs(n[k]))
        u, v = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[ax]
        s = 1.0 / float(mat.get("uv_tile", 0.1))
        return [(p[u] * s, p[v] * s) for p in pts]
    if mode == "front":
        x0, x1, z0, z1 = mat["uv_rect"]
        n = _normal(pts)
        c = sum(pts, Vector()) / len(pts)
        if n.y < -0.3 and x0 < c.x < x1 and z0 < c.z < z1:
            return [((p.x - x0) / (x1 - x0), (p.z - z0) / (z1 - z0)) for p in pts]
    return [NEUTRAL_UV] * len(pts)


def build_mesh(name, verts, faces, face_mats, face_sharp, colours=None):
    """A mesh datablock: face_mats one material per face, face_sharp one smoothing angle (degrees) per face (an edge
    between two faces turned further apart than the smaller of their angles stays hard; 0 is flat shading),
    colours one linear RGB per vertex (a "Color" attribute, exported as COLOR_0) or None."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.update()
    mats = []
    for mat in face_mats:
        if mat not in mats:
            mats.append(mat)
    for mat in mats:
        me.materials.append(mat)
    me.polygons.foreach_set("material_index", [mats.index(m) for m in face_mats])
    if any("uv" in m for m in mats):
        uvs = []
        for f, m in zip(faces, face_mats):
            uvs += [c for uv in face_uvs(verts, f, m) for c in uv]
        me.uv_layers.new(name="UVMap").data.foreach_set("uv", uvs)
    if colours is not None:
        attr = me.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
        attr.data.foreach_set("color", [c for rgb in colours for c in (*rgb[:3], 1.0)])
        me.color_attributes.active_color = attr
        me.color_attributes.render_color_index = 0
    me.shade_smooth()
    _sharpen(me, verts, faces, face_mats, face_sharp)
    me.update()
    return me


def _sharpen(me, verts, faces, face_mats, face_sharp):
    nrm = [_normal([Vector(verts[i]) for i in f]) for f in faces]
    edge_faces = {}
    for fi, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(fi)
    sharp = [False] * len(me.edges)
    for e in me.edges:
        a, b = e.vertices[0], e.vertices[1]
        fs = edge_faces.get((min(a, b), max(a, b)), [])
        if len(fs) != 2 or face_mats[fs[0]] is not face_mats[fs[1]]:
            continue
        limit = min(face_sharp[fs[0]], face_sharp[fs[1]])
        sharp[e.index] = math.degrees(nrm[fs[0]].angle(nrm[fs[1]], 0.0)) > limit
    if any(sharp):
        attr = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
        attr.data.foreach_set("value", sharp)


def bevelled(g, width, segments=2, angle=30.0):
    """g with its edges sharper than angle (degrees) rounded off by width (Blender's Bevel modifier, applied), read
    back as a Geo. A bevelled box weighs about five plain ones in the file."""
    me = bpy.data.meshes.new("blendpipe-bevel")
    me.from_pydata([tuple(v) for v in g.verts], [], [tuple(f) for f in g.faces])
    me.update()
    o = bpy.data.objects.new("blendpipe-bevel", me)
    bpy.context.scene.collection.objects.link(o)
    mod = o.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(angle)
    bpy.context.view_layer.update()
    ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
    out = ev.to_mesh()
    result = Geo([tuple(v.co) for v in out.vertices], [tuple(p.vertices) for p in out.polygons])
    ev.to_mesh_clear()
    bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.meshes.remove(me)
    return result
