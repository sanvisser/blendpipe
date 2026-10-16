"""Clips: a function of t in [0, 1] (the share of the clip done) that gives a rig.Pose, keyed on every frame.

record() keys a clip as an action named "<model>@<clip>" on the model's armature and parks it on its own NLA track,
so the exporter writes this model's clips and no other's (the export names the glTF animation after the clip). A
loop's last frame is its first, so it closes exactly.

Poses are often easiest written as keys: nested dicts of numbers ("hips": {"at": (0, 0, 0.97)}, "spine": (2, 0, 0))
mixed with blend(), laid out in time with timeline() and turned into a Pose by a function of your own (see
biped.pose for a humanoid one).

Blender 5.2 keeps an action's curves in layers: read them with channels(action), never action.fcurves.
"""
import math

import bpy
from mathutils import Quaternion

from . import rig as R
from .errors import BuildError


# ---------------------------------------------------------------- numbers

def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def smooth(x):
    """Smoothstep: eases in and out over 0..1."""
    x = clamp(x)
    return x * x * (3 - 2 * x)


def lerp(a, b, w):
    if isinstance(a, (int, float)):
        return a + (b - a) * w
    return tuple(x + (y - x) * w for x, y in zip(a, b))


def wave(t, k=1.0, phase=0.0):
    """sin of k full turns over t 0..1, shifted by phase (in turns): loops cleanly when k is whole."""
    return math.sin(math.tau * (k * t + phase))


def bump(t, a, b):
    """0 outside [a, b], rising and falling smoothly to 1 in its middle."""
    if t <= a or t >= b:
        return 0.0
    return math.sin(math.pi * (t - a) / (b - a)) ** 2


# ---------------------------------------------------------------- keys: poses as numbers

def blend(a, b, w):
    """Mixes two keys (nested dicts of numbers, tuples and quaternions) by w; strings and flags switch halfway."""
    if isinstance(a, dict):
        out = {k: blend(a[k], b[k], w) if k in b else a[k] for k in a}
        out.update({k: b[k] for k in b if k not in a})
        return out
    if isinstance(a, str) or a is None or isinstance(a, bool):
        return a if w < 0.5 else b
    if isinstance(a, Quaternion):
        return a.slerp(b, w)
    return lerp(a, b, w)


def timeline(keys, t, ease=smooth):
    """keys [(time, key), ...] in order: the key at t, eased between its neighbours; holds the ends."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, k0), (t1, k1) in zip(keys, keys[1:]):
        if t <= t1:
            return blend(k0, k1, ease((t - t0) / (t1 - t0)) if t1 > t0 else 1.0)
    return keys[-1][1]


def pose_timeline(keys, t, ease=smooth):
    """keys [(time, Pose), ...]: the pose at t, eased between its neighbours."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
        if t <= t1:
            return R.blend_pose(p0, p1, ease((t - t0) / (t1 - t0)) if t1 > t0 else 1.0)
    return keys[-1][1]


def merge(base, **changes):
    """A copy of key base with some entries replaced; nested dicts merge one level down."""
    out = dict(base)
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            inner = dict(out[k])
            inner.update(v)
            out[k] = inner
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- recording and playing

def record(m, name, frames, fn, loop=None):
    """Keys clip name of model m over frames + 1 frames (0..frames): fn(t) gives the Pose at t in [0, 1]. loop
    (default: the spec's clips[name]["loop"]) makes the last frame the first."""
    clips = m.spec.get("clips", {})
    if name not in clips:
        raise BuildError(f"{m.id}: clip {name} is not in the spec's clips {sorted(clips)}")
    if loop is None:
        loop = bool(clips[name].get("loop", False))
    if frames < 2:
        raise BuildError(f"{m.id}: clip {name} needs at least 2 frames")
    arm, rg = m.arm, m.rig
    act = bpy.data.actions.new(f"{m.id}@{name}")
    act.use_fake_user = True
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    keep, first = {}, None
    for f in range(frames + 1):
        pose = first if loop and f == frames else fn(f / frames)
        if f == 0:
            first = pose
        keep = R.keyframe(arm, rg, pose, f, keep)
    act.use_frame_range = True
    act.frame_start, act.frame_end = 0, frames
    act.use_cyclic = bool(loop)
    slot = ad.action_slot
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = f"NlaTrack {name}"
    strip = track.strips.new(act.name, 0, act)
    if strip.action_slot is None and slot is not None:
        strip.action_slot = slot
    ad.use_nla = False
    m.clips[name] = act
    return act


def play(m, name, frame):
    """Shows clip name of model m at frame (for renders and checks)."""
    ad = m.arm.animation_data
    act = m.clips[name]
    ad.use_nla = False
    ad.action = act
    if ad.action_slot is None:
        ad.action_slot = act.slots[0]
    bpy.context.scene.frame_set(int(frame))


def hold(m, name, frame):
    """Shows clip name at frame and keeps that pose while the scene goes to other frames (one model held still
    while another plays): the pose is copied off the clip, which is then taken off. play() undoes it."""
    play(m, name, frame)
    pose = [(pb, pb.location.copy(), pb.rotation_quaternion.copy(), pb.scale.copy()) for pb in m.arm.pose.bones]
    m.arm.animation_data.action = None
    for pb, loc, q, s in pose:
        pb.location, pb.rotation_quaternion, pb.scale = loc, q, s
    bpy.context.view_layer.update()


def rest(m):
    """Takes any clip off and shows the rest pose."""
    ad = m.arm.animation_data
    if ad:
        ad.action = None
    for pb in m.arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()


def channels(act):
    """Every F-curve of an action (Blender 5.2's layered actions: layers > strips > channelbags > fcurves)."""
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                out += list(bag.fcurves)
    return out


def length(act):
    """The clip's last frame (it starts at 0)."""
    return int(act.frame_end)
