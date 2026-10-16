"""Deterministic geometry: vertex and face lists in a fixed order, built without bpy.ops.

Blender's own primitive operators make their faces in a different order on each run, which breaks byte-for-byte
rebuilds; everything here is plain maths on lists, so the same call always gives the same mesh. Only `mathutils` is
needed (bundled with Blender, or `pip install mathutils`).

Conventions: metres, z up, a model faces -y (glTF +z after export), its left is +x. Faces run counter-clockwise seen
from outside, so closed shapes face outwards (their signed volume is positive): materials are single-sided by
default, and a face built the wrong way round shows as a hole.

Every primitive returns a `Geo`; most take `loc` and `rot` (Euler degrees x, y, z) or a 4x4 matrix `m` (see `xf`).
"""
import math

from mathutils import Euler, Matrix, Quaternion, Vector


# ---------------------------------------------------------------- placement

def xf(loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0):
    """A 4x4 placement: rot is Euler degrees (x, y, z), a Quaternion or a 3x3 Matrix; scale a number or (x, y, z)."""
    if isinstance(rot, Quaternion):
        r = rot.to_matrix().to_4x4()
    elif isinstance(rot, Matrix):
        r = rot.to_4x4()
    else:
        r = Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
    s = (scale,) * 3 if isinstance(scale, (int, float)) else tuple(scale)
    return Matrix.Translation(loc) @ r @ Matrix.Diagonal((*s, 1.0))


def basis(x_to, y_to, z_to, loc=(0, 0, 0)):
    """A 4x4 sending the local axes to x_to, y_to, z_to; refused if it would mirror (faces would turn inside out)."""
    m = Matrix((x_to, y_to, z_to)).transposed()
    if m.determinant() <= 0:
        raise ValueError(f"basis {x_to}, {y_to}, {z_to} mirrors; faces would turn inside out")
    out = m.to_4x4()
    out.translation = Vector(loc)
    return out


def frame_to(axis, up=None):
    """A 3x3 rotation turning +z onto axis, with +y as close to up as it can be (default: -y, else +z)."""
    a = Vector(axis).normalized()
    ref = Vector(up) if up is not None else Vector((0, -1, 0))
    if abs(a.dot(ref.normalized())) > 0.98:
        ref = Vector((0, 0, 1)) if abs(a.z) < 0.9 else Vector((0, -1, 0))
    y = (ref - a * ref.dot(a)).normalized()
    x = y.cross(a)
    return Matrix((x, y, a)).transposed()


def square_axes(direction, ref=(0, -1, 0)):
    """Two axes (x, y) square to direction, x as near ref as it can be, with x cross y = direction."""
    d = Vector(direction).normalized()
    r = Vector(ref)
    if abs(r.normalized().dot(d)) > 0.97:
        r = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((0, -1, 0))
    x = (r - d * r.dot(d)).normalized()
    return x, d.cross(x)


def _placement(loc, rot, m):
    if m is not None:
        return m
    if tuple(loc) == (0, 0, 0) and (isinstance(rot, tuple) and rot == (0, 0, 0)):
        return None
    return xf(loc, rot)


# ---------------------------------------------------------------- the mesh

class Geo:
    """Vertices (tuples of floats) and faces (tuples of vertex indices) in a fixed order."""

    def __init__(self, verts=None, faces=None, m=None):
        self.verts = [tuple(m @ Vector(v)) if m is not None else tuple(float(c) for c in v) for v in verts or []]
        self.faces = [tuple(f) for f in faces or []]

    def add(self, other, m=None):
        """Appends another Geo (moved by the 4x4 m, when given); returns self, so adds chain."""
        base = len(self.verts)
        self.verts += [tuple(m @ Vector(v)) if m is not None else tuple(v) for v in other.verts]
        self.faces += [tuple(i + base for i in f) for f in other.faces]
        return self

    def copy(self):
        return Geo(self.verts, self.faces)

    def transformed(self, m):
        return Geo(self.verts, self.faces, m)

    def mirrored_x(self):
        """The shape mirrored to the other side (x negated), its faces turned back outwards."""
        return Geo([(-x, y, z) for x, y, z in self.verts], [tuple(reversed(f)) for f in self.faces])

    def tris(self):
        return sum(len(f) - 2 for f in self.faces)

    def bounds(self):
        """(lo, hi) corners of the axis-aligned box around the vertices."""
        xs, ys, zs = zip(*self.verts)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def is_closed(self):
        """Whether every edge is shared by exactly two faces (a watertight shell)."""
        edges = {}
        for f in self.faces:
            for a, b in zip(f, f[1:] + f[:1]):
                key = (min(a, b), max(a, b))
                edges[key] = edges.get(key, 0) + 1
        return bool(edges) and all(c == 2 for c in edges.values())

    def volume(self):
        """The signed volume (positive when a closed shape faces outwards)."""
        co = [Vector(v) for v in self.verts]
        vol = 0.0
        for f in self.faces:
            for i in range(1, len(f) - 1):
                vol += co[f[0]].dot(co[f[i]].cross(co[f[i + 1]])) / 6
        return vol


def polyhedron(verts, faces, m=None):
    """Any shape given as vertices and faces (counter-clockwise seen from outside)."""
    return Geo(verts, faces, m)


# ---------------------------------------------------------------- turned shapes

def _ring(n, rx, ry, z, spin=0.0, power=2.0):
    out = []
    for i in range(n):
        c, s = math.cos(spin + i / n * math.tau), math.sin(spin + i / n * math.tau)
        if power != 2.0:        # a superellipse: straighter sides, rounder corners
            c = math.copysign(abs(c) ** (2 / power), c)
            s = math.copysign(abs(s) ** (2 / power), s)
        out.append((rx * c, ry * s, z))
    return out


def lathe(profile, n=8, *, loc=(0, 0, 0), rot=(0, 0, 0), m=None, spin=None, ry=None, power=2.0, caps=True):
    """A turned shape about z: profile [(r, z), ...] from the bottom up; an r of 0 closes it with a point there.
    ry scales the y radii (an oval); power above 2 squares the rings off (a superellipse); caps=False leaves the
    ends open (a band). n is the number of sides."""
    spin = math.pi / n if spin is None else spin
    verts, rings = [], []
    for r, z in profile:
        if r == 0:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
        else:
            rings.append(list(range(len(verts), len(verts) + n)))
            verts += _ring(n, r, r * (ry if ry is not None else 1.0), z, spin, power)
    faces = []
    if caps and len(rings[0]) > 1:
        faces.append(tuple(reversed(rings[0])))
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1 and len(b) > 1:
            faces += [(a[0], b[(i + 1) % n], b[i]) for i in range(n)]
        elif len(b) == 1 and len(a) > 1:
            faces += [(a[i], a[(i + 1) % n], b[0]) for i in range(n)]
        elif len(a) > 1:
            faces += [(a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]) for i in range(n)]
    if caps and len(rings[-1]) > 1:
        faces.append(tuple(rings[-1]))
    return Geo(verts, faces, _placement(loc, rot, m))


def band(profile, n=8, **kw):
    """An open band about z (a lathe without caps): a skirt, a lampshade, a brim."""
    return lathe(profile, n, caps=False, **kw)


def cylinder(r, h, n=12, *, loc=(0, 0, 0), rot=(0, 0, 0), m=None, r_top=None, caps=True):
    """A cylinder (or a frustum, with r_top) of height h along z, centred on loc."""
    return lathe([(r, -h / 2), (r if r_top is None else r_top, h / 2)], n, loc=loc, rot=rot, m=m, caps=caps)


def cone(r, h, n=12, *, loc=(0, 0, 0), rot=(0, 0, 0), m=None, r_top=0.0):
    """A cone of height h along z, centred on loc; r_top above 0 cuts its tip off."""
    return lathe([(r, -h / 2), (r_top, h / 2)], n, loc=loc, rot=rot, m=m)


def disc(r, n=8, *, loc=(0, 0, 0), rot=(0, 0, 0), m=None):
    """A flat filled circle facing +z (one face): a painted spot, a coin's face, a lid seen from above."""
    verts = _ring(n, r, r, 0.0, math.pi / n)
    return Geo(verts, [tuple(range(n))], _placement(loc, rot, m))


def ball(r, n=8, rings=4, *, loc=(0, 0, 0), scale=(1, 1, 1), rot=(0, 0, 0)):
    """A smooth ellipsoid: a lathe of a half circle (n sides, rings bands from pole to pole)."""
    profile = [(0, -r)] + [(r * math.sin(math.pi * i / rings), -r * math.cos(math.pi * i / rings))
                           for i in range(1, rings)] + [(0, r)]
    return lathe(profile, n, m=xf(loc, rot, scale))


def torus(major, minor, n=16, n_minor=6, *, loc=(0, 0, 0), rot=(0, 0, 0), m=None):
    """A ring about z: major the radius to the tube's middle, minor the tube's. Costs 2 * n * n_minor triangles."""
    verts, faces = [], []
    for i in range(n):
        u = i / n * math.tau
        for j in range(n_minor):
            v = j / n_minor * math.tau
            rr = major + minor * math.cos(v)
            verts.append((rr * math.cos(u), rr * math.sin(u), minor * math.sin(v)))
    for i in range(n):
        for j in range(n_minor):
            a, b = i * n_minor + j, ((i + 1) % n) * n_minor + j
            c, d = ((i + 1) % n) * n_minor + (j + 1) % n_minor, i * n_minor + (j + 1) % n_minor
            faces.append((a, b, c, d))
    return Geo(verts, faces, _placement(loc, rot, m))


# ---------------------------------------------------------------- boxes and limbs

def box(size, loc=(0, 0, 0), rot=(0, 0, 0), taper=(1.0, 1.0), m=None):
    """A box of size (x, y, z) centred on loc; taper scales its top face (x, y)."""
    sx, sy, sz = (s / 2 for s in size)
    tx, ty = taper
    verts = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
             (-sx * tx, -sy * ty, sz), (sx * tx, -sy * ty, sz), (sx * tx, sy * ty, sz), (-sx * tx, sy * ty, sz)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return Geo(verts, faces, m if m is not None else xf(loc, rot))


def box_between(lo, hi):
    """An axis-aligned box from corner lo to corner hi."""
    lo, hi = Vector(lo), Vector(hi)
    return box(tuple(hi - lo), tuple((lo + hi) / 2))


def limb(a, b, ra, rb, n=6, *, spin=None, up=None, caps=True, rya=None, ryb=None):
    """A tapered n-sided prism from point a to point b (radius ra at a, rb at b; rya/ryb make the ends oval)."""
    a, b = Vector(a), Vector(b)
    g = lathe([(ra, 0.0), (rb, (b - a).length)], n, spin=spin, caps=caps)
    if rya is not None or ryb is not None:
        k = [rya if rya is not None else 1.0, ryb if ryb is not None else 1.0]
        g.verts = [(x, y * k[0 if i < n else 1], z) for i, (x, y, z) in enumerate(g.verts)]
    return g.transformed(Matrix.Translation(a) @ frame_to(b - a, up).to_4x4())


# ---------------------------------------------------------------- lumps

_ICO = None


def _icosahedron():
    global _ICO
    if _ICO is None:
        t = (1 + 5 ** 0.5) / 2
        v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
        v = [tuple(c / math.sqrt(1 + t * t) for c in p) for p in v]
        f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11),
             (6, 2, 10), (8, 6, 7), (9, 8, 1)]
        _ICO = (v, f)
    return _ICO


def _subdivide(verts, faces):
    verts = [Vector(v) for v in verts]
    mids, out = {}, []

    def mid(i, j):
        key = (min(i, j), max(i, j))
        if key not in mids:
            mids[key] = len(verts)
            verts.append(((verts[i] + verts[j]) / 2).normalized())
        return mids[key]

    for a, b, c in faces:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        out += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    return [tuple(v) for v in verts], out


def lump(r, *, loc=(0, 0, 0), scale=(1, 1, 1), rot=(0, 0, 0), rng=None, jitter=0.0, subdiv=0, flat_bottom=None):
    """A faceted lump (a rock, a bush): an icosahedron (20 faces; 80 with subdiv 1, 320 with 2) scaled to an
    ellipsoid, each vertex pushed in or out by up to jitter of the radius. rng must be a random.Random(<number>), so
    a rebuild is the same. flat_bottom (-1..1, in the lump's own units) cuts it flat below that height."""
    v, f = _icosahedron()
    for _ in range(subdiv):
        v, f = _subdivide(v, f)
    out = []
    for p in v:
        k = 1.0 + (rng.uniform(-jitter, jitter) if rng and jitter else 0.0)
        x, y, z = (c * k for c in p)
        if flat_bottom is not None and z < flat_bottom:
            z = flat_bottom
        out.append((x * r, y * r, z * r))
    return Geo(out, f, xf(loc, rot, scale))


# ---------------------------------------------------------------- flat shapes

def slab(outline, thickness, m=None, bevel=0.0):
    """A flat convex shape: outline [(x, z), ...] counter-clockwise seen from -y (the front), extruded thickness
    along y and centred on y 0. bevel (0..1) shrinks the back face towards the middle (a rounded shield's edge)."""
    n = len(outline)
    h = thickness / 2
    cx = sum(p[0] for p in outline) / n
    cz = sum(p[1] for p in outline) / n
    front = [(x, -h, z) for x, z in outline]
    back = [(cx + (x - cx) * (1 - bevel), h, cz + (z - cz) * (1 - bevel)) for x, z in outline]
    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((j, i, n + i, n + j))
    return Geo(front + back, faces, m)


def fin(outline, half, x=0.0, m=None):
    """A flat shape in the yz plane (a mane, a crest, a sail): outline [(y, z), ...] counter-clockwise seen from +x,
    half its thickness to either side of x."""
    n = len(outline)
    verts = [(x + half, y, z) for y, z in outline] + [(x - half, y, z) for y, z in outline]
    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((j, i, n + i, n + j))
    return Geo(verts, faces, m)


def strip(points, width, thickness, up=(0, 0, 1)):
    """A thin flat band along points (a bow's limb, a strap): width across (a number, or one per point), thickness
    along up x the direction of travel. Closed at both ends."""
    pts = [Vector(p) for p in points]
    verts, faces = [], []
    up = Vector(up)
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        side = d.cross(up).normalized()
        nrm = side.cross(d).normalized()
        w = width[i] if isinstance(width, (list, tuple)) else width
        for sx, sy in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
            verts.append(tuple(p + side * sx * w / 2 + nrm * sy * thickness / 2))
    for i in range(len(pts) - 1):
        a, b = 4 * i, 4 * (i + 1)
        for k in range(4):
            k2 = (k + 1) % 4
            faces.append((a + k, a + k2, b + k2, b + k))
    faces.append((3, 2, 1, 0))
    e = 4 * (len(pts) - 1)
    faces.append((e, e + 1, e + 2, e + 3))
    return Geo(verts, faces)


# ---------------------------------------------------------------- lofts: rings joined into tubes and shells

def ring(centre, x_axis, y_axis, pts):
    """2D points (x, y) placed in the plane through centre spanned by x_axis and y_axis."""
    c, xa, ya = Vector(centre), Vector(x_axis), Vector(y_axis)
    return [c + xa * x + ya * y for x, y in pts]


def loft(rings, cap_start=False, cap_end=False, closed=True):
    """Joins rings of equal size, each running counter-clockwise about the direction the loft runs (first ring to
    last), so the faces point outwards. closed: the rings are loops (else open strips side by side). Caps close
    the ends with one face each."""
    n = len(rings[0])
    verts = [tuple(v) for r in rings for v in r]
    faces = []
    if cap_start and closed:
        faces.append(tuple(reversed(range(n))))
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n if closed else n - 1):
            k = (j + 1) % n
            faces.append((a + j, a + k, b + k, b + j))
    if cap_end and closed:
        last = (len(rings) - 1) * n
        faces.append(tuple(last + j for j in range(n)))
    return Geo(verts, faces)


def loft_fans(rings, top=None, bottom=None):
    """A loft closed to apex points at either end (bottom: before the first ring, top: after the last)."""
    g = loft(rings)
    n = len(rings[0])
    if bottom is not None:
        g.verts.append(tuple(bottom))
        c = len(g.verts) - 1
        g.faces += [((j + 1) % n, j, c) for j in range(n)]
    if top is not None:
        g.verts.append(tuple(top))
        c = len(g.verts) - 1
        last = (len(rings) - 1) * n
        g.faces += [(last + j, last + (j + 1) % n, c) for j in range(n)]
    return g


def section(n, half_x, front, back, power=2.0, cy=0.0, tweak=None):
    """A horizontal cross-section (2D points), counter-clockwise seen from above, starting at the left (+x): half_x
    across, front (towards -y) and back depths; power above 2 squares it off. tweak(k, angle, x, y) may move a
    point. Place it with ring() and join sections with loft() for a torso, a bottle, a hull."""
    pts = []
    for k in range(n):
        a = math.tau * k / n
        c, s = math.cos(a), math.sin(a)
        x = half_x * math.copysign(abs(c) ** (2 / power), c)
        y = (back if s > 0 else front) * math.copysign(abs(s) ** (2 / power), s)
        if tweak:
            x, y = tweak(k, a, x, y)
        pts.append((x, cy + y))
    return pts


def tube_rings(path, radii, n=8, ref=(0, -1, 0), shape=None):
    """Rings along a polyline path, each square to the path there; radii [(rx, ry), ...] per point (rx along the
    ring's x, nearest ref). shape(i, k, angle) -> (fx, fy) scales a ring point (a bulge on one side)."""
    path = [Vector(p) for p in path]
    rings = []
    for i, p in enumerate(path):
        if i == 0:
            d = path[1] - path[0]
        elif i == len(path) - 1:
            d = path[-1] - path[-2]
        else:
            d = (path[i + 1] - path[i]).normalized() + (path[i] - path[i - 1]).normalized()
        xa, ya = square_axes(d, ref)
        rx, ry = radii[i]
        pts = []
        for k in range(n):
            a = math.tau * k / n
            fx, fy = shape(i, k, a) if shape else (1.0, 1.0)
            pts.append((rx * math.cos(a) * fx, ry * math.sin(a) * fy))
        rings.append(ring(p, xa, ya, pts))
    return rings


def tube(path, radius, n=8, caps=True, ref=(0, -1, 0)):
    """A tube along a polyline (a pipe, a handle, a tail): radius a number, one per point, or (rx, ry) per point.
    For a curve, pass smooth_path(points)."""
    if isinstance(radius, (int, float)):
        radii = [(radius, radius)] * len(path)
    else:
        radii = [(r, r) if isinstance(r, (int, float)) else tuple(r) for r in radius]
    return loft(tube_rings(path, radii, n, ref), cap_start=caps, cap_end=caps)


def smooth_path(points, segments=4):
    """A Catmull-Rom curve through points, segments steps between each two: a smooth path for tube()."""
    pts = [Vector(p) for p in points]
    if len(pts) < 3:
        return [tuple(p) for p in pts]
    ext = [pts[0] * 2 - pts[1], *pts, pts[-1] * 2 - pts[-2]]
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for s in range(segments):
            t = s / segments
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    out.append(tuple(pts[-1]))
    return out


def offset_surface(g, d):
    """g with its vertices pushed d along their (area-weighted) normals: a shell over a surface (hair over a head,
    a coat over a body). Faces keep their order."""
    acc = [Vector() for _ in g.verts]
    co = [Vector(v) for v in g.verts]
    for f in g.faces:
        nrm = Vector()
        for i in range(1, len(f) - 1):
            nrm += (co[f[i]] - co[f[0]]).cross(co[f[i + 1]] - co[f[0]])
        for i in f:
            acc[i] += nrm
    return Geo([tuple(v + (a.normalized() * d if a.length > 1e-12 else Vector())) for v, a in zip(co, acc)], g.faces)
