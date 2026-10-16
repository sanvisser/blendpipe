"""Skinned models: each variant is ONE mesh smoothly weighted to the model's rig (at most four bones a vertex), its
faces in a few materials, its colours as vertex colours the materials multiply in (COLOR_0 in the glb).

Build in the rig's rest space (metres, z up, facing -y, left +x). Add each piece to a variant with a weight rule:
a dict ({"forearm.L": 1.0}), a function of the vertex, a list (one dict per vertex) or a Chain, a run of bones the
piece follows, blended smoothly across each joint. Left-side pieces are built once and added with add_both(), which
mirrors them with their weights swapped to the right side. Variants (heads, builds, kit) share the skeleton,
sockets and clips. Nothing calls bpy.ops and faces come in a fixed order, so a rebuild writes the same bytes.
"""
import bpy
import numpy as np
from mathutils import Vector

from .colour import linear
from .errors import BuildError
from .geo import Geo
from .mesh import build_mesh
from .model import BaseModel

WHITE = (1.0, 1.0, 1.0)


# ---------------------------------------------------------------- weights

def smoothstep(x):
    x = 0.0 if x < 0 else 1.0 if x > 1 else x
    return x * x * (3 - 2 * x)


def blend(a, b, w):
    """Two weight dicts mixed by w (0: a, 1: b)."""
    out = {}
    for k, v in a.items():
        out[k] = out.get(k, 0.0) + v * (1 - w)
    for k, v in b.items():
        out[k] = out.get(k, 0.0) + v * w
    return out


def top4(d):
    """The four strongest bones, normalised; ties broken by name, so the order is fixed."""
    items = sorted(((w, b) for b, w in d.items() if w > 1e-4), key=lambda x: (-x[0], x[1]))[:4]
    total = sum(w for w, _ in items)
    if total <= 0:
        raise BuildError(f"a vertex has no weight: {d}")
    return {b: w / total for w, b in items}


def swap_sides(d, a=".L", b=".R"):
    """A weight dict for the mirrored side: bone names ending in a end in b and the other way round."""
    out = {}
    for bone, w in d.items():
        if bone.endswith(a):
            bone = bone[:-len(a)] + b
        elif bone.endswith(b):
            bone = bone[:-len(b)] + a
        out[bone] = w
    return out


class Chain:
    """A piece that runs along bones: points p0..pn (bones[i] runs from p[i] to p[i+1]) and the half-width of the
    blend at each inner joint. A vertex is weighted by where it projects onto that polyline."""

    def __init__(self, points, bones, blends):
        self.points = [Vector(p) for p in points]
        self.bones = list(bones)
        self.blends = list(blends)
        if len(self.points) != len(self.bones) + 1 or len(self.blends) != len(self.bones) - 1:
            raise BuildError(f"Chain {bones}: {len(points)} points and {len(blends)} blends; it needs "
                             f"{len(self.bones) + 1} and {len(self.bones) - 1}")
        self.lengths = [(b - a).length for a, b in zip(self.points, self.points[1:])]
        self.starts = [sum(self.lengths[:i]) for i in range(len(self.lengths))]

    def param(self, v):
        v = Vector(v)
        best = None
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            ab = b - a
            t = 0.0 if ab.length < 1e-9 else max(0.0, min(1.0, (v - a).dot(ab) / ab.length_squared))
            d = (a + ab * t - v).length
            if best is None or d < best[0] - 1e-9:
                best = (d, self.starts[i] + t * self.lengths[i])
        return best[1]

    def at(self, s):
        """The weights at arc length s along the chain."""
        f = [smoothstep((s - self.starts[j + 1] + h) / (2 * h)) if h > 0 else float(s >= self.starts[j + 1])
             for j, h in enumerate(self.blends)]
        out = {}
        n = len(self.bones)
        for i, b in enumerate(self.bones):
            lo = 1.0 if i == 0 else f[i - 1]
            hi = 0.0 if i == n - 1 else f[i]
            if lo - hi > 1e-6:
                out[b] = out.get(b, 0.0) + lo - hi
        return out

    def __call__(self, v):
        return self.at(self.param(v))


# ---------------------------------------------------------------- a variant's mesh

def _per_vertex(rule, verts, kind):
    out = []
    for i, v in enumerate(verts):
        if callable(rule):
            out.append(rule(Vector(v)) if kind == "weights" else rule(Vector(v), i))
        elif isinstance(rule, list):
            out.append(rule[i])
        else:
            out.append(rule)
    return out


class SkinGeo:
    """A variant's mesh under construction: vertices with weights and colours, faces with a material and a
    smoothing angle (edges sharper than it stay hard)."""

    def __init__(self):
        self.verts, self.weights, self.colours = [], [], []
        self.faces, self.mats, self.sharp = [], [], []

    def add(self, g, mat, weights, col=WHITE, sharp=75.0):
        """Adds Geo g (rest space) in material mat. weights: a dict, a function of the vertex (a Chain), or one
        dict per vertex. col: a colour ('#rrggbb', a grey 0..1 or linear rgb), a function of (vertex, index), or
        one per vertex. Returns self."""
        ws = _per_vertex(weights, g.verts, "weights")
        cs = _per_vertex(col, g.verts, "colours")
        return self._append(g, mat, ws, cs, sharp)

    def add_both(self, g, mat, weights, col=WHITE, sharp=75.0, sides=(".L", ".R")):
        """Adds a left-side piece and its mirror on the right, the mirror's weights on the other side's bones."""
        ws = _per_vertex(weights, g.verts, "weights")
        cs = _per_vertex(col, g.verts, "colours")
        self._append(g, mat, ws, cs, sharp)
        return self._append(g.mirrored_x(), mat, [swap_sides(w, *sides) for w in ws], cs, sharp)

    def _append(self, g, mat, ws, cs, sharp):
        base = len(self.verts)
        self.verts += [Vector(v) for v in g.verts]
        self.weights += [top4(w) for w in ws]
        self.colours += [linear(c) for c in cs]
        self.faces += [tuple(i + base for i in f) for f in g.faces]
        self.mats += [mat] * len(g.faces)
        self.sharp += [sharp] * len(g.faces)
        return self

    def tris(self):
        return sum(len(f) - 2 for f in self.faces)

    def geo(self):
        return Geo([tuple(v) for v in self.verts], self.faces)


# ---------------------------------------------------------------- the model

class SkinModel(BaseModel):
    """A skinned model: the root (its extras), the armature, one mesh per variant bound to it, sockets on bones."""

    def __init__(self, mid, spec=None):
        super().__init__(mid, spec)
        self.variants = list(self.spec.get("variants") or ["default"])
        self.root["variants"] = list(self.variants)
        self.geos = {}
        self._lbs = {}

    def variant(self, name="default"):
        """The SkinGeo of variant name (one of the spec's variants)."""
        if name not in self.variants:
            raise BuildError(f"{self.id}: variant {name} is none of {self.variants}")
        if name not in self.geos:
            self.geos[name] = SkinGeo()
        return self.geos[name]

    def finish(self, join=False):
        missing = [v for v in self.variants if v not in self.geos]
        if missing:
            raise BuildError(f"{self.id}: variants {missing} were never built")
        if self.arm is None:
            raise BuildError(f"{self.id}: a skinned model needs a rig (spec rig=...)")
        for idx, name in enumerate(self.variants):
            g = self.geos[name]
            if not g.faces:
                raise BuildError(f"{self.id}: variant {name} is empty")
            me = build_mesh(f"{self.id}-{name}", g.verts, g.faces, g.mats, g.sharp, g.colours)
            o = bpy.data.objects.new(self._unique(f"{self.id}-{name}"), me)
            bpy.context.scene.collection.objects.link(o)
            o.parent = self.arm
            o["variant"] = name
            o["index"] = idx
            for b in self.rig.order:
                o.vertex_groups.new(name=b)
            groups = {b: o.vertex_groups[b] for b in self.rig.order}
            for i, w in enumerate(g.weights):
                for b, x in w.items():
                    if b not in groups:
                        raise BuildError(f"{self.id}/{name}: a vertex is weighted to {b}, which the rig does not have")
                    groups[b].add([i], x, "REPLACE")
            mod = o.modifiers.new("Armature", "ARMATURE")
            mod.object = self.arm
            self.objects.append(o)

    def parts(self):
        return self.meshes()

    # ---- linear blend skinning in numpy, as the GPU does it: grounding poses while writing clips, and checks

    def lbs_data(self, name=None):
        name = name or self.variants[0]
        if name not in self._lbs:
            g = self.geos[name]
            index = {b: i for i, b in enumerate(self.rig.order)}
            V = np.array([tuple(v) for v in g.verts], dtype=np.float64)
            J = np.zeros((len(g.verts), 4), dtype=np.int64)
            W = np.zeros((len(g.verts), 4), dtype=np.float64)
            for i, w in enumerate(g.weights):
                for k, (b, x) in enumerate(sorted(w.items())):
                    J[i, k], W[i, k] = index[b], x
            self._lbs[name] = (V, J, W)
        return self._lbs[name]

    def deform(self, mats, name=None):
        """Rest vertices of a variant moved by per-bone 4x4 matrices (rig order, armature space)."""
        V, J, W = self.lbs_data(name)
        M = np.asarray(mats)
        R, T = M[:, :3, :3], M[:, :3, 3]
        out = np.zeros_like(V)
        for k in range(4):
            out += W[:, k:k + 1] * (np.einsum("nij,nj->ni", R[J[:, k]], V) + T[J[:, k]])
        return out

    def lowest(self, pose, name=None):
        """The lowest z of a variant in pose (armature space): to stand a pose on the ground while writing a clip."""
        return float(self.deform(pose_matrices(self.rig, pose), name)[:, 2].min())


def pose_matrices(rig, pose):
    """Per-bone deform matrices (rig order, armature space) of a Pose: v' = P + D (v - head)."""
    D, P = pose.solve()
    out = []
    for b in rig.order:
        m = D[b].to_matrix().to_4x4()
        m.translation = P[b] - D[b] @ rig.heads[b]
        out.append(np.array(m))
    return out


def blender_matrices(arm, rig):
    """Per-bone deform matrices of the armature as Blender has posed it now (armature space)."""
    return [np.array(arm.pose.bones[b].matrix @ arm.data.bones[b].matrix_local.inverted()) for b in rig.order]


def posed(m, name=None):
    """A skinned model's variant as Blender has posed it now, in world space (n x 3)."""
    pts = m.deform(blender_matrices(m.arm, m.rig), name)
    mw = np.array(m.arm.matrix_world)
    return pts @ mw[:3, :3].T + mw[:3, 3]

