"""The command line, in plain Python; the builds start Blender (skipped when Blender or gltfpack is missing).

    python -m unittest discover -s tests -t .
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from blendpipe import cli, tools  # noqa: E402

STARTER = os.path.join(ROOT, "src", "blendpipe", "starter")
BLENDER = tools.find_blender()
GLTFPACK = tools.find_gltfpack(ROOT)


def blendpipe(*args):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    return subprocess.run([sys.executable, "-m", "blendpipe.cli", *args], capture_output=True, text=True, env=env,
                          cwd=ROOT, timeout=900)


def digests(folder, suffix=".glb"):
    out = {}
    for d, _, files in os.walk(folder):
        for f in files:
            if f.endswith(suffix):
                with open(os.path.join(d, f), "rb") as fh:
                    out[os.path.relpath(os.path.join(d, f), folder)] = hashlib.sha256(fh.read()).hexdigest()
    return out


class New(unittest.TestCase):
    def test_new_copies_the_starter(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "art")
            self.assertEqual(cli.main(["new", dest]), 0)
            self.assertTrue(os.path.exists(os.path.join(dest, ".gitignore")))
            self.assertFalse(os.path.exists(os.path.join(dest, "gitignore")))
            self.assertEqual(sorted(os.listdir(os.path.join(dest, "models"))),
                             ["crate.py", "lantern.py", "rock.py", "walker.py"])
            for d, dirs, _ in os.walk(dest):
                self.assertNotIn("__pycache__", dirs)

    def test_new_refuses_a_folder_with_things_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "x"), "w").close()
            with self.assertRaises(SystemExit):
                cli.main(["new", tmp])


class Gltfpack(unittest.TestCase):
    def test_found_in_a_folder_above_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "node_modules", "gltfpack"))
            open(os.path.join(tmp, "node_modules", "gltfpack", "cli.js"), "w").close()
            project = os.path.join(tmp, "art", "props")
            os.makedirs(project)
            saved = os.environ.pop("GLTFPACK", None)
            try:
                cmd = tools.find_gltfpack(project)
            finally:
                if saved is not None:
                    os.environ["GLTFPACK"] = saved
            self.assertEqual(cmd[-1], os.path.join(tmp, "node_modules", "gltfpack", "cli.js"))

    def test_a_wrong_GLTFPACK_says_so(self):
        saved = os.environ.get("GLTFPACK")
        os.environ["GLTFPACK"] = "/no/such/gltfpack"
        try:
            with self.assertRaises(FileNotFoundError):
                tools.find_gltfpack()
        finally:
            if saved is None:
                del os.environ["GLTFPACK"]
            else:
                os.environ["GLTFPACK"] = saved


@unittest.skipUnless(BLENDER and GLTFPACK, "needs Blender and gltfpack")
class Builds(unittest.TestCase):
    def test_the_starter_builds_the_same_bytes_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = []
            for n in (1, 2):
                out = os.path.join(tmp, f"out{n}")
                done = blendpipe("build", STARTER, out)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                runs.append(digests(out))
            self.assertEqual(sorted(runs[0]), ["props/crate.glb", "props/lantern.glb", "props/rock.glb",
                                               "units/walker-far.glb", "units/walker.glb"])
            self.assertEqual(runs[0], runs[1])

    def test_a_broken_model_fails_the_build_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "art", "models"))
            with open(os.path.join(tmp, "art", "models", "bad.py"), "w") as f:
                f.write(textwrap.dedent("""
                    import random
                    import blendpipe as bp
                    from blendpipe import geo
                    SPEC = dict(tris=6)
                    def build(m):
                        n = random.random()
                        m.part("p", bp.material("bad-m", "#888888")).add(geo.box((1, 1, 1), (0, 0, 0.5 + n)))
                    """))
            done = blendpipe("build", os.path.join(tmp, "art"), os.path.join(tmp, "out"))
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("random.random", done.stdout + done.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "out")))
