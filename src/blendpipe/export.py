"""Writing a model as a glb: Blender's glTF export of the model's tree, compressed by gltfpack (meshopt and quantised
attributes), then slimmed (see slim()).

gltfpack is found by find_gltfpack(): $GLTFPACK (a native binary, or the npm package's cli.js run with node), a
node_modules/gltfpack in the project folder or above it (npm i -D gltfpack@1.2.0), or gltfpack on the PATH. Apps
decode the result with three.js's MeshoptDecoder (or any loader that supports EXT_meshopt_compression and
KHR_mesh_quantization).
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile

import bpy

from . import textures, tools
from .errors import BuildError
from .materials import BUILD_ONLY
from .mesh import normal_mapped
from .scene import descendants

EXTENSIONS = {"EXT_meshopt_compression", "KHR_mesh_quantization"}
LIGHTS = "KHR_lights_punctual"
EMISSIVE_STRENGTH = "KHR_materials_emissive_strength"     # emission brighter than 1


def find_gltfpack(project_dir=None):
    """The command that runs gltfpack, as a list, or None (see tools.find_gltfpack)."""
    try:
        return tools.find_gltfpack(project_dir)
    except FileNotFoundError as e:
        raise BuildError(str(e)) from None


def gltfpack(cmd, src, dst, flags):
    done = subprocess.run([*cmd, "-i", src, "-o", dst, *flags], capture_output=True, text=True)
    if done.returncode:
        raise BuildError(f"gltfpack failed on {os.path.basename(dst)}:\n{done.stderr or done.stdout}")


def far_path(path):
    return path[:-len(".glb")] + "-far.glb"


def export_model(m, path, *, gltfpack_cmd=None, far=None, strip_names=False, check_raw=None,
                 quantize_skinned=False):
    """Writes model m to path (and, with far=(ratio, error), a simplified <id>-far.glb beside it). gltfpack_cmd None
    writes Blender's export uncompressed. check_raw(doc) sees the export before compression. Returns the paths.

    A skinned model keeps float positions unless quantize_skinned: quantised positions need a dequantisation
    transform on the skinned mesh's node, which the glTF spec says engines ignore (three.js applies it; others may
    not). Float positions cost a few percent and work everywhere."""
    skinned = bool(getattr(m, "variants", None)) and m.arm is not None and hasattr(m, "geos")
    tree = [m.root, *descendants(m.root)]
    mats = [mat for o in tree if o.type == "MESH" for mat in o.data.materials if mat]
    textured = any(textures.is_textured(mat) for mat in mats)
    tangents = any(normal_mapped(mat) for mat in mats)
    lights = any(o.type == "LIGHT" for o in tree)
    bpy.ops.object.select_all(action="DESELECT")
    for o in tree:
        o.select_set(True)
    for name, act in m.clips.items():
        act.name = name
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    written = [path]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, os.path.basename(path))
            bpy.ops.export_scene.gltf(
                filepath=raw, use_selection=True, export_format="GLB", export_yup=True, export_apply=True,
                export_extras=True, export_texcoords=textured, export_normals=True, export_tangents=tangents,
                export_lights=lights,
                export_cameras=False, export_animations=bool(m.clips), export_animation_mode="ACTIONS",
                export_force_sampling=True, export_optimize_animation_size=True, export_morph=False,
                export_anim_single_armature=False, export_skins=skinned, export_influence_nb=4,
                export_all_influences=False, export_vertex_color="ACTIVE" if skinned else "MATERIAL",
            )
            if check_raw is not None:
                check_raw(read_glb(raw)[0])
            if gltfpack_cmd is None:
                shutil.copyfile(raw, path)
            else:
                flags = ["-cc", "-kn", "-km", "-ke"]
                if m.clips:
                    flags += ["-af", str(m.fps)]
                if textured:
                    flags.append("-vtf")    # float UVs: box-projected UVs run far past 0..1
                if skinned and not quantize_skinned:
                    flags.append("-vpf")    # float positions: no transform on the skinned mesh's node
                gltfpack(gltfpack_cmd, raw, path, flags)
                if far:
                    ratio, error = far
                    gltfpack(gltfpack_cmd, raw, far_path(path), [*flags, "-si", str(ratio), "-sp", "-se", str(error)])
                    written.append(far_path(path))
        for p in written:
            slim(p, strip_names=strip_names)
    finally:
        for name, act in m.clips.items():
            act.name = f"{m.id}@{name}"
    return written


# ---------------------------------------------------------------- reading and rewriting glbs

def read_glb(path):
    """(JSON document, binary chunk) of a glb."""
    with open(path, "rb") as f:
        data = f.read()
    magic, _, _ = struct.unpack_from("<4sII", data, 0)
    length, kind = struct.unpack_from("<I4s", data, 12)
    if magic != b"glTF" or kind != b"JSON":
        raise BuildError(f"{path} is not a glb")
    return json.loads(data[20:20 + length]), data[20 + length:]


def write_glb(path, doc, rest):
    """Writes doc (and the binary chunk rest, as it was read) as a glb."""
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()
    text += b" " * (-len(text) % 4)
    out = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(text) + len(rest)) + \
        struct.pack("<I4s", len(text), b"JSON") + text + rest
    with open(path, "wb") as f:
        f.write(out)


def triangles_by_node(path):
    """Triangles per mesh node of a glb: {variant, part or node name: count}."""
    doc, _ = read_glb(path)
    out = {}
    for i, n in enumerate(doc.get("nodes", [])):
        if "mesh" not in n:
            continue
        ex = n.get("extras", {})
        key = ex.get("variant") or ex.get("part") or n.get("name") or f"node {i}"
        prims = doc["meshes"][n["mesh"]]["primitives"]
        out[key] = out.get(key, 0) + sum(doc["accessors"][p["indices"]]["count"] // 3 for p in prims if "indices" in p)
    return out


def _rotate(q, v):
    x, y, z, w = q
    cx, cy, cz = y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0]
    dx, dy, dz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return [v[0] + 2 * (w * cx + dx), v[1] + 2 * (w * cy + dy), v[2] + 2 * (w * cz + dz)]


def _fold_dequantisation(doc):
    """gltfpack -kn keeps each named node but hangs its mesh on a new child carrying the dequantisation transform
    (a translation and a uniform scale). Folds that child into the part node, so the part node holds its mesh:
    T_p R_p S_p T_d S_d = T(T_p + R_p S_p T_d) R_p (S_p S_d). A skinned variant's primitives may come back spread
    over several such children (gltfpack shares a primitive two variants have in common): with one transform and
    skin between them they become one mesh on the variant node again."""
    nodes = doc.get("nodes", [])
    drop = set()
    for n in nodes:
        kids = n.get("children", [])
        ex = n.get("extras", {})
        if ("part" not in ex and "variant" not in ex) or not kids or ("mesh" in n and "variant" not in ex):
            continue
        cs = [nodes[k] for k in kids]
        if any(set(c) - {"mesh", "translation", "scale", "skin"} or "mesh" not in c for c in cs):
            continue
        if "mesh" in n:
            # float positions (no dequantisation): gltfpack put the primitives variants share on the node and
            # the rest on untransformed children; they become one mesh on the node again
            if any("translation" in c or "scale" in c or c.get("skin") != n.get("skin") for c in cs):
                continue
            prims = doc["meshes"][n["mesh"]]["primitives"] + [p for c in cs for p in doc["meshes"][c["mesh"]]["primitives"]]
            doc["meshes"].append({"primitives": [dict(p) for p in prims]})
            n["mesh"] = len(doc["meshes"]) - 1
            del n["children"]
            drop.update(kids)
            continue
        c = cs[0]
        if len(cs) > 1:
            same = all(all(o.get(k) == c.get(k) for k in ("translation", "scale", "skin")) for o in cs)
            if "variant" not in ex or not same:
                continue
            doc["meshes"].append({"primitives": [dict(p) for o in cs for p in doc["meshes"][o["mesh"]]["primitives"]]})
            mesh = len(doc["meshes"]) - 1
        else:
            mesh = c["mesh"]
        if "skin" in c:
            n["skin"] = c["skin"]
        tp, rp, sp = n.get("translation", [0, 0, 0]), n.get("rotation", [0, 0, 0, 1]), n.get("scale", [1, 1, 1])
        td, sd = c.get("translation", [0, 0, 0]), c.get("scale", [1, 1, 1])
        off = _rotate(rp, [sp[i] * td[i] for i in range(3)])
        n["translation"] = [tp[i] + off[i] for i in range(3)]
        n["scale"] = [sp[i] * sd[i] for i in range(3)]
        n["mesh"] = mesh
        del n["children"]
        drop.update(kids)
    if not drop:
        return
    used = sorted({n["mesh"] for i, n in enumerate(nodes) if "mesh" in n and i not in drop})
    if len(used) != len(doc["meshes"]):
        remap = {old: k for k, old in enumerate(used)}
        doc["meshes"] = [doc["meshes"][i] for i in used]
        for i, n in enumerate(nodes):
            if "mesh" in n and i not in drop:
                n["mesh"] = remap[n["mesh"]]
    new = {}
    for i in range(len(nodes)):
        if i not in drop:
            new[i] = len(new)
    doc["nodes"] = [n for i, n in enumerate(nodes) if i not in drop]
    for n in doc["nodes"]:
        if "children" in n:
            n["children"] = [new[i] for i in n["children"]]
    for s in doc.get("scenes", []):
        s["nodes"] = [new[i] for i in s["nodes"]]
    for a in doc.get("animations", []):
        for ch in a["channels"]:
            ch["target"]["node"] = new[ch["target"]["node"]]
    for sk in doc.get("skins", []):
        sk["joints"] = [new[i] for i in sk["joints"]]
        if "skeleton" in sk:
            sk["skeleton"] = new[sk["skeleton"]]


def joint_name(bone):
    """A bone's name as the glb's skin joint carries it: three.js strips dots from node names."""
    return bone.replace(".", "_")


def slim(path, strip_names=False):
    """Tidies a written glb's JSON, leaving its binary chunk as it is: each part's dequantisation node folded into
    it, skin joints renamed "." -> "_" (upper_arm.L -> upper_arm_L), node transforms rounded (the export's 1e-8
    noise) and left out where they are the identity, byteOffset 0 left out, build-only material extras dropped.
    strip_names also drops the names of parts, sockets, meshes and materials (an app that reads extras needs
    none; a unit's JSON can outweigh its binary)."""
    doc, rest = read_glb(path)
    _fold_dequantisation(doc)
    for sk in doc.get("skins", []):
        for j in sk["joints"]:
            n = doc["nodes"][j]
            n["name"] = joint_name(n["name"])

    def r(v, key):
        if key != "scale" and abs(v) < 5e-7:
            return 0
        if key == "scale" and abs(v - 1) < 5e-7:
            return 1
        x = float(f"{v:.7g}")
        return int(x) if x == int(x) else x

    for n in doc.get("nodes", []):
        for key, ident in (("translation", [0, 0, 0]), ("rotation", [0, 0, 0, 1]), ("scale", [1, 1, 1])):
            if key in n:
                vals = [r(v, key) for v in n[key]]
                if key == "rotation" and vals[3] < 0:
                    vals = [r(-v, key) for v in vals]
                if vals == ident:
                    del n[key]
                else:
                    n[key] = vals
        if strip_names and ("part" in n.get("extras", {}) or "socket" in n.get("extras", {})):
            n.pop("name", None)
    if strip_names:
        for m in doc.get("meshes", []) + doc.get("materials", []):
            m.pop("name", None)
    for m in doc.get("materials", []):
        ex = m.get("extras")
        if ex:
            for key in BUILD_ONLY:
                ex.pop(key, None)
            if not ex:
                del m["extras"]
    for a in doc.get("accessors", []) + doc.get("bufferViews", []):
        if a.get("byteOffset") == 0:
            del a["byteOffset"]
    write_glb(path, doc, rest)
