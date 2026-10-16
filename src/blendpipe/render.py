"""Review renders (EEVEE, headless; Cycles on the CPU where Blender gets no GPU, see choose_renderer): a sheet per
model, a lineup of every model at one scale, and thumbnails.

A model's sheet (<dir>/<id>.png) shows, top to bottom: a title with its triangles; a 3/4 view of every variant
beside a 2 m ruler and its back; each of its groups on its own; six frames of every clip from the side-front. The
lineup (<dir>/lineup.png) stands every model side by side, so their sizes can be compared. Look at the sheets after
every change: they catch what no check can (a hat floating off a head, a leg passing through a table).

Tinted materials are greys the app colours: the renders multiply them by the project's TINTS, and skinned meshes'
vertex colours are multiplied in as glTF's COLOR_0 is. Renders happen after the export, so none of this reaches
the files.
"""
import math
import os
import re
import subprocess

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

from . import anim, materials
from .colour import srgb
from .errors import BuildError
from .scene import descendants, triangles
from .tools import RENDERERS

BACKGROUND = "#2b2f36"
GROUND = "#6d7a4c"
SKY = "#b9c7d8"
LABEL = "#e9e4d6"
GAP = 6

ENGINES = {"eevee": "BLENDER_EEVEE", "cycles": "CYCLES"}
SOFTWARE_GL = re.compile(r"llvmpipe|softpipe|swrast|lavapipe|software", re.I)    # Mesa's CPU rasterisers
CYCLES_SAMPLES = 0.25           # Cycles samples per EEVEE sample: its denoiser makes up the rest

# Run in a second Blender (see probe_gpu)
_PROBE = """\
import gpu
if hasattr(gpu, "init"):
    gpu.init()
    print("gpu:", gpu.platform.backend_type_get(), "|", gpu.platform.renderer_get())
else:
    print("gpu: unknown")
"""


def probe_gpu():
    """The GPU Blender gets in the background ("OPENGL | llvmpipe (LLVM 20.1.2, 256 bits)"), "unknown" if this
    Blender cannot be asked (gpu.init is newer than 5.0), or None when it gets none. A second Blender is asked:
    gpu.init() crashes Blender itself, which no try/except catches, when there is no OpenGL 4.3 (none installed,
    or a Mesa that is too old)."""
    cmd = [bpy.app.binary_path, "--background", "--factory-startup", "--disable-crash-handler", "--python-expr",
           _PROBE]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^gpu: (.+)$", done.stdout, re.M)
    return m.group(1) if m and done.returncode == 0 else None


def choose_renderer(want="auto"):
    """"eevee" or "cycles": the engine the renders use, after saying which and why. auto: EEVEE where Blender gets
    a GPU, Cycles on the CPU where it does not (EEVEE needs OpenGL 4.3, Metal or Vulkan) or only gets Mesa's CPU
    rasteriser (EEVEE runs on that, but slower than Cycles). want "eevee" or "cycles" skips the question."""
    if want not in RENDERERS:
        raise BuildError(f"the renderer is one of {', '.join(RENDERERS)}, not {want}")
    if want != "auto":
        print(f"renderer: {want} (asked for)")
        return want
    gpu = probe_gpu()
    if gpu is None:
        print("renderer: cycles on the CPU (Blender gets no GPU context here, and EEVEE needs one; "
              "--renderer eevee tries it anyway)")
        return "cycles"
    if SOFTWARE_GL.search(gpu):
        print(f"renderer: cycles on the CPU (Blender only gets {gpu}, which runs EEVEE slowly; "
              "--renderer eevee uses it anyway)")
        return "cycles"
    print("renderer: eevee" + ("" if gpu == "unknown" else f" on {gpu}"))
    return "eevee"


def _setup(engine="eevee"):
    scene = bpy.context.scene
    scene.render.engine = ENGINES[engine]
    scene.eevee.taa_render_samples = 24
    if engine == "cycles":
        cycles = scene.cycles
        cycles.device = "CPU"
        cycles.use_denoising = True
        cycles.denoiser = "OPENIMAGEDENOISE"
        cycles.max_bounces = 2          # as bright as 12 to the eye, and EEVEE has no more than a bounce either
        cycles.seed = 0
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "AgX"
    scene.render.resolution_percentage = 100
    world = bpy.data.worlds.new("blendpipe-sky")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = srgb(SKY)
    bg.inputs[1].default_value = 0.9
    sun_data = bpy.data.lights.new("blendpipe-sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(4)
    sun_data.color = srgb("#fff3dc")[:3]
    sun = bpy.data.objects.new("blendpipe-sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(50), 0, math.radians(-35)))
    me = bpy.data.meshes.new("blendpipe-ground")
    s = 60.0
    me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("blendpipe-ground", me)
    scene.collection.objects.link(ground)
    me.materials.append(_flat("blendpipe-ground", GROUND))
    cam = bpy.data.objects.new("blendpipe-camera", bpy.data.cameras.new("blendpipe-camera"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    return sun, ground, cam


def _flat(name, hex_, emit=None):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = srgb(hex_)
    bsdf.inputs["Roughness"].default_value = 1.0
    if emit:
        bsdf.inputs["Emission Color"].default_value = srgb(emit)
        bsdf.inputs["Emission Strength"].default_value = 1.0
    return m


# ---------------------------------------------------------------- colouring as the app does

def _multiply_node(nt, name):
    mix = nt.nodes.new("ShaderNodeMix")
    mix.name = name
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    a = [s for s in mix.inputs if s.name == "A" and s.type == "RGBA"][0]
    b = [s for s in mix.inputs if s.name == "B" and s.type == "RGBA"][0]
    return a, b, [s for s in mix.outputs if s.type == "RGBA"][0]


def _vertex_colours(mat):
    """Makes a material multiply in its mesh's vertex colours (as COLOR_0 does in the app), and its texture."""
    nt = mat.node_tree
    if "blendpipe-mix" in nt.nodes:
        return
    bsdf = nt.nodes["Principled BSDF"]
    tex = bsdf.inputs["Base Color"].links[0].from_socket if bsdf.inputs["Base Color"].is_linked else None
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Color"
    a, b, out = _multiply_node(nt, "blendpipe-mix")
    b.default_value = bsdf.inputs["Base Color"].default_value[:]
    nt.links.new(attr.outputs["Color"], a)
    if tex is not None:
        a2, b2, out2 = _multiply_node(nt, "blendpipe-texture")
        nt.links.new(out, a2)
        nt.links.new(tex, b2)
        out = out2
    nt.links.new(out, bsdf.inputs["Base Color"])


def tint(tints):
    """Colours every tinted material by its role's colour (tints {role: '#rrggbb'}), as the app would."""
    for mat in materials.all_materials():
        role = materials.tint_of(mat)
        grey = srgb(materials.colour_of(mat))
        colour = grey
        if role is not None and tints and role in tints:
            c = srgb(tints[role])
            colour = tuple(g * k for g, k in zip(grey, c))
        colour = (*colour[:3], 1.0)
        mix = mat.node_tree.nodes.get("blendpipe-mix")
        if mix is not None:
            [s for s in mix.inputs if s.name == "B" and s.type == "RGBA"][0].default_value = colour
        elif not mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].is_linked:
            mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = colour


# ---------------------------------------------------------------- cameras, framing, rendering

def show_only(objs):
    keep = set(objs)
    for o in bpy.context.scene.objects:
        o.hide_render = o not in keep


def aim(cam, elevation, azimuth, centre=(0, 0, 0), distance=40.0):
    """Points an ortho camera at centre from elevation/azimuth (degrees; azimuth 0 looks at the model's front)."""
    e, a = math.radians(elevation), math.radians(azimuth)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = Vector(centre) + d * distance
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.type = "ORTHO"
    cam.data.clip_end = 500
    return cam


def points(objs):
    """The corners of the meshes' boxes as posed (a skinned mesh's box is its deformed one)."""
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type != "MESH":
            continue
        e = o.evaluated_get(dg)
        mw = e.matrix_world
        if o.modifiers:
            me = e.to_mesh()
            vs = [mw @ v.co for v in me.vertices]
            e.to_mesh_clear()
            lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
            hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
            pts += [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
        else:
            pts += [mw @ Vector(c) for c in o.bound_box]
    return pts


def frame(cam, pts, w, h, margin=1.1):
    """Centres the (already aimed) ortho camera on pts for a w x h image; Blender's ortho_scale spans the image's
    longer side."""
    m = cam.rotation_euler.to_matrix()
    right, up, view = m.col[0], m.col[1], -m.col[2]
    xs, ys = [p.dot(right) for p in pts], [p.dot(up) for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span_x, span_y = max((max(xs) - min(xs)) * margin, 1e-3), max((max(ys) - min(ys)) * margin, 1e-3)
    cam.data.ortho_scale = max(span_x, span_y * w / h) if w >= h else max(span_y, span_x * h / w)
    cam.location = right * cx + up * cy - view * 60
    return cam.data.ortho_scale


def render(path, w, h, samples=24, fmt="PNG", quality=85):
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = w, h
    if scene.render.engine == ENGINES["cycles"]:
        scene.cycles.samples = max(2, round(samples * CYCLES_SAMPLES))
    else:
        scene.eevee.taa_render_samples = samples
    scene.render.image_settings.file_format = fmt
    scene.render.image_settings.color_mode = "RGBA"
    if fmt == "WEBP":
        scene.render.image_settings.quality = quality
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def load(path):
    """A rendered PNG as a float array (h, w, 4), row 0 at the top."""
    img = bpy.data.images.load(path)
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)[::-1]


def _hex(c):
    return np.array([int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)], dtype=np.float32)


def compose(rows, path, background=BACKGROUND):
    """Rows of tiles (h x w x 4 float arrays, top row first) laid out on the background, saved as one PNG."""
    rows = [r for r in rows if r]
    width = max(sum(t.shape[1] for t in r) + GAP * (len(r) + 1) for r in rows)
    height = sum(max(t.shape[0] for t in r) for r in rows) + GAP * (len(rows) + 1)
    canvas = np.empty((height, width, 4), dtype=np.float32)
    canvas[...] = [*_hex(background), 1.0]
    y = GAP
    for r in rows:
        x = GAP
        for t in r:
            h, w = t.shape[:2]
            a = t[..., 3:4]
            canvas[y:y + h, x:x + w, :3] = t[..., :3] * a + canvas[y:y + h, x:x + w, :3] * (1 - a)
            x += w + GAP
        y += max(t.shape[0] for t in r) + GAP
    img = bpy.data.images.new("blendpipe-sheet", width, height, alpha=False)
    img.pixels.foreach_set(canvas[::-1].ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    print(f"sheet: {path} ({width} x {height})")
    return path


class Labels:
    """Text tiles: a text object far from the models, shot by the camera turned to it."""

    def __init__(self):
        self.mat = _flat("blendpipe-label", "#000000", emit=LABEL)

    def tile(self, text, w, h, path, size=0.26):
        scene = bpy.context.scene
        curve = bpy.data.curves.new("blendpipe-label", "FONT")
        curve.body = text
        curve.size = size
        curve.align_x, curve.align_y = "LEFT", "CENTER"
        curve.materials.append(self.mat)
        o = bpy.data.objects.new("blendpipe-label", curve)
        scene.collection.objects.link(o)
        o.location = (1000.0, 0.0, 0.0)
        cam = scene.camera
        old = (cam.location.copy(), cam.rotation_euler.copy(), cam.data.ortho_scale)
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = max(w, h) / 100
        cam.rotation_euler = (0, 0, 0)
        cam.location = (1000.0 + w / 200 - 0.12, 0.0, 10.0)
        show_only([o, cam])
        render(path, w, h, samples=4)
        cam.location, cam.rotation_euler, cam.data.ortho_scale = old
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.curves.remove(curve)
        return load(path)


def ruler(at=(0, 0, 0), height=2.0):
    """A post height metres tall with a tick every 10 cm, longer every 50 cm."""
    from .geo import Geo, box
    g = Geo().add(box((0.03, 0.03, height), (0, 0, height / 2)))
    for n in range(int(round(height * 10)) + 1):
        reach = 0.14 if n % 5 == 0 else 0.07
        g.add(box((reach, 0.012, 0.012), (0.015 + reach / 2, 0, n * 0.1)))
    me = bpy.data.meshes.new("blendpipe-ruler")
    me.from_pydata(g.verts, [], g.faces)
    me.materials.append(_flat("blendpipe-ruler", "#f2efe6"))
    o = bpy.data.objects.new("blendpipe-ruler", me)
    bpy.context.scene.collection.objects.link(o)
    o.location = at
    return o


# ---------------------------------------------------------------- what each model shows

class Stage:
    """Everything the renders share: the light, the ground, the camera, labels, and the tints."""

    def __init__(self, tints=None, renderer="auto"):
        self.renderer = choose_renderer(renderer)
        self.sun, self.ground, self.cam = _setup(self.renderer)
        self.labels = Labels()
        self.tints = tints or {}
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and o.data.color_attributes:
                for mat in o.data.materials:
                    _vertex_colours(mat)
        tint(self.tints)

    def shot(self, objs, path, w, h, samples=24):
        show_only([*objs, self.ground, self.sun, self.cam])
        return load(render(path, w, h, samples))


def _variant_tree(m, variant=None):
    """The model's objects with only one variant's mesh (a static model: all of them)."""
    objs = m.tree()
    if hasattr(m, "geos"):
        want = variant or m.variants[0]
        objs = [o for o in objs if o.type != "MESH" or o.get("variant") == want]
    return objs


def _pose(m, clip=None, frame=0):
    if m.arm is not None:
        if clip:
            anim.play(m, clip, frame)
        else:
            anim.rest(m)
    bpy.context.view_layer.update()


def model_sheet(st, m, out_dir, tiles):
    """<out_dir>/<id>.png for model m."""
    cam = st.cam
    clips = list(m.spec.get("clips", {}))
    first = clips[0] if clips else None
    _pose(m, first, 0)
    pts = points(_variant_tree(m))
    reach = max(max(abs(p.x), abs(p.y)) for p in pts)
    rule = ruler((reach + 0.4, 0.4, 0.0))
    rows = [[]]
    for v in (m.variants if hasattr(m, "geos") else [None]):
        objs = _variant_tree(m, v)
        aim(cam, 18, 32)
        frame(cam, pts + points([rule]) + [Vector((0, 0, 0))], 520, 600, 1.08)
        rows[0].append(st.shot([*objs, rule], os.path.join(tiles, f"{m.id}-hero-{v or 'model'}.png"), 520, 600, 48))
    bpy.data.objects.remove(rule, do_unlink=True)
    aim(cam, 18, 200)
    frame(cam, pts + [Vector((0, 0, 0))], 300, 600, 1.08)
    rows[0].append(st.shot(_variant_tree(m), os.path.join(tiles, f"{m.id}-back.png"), 300, 600, 32))

    groups = [o for o in m.root.children if "group" in o]
    if groups:
        loose = [o for o in m.tree() if not any(o == g or o in descendants(g) for g in groups)]
        row = []
        for g in groups:
            objs = [*loose, g, *descendants(g)]
            aim(cam, 22, 32)
            frame(cam, points(objs) + [Vector((0, 0, 0))], 260, 260, 1.1)
            row.append(st.shot(objs, os.path.join(tiles, f"{m.id}-group-{g['group']}.png"), 260, 260, 32))
            row.append(st.labels.tile(g["group"], 120, 260, os.path.join(tiles, f"{m.id}-group-{g['group']}-l.png")))
        rows.append(row)

    for name in clips:
        act = m.clips.get(name)
        if act is None:
            continue
        end = int(act.frame_end)
        loop = bool(m.spec["clips"][name].get("loop"))
        frames = [round(end * i / 6) for i in range(6)] if loop else [round(end * i / 5) for i in range(6)]
        allpts = [Vector((0, 0, 0))]
        for f in frames:
            _pose(m, name, f)
            allpts += points(_variant_tree(m))
        w, h = 230, 300
        aim(cam, 14, -64)
        frame(cam, allpts, w, h, 1.06)
        speed = m.spec["clips"][name].get("speed")
        caption = f"{name}\n{'loop' if loop else 'once'}" + (f"\n{speed} m/s" if speed else "") + f"\n{end + 1} fr"
        row = [st.labels.tile(caption, 150, h, os.path.join(tiles, f"{m.id}-{name}-label.png"), 0.24)]
        for f in frames:
            _pose(m, name, f)
            row.append(st.shot(_variant_tree(m), os.path.join(tiles, f"{m.id}-{name}-{f}.png"), w, h, 16))
        rows.append(row)
    _pose(m)
    if hasattr(m, "geos"):
        tris = ", ".join(f"{o['variant']} {triangles([o])}" for o in m.meshes())
    else:
        tris = str(triangles(m.meshes()))
    title = f"{m.id}   triangles {tris}" + (f"   rig {m.spec['rig']}" if m.spec.get("rig") else "")
    rows.insert(0, [st.labels.tile(title, 900, 40, os.path.join(tiles, f"{m.id}-title.png"))])
    return compose(rows, os.path.join(out_dir, f"{m.id}.png"))


def lineup(st, models, out_dir, tiles):
    """<out_dir>/lineup.png: every model side by side at one scale, from the front and from above."""
    x = 0.0
    shown = []
    for m in models:
        _pose(m)
        objs = _variant_tree(m)
        pts = points(objs)
        lo, hi = min(p.x for p in pts), max(p.x for p in pts)
        m.root.matrix_world = Matrix.Translation((x - lo, 0, 0))
        shown += objs
        x += hi - lo + 0.5
    rule = ruler((-0.6, 0, 0))
    bpy.context.view_layer.update()
    pts = points(shown + [rule])
    rows = []
    for elevation, azimuth in ((10, 0), (48, 20)):
        aim(st.cam, elevation, azimuth)
        frame(st.cam, pts, 2000, 600, 1.03)
        rows.append([st.shot([*shown, rule], os.path.join(tiles, f"lineup-{elevation}.png"), 2000, 600, 32)])
    for m in models:
        m.root.matrix_world = Matrix.Identity(4)
    bpy.data.objects.remove(rule, do_unlink=True)
    bpy.context.view_layer.update()
    return compose(rows, os.path.join(out_dir, "lineup.png"))


def sheets(out_dir, models, tints=None, stage=None, renderer="auto"):
    """Renders a sheet per model and the lineup into out_dir (tiles in out_dir/tiles); returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    tiles = os.path.join(out_dir, "tiles")
    os.makedirs(tiles, exist_ok=True)
    st = stage or Stage(tints, renderer)
    paths = [model_sheet(st, m, out_dir, tiles) for m in models]
    paths.append(lineup(st, models, out_dir, tiles))
    return paths


def thumbnails(models, paths, size=256, tints=None, stage=None, renderer="auto"):
    """A transparent 3/4 view of each model (its first variant, at rest) written to paths[i] as webp."""
    st = stage or Stage(tints, renderer)
    for m, path in zip(models, paths):
        _pose(m)
        objs = _variant_tree(m)
        aim(st.cam, 22, 32)
        frame(st.cam, points(objs), size, size, 1.06)
        show_only([*objs, st.sun, st.cam])
        render(path, size, size, 32, fmt="WEBP")
    return paths
