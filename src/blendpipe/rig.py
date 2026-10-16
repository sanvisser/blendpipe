"""Rigs as plain data, the armatures made from them, and the pose maths clips are written in.

A rig is a table of bones: (name, parent, head, tail) in metres, rest pose, z up, facing -y, left +x, parents
before their children. Keep the table in the order the glTF exporter lists a skin's joints (depth first, siblings
by name) and the joints come out in your order.

A Pose holds each bone's rotation relative to its parent, as a rotation of armature space (not the bone's own
axes, so poses read the same whatever a bone's roll), and the root bone's offset. Pose.solve() is forward
kinematics; aim(), ik() and set_world() place limbs by where they should point or reach. keyframe() turns a pose
into Blender's pose-bone channels: basis = rest^-1 @ rel @ rest, and the root bone's location in its own axes.
"""
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .errors import BuildError


def mirror_table(bones, a=".L", b=".R"):
    """Bones of one side mirrored to the other (x flipped, a renamed to b in names and parents)."""
    out = []
    for name, parent, head, tail in bones:
        flip = lambda p: (-p[0], p[1], p[2])  # noqa: E731
        out.append((name.replace(a, b), parent.replace(a, b) if parent else None, flip(head), flip(tail)))
    return out


class Rig:
    """A rig's rest pose as data: heads, tails, parents and rest rotations (armature space), parents first."""

    def __init__(self, name, table, arm=None):
        self.name = name
        self.order = [b[0] for b in table]
        self.parent = {b[0]: b[1] for b in table}
        self.heads = {b[0]: Vector(b[2]) for b in table}
        self.tails = {b[0]: Vector(b[3]) for b in table}
        seen = set()
        for b, p in self.parent.items():
            if p is not None and p not in seen:
                raise BuildError(f"rig {name}: bone {b}'s parent {p} must come before it")
            seen.add(b)
        self.rest = {}
        if arm is not None:
            for b in arm.data.bones:
                self.rest[b.name] = b.matrix_local.to_quaternion()

    def length(self, bone):
        return (self.tails[bone] - self.heads[bone]).length

    def vec(self, bone):
        return self.tails[bone] - self.heads[bone]


def build(name, table, parent=None, loc=(0, 0, 0)):
    """Makes an armature object from a rig table (bones unconnected, roll 0) and returns it with its Rig."""
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(arm)
    arm.parent = parent
    arm.location = loc
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for bname, pname, head, tail in table:
        eb = data.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        eb.roll = 0.0
        if pname:
            eb.parent = data.edit_bones[pname]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return arm, Rig(name, table, arm)


# ---------------------------------------------------------------- poses

def rot(x=0.0, y=0.0, z=0.0):
    """A rotation of armature space, degrees about x (pitch: + tips the top of an upright bone forward), then y
    (roll: + tips it to the left, +x), then z (yaw: + turns the front to the left)."""
    q = Quaternion((1, 0, 0), math.radians(x))
    q = Quaternion((0, 1, 0), math.radians(y)) @ q
    return Quaternion((0, 0, 1), math.radians(z)) @ q


def aim_q(rest_dir, direction, rest_side=None, side=None):
    """The rotation taking rest_dir onto direction and, when given, rest_side onto (the square part of) side."""
    a0 = Vector(rest_dir).normalized()
    a1 = Vector(direction).normalized()
    if rest_side is None or side is None:
        return a0.rotation_difference(a1)
    s0 = Vector(rest_side) - a0 * Vector(rest_side).dot(a0)
    s1 = Vector(side) - a1 * Vector(side).dot(a1)
    if s0.length < 1e-6 or s1.length < 1e-6:
        return a0.rotation_difference(a1)
    s0.normalize()
    s1.normalize()
    m0 = Matrix((a0, s0, a0.cross(s0))).transposed()
    m1 = Matrix((a1, s1, a1.cross(s1))).transposed()
    return (m1 @ m0.transposed()).to_quaternion()


def frame_q(rest_fwd, rest_up, fwd, up):
    """The rotation taking the rest frame (rest_fwd, rest_up) onto (fwd, up): how a held thing or a foot turns."""
    return aim_q(rest_fwd, fwd, rest_up, up)


class Pose:
    def __init__(self, rig):
        self.rig = rig
        self.rel = {b: Quaternion() for b in rig.order}
        self.offset = Vector()          # how far the root bone's head moved from rest
        self._solved = None

    def copy(self):
        p = Pose(self.rig)
        p.rel = {b: q.copy() for b, q in self.rel.items()}
        p.offset = self.offset.copy()
        return p

    def set(self, bone, q):
        """Sets bone's rotation relative to its parent (a rotation of armature space, see rot())."""
        self.rel[bone] = q
        self._solved = None

    def turn(self, bone, q):
        """Adds a rotation on top of the bone's current one, relative to its parent."""
        self.rel[bone] = q @ self.rel[bone]
        self._solved = None

    def move(self, d):
        """Moves the whole pose (the root bone's head) by d."""
        self.offset = self.offset + Vector(d)
        self._solved = None

    def solve(self):
        """Each bone's world rotation (armature space) and head position: ({bone: Quaternion}, {bone: Vector})."""
        if self._solved:
            return self._solved
        rig = self.rig
        D, P = {}, {}
        for b in rig.order:
            p = rig.parent[b]
            if p is None:
                D[b] = self.rel[b].copy()
                P[b] = rig.heads[b] + self.offset
            else:
                D[b] = D[p] @ self.rel[b]
                P[b] = P[p] + D[p] @ (rig.heads[b] - rig.heads[p])
        self._solved = (D, P)
        return D, P

    def world(self, bone):
        D, P = self.solve()
        return D[bone], P[bone]

    def point(self, bone, rest_point):
        """Where a point fixed to bone (given in the rest pose) is now."""
        D, P = self.solve()
        return P[bone] + D[bone] @ (Vector(rest_point) - self.rig.heads[bone])

    def tail(self, bone):
        return self.point(bone, self.rig.tails[bone])

    def set_world(self, bone, q):
        """Sets bone's rotation so its world rotation is q (its parent's stays)."""
        p = self.rig.parent[bone]
        parent_q = self.world(p)[0] if p else Quaternion()
        self.set(bone, parent_q.inverted() @ q)

    def aim(self, bone, direction, side=None, rest_side=None):
        """Turns bone to point along direction; side (a world direction) and rest_side (the bone's matching rest
        direction) fix its twist, else the shortest turn."""
        self.set_world(bone, aim_q(self.rig.vec(bone), direction, rest_side, side))

    def twist(self, bone, degrees):
        """Turns bone about its own (current) length, its children with it."""
        D, _ = self.solve()
        axis = (D[bone] @ self.rig.vec(bone)).normalized()
        self.set_world(bone, Quaternion(axis, math.radians(degrees)) @ D[bone])

    def ik(self, upper, lower, target, pole, bend, end=None, end_q=None):
        """Two-bone IK: turns upper and lower so lower's tail reaches target (as near as it can), the joint between
        them pointing towards pole (a world direction). bend is the rest direction the joint points to as the limb
        bends (an elbow's +y, a knee's -y): it keeps the limb's twist natural. end, when given, gets world
        rotation end_q (a hand, a foot). Returns how far short of the target the limb fell."""
        rig = self.rig
        _, P = self.solve()
        root = P[upper]
        l1, l2 = rig.length(upper), rig.length(lower)
        v = Vector(target) - root
        d = max(min(v.length, (l1 + l2) * 0.9995), abs(l1 - l2) + 1e-4)
        n = v.normalized()
        a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
        h = math.sqrt(max(l1 * l1 - a * a, 0.0))
        pole = Vector(pole)
        perp = pole - n * pole.dot(n)
        if perp.length < 1e-6:
            perp = n.orthogonal()
        perp.normalize()
        joint = root + n * a + perp * h
        self.aim(upper, joint - root, perp, bend)
        self.aim(lower, root + n * d - joint, perp, bend)
        if end is not None:
            self.set_world(end, end_q if end_q is not None else Quaternion())
        return v.length - d


def blend_pose(a, b, w):
    """Two poses mixed bone by bone (w 0: a, 1: b)."""
    p = Pose(a.rig)
    for bone in a.rel:
        qa, qb = a.rel[bone], b.rel[bone]
        if qa.dot(qb) < 0:
            qb = -qb
        p.rel[bone] = qa.slerp(qb, w)
    p.offset = a.offset.lerp(b.offset, w)
    return p


# ---------------------------------------------------------------- keyframes

def keyframe(arm, rig, pose, frame, keep=None):
    """Keys every bone's rotation (and the root bone's location) at frame. keep carries the last keys between
    calls, so each key turns the short way from the one before; returns it."""
    prev = keep if keep is not None else {}
    for b in rig.order:
        pb = arm.pose.bones[b]
        r = rig.rest[b]
        q = r.inverted() @ pose.rel[b] @ r
        q.normalize()
        last = prev.get(b)
        if last is not None and last.dot(q) < 0:
            q.negate()
        prev[b] = q.copy()
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=frame)
        if rig.parent[b] is None:
            pb.location = r.inverted() @ pose.offset
            pb.keyframe_insert("location", frame=frame)
    return prev


def apply(arm, rig, pose):
    """Shows pose on the armature without keying it."""
    for b in rig.order:
        pb = arm.pose.bones[b]
        r = rig.rest[b]
        pb.rotation_quaternion = r.inverted() @ pose.rel[b] @ r
        if rig.parent[b] is None:
            pb.location = r.inverted() @ pose.offset
    bpy.context.view_layer.update()
