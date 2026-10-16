"""Runs blendpipe's tests that need Blender (tests/blender), inside Blender:

    blender --background --factory-startup --python-exit-code 1 --python tools/run_tests.py

The tests that run in plain Python (the CLI, and a full build twice to prove the bytes are the same):

    python -m unittest discover -s tests -t .
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "src"))
HERE = os.path.join(ROOT, "tests", "blender")      # no __init__.py: plain-Python discovery leaves it alone

suite = unittest.defaultTestLoader.discover(HERE, top_level_dir=HERE)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0 if result.wasSuccessful() else 1)
