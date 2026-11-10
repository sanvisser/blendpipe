# Changelog

All notable changes to blendpipe are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/),
with pre-releases written the way Python writes them (`0.2.0a1`, tagged `v0.2.0a1`). How a release is made is in the
README, under "Releasing".

## [Unreleased]

### Added

- Linux support. blendpipe finds Blender in the usual Linux places (`/usr/bin`, `/usr/local/bin`, `/snap/bin`,
  flatpak's wrapper, `~/.local/opt/blender-*`, `~/blender-*`, `/opt/blender*`). A Blender on the `PATH` still wins when
  it is 5.0 or newer, and an older one no longer hides a newer one elsewhere.
- `--renderer auto|eevee|cycles` (or `BLENDPIPE_RENDERER`) for `--sheet` and `--thumbs`. `auto` uses EEVEE where Blender
  gets a real GPU and Cycles on the CPU where it does not, so review sheets render on a headless machine.
- A Linux section in the README: installing Blender, where it is looked for, the renderer choice, and what was tried.
- Tests on Linux in GitHub Actions (`.github/workflows/tests.yml`), with a checksum-verified Blender and gltfpack.
- A release setup. Pushing a tag such as `v0.2.0a1` runs the tests, builds the sdist and the wheel, writes
  `SHA256SUMS` and publishes a GitHub release (a pre-release when the version is an alpha, beta or release candidate).
  The README has new "Releasing" and "Trust model" sections, and this changelog is new.

### Changed

- The version is written once, in `blendpipe.__version__`; `pyproject.toml` reads it from there.
- The tests also run on pushes to `main`, and another workflow can call them.
- `blendpipe new` prints the opener of the platform (`open`, `start` or `xdg-open`) for looking at the sheets.
- The command line says so when Blender is killed by a signal (it used to exit without a word), and hides Mesa's
  "failed to open /dev/dri" and Cycles' "CUEW" warnings unless `--verbose` is given.

### Fixed

- `blendpipe new` from a read-only install (a Nix store, a read-only mount) made a read-only project and failed when it
  renamed `gitignore` to `.gitignore`.
- In the Cycles sheets, a point light inside a mesh (the lantern's flame) no longer lights the glass around it, which
  matches the EEVEE sheets.

## [0.1.0] - 2026-10-16

The first version (commit 4d1f38d, not tagged).

### Added

- Models as Python modules in `models/`, each with an optional `SPEC` and a `build(m)`, built from a deterministic
  geometry kit (`blendpipe.geo`) and materials with named finishes and tint roles.
- Checks on every model: triangle, size and material budgets, faces built inside out, standing on the ground, sockets,
  skin weights, loops that do not close, feet that sink or float, and the rules for the code of a model.
- Export as glb, compressed with gltfpack 1.2.0, and EEVEE review sheets and thumbnails.
- Skinned characters: smooth weights, a 21-bone humanoid rig, IK posing, and walk and run cycles whose planted feet do
  not slide.
- The `blendpipe` command: `new` (a project from the starter), `doctor` and `build`.
