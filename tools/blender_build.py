"""Runs a blendpipe build inside Blender without installing blendpipe (a clone or a git submodule is enough):

    blender --background --factory-startup --python-exit-code 1 \\
        --python path/to/blendpipe/tools/blender_build.py -- <project dir> <out dir> [--only id,id] [--sheet DIR] \\
        [--thumbs] [--no-pack]

With blendpipe installed (pip or pipx), `blendpipe build <project dir> <out dir> ...` does the same.
"""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from blendpipe.runner import USAGE, run  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 2:
    print(USAGE, file=sys.stderr)
    sys.exit(2)
run(argv[0], argv[1:])
