"""The blendpipe command (standard library only; it starts Blender for the work that needs it).

    blendpipe new <dir>                    a new project from the starter (four models, settings, gltfpack pin)
    blendpipe doctor [<project dir>]       checks Blender, Node.js and gltfpack are there and new enough
    blendpipe build <project dir> <out dir> [--only id,id] [--sheet DIR] [--thumbs] [--no-pack]
                    [--blender PATH] [--verbose]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

from . import __version__, tools

PACKAGE = os.path.dirname(os.path.abspath(__file__))
STARTER = os.path.join(PACKAGE, "starter")

# Run inside Blender: loads exactly this package (nothing else from this Python's site-packages, whose compiled
# modules may not suit Blender's Python), then the build.
_BOOT = """\
import importlib.util, sys
p = {pkg!r}
s = importlib.util.spec_from_file_location("blendpipe", p + {init!r}, submodule_search_locations=[p])
m = importlib.util.module_from_spec(s)
sys.modules["blendpipe"] = m
s.loader.exec_module(m)
from blendpipe.runner import run
a = sys.argv[sys.argv.index("--") + 1:]
run(a[0], a[1:])
"""

# Blender's, the glTF exporter's and the renderer's own chatter, hidden unless --verbose
_NOISE = re.compile(r"\| INFO: |^INFO (Draco|MeshOptimizer) is available|render +\| Saved: |^Fra:|^Blender quit$"
                    r"|^Read prefs:|^Blender \d+\.\d+|^\s*$|^\s+Time: ")


def _fmt(v):
    return ".".join(map(str, v))


def _blender_or_exit(explicit):
    try:
        blender = tools.find_blender(explicit)
    except FileNotFoundError as e:
        sys.exit(f"blendpipe: {e}")
    if not blender:
        sys.exit("blendpipe: Blender is not found: install Blender 5.2 (blender.org) or set BLENDER to its "
                 "executable (on macOS /Applications/Blender.app/Contents/MacOS/Blender)")
    return blender


def cmd_build(a):
    blender = _blender_or_exit(a.blender)
    project = os.path.abspath(a.project)
    if not os.path.isdir(os.path.join(project, "models")):
        sys.exit(f"blendpipe: {project} has no models/ folder (blendpipe new <dir> makes a project)")
    opts = []
    if a.only:
        opts += ["--only", a.only]
    if a.sheet:
        opts += ["--sheet", os.path.abspath(a.sheet)]
    if a.thumbs:
        opts.append("--thumbs")
    if a.no_pack:
        opts.append("--no-pack")
    boot = _BOOT.format(pkg=PACKAGE, init=os.sep + "__init__.py")
    cmd = [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python-expr", boot, "--",
           project, os.path.abspath(a.out), *opts]
    if a.verbose:
        return subprocess.run(cmd).returncode
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        if not _NOISE.search(line):
            sys.stdout.write(line)
            sys.stdout.flush()
    return proc.wait()


def cmd_doctor(a):
    ok = True

    def say(good, what, detail):
        nonlocal ok
        ok = ok and good is not False
        mark = "ok  " if good else ("--  " if good is None else "MISSING")
        print(f"{mark:8}{what:10}{detail}")

    say(tools.python_ok(), "python", f"{sys.version.split()[0]} (for this command; models run in Blender's own)")
    try:
        blender = tools.find_blender(a.blender)
    except FileNotFoundError as e:
        blender = None
        print(f"         {e}")
    if blender:
        v = tools.blender_version(blender)
        if v is None:
            say(False, "blender", f"{blender} does not say its version")
        elif v < tools.MIN_BLENDER:
            say(False, "blender", f"{_fmt(v)} at {blender}: {_fmt(tools.MIN_BLENDER)} or newer is needed")
        else:
            note = "" if v >= tools.TESTED_BLENDER else f" (tested on {_fmt(tools.TESTED_BLENDER)})"
            say(True, "blender", f"{_fmt(v)} at {blender}{note}")
    else:
        say(False, "blender", "not found: install Blender 5.2 from blender.org, or set BLENDER to its executable")
    node = shutil.which("node")
    say(True if node else None, "node", node or "not found (needed only for the npm gltfpack)")
    try:
        pack = tools.find_gltfpack(a.project)
    except FileNotFoundError as e:
        pack = None
        print(f"         {e}")
    if pack:
        v = tools.gltfpack_version(pack)
        good = v is not None
        say(good, "gltfpack", f"{v or 'does not run'} via {' '.join(pack)}"
            + ("" if not v or tools.GLTFPACK_VERSION.startswith(v) else f" (tested with {tools.GLTFPACK_VERSION})"))
    else:
        say(False, "gltfpack", f"not found: npm i -D gltfpack@{tools.GLTFPACK_VERSION} in your project (or -g), or "
            "set GLTFPACK to a gltfpack binary; builds with --no-pack work without it")
    print("\nall set" if ok else "\nsomething is missing (see above)")
    return 0 if ok else 1


def cmd_new(a):
    dest = os.path.abspath(a.dir)
    if os.path.exists(dest) and os.listdir(dest):
        sys.exit(f"blendpipe: {dest} exists and is not empty")
    shutil.copytree(STARTER, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if os.path.exists(os.path.join(dest, "gitignore")):
        os.replace(os.path.join(dest, "gitignore"), os.path.join(dest, ".gitignore"))
    rel = os.path.relpath(dest)
    if rel.startswith(".."):
        rel = dest
    print(f"""made {rel}: project.py, models/ (crate, lantern, rock, walker), patterns.py, package.json

next:
  cd {rel}
  npm install                                   # gltfpack {tools.GLTFPACK_VERSION}, pinned in package.json
  blendpipe build . out/assets --sheet out/sheets
  open out/sheets/walker.png                    # look at every sheet after a change
""")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="blendpipe", description="Procedural low-poly assets built headless in "
                                "Blender, checked, exported as compressed glb and rendered for review.")
    p.add_argument("--version", action="version", version=f"blendpipe {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build, check and export a project's models")
    b.add_argument("project", help="the project folder (holds models/ and optionally project.py)")
    b.add_argument("out", help="where the glbs go")
    b.add_argument("--only", help="only these models, comma separated")
    b.add_argument("--sheet", metavar="DIR", help="render review sheets into DIR (also when a check fails)")
    b.add_argument("--thumbs", action="store_true", help="also write <id>.webp thumbnails beside the glbs")
    b.add_argument("--no-pack", action="store_true", help="write Blender's export uncompressed (no gltfpack)")
    b.add_argument("--blender", help="the Blender executable (default: $BLENDER, PATH, usual places)")
    b.add_argument("--verbose", action="store_true", help="show all of Blender's output")
    b.set_defaults(fn=cmd_build)

    d = sub.add_parser("doctor", help="check Blender, Node.js and gltfpack")
    d.add_argument("project", nargs="?", default=".", help="where to look for node_modules/gltfpack")
    d.add_argument("--blender", help="the Blender executable")
    d.set_defaults(fn=cmd_doctor)

    n = sub.add_parser("new", help="start a project from the starter")
    n.add_argument("dir")
    n.set_defaults(fn=cmd_new)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
