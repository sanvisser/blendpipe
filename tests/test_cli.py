"""The command line, in plain Python; the builds start Blender (skipped when Blender or gltfpack is missing).

    python -m unittest discover -s tests -t .
"""
import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from blendpipe import cli, tools  # noqa: E402

STARTER = os.path.join(ROOT, "src", "blendpipe", "starter")
BLENDER = tools.find_blender()
GLTFPACK = tools.find_gltfpack(ROOT)


def blendpipe(*args, env=None):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"), **(env or {}))
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

    @unittest.skipIf(sys.platform == "win32" or os.geteuid() == 0, "needs read-only files to mean something")
    def test_new_from_a_read_only_install_makes_a_project_you_can_write_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = os.path.join(tmp, "installed")
            shutil.copytree(STARTER, installed, ignore=shutil.ignore_patterns("__pycache__"))
            for d, dirs, files in os.walk(installed, topdown=False):
                for name in [*(os.path.join(d, n) for n in dirs + files), d]:
                    os.chmod(name, os.stat(name).st_mode & ~0o222)
            try:
                with mock.patch.object(cli, "STARTER", installed), contextlib.redirect_stdout(io.StringIO()):
                    cli.main(["new", os.path.join(tmp, "art")])
                art = os.path.join(tmp, "art")
                self.assertTrue(os.path.exists(os.path.join(art, ".gitignore")))
                for d, dirs, files in os.walk(art):
                    for name in [d, *(os.path.join(d, n) for n in dirs + files)]:
                        self.assertTrue(os.access(name, os.W_OK), name)
            finally:
                for d, dirs, files in os.walk(installed):
                    for name in [d, *(os.path.join(d, n) for n in dirs + files)]:
                        os.chmod(name, os.stat(name).st_mode | 0o200)

    def test_new_shows_sheets_with_the_platforms_opener(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["new", os.path.join(tmp, "art")])
        self.assertIn(f"{cli.OPEN} out/sheets/walker.png", out.getvalue())
        self.assertEqual(cli.OPEN, {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open"))

    def test_new_refuses_a_folder_with_things_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "x"), "w").close()
            with self.assertRaises(SystemExit):
                cli.main(["new", tmp])


def fake_blender(path, version):
    """An executable that says it is that Blender version (enough for find_blender)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"#!/bin/sh\necho 'Blender {version}'\n")
    os.chmod(path, 0o755)
    return path


@unittest.skipIf(sys.platform == "win32", "the stand-in Blenders are shell scripts")
class Crash(unittest.TestCase):
    def test_a_crash_of_blender_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            crasher = os.path.join(tmp, "blender")
            with open(crasher, "w") as f:
                f.write("#!/bin/sh\nkill -SEGV $$\n")
            os.chmod(crasher, 0o755)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["build", STARTER, os.path.join(tmp, "out"), "--blender", crasher])
            self.assertLess(code, 0)
            self.assertIn("Blender crashed (SIGSEGV)", err.getvalue())
            self.assertIn("--renderer cycles", err.getvalue())


@unittest.skipIf(sys.platform == "win32", "the stand-in Blenders are shell scripts")
class FindBlender(unittest.TestCase):
    def find(self, home, path=""):
        env = {k: v for k, v in os.environ.items() if k != "BLENDER"}
        with mock.patch.dict(os.environ, {**env, "HOME": home, "PATH": path}, clear=True), \
                mock.patch.object(tools, "SYSTEM_BLENDERS", ()):
            return tools.find_blender()

    def test_the_newest_unpacked_blender_wins(self):
        with tempfile.TemporaryDirectory() as home:
            fake_blender(os.path.join(home, ".local", "opt", "blender-5.0.1-linux-x64", "blender"), "5.0.1")
            new = fake_blender(os.path.join(home, ".local", "opt", "blender-5.2.2-linux-x64", "blender"), "5.2.2")
            fake_blender(os.path.join(home, "blender-4.5.3-linux-x64", "blender"), "4.5.3")
            self.assertEqual(self.find(home), new)

    def test_sorts_versions_as_numbers_not_text(self):
        with tempfile.TemporaryDirectory() as home:
            fake_blender(os.path.join(home, "blender-5.9.0", "blender"), "5.9.0")
            new = fake_blender(os.path.join(home, "blender-5.10.0", "blender"), "5.10.0")
            self.assertEqual(self.find(home), new)

    def test_the_path_wins_when_it_is_new_enough(self):
        with tempfile.TemporaryDirectory() as home:
            fake_blender(os.path.join(home, "blender-5.2.2", "blender"), "5.2.2")
            on_path = fake_blender(os.path.join(home, "bin", "blender"), "5.0.0")
            self.assertEqual(self.find(home, os.path.dirname(on_path)), on_path)

    def test_an_old_blender_on_the_path_does_not_hide_a_new_one(self):
        with tempfile.TemporaryDirectory() as home:
            new = fake_blender(os.path.join(home, "blender-5.2.2", "blender"), "5.2.2")
            old = fake_blender(os.path.join(home, "bin", "blender"), "4.0.2")
            self.assertEqual(self.find(home, os.path.dirname(old)), new)

    def test_only_an_old_blender_is_still_found_so_doctor_can_say_so(self):
        with tempfile.TemporaryDirectory() as home:
            old = fake_blender(os.path.join(home, "blender-4.5.3", "blender"), "4.5.3")
            self.assertEqual(self.find(home), old)

    def test_flatpaks_wrapper_is_found(self):
        with tempfile.TemporaryDirectory() as home:
            wrapper = fake_blender(os.path.join(home, ".local", "share", "flatpak", "exports", "bin",
                                                "org.blender.Blender"), "5.2.2")
            self.assertEqual(self.find(home), wrapper)

    def test_a_folder_that_is_not_executable_is_skipped(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "blender-5.2.2", "blender"))      # a folder, not the program
            self.assertIsNone(self.find(home))

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(self.find(home))

    def test_BLENDER_names_the_executable_file(self):
        with tempfile.TemporaryDirectory() as home:
            exe = fake_blender(os.path.join(home, "mine", "blender"), "5.2.2")
            with mock.patch.dict(os.environ, {"BLENDER": exe}):
                self.assertEqual(tools.find_blender(), exe)
            with mock.patch.dict(os.environ, {"BLENDER": os.path.dirname(exe)}), self.assertRaises(FileNotFoundError):
                tools.find_blender()


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

    def test_the_bytes_do_not_depend_on_where_the_project_lives(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "out1")
            done = blendpipe("build", STARTER, first)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            copy = os.path.join(tmp, "a project", "art")        # another path, with a space, and its own temp folder
            shutil.copytree(STARTER, copy, ignore=shutil.ignore_patterns("__pycache__"))
            os.makedirs(os.path.join(tmp, "tmp"))
            env = {"TMPDIR": os.path.join(tmp, "tmp"), "GLTFPACK": GLTFPACK[-1]}      # no node_modules above the copy
            done = blendpipe("build", copy, os.path.join(tmp, "out2"), env=env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(digests(first), digests(os.path.join(tmp, "out2")))

    def test_a_building_is_held_to_the_projects_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = os.path.join(tmp, "art")
            os.makedirs(os.path.join(art, "models"))
            with open(os.path.join(art, "models", "hut.py"), "w") as f:
                f.write(textwrap.dedent("""
                    import blendpipe as bp
                    from blendpipe import geo
                    SPEC = dict(footprint=(1, 1), height=1.5, floating=0.01)
                    def build(m):
                        m.part("walls", bp.material("hut-m", "#888888")).add(
                            geo.box_between((-0.9, -0.9, 0), (0.9, 0.9, 1)))
                    """))
            done = blendpipe("build", art, os.path.join(tmp, "out"), "--no-pack")        # the default tile is 1 m
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("hut: footprint: vertex at x = -0.900 is 0.400 past the tile edge (0.500)",
                          done.stdout + done.stderr)
            with open(os.path.join(art, "project.py"), "w") as f:
                f.write("TILE = 2.0\n")
            done = blendpipe("build", art, os.path.join(tmp, "out"), "--no-pack")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(os.path.exists(os.path.join(tmp, "out", "hut.glb")))

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


# Mesa (the OpenGL most Linux machines have) can be told to offer only OpenGL 3.3, which is what a machine without
# a GPU or with an old driver looks like to Blender: EEVEE needs 4.3, and Blender crashes outright without it.
OLD_GL = {"MESA_GL_VERSION_OVERRIDE": "3.3", "MESA_GLSL_VERSION_OVERRIDE": "330"}


@unittest.skipUnless(BLENDER and GLTFPACK, "needs Blender and gltfpack")
class Renderer(unittest.TestCase):
    def thumbs(self, tmp, *args, env=None):
        done = blendpipe("build", STARTER, os.path.join(tmp, "out"), "--only", "rock", "--thumbs", *args,
                         env={"TMPDIR": tmp, **(env or {})})
        return done, done.stdout + done.stderr

    def test_the_flag_picks_the_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, text = self.thumbs(tmp, "--renderer", "cycles")
            self.assertEqual(done.returncode, 0, text)
            self.assertIn("renderer: cycles (asked for)", text)
            self.assertTrue(os.path.exists(os.path.join(tmp, "out", "props", "rock.webp")))

    def test_the_environment_picks_the_engine_and_the_flag_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, text = self.thumbs(tmp, env={"BLENDPIPE_RENDERER": "cycles"})
            self.assertEqual(done.returncode, 0, text)
            self.assertIn("renderer: cycles (asked for)", text)
            done, text = self.thumbs(tmp, "--renderer", "auto", env={"BLENDPIPE_RENDERER": "luxrender"})
            self.assertEqual(done.returncode, 0, text)
            self.assertNotIn("asked for", text)

    def test_an_unknown_engine_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, text = self.thumbs(tmp, "--renderer", "luxrender")
            self.assertEqual(done.returncode, 2, text)
            done, text = self.thumbs(tmp, env={"BLENDPIPE_RENDERER": "luxrender"})
            self.assertEqual(done.returncode, 1, text)
            self.assertIn("one of auto, eevee, cycles", text)

    def test_without_opengl_4_3_the_sheets_fall_back_to_the_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, text = self.thumbs(tmp, env=OLD_GL)
            self.assertEqual(done.returncode, 0, text)
            self.assertIn("renderer: ", text)
            self.assertTrue(os.path.exists(os.path.join(tmp, "out", "props", "rock.webp")))
