"""The build: every model of a project, built, checked, exported, checked again as a file, and rendered for review.

A project is a folder:

    my-art/
      project.py          optional settings (see below)
      models/<id>.py      one module per model: SPEC (optional) and build(m); animate(m) for a rigged one
      <helper>.py         shared building code the models may import (a leg, a window, a palette)

Run inside Blender (the blendpipe CLI does this for you):

    blender --background --factory-startup --python-exit-code 1 --python tools/blender_build.py -- \\
        <project dir> <out dir> [--only id,id] [--sheet DIR] [--thumbs] [--no-pack]
        [--renderer auto|eevee|cycles]

<out dir>/<folder>/<id>.glb is written for each model (folder from its spec, default none), plus <id>-far.glb when
its spec asks for a far level of detail and <id>.webp with --thumbs. --only builds, checks and writes only those
models: the quick loop while making one. --sheet renders the review sheets into DIR, also when a check fails, so you
can see what is wrong. --no-pack writes Blender's export uncompressed (no gltfpack needed). --renderer (or
$BLENDPIPE_RENDERER) picks what the sheets are rendered with: auto is EEVEE, or Cycles on the CPU where Blender
gets no GPU (see render.choose_renderer).

project.py may set:
    DEFAULTS     spec values every model starts from, e.g. dict(kb=64, tris=2000)
    SPECS        {id: spec} instead of (or on top of) each module's SPEC
    FINISHES     {name: dict(rough=, metal=, emit=, strength=)} for materials' finish=
    TINTS        {role: '#rrggbb'}: the tint roles materials may use, and how the sheets preview them
    TILE         metres along one edge of a tile (default 1.0): what a spec's footprint=(fx, fy) is a multiple of
    RIGS         {name: bone table} beside the built-in "humanoid"
    IMPORTS      extra module names model modules may import
    FPS          frames per second (default 30)
    TOTAL_KB     most kilobytes all glbs under <out dir> may weigh together
    MAX_IMAGES   most textures a glb may embed
    EXTENSIONS   glTF extensions the glbs may use beyond meshopt, quantisation, lights and emissive strength
    QUANTIZE_SKINNED  quantise skinned models' positions too (a few % smaller; three.js only, see export.py)
    STRIP_NAMES  drop part, socket, mesh and material names from the glbs (the app reads extras)
    THUMBNAIL    thumbnail size in pixels (default 256)
"""
import glob
import importlib.util
import os
import sys
import time

import bpy

from . import biped, checks, export, materials, render, rig, scene
from .errors import BuildError
from .model import Model
from .skin import SkinModel
from .tools import GLTFPACK_VERSION, MIN_BLENDER, RENDERERS, TESTED_BLENDER

BUILTIN_RIGS = {"humanoid": biped.HUMANOID}
USAGE = ("usage: <project dir> <out dir> [--only id,id] [--sheet DIR] [--thumbs] [--no-pack] "
         "[--renderer auto|eevee|cycles]")


def _options(argv):
    if len(argv) < 2 or argv[0].startswith("--") or argv[1].startswith("--"):
        raise BuildError(USAGE)
    known = {"--only": True, "--sheet": True, "--renderer": True, "--thumbs": False, "--no-pack": False}
    out = {"project": os.path.abspath(argv[0]), "out": os.path.abspath(argv[1]), "only": None, "sheet": None,
           "thumbs": False, "pack": True, "renderer": os.environ.get("BLENDPIPE_RENDERER") or "auto"}
    i = 2
    while i < len(argv):
        a = argv[i]
        if a not in known:
            raise BuildError(f"unknown option {a}; {USAGE}")
        if known[a]:
            if i + 1 >= len(argv):
                raise BuildError(f"{a} needs a value; {USAGE}")
            value = argv[i + 1]
            if a == "--only":
                out["only"] = [v for v in value.split(",") if v]
            elif a == "--renderer":
                out["renderer"] = value
            else:
                out["sheet"] = os.path.abspath(value)
            i += 2
        else:
            out["thumbs" if a == "--thumbs" else "pack"] = a == "--thumbs"
            i += 1
    if out["renderer"] not in RENDERERS:
        raise BuildError(f"the renderer is one of {', '.join(RENDERERS)}, not {out['renderer']}")
    return out


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Project:
    def __init__(self, folder):
        if not os.path.isdir(folder):
            raise BuildError(f"{folder} is not a folder")
        self.folder = folder
        self.models_dir = os.path.join(folder, "models")
        if not os.path.isdir(self.models_dir):
            raise BuildError(f"{folder} has no models/ folder: a project keeps one module per model there")
        if folder not in sys.path:
            sys.path.insert(0, folder)
        path = os.path.join(folder, "project.py")
        conf = _load("blendpipe_project", path) if os.path.exists(path) else None
        get = (lambda k, d: getattr(conf, k, d)) if conf else (lambda k, d: d)
        self.defaults = dict(get("DEFAULTS", {}))
        self.specs = dict(get("SPECS", {}))
        self.tints = get("TINTS", None)
        self.tile = float(get("TILE", checks.DEFAULT_TILE))
        if not self.tile > 0:
            raise BuildError(f"TILE is {self.tile:g} m; it must be above 0")
        self.rigs = {**BUILTIN_RIGS, **get("RIGS", {})}
        self.fps = int(get("FPS", scene.FPS))
        self.total_kb = get("TOTAL_KB", None)
        self.max_images = get("MAX_IMAGES", None)
        self.strip_names = bool(get("STRIP_NAMES", False))
        self.thumbnail = int(get("THUMBNAIL", 256))
        self.finishes = dict(get("FINISHES", {}))
        self.extensions = set(get("EXTENSIONS", ()))
        self.quantize_skinned = bool(get("QUANTIZE_SKINNED", False))
        helpers = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(folder, "*.py"))} - {"project"}
        self.imports = set(get("IMPORTS", ())) | helpers
        self.modules = {os.path.basename(p)[:-3]: p for p in sorted(glob.glob(os.path.join(self.models_dir, "*.py")))
                        if not os.path.basename(p).startswith("_")}

    def ids(self):
        return list(self.specs) if self.specs else list(self.modules)


def build_model(project, mid, mod):
    """Builds one model from its module: the spec, the rig, build(m), the meshes, animate(m)."""
    spec = {**project.defaults, **getattr(mod, "SPEC", {}), **project.specs.get(mid, {})}
    m = SkinModel(mid, spec) if spec.get("skinned") else Model(mid, spec)
    if spec.get("rig"):
        if spec["rig"] not in project.rigs:
            raise BuildError(f"{mid}: rig {spec['rig']} is none of {sorted(project.rigs)}")
        m.arm, m.rig = rig.build(f"{mid}-rig", project.rigs[spec["rig"]], parent=m.root,
                                 loc=spec.get("armature_at", (0, 0, 0)))
        m.objects.append(m.arm)
    if not hasattr(mod, "build"):
        raise BuildError(f"models/{mid}.py has no build(m)")
    mod.build(m)
    m.finish(join=bool(spec.get("join", False)))
    if spec.get("clips"):
        if m.arm is None:
            raise BuildError(f"{mid}: clips need a rig (spec rig=...)")
        if not hasattr(mod, "animate"):
            raise BuildError(f"models/{mid}.py has clips in its spec but no animate(m)")
        mod.animate(m)
        if m.arm is not None:
            from .anim import rest
            rest(m)
    return m


def main(project_dir, argv):
    """Builds the project at project_dir; argv: <out dir> and the options. Raises BuildError on any problem."""
    t0 = time.time()
    if bpy.app.version < MIN_BLENDER:
        raise BuildError(f"Blender {'.'.join(map(str, MIN_BLENDER))} or newer is needed, this is "
                         f"{bpy.app.version_string}")
    if bpy.app.version < TESTED_BLENDER:
        print(f"note: blendpipe is tested on Blender 5.2; this is {bpy.app.version_string}")
    opts = _options([project_dir, *argv])
    project = Project(opts["project"])
    scene.reset(project.fps)
    if project.finishes:
        materials.finishes(**project.finishes)

    problems = checks.Problems()
    for mid, path in project.modules.items():
        checks.code(path, problems, project.imports, project.folder)
    ids = project.ids()
    for mid in ids:
        if mid not in project.modules:
            problems.add(f"SPECS names {mid}, but models/{mid}.py does not exist")
    if project.specs:
        for orphan in sorted(set(project.modules) - set(project.specs)):
            problems.add(f"models/{orphan}.py builds no model SPECS names")
    if opts["only"]:
        unknown = [i for i in opts["only"] if i not in ids]
        if unknown:
            raise BuildError(f"--only names {unknown}; the models are {ids}")
        ids = [i for i in ids if i in opts["only"]]
    if problems:
        raise BuildError(problems.text("The model modules break the rules"))

    models = []
    for mid in ids:
        mod = _load(f"blendpipe_model_{mid}", project.modules[mid])
        m = build_model(project, mid, mod)
        models.append(m)
        print(f"built {mid}: {scene.triangles(m.meshes())} triangles"
              + (f", clips {sorted(m.clips)}" if m.clips else ""))
    for m in models:
        checks.model(m, problems, project.tints, project.tile)
    if problems:
        if opts["sheet"]:
            render.sheets(opts["sheet"], models, project.tints, renderer=opts["renderer"])
        raise BuildError(problems.text())

    cmd = None
    if opts["pack"]:
        cmd = export.find_gltfpack(project.folder)
        if cmd is None:
            raise BuildError(f"gltfpack is missing: npm i -D gltfpack@{GLTFPACK_VERSION} in the project, npm i -g "
                             f"gltfpack@{GLTFPACK_VERSION}, or set GLTFPACK to a gltfpack binary (or --no-pack to "
                             "write uncompressed files)")
    written = {}
    for m in models:
        folder = os.path.join(opts["out"], m.spec.get("folder", ""))
        path = os.path.join(folder, f"{m.id}.glb")
        written[m.id] = export.export_model(m, path, gltfpack_cmd=cmd, far=m.spec.get("far"),
                                            strip_names=project.strip_names,
                                            quantize_skinned=project.quantize_skinned,
                                            check_raw=lambda doc, m=m: checks.raw_export(m, doc, problems))
        for p in written[m.id]:
            checks.file(m, p, problems, project.max_images, project.extensions)
    size = checks.total(opts["out"], project.total_kb, problems)
    for m in models:
        for p in written[m.id]:
            tris = export.triangles_by_node(p)
            shown = ", ".join(f"{k} {v}" for k, v in tris.items()) if len(tris) <= 6 else str(sum(tris.values()))
            print(f"wrote {os.path.relpath(p, opts['out'])}: {os.path.getsize(p) / 1024:.1f} KB"
                  + (f" (at most {m.spec['kb']})" if m.spec.get("kb") and not p.endswith("-far.glb") else "")
                  + f", triangles {shown}")
    print(f"all glbs under {opts['out']}: {size / 1024:.1f} KB" +
          (f" (at most {project.total_kb})" if project.total_kb else ""))
    if problems:
        raise BuildError(problems.text("The written files break the rules"))

    stage = None
    if opts["sheet"]:
        stage = render.Stage(project.tints, opts["renderer"])
        render.sheets(opts["sheet"], models, stage=stage)
    if opts["thumbs"]:
        paths = [os.path.join(opts["out"], m.spec.get("folder", ""), f"{m.id}.webp") for m in models]
        render.thumbnails(models, paths, project.thumbnail, tints=project.tints, stage=stage,
                          renderer=opts["renderer"])
        for p in paths:
            print(f"wrote {os.path.relpath(p, opts['out'])}")
    print(f"done in {time.time() - t0:.1f} s")


def run(project_dir, argv):
    """main(), with a BuildError printed plainly and the process ending with exit code 1."""
    try:
        main(project_dir, argv)
    except BuildError as e:
        print(f"\nblendpipe: {e}\n", file=sys.stderr)
        sys.stderr.flush()
        sys.stdout.flush()
        os._exit(1)
