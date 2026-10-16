"""Finding the external tools: Blender and gltfpack. Standard library only (the CLI uses it outside Blender)."""
import glob
import os
import re
import shutil
import subprocess
import sys

GLTFPACK_VERSION = "1.2.0"          # the version blendpipe is tested with (npm i -D gltfpack@1.2.0)
MIN_BLENDER = (5, 0, 0)
TESTED_BLENDER = (5, 2, 0)


def find_blender(explicit=None):
    """The Blender executable: explicit, $BLENDER, blender on the PATH, or the usual install places."""
    for c in (explicit, os.environ.get("BLENDER")):
        if c:
            found = shutil.which(c) or (c if os.path.exists(c) else None)
            if not found:
                raise FileNotFoundError(f"Blender is not at {c}")
            return found
    found = shutil.which("blender")
    if found:
        return found
    places = ["/Applications/Blender.app/Contents/MacOS/Blender",
              os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"), "/snap/bin/blender"]
    places += sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    return next((p for p in places if os.path.exists(p)), None)


def blender_version(blender):
    """(major, minor, patch) of a Blender executable, or None if it does not say."""
    try:
        out = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Blender (\d+)\.(\d+)(?:\.(\d+))?", out)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def _node_or_binary(path):
    if path.endswith(".js"):
        node = shutil.which("node")
        if not node:
            raise FileNotFoundError(f"gltfpack is {path}, which needs Node.js on the PATH")
        return [node, path]
    return [shutil.which(path) or path]


def find_gltfpack(project_dir=None):
    """The command that runs gltfpack, as a list, or None: $GLTFPACK (a binary, or the npm package's cli.js), a
    node_modules/gltfpack in the project folder or any folder above it, or gltfpack on the PATH."""
    env = os.environ.get("GLTFPACK")
    if env:
        if not os.path.exists(env) and not shutil.which(env):
            raise FileNotFoundError(f"GLTFPACK names {env}, which does not exist")
        return _node_or_binary(env)
    d = os.path.abspath(project_dir) if project_dir else None
    while d:
        cli = os.path.join(d, "node_modules", "gltfpack", "cli.js")
        if os.path.exists(cli):
            return _node_or_binary(cli)
        parent = os.path.dirname(d)
        d = parent if parent != d else None
    found = shutil.which("gltfpack")
    return [found] if found else None


def gltfpack_version(cmd):
    """gltfpack's version as it prints it ("1.2"), or None."""
    try:
        done = subprocess.run([*cmd, "-h"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"gltfpack (\d+(?:\.\d+)*)", done.stdout + done.stderr)
    return m.group(1) if m else None


def python_ok():
    return sys.version_info >= (3, 9)
