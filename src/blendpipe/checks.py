"""The rules every model is held to, on the built scene and again on the written glb. A build collects every
problem, then stops if there is any: fix the model, don't weaken the rule.

What a model's spec turns on (all optional; see the README for the full list):
  tris / tris_min   triangle budget (per variant for a skinned model)
  materials         most materials a model may use
  kb                most kilobytes its glb may weigh
  sockets           the socket kinds it must have, exactly
  ground            (lo, hi): where a static model's lowest point must lie (default (-0.01, 0.01); None: no check)
  footprint         (fx, fy): every vertex lies within f * TILE / 2 + overhang of the origin on x and y (TILE is the
                    project's tile size in metres, default 1.0), so a building stays on its tile
  overhang          metres past the footprint a roof or an awning may reach (default 0)
  height            the highest point of the model, in metres
  fill              (lo, hi): the plan's extent on each axis as a share of the footprint
  floating          metres: every piece of the model (each primitive added to a part) touches the ground, or the
                    bounding box of another piece, within this
  clips             {name: {loop, speed?, contact?, sink?}}: the clips it must have; each starts at frame 0, a loop
                    ends on the pose it starts with, nothing sinks below -sink (default 0.03 m) on any frame, and
                    contact (True, or a share of frames) keeps something on the ground
"""
import ast
import os

import bpy

from . import anim, materials
from .export import EMISSIVE_STRENGTH, EXTENSIONS, LIGHTS, joint_name, read_glb
from .scene import triangles

DEFAULT_GROUND = (-0.01, 0.01)
DEFAULT_SINK = 0.03
DEFAULT_CONTACT = 0.03
DEFAULT_TILE = 1.0
MM = 0.0005             # lengths of the building checks are compared to within half a millimetre

ALLOWED_IMPORTS = {"blendpipe", "math", "mathutils", "random"}
FORBIDDEN_NAMES = {"bpy", "bmesh", "exec", "eval", "open", "compile", "__import__", "globals"}
FORBIDDEN_ATTRIBUTES = {"bpy", "bmesh", "ops", "context"}
NOISE = "mathutils.noise"
NOISE_WHY = ("it draws on a random state shared by the whole session, so a rebuild is not the same; "
             "use random.Random(<number>)")


class Problems:
    def __init__(self):
        self.items = []

    def add(self, text):
        self.items.append(text)

    def __bool__(self):
        return bool(self.items)

    def text(self, title="The models break the rules"):
        return title + ":\n- " + "\n- ".join(self.items)


# ---------------------------------------------------------------- the code

def code(path, problems, allowed=(), root=None):
    """A model module builds from the kit only: it imports only blendpipe, math, mathutils, random and the
    project's own modules (allowed), never Blender itself, and uses randomness only as random.Random(<number>), so a
    rebuild is the same. That rules out mathutils.noise.seed_set and the noise.random functions too, which share one
    random state; the rest of mathutils.noise (noise.noise, turbulence, cell, ...) gives the same value for the same
    input and is fine."""
    name = os.path.relpath(path, root) if root else os.path.basename(path)
    ok = ALLOWED_IMPORTS | set(allowed)
    with open(path) as f:
        tree = ast.parse(f.read(), path)
    imported = _imported(tree)
    for node in ast.walk(tree):
        where = f"{name}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ok:
                    problems.add(f"{where}: imports {alias.name}; a model builds from {sorted(ok)}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").split(".")[0] not in ok:
                problems.add(f"{where}: imports from {node.module}; a model builds from {sorted(ok)}")
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES or alias.name == "*":
                    problems.add(f"{where}: imports {alias.name}")
                if node.module == "random" and alias.name != "Random":
                    problems.add(f"{where}: imports random.{alias.name}; use random.Random(<number>)")
                if node.module == NOISE and _shared_state(f"{NOISE}.{alias.name}"):
                    problems.add(f"{where}: imports {NOISE}.{alias.name}; {NOISE_WHY}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.add(f"{where}: uses {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            problems.add(f"{where}: reaches into Blender through .{node.attr}; build with blendpipe")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "random":
            if node.attr != "Random":
                problems.add(f"{where}: random.{node.attr}; use random.Random(<number>), so a rebuild is the same")
        elif isinstance(node, ast.Attribute) and _shared_state(_dotted(node, imported)):
            problems.add(f"{where}: {_dotted(node, imported)}; {NOISE_WHY}")
        elif isinstance(node, ast.Call) and _called(node) == "Random":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or \
                    not isinstance(node.args[0].value, int) or node.keywords:
                problems.add(f"{where}: Random needs one fixed whole number, so a rebuild is the same")


def _called(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def _imported(tree):
    """What each name the module imports stands for: {"nz": "mathutils.noise", "mu": "mathutils", ...}."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    names[alias.name.split(".")[0]] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _dotted(node, imported):
    """A chain of attributes such as nz.random as the full name its imports give it (mathutils.noise.random), or None
    when it does not start from a plain name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([imported.get(node.id, node.id), *reversed(parts)])


def _shared_state(dotted):
    """Whether a full name is mathutils.noise.seed_set or one of the mathutils.noise.random* functions."""
    module, _, name = (dotted or "").rpartition(".")
    return module == NOISE and (name == "seed_set" or name.startswith("random"))


# ---------------------------------------------------------------- the built model

def model(m, problems, tints=None, tile=DEFAULT_TILE):
    """Every rule of the spec on the built model m (before export). tile: the project's tile size in metres."""
    spec, mid = m.spec, m.id
    skinned = hasattr(m, "geos")
    meshes = m.meshes()
    if not meshes:
        problems.add(f"{mid}: has no mesh")
        return
    if skinned:
        _skinned(m, problems)
    else:
        tris = triangles(meshes)
        if spec.get("tris") is not None and tris > spec["tris"]:
            problems.add(f"{mid}: {tris} triangles, at most {spec['tris']}")
        if spec.get("tris_min") is not None and tris < spec["tris_min"]:
            problems.add(f"{mid}: {tris} triangles, at least {spec['tris_min']}")
        for o in meshes:
            vol = closed_volume(o)
            if vol is not None and vol <= 0:
                problems.add(f"{mid}: part {o.get('part')} is inside out (volume {vol:.5f}); its faces must run "
                             "counter-clockwise seen from outside")
    mats = {mat.name: mat for o in meshes for mat in o.data.materials if mat}
    if spec.get("materials") is not None and len(mats) > spec["materials"]:
        problems.add(f"{mid}: {len(mats)} materials ({sorted(mats)}), at most {spec['materials']}")
    if tints is not None:
        for mat in mats.values():
            role = materials.tint_of(mat)
            if role is not None and role not in tints:
                problems.add(f"{mid}: material {mat.name} has tint {role}, none of the project's {sorted(tints)}")
    if "sockets" in spec:
        kinds = sorted(o["socket"] for o in m.sockets())
        if kinds != sorted(spec["sockets"]):
            problems.add(f"{mid}: sockets {kinds}, the spec says {sorted(spec['sockets'])}")
    if m.root.get("model") != mid:
        problems.add(f"{mid}: its root's extras say model {m.root.get('model')}")
    clips = spec.get("clips", {})
    if sorted(m.clips) != sorted(clips):
        problems.add(f"{mid}: clips {sorted(m.clips)}, the spec says {sorted(clips)}")
    for name, act in m.clips.items():
        if name in clips:
            _clip(m, name, act, clips[name], problems)
    if not m.clips and m.arm is None:
        lo_hi = spec.get("ground", DEFAULT_GROUND)
        if lo_hi is not None:
            low = min((o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices)
            if not lo_hi[0] <= low <= lo_hi[1]:
                problems.add(f"{mid}: its lowest point is at {low:.3f} m; it must stand on the ground "
                             f"(between {lo_hi[0]} and {lo_hi[1]})")
    building(m, problems, tile)


def closed_volume(o):
    """The signed volume of a closed mesh object (positive when its faces point outwards), or None if it is open."""
    me = o.data
    edges = {}
    for p in me.polygons:
        vs = list(p.vertices)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            key = (min(a, b), max(a, b))
            edges[key] = edges.get(key, 0) + 1
    if not edges or any(c != 2 for c in edges.values()):
        return None
    co = [v.co for v in me.vertices]
    vol = 0.0
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(1, len(vs) - 1):
            vol += co[vs[0]].dot(co[vs[i]].cross(co[vs[i + 1]])) / 6
    return vol


def _skinned(m, problems):
    spec, mid = m.spec, m.id
    meshes = m.meshes()
    names = [o.get("variant") for o in meshes]
    if names != list(m.variants):
        problems.add(f"{mid}: variant meshes {names}, the spec says {m.variants}")
    bones = set(m.rig.order)
    for o in meshes:
        v = o.get("variant")
        tris = triangles([o])
        if spec.get("tris") is not None and tris > spec["tris"]:
            problems.add(f"{mid}/{v}: {tris} triangles, at most {spec['tris']}")
        if spec.get("tris_min") is not None and tris < spec["tris_min"]:
            problems.add(f"{mid}/{v}: {tris} triangles, at least {spec['tris_min']}")
        groups = {vg.name for vg in o.vertex_groups}
        if groups - bones:
            problems.add(f"{mid}/{v}: vertex groups {sorted(groups - bones)} are not bones")
        bad = sum(1 for vert in o.data.vertices
                  if not 1 <= len([g for g in vert.groups if g.weight > 0]) <= 4
                  or abs(sum(g.weight for g in vert.groups) - 1) > 2e-3)
        if bad:
            problems.add(f"{mid}/{v}: {bad} vertices without 1..4 weights summing to 1")
        if not any(md.type == "ARMATURE" and md.object == m.arm for md in o.modifiers):
            problems.add(f"{mid}/{v}: not bound to the armature")


def _clip(m, name, act, cspec, problems):
    start, end = int(act.frame_start), int(act.frame_end)
    if start != 0 or end < 2:
        problems.add(f"{m.id}: clip {name} runs frames {start}..{end}; a clip starts at 0")
        return
    if cspec.get("loop"):
        comps = {}
        for fc in anim.channels(act):
            comps.setdefault(fc.data_path, {})[fc.array_index] = fc
        for path, cs in comps.items():
            a = [cs[i].evaluate(start) for i in sorted(cs)]
            b = [cs[i].evaluate(end) for i in sorted(cs)]
            if path.endswith("rotation_quaternion"):
                same = abs(sum(x * y for x, y in zip(a, b))) > 1 - 1e-6
            else:
                same = all(abs(x - y) < 1e-5 for x, y in zip(a, b))
            if not same:
                problems.add(f"{m.id}: loop {name} ends on another pose than it starts ({path})")
                break
    sink = cspec.get("sink", DEFAULT_SINK)
    contact = cspec.get("contact")
    if sink is None and not contact:
        return
    lows = []
    for f in range(end + 1):
        anim.play(m, name, f)
        lows.append(_lowest_now(m))
    anim.rest(m)
    worst = min(range(len(lows)), key=lambda f: lows[f])
    if sink is not None and lows[worst] < -sink:
        problems.add(f"{m.id}: clip {name} sinks {-lows[worst]:.3f} m into the ground (frame {worst})")
    if contact:
        tol = cspec.get("contact_tolerance", DEFAULT_CONTACT)
        share = 1.0 if contact is True else float(contact)
        down = [f for f, z in enumerate(lows) if z <= tol]
        if len(down) < share * len(lows) - 1e-9:
            off = [f for f in range(len(lows)) if f not in down]
            problems.add(f"{m.id}: clip {name} leaves the ground on frames {off[:8]}{'…' if len(off) > 8 else ''} "
                         f"(it must touch it on {share:.0%} of its frames)")


def _lowest_now(m):
    """The lowest point of the model as Blender has posed it now (world space)."""
    if hasattr(m, "geos"):
        from .skin import posed
        return float(posed(m)[:, 2].min())
    low = 1e9
    for o in m.meshes():
        mw = o.matrix_world
        low = min(low, min((mw @ v.co).z for v in o.data.vertices))
    return low


# ---------------------------------------------------------------- buildings (all opt-in)

def building(m, problems, tile=DEFAULT_TILE):
    """The rules for a model that stands on a tile: footprint (with overhang), height, fill and floating. A spec
    without those keys is not looked at. Lengths are metres, in world space, compared to within MM."""
    spec, mid = m.spec, m.id
    if all(spec.get(k) is None for k in ("footprint", "overhang", "height", "fill", "floating")):
        return
    foot = _pair(mid, spec, "footprint", problems, lambda a, b: a > 0 and b > 0, "two numbers above 0, (fx, fy)")
    fill = _pair(mid, spec, "fill", problems, lambda lo, hi: 0 <= lo <= hi, "two numbers, (lo, hi) with 0 <= lo <= hi")
    overhang = _metres(mid, spec, "overhang", problems)
    height = _metres(mid, spec, "height", problems)
    tol = _metres(mid, spec, "floating", problems)
    if spec.get("footprint") is None:
        for key in ("overhang", "fill"):
            if spec.get(key) is not None:
                problems.add(f"{mid}: {key} is set without a footprint")
    bpy.context.view_layer.update()         # so that a part hung from a bone is where the rig holds it now
    worlds = [(o, [tuple(o.matrix_world @ v.co) for v in o.data.vertices]) for o in m.meshes()]
    pts = [p for _, ps in worlds for p in ps]
    if not pts:
        return
    if foot:
        _footprint(mid, pts, foot, overhang or 0.0, tile, problems)
        if fill:
            _fill(mid, pts, foot, fill, tile, problems)
    top = max(p[2] for p in pts)
    if height is not None and top > height + MM:
        problems.add(f"{mid}: height: the highest point is at z = {top:.3f}, {top - height:.3f} over the limit "
                     f"({height:.3f})")
    if tol is not None:
        _floating(mid, worlds, tol, problems)
    # grow="tier" needs model params, which come in a later change; it goes here.


def _pair(mid, spec, key, problems, ok, rule):
    """spec[key] as two floats, or None when it is not set or not what it should be (which is a problem)."""
    value = spec.get(key)
    if value is None:
        return None
    try:
        a, b = (float(v) for v in value)
    except (TypeError, ValueError):
        a = b = None
    if a is None or not ok(a, b):
        problems.add(f"{mid}: {key} is {value!r}; it must be {rule}")
        return None
    return a, b


def _metres(mid, spec, key, problems):
    """spec[key] as a float number of metres, or None when it is not set or not 0 or more (which is a problem)."""
    value = spec.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        problems.add(f"{mid}: {key} is {value!r}; it must be a number of metres, 0 or more")
        return None
    return float(value)


def _footprint(mid, pts, foot, overhang, tile, problems):
    """Every vertex within f * tile / 2 + overhang of the origin on x and y: the worst one on each side is named."""
    edge = "tile edge plus overhang" if overhang else "tile edge"
    for axis, k in (("x", 0), ("y", 1)):
        limit = foot[k] * tile / 2 + overhang
        lo, hi = min(p[k] for p in pts), max(p[k] for p in pts)
        for at, past in ((lo, -lo - limit), (hi, hi - limit)):
            if past > MM:
                problems.add(f"{mid}: footprint: vertex at {axis} = {at:.3f} is {past:.3f} past the {edge} "
                             f"({limit:.3f})")


def _fill(mid, pts, foot, fill, tile, problems):
    """The plan's extent on each axis, as a share of the footprint (without any overhang), within the range."""
    for axis, k in (("x", 0), ("y", 1)):
        size = foot[k] * tile
        extent = max(p[k] for p in pts) - min(p[k] for p in pts)
        if not fill[0] * size - MM <= extent <= fill[1] * size + MM:
            problems.add(f"{mid}: fill: the plan along {axis} spans {extent:.3f} m, {extent / size:.2f} of the "
                         f"footprint ({size:.3f} m); the range is {fill[0]:g} to {fill[1]:g} "
                         f"({fill[0] * size:.3f} to {fill[1] * size:.3f} m)")


def _floating(mid, worlds, tol, problems):
    """Every piece touches z 0 or the bounding box of another piece, within tol. A piece is a set of faces joined by
    shared vertices: each primitive added to a part, whatever mesh the part ends up in."""
    pieces = [(o.get("part"), lo, hi) for o, pts in worlds for lo, hi in _pieces(o, pts)]
    for i, (part, lo, hi) in enumerate(pieces):
        near = max(lo[2], -hi[2], 0.0)      # the distance to the ground
        for j, (_, lo2, hi2) in enumerate(pieces):
            if near <= tol + MM:
                break
            if j != i:
                near = min(near, max(max(c - b, a - d, 0.0) for a, b, c, d in zip(lo, hi, lo2, hi2)))
        if near > tol + MM:
            at = ", ".join(f"{(a + b) / 2:.3f}" for a, b in zip(lo, hi))
            problems.add(f"{mid}: floating: a piece of part {part} around ({at}) is {near:.3f} m clear of the ground "
                         f"and of every other piece, at most {tol:g} m allowed")


def _pieces(o, pts):
    """The pieces of mesh o (its vertices at pts, in world space) as boxes (lo, hi)."""
    root = list(range(len(pts)))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for poly in o.data.polygons:
        first = find(poly.vertices[0])
        for v in poly.vertices[1:]:
            root[find(v)] = first
    boxes = {}
    for i in sorted({v for poly in o.data.polygons for v in poly.vertices}):
        lo, hi = boxes.setdefault(find(i), (list(pts[i]), list(pts[i])))
        for k in range(3):
            lo[k] = min(lo[k], pts[i][k])
            hi[k] = max(hi[k], pts[i][k])
    return list(boxes.values())


# ---------------------------------------------------------------- the files

def raw_export(m, doc, problems):
    """Blender's export, before compression: one glTF animation per clip, named after it, as long as the clip.
    (Catches clips of other models leaking into this file.)"""
    anims = {a.get("name"): a for a in doc.get("animations", [])}
    if sorted(anims) != sorted(m.clips):
        problems.add(f"{m.id}: the export has animations {sorted(anims)}, the model's clips are {sorted(m.clips)}")
        return
    for name, a in anims.items():
        want = (m.clips[name].frame_end - m.clips[name].frame_start) / m.fps
        got = max(doc["accessors"][s["input"]]["max"][0] for s in a["samplers"])
        if abs(got - want) > 1e-3:
            problems.add(f"{m.id}: animation {name} lasts {got:.3f} s, the clip {want:.3f} s")


def file(m, path, problems, max_images=None, extensions=()):
    """The written glb: its size, its extensions (meshopt and quantisation; lights and emission strength when the
    model has them; the project's EXTENSIONS), and that what the app reads survived compression: the root's
    extras, sockets, animations and their lengths, a skinned model's variants and shared skin."""
    mid, spec = m.id, m.spec
    base = os.path.basename(path)
    kb = os.path.getsize(path) / 1024
    if spec.get("kb") is not None and kb > spec["kb"] and not path.endswith("-far.glb"):
        problems.add(f"{base}: {kb:.1f} KB, at most {spec['kb']}")
    doc, _ = read_glb(path)
    allowed = EXTENSIONS | set(extensions)
    if any(o.type == "LIGHT" for o in m.tree()):
        allowed.add(LIGHTS)
    if any(_glows(mat) for o in m.meshes() for mat in o.data.materials if mat):
        allowed.add(EMISSIVE_STRENGTH)
    for ext in set(doc.get("extensionsUsed", [])) - allowed:
        problems.add(f"{base}: uses {ext}; only {sorted(allowed)}")
    nodes = doc.get("nodes", [])
    top = [nodes[i] for i in doc["scenes"][doc.get("scene", 0)]["nodes"]]
    roots = [n for n in top if n.get("extras", {}).get("model") == mid]
    if len(roots) != 1:
        problems.add(f"{base}: no single top-level node with extras model={mid}")
        return
    sockets = sorted(n["extras"]["socket"] for n in nodes if "socket" in n.get("extras", {}))
    if sockets != sorted(o["socket"] for o in m.sockets()):
        problems.add(f"{base}: sockets {sockets} after compression")
    anims = {a.get("name"): a for a in doc.get("animations", [])}
    if sorted(anims) != sorted(m.clips):
        problems.add(f"{base}: animations {sorted(anims)}, the model's clips are {sorted(m.clips)}")
    for name, a in anims.items():
        if name in m.clips:
            want = (m.clips[name].frame_end - m.clips[name].frame_start) / m.fps
            got = max(doc["accessors"][s["input"]]["max"][0] for s in a["samplers"])
            if abs(got - want) > 0.02:
                problems.add(f"{base}: animation {name} lasts {got:.3f} s after compression, the clip {want:.3f} s")
    if hasattr(m, "geos"):
        _skinned_file(m, base, doc, problems)
    else:
        for n in nodes:
            if "part" in n.get("extras", {}) and ("mesh" not in n or n.get("children")):
                problems.add(f"{base}: part {n['extras']['part']} does not hold its mesh itself")
    for img in doc.get("images", []):
        if img.get("mimeType") != "image/png" or "bufferView" not in img:
            problems.add(f"{base}: image {img.get('name')} is not an embedded PNG")
    if max_images is not None and len(doc.get("images", [])) > max_images:
        problems.add(f"{base}: {len(doc['images'])} images, at most {max_images}")


def _glows(mat):
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    return bool(bsdf) and bsdf.inputs["Emission Strength"].default_value > 0


def _skinned_file(m, base, doc, problems):
    nodes = doc["nodes"]
    vs = [n for n in nodes if "variant" in n.get("extras", {})]
    if [n["extras"]["variant"] for n in vs] != list(m.variants):
        problems.add(f"{base}: variant nodes {[n['extras'].get('variant') for n in vs]}, want {m.variants}")
    skins = {n.get("skin") for n in vs}
    if len(skins) != 1 or None in skins:
        problems.add(f"{base}: the variants use skins {skins}; they must share one")
        return
    sk = doc["skins"][skins.pop()]
    joints = [nodes[j].get("name") for j in sk["joints"]]
    want = [joint_name(b) for b in m.rig.order]
    if sorted(joints) != sorted(want):
        problems.add(f"{base}: skin joints {joints}, the rig's bones are {want}")
    for n in vs:
        for prim in doc["meshes"][n["mesh"]]["primitives"]:
            attrs = prim["attributes"]
            if "JOINTS_1" in attrs or "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                problems.add(f"{base}: variant {n['extras']['variant']} has attributes {sorted(attrs)}")
            mat = doc["materials"][prim["material"]] if "material" in prim else {}
            pbr = mat.get("pbrMetallicRoughness", {})
            maps = [t for t in (pbr.get("baseColorTexture"), mat.get("normalTexture")) if t is not None]
            if maps and "TEXCOORD_0" not in attrs:
                problems.add(f"{base}: a textured material on a primitive without TEXCOORD_0")


def total(out_dir, max_kb, problems):
    """The size of every glb under out_dir together (bytes); a problem past max_kb."""
    size = 0
    for d, _, files in os.walk(out_dir):
        size += sum(os.path.getsize(os.path.join(d, f)) for f in files if f.endswith(".glb"))
    if max_kb is not None and size / 1024 > max_kb:
        problems.add(f"all glbs under {out_dir}: {size / 1024:.0f} KB, at most {max_kb}")
    return size

