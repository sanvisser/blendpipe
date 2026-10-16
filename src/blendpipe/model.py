"""A model under construction: a root node carrying what the app reads (its extras), its parts, groups, sockets and
lights. One model becomes one glb.

A part is a Geo (accumulate primitives into it) with one material; it becomes one mesh node, or, with join, every
part of a group is merged into one mesh with several materials (fewer nodes, a smaller file). A part may hang rigidly
from a bone of the model's rig. Groups are nodes under the root that the app can show or hide (levels, damage
states, LODs), sockets are empty nodes where the app attaches things (a hand, a saddle, a flag), lights export as
KHR_lights_punctual. Everything carries its role in its extras, so the app never has to parse names:

    root      {model: id, rig?, clips?, variants?, ...spec extras}
    part      {part: name, tint?}        group  {group: name, ...}
    socket    {socket: kind, ...}        light  {light: name, ...}
"""
import bpy
from mathutils import Matrix, Vector

from . import materials
from .errors import BuildError
from .geo import Geo, xf
from .mesh import bevelled, build_mesh
from .scene import descendants, empty


class BaseModel:
    """What static and skinned models share: the root, groups, sockets, lights, the armature."""

    def __init__(self, mid, spec=None):
        self.id = mid
        self.spec = dict(spec or {})
        self.root = empty(mid)
        self.root["model"] = mid
        for key, value in self.spec.get("extras", {}).items():
            self.root[key] = value
        if self.spec.get("rig"):
            self.root["rig"] = self.spec["rig"]
        if self.spec.get("clips"):
            self.root["clips"] = {name: dict(c) for name, c in self.spec["clips"].items()}
        self.fps = bpy.context.scene.render.fps
        self.arm = None
        self.rig = None
        self.objects = [self.root]
        self.clips = {}
        self._groups = {}
        self._names = set()

    # ---- nodes the app reads

    def group(self, name, **extras):
        """The group node called name (made on first use), under the root, with extras {group: name, **extras}."""
        if name not in self._groups:
            g = empty(self._unique(f"{self.id}-group-{name}"), self.root)
            g["group"] = name
            for key, value in extras.items():
                g[key] = value
            self._groups[name] = g
            self.objects.append(g)
        elif extras:
            raise BuildError(f"{self.id}: group {name} is given its extras twice")
        return self._groups[name]

    def socket(self, kind, loc, rot=(0, 0, 0), bone=None, group=None, name=None, **extras):
        """An empty where the app attaches something: at loc (model space, rest pose), turned by rot (degrees) from
        the model's axes, carried by bone when given. Its extras say {socket: kind, **extras}."""
        name = name or kind
        e = empty(self._unique(f"{self.id}-socket-{name}"))
        e["socket"] = kind
        for key, value in extras.items():
            e[key] = value
        self._attach(e, xf(loc, rot), bone, group)
        self.objects.append(e)
        return e

    def light(self, name, loc, colour, watts, radius=0.05, bone=None, group=None, **extras):
        """A point light (KHR_lights_punctual in the glb): colour '#rrggbb', watts as Blender measures them."""
        from .colour import srgb
        data = bpy.data.lights.new(f"{self.id}-{name}", "POINT")
        data.color = srgb(colour)[:3]
        data.energy = watts
        data.shadow_soft_size = radius
        o = bpy.data.objects.new(self._unique(f"{self.id}-{name}"), data)
        bpy.context.scene.collection.objects.link(o)
        o["light"] = name
        for key, value in extras.items():
            o[key] = value
        self._attach(o, Matrix.Translation(loc), bone, group)
        self.objects.append(o)
        return o

    # ---- placing

    def _unique(self, name):
        if name in self._names:
            raise BuildError(f"{self.id}: two nodes are called {name}; give one another name")
        self._names.add(name)
        return name

    def _attach(self, o, at, bone, group):
        """Parents o to the root, a group (at: its placement in model space) or a bone (at: in the armature's space,
        rest pose). A bone's child hangs from the bone's tail, in the bone's axes."""
        if bone is not None and group is not None:
            raise BuildError(f"{self.id}: {o.name} is put on bone {bone} and in group {group}; choose one")
        if bone is None:
            o.parent = self.group(group) if group is not None else self.root
            o.matrix_basis = at
            return
        if self.arm is None or bone not in self.arm.data.bones:
            raise BuildError(f"{self.id}: {o.name} is put on bone {bone}, which the rig does not have")
        o.parent = self.arm
        o.parent_type = "BONE"
        o.parent_bone = bone
        b = self.arm.data.bones[bone]
        o.matrix_basis = (b.matrix_local @ Matrix.Translation((0, b.length, 0))).inverted() @ at

    # ---- what was made

    def tree(self):
        return [self.root, *descendants(self.root)]

    def meshes(self):
        return [o for o in self.objects if o.type == "MESH"]

    def sockets(self):
        return [o for o in self.objects if o.type == "EMPTY" and "socket" in o]


class Model(BaseModel):
    """A static model (props, buildings, items) or one whose parts hang rigidly from bones (a robot, a windmill)."""

    def __init__(self, mid, spec=None):
        super().__init__(mid, spec)
        self._parts = {}

    def part(self, name, mat, *, bone=None, group=None, smooth=40.0, bevel=0.0, segments=2):
        """The Geo of part name: add primitives to it (model space, rest pose). The same name gives the same part.
        smooth: edges sharper than this many degrees stay hard (0: flat shaded). bevel: rounds its edges off by
        that many metres (Blender's Bevel modifier, applied at finish)."""
        settings = (mat, bone, group, float(smooth), float(bevel), int(segments))
        if name in self._parts:
            g, before = self._parts[name]
            if before != settings:
                raise BuildError(f"{self.id}: part {name} is asked for with other settings than the first time")
            return g
        if bone is not None and (self.rig is None or bone not in self.rig.heads):
            raise BuildError(f"{self.id}: part {name} on bone {bone}, which the rig does not have")
        g = Geo()
        self._parts[name] = (g, settings)
        return g

    def finish(self, join=False):
        """Makes the mesh nodes: one per part, or with join one per group (and bone), its vertices in its bone's
        space when it has one."""
        joined = {}
        for name, (g, (mat, bone, group, smooth, bevel, segments)) in self._parts.items():
            if not g.faces:
                raise BuildError(f"{self.id}: part {name} is empty")
            if bevel:
                g = bevelled(g, bevel, segments)
            key = (group, bone) if join else (name,)
            joined_name = (group or "body") + (f"-{bone}" if bone else "")
            node = joined.setdefault(key, {"name": joined_name if join else name,
                                           "group": group, "bone": bone, "verts": [], "faces": [], "mats": [],
                                           "sharp": [], "tints": set()})
            base = len(node["verts"])
            node["verts"] += g.verts
            node["faces"] += [tuple(i + base for i in f) for f in g.faces]
            node["mats"] += [mat] * len(g.faces)
            node["sharp"] += [smooth] * len(g.faces)
            node["tints"].add(materials.tint_of(mat))
        for node in joined.values():
            bone, verts, at = node["bone"], node["verts"], Matrix.Identity(4)
            if bone is not None:
                b = self.arm.data.bones[bone]
                to_bone = b.matrix_local.inverted()
                verts = [tuple(to_bone @ Vector(v)) for v in verts]
                at = b.matrix_local.copy()
            me = build_mesh(f"{self.id}-{node['name']}", verts, node["faces"], node["mats"], node["sharp"])
            o = bpy.data.objects.new(self._unique(f"{self.id}-{node['name']}"), me)
            bpy.context.scene.collection.objects.link(o)
            o["part"] = node["name"]
            tints = node["tints"] - {None}
            if len(tints) == 1 and len(set(node["mats"])) == 1:
                o["tint"] = tints.pop()
            self._attach(o, at, bone, node["group"])
            self.objects.append(o)

    def parts(self):
        return self.meshes()
