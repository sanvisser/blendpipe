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


# Where Blender lives when it is not on the PATH (Linux: a distro package, snap, flatpak's wrapper, or the tarball
# from blender.org unpacked in the home folder or /opt; macOS and Windows: the installers' folders).
SYSTEM_BLENDERS = ("/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
                   "/var/lib/flatpak/exports/bin/org.blender.Blender",
                   "/Applications/Blender.app/Contents/MacOS/Blender")
UNPACKED_BLENDERS = ("~/.local/opt/blender-*/blender", "~/blender-*/blender", "/opt/blender*/blender",
                     "~/.local/share/flatpak/exports/bin/org.blender.Blender",
                     "~/Applications/Blender.app/Contents/MacOS/Blender",
                     r"C:\Program Files\Blender Foundation\Blender *\blender.exe")


def _runnable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def blender_places():
    """The Blender executables found in the usual places, each once (symlinks to one file count once)."""
    paths = list(SYSTEM_BLENDERS)
    for pattern in UNPACKED_BLENDERS:
        paths += glob.glob(os.path.expanduser(pattern))
    seen, out = set(), []
    for p in paths:
        real = os.path.realpath(p)
        if real not in seen and _runnable(p):
            seen.add(real)
            out.append(p)
    return out


def find_blender(explicit=None):
    """The Blender executable: explicit, $BLENDER, blender on the PATH, or the usual install places. A blender on
    the PATH that is new enough wins. Otherwise the newest of the usual places that is new enough; failing that
    the first one found, so that doctor can say what is wrong with it."""
    for c in (explicit, os.environ.get("BLENDER")):
        if c:
            found = shutil.which(c) or (c if os.path.isfile(c) else None)
            if not found:
                raise FileNotFoundError(f"Blender is not at {c}")
            return found
    on_path = shutil.which("blender")
    if on_path and (blender_version(on_path) or MIN_BLENDER) >= MIN_BLENDER:
        return on_path
    seen = {os.path.realpath(on_path)} if on_path else set()
    versions = [(blender_version(p), p) for p in blender_places() if os.path.realpath(p) not in seen]
    newest = max(((v, p) for v, p in versions if v), default=None)
    if newest and newest[0] >= MIN_BLENDER:
        return newest[1]
    return on_path or (newest[1] if newest else next((p for _, p in versions), None))


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
