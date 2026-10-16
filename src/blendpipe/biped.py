"""A ready humanoid: a 21-bone skeleton of a 1.80 m figure, poses written as keys, and walk/run cycles whose planted
feet stay put on the ground at the clip's speed.

The rig (HUMANOID) stands on z 0 facing -y, its left +x. Its table is in the order the glTF exporter lists the
joints, so the glb's skin has them in this order (with "_" for "." once slimmed: three.js strips dots from names).

A key is a dict:
  hips   {"at": (x, y, z) of the hips bone's head, "rot": (x, y, z) degrees}
  spine, chest, neck, head   (x, y, z) degrees relative to the parent
  legs   {"L": {"ankle": (x, y, z), "foot": (x, y, z) degrees (world), "pole": where the knee points,
                "toe": degrees or "flat", "free": True for a swinging foot}, "R": {...}}
  arms   {"L": {"mode": "fk", "upper": (x, y, z), "fore": (x, y, z), "hand": (x, y, z)}  (degrees, relative)
         or    {"mode": "ik", "wrist": (x, y, z), "pole": elbow direction, "hand": (x, y, z) degrees (world)}}
  reach  True lowers the hips until the planted legs reach their ankles (default)
pose(rig, key) turns it into a rig.Pose; anim.timeline() and anim.blend() mix keys.
"""
import math

from mathutils import Vector

from . import anim
from .anim import bump, merge, smooth
from .rig import Pose, mirror_table, rot

_LEFT = [
    ("shoulder.L", "chest", (0.025, -0.03, 1.415), (0.185, 0.0, 1.43)),
    ("upper_arm.L", "shoulder.L", (0.185, 0.0, 1.43), (0.215, 0.02, 1.13)),
    ("forearm.L", "upper_arm.L", (0.215, 0.02, 1.13), (0.235, -0.005, 0.87)),
    ("hand.L", "forearm.L", (0.235, -0.005, 0.87), (0.242, -0.02, 0.78)),
    ("thigh.L", "hips", (0.095, 0.0, 0.93), (0.10, -0.015, 0.50)),
    ("shin.L", "thigh.L", (0.10, -0.015, 0.50), (0.10, 0.02, 0.085)),
    ("foot.L", "shin.L", (0.10, 0.02, 0.085), (0.105, -0.115, 0.025)),
    ("toe.L", "foot.L", (0.105, -0.115, 0.025), (0.108, -0.19, 0.02)),
]
_ARM_L, _LEG_L = _LEFT[:4], _LEFT[4:]

HUMANOID = [
    ("hips", None, (0, 0.0, 0.97), (0, 0.0, 1.06)),
    ("spine", "hips", (0, 0.0, 1.06), (0, 0.0, 1.22)),
    ("chest", "spine", (0, 0.0, 1.22), (0, 0.0, 1.45)),
    ("neck", "chest", (0, 0.005, 1.46), (0, -0.005, 1.585)),
    ("head", "neck", (0, -0.005, 1.585), (0, -0.005, 1.80)),
    *_ARM_L,
    *mirror_table(_ARM_L),
    *_LEG_L,
    *mirror_table(_LEG_L),
]

HIPS_Z = 0.97                                   # the hips bone's head, standing straight
ANKLE = 0.085                                   # the ankle above a flat foot's sole
HEEL = Vector((0, 0.058, -ANKLE))               # the heel, the ball of the foot and the toe tip, from the ankle
BALL = Vector((0, -0.135, -ANKLE))
TOE = Vector((0, -0.215, -ANKLE))


def stand_key(width=0.11, stagger=0.0, crouch=0.0):
    """Standing at ease: the key the others are written from."""
    return {
        "hips": {"at": (0.0, 0.0, HIPS_Z - crouch), "rot": (0.0, 0.0, 0.0)},
        "spine": (0.0, 0.0, 0.0), "chest": (0.0, 0.0, 0.0), "neck": (0.0, 0.0, 0.0), "head": (0.0, 0.0, 0.0),
        "legs": {
            "L": {"ankle": (width, -stagger, ANKLE), "foot": (0.0, 0.0, 6.0), "pole": (0.15, -1.0, 0.0)},
            "R": {"ankle": (-width, stagger, ANKLE), "foot": (0.0, 0.0, -6.0), "pole": (-0.15, -1.0, 0.0)},
        },
        "arms": {
            "L": {"mode": "fk", "upper": (4.0, -7.0, 0.0), "fore": (-14.0, 0.0, 0.0), "hand": (0.0, 0.0, 0.0)},
            "R": {"mode": "fk", "upper": (4.0, 7.0, 0.0), "fore": (-14.0, 0.0, 0.0), "hand": (0.0, 0.0, 0.0)},
        },
        "reach": True,
    }


def pose(rig, k):
    """A rig.Pose of the humanoid from a key (see the module's docstring)."""
    p = Pose(rig)
    hips = k["hips"]
    p.offset = Vector(hips["at"]) - rig.heads["hips"]
    p.set("hips", rot(*hips["rot"]))
    for b in ("spine", "chest", "neck", "head"):
        p.set(b, rot(*k.get(b, (0, 0, 0))))
    legs = k["legs"]
    if k.get("reach", True):
        for _ in range(3):
            short = 0.0
            for side in "LR":
                leg = legs[side]
                if "knee" in leg or leg.get("free"):
                    continue
                hip = p.world(f"thigh.{side}")[1]
                full = (rig.length(f"thigh.{side}") + rig.length(f"shin.{side}")) * 0.995
                v = Vector(leg["ankle"]) - hip
                if v.length > full:
                    flat = Vector((v.x, v.y, 0)).length
                    if flat < full:
                        short = max(short, hip.z - (leg["ankle"][2] + math.sqrt(full * full - flat * flat)))
            if short <= 1e-5:
                break
            p.move((0, 0, -short))
    for side in "LR":
        leg = legs[side]
        thigh, shin, foot = f"thigh.{side}", f"shin.{side}", f"foot.{side}"
        fq = rot(*leg.get("foot", (0, 0, 0)))
        if "knee" in leg:
            hip = p.world(thigh)[1]
            p.aim(thigh, Vector(leg["knee"]) - hip, Vector((0, -1, 0)), Vector((0, -1, 0)))
            p.aim(shin, Vector(leg["ankle"]) - p.tail(thigh), Vector((0, -1, 0)), Vector((0, -1, 0)))
            p.set_world(foot, fq)
        else:
            p.ik(thigh, shin, leg["ankle"], leg.get("pole", (0, -1, 0)), (0, -1, 0), foot, fq)
        toe = leg.get("toe", 0.0)
        if toe == "flat":
            p.set_world(f"toe.{side}", rot(0.0, 0.0, leg.get("foot", (0, 0, 0))[2]))
        else:
            p.set(f"toe.{side}", rot(toe))
    for side in "LR":
        arm = k["arms"][side]
        upper, fore, hand = f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}"
        p.set(f"shoulder.{side}", rot(*arm.get("shoulder", (0, 0, 0))))
        if arm["mode"] == "fk":
            p.set(upper, rot(*arm["upper"]))
            p.set(fore, rot(*arm["fore"]))
            p.set(hand, rot(*arm.get("hand", (0, 0, 0))))
        else:
            p.ik(upper, fore, arm["wrist"], arm.get("pole", (0.4, 0.6, -0.5)), (0, 1, 0), hand,
                 rot(*arm.get("hand", (0, 0, 0))))
    return p


# ---------------------------------------------------------------- walking and running

class Gait:
    """A biped's feet over one cycle at speed (m/s) and period (s): duty is the share of the cycle a foot is down,
    lift how high a swinging foot rises, kick how far a running foot flicks back, heel and toe (degrees) how far
    the foot rolls at the start and the end of its stance. The left foot strikes at t 0, the right at 0.5. A
    planted foot moves backwards at speed, so it stays put on the ground while the figure moves forwards."""

    def __init__(self, speed, period, duty, lift, kick=0.0, heel=14.0, toe=30.0, width=0.10, ahead=0.0):
        self.speed, self.period, self.duty = speed, period, duty
        self.lift, self.kick, self.heel, self.toe = lift, kick, heel, toe
        self.width, self.ahead = width, ahead
        self.stride = speed * period            # metres the body travels in one cycle

    def _stance(self, s):
        """Ankle (y, z) and pitch at stance progress s: heel strike, flat, toe off."""
        sweep = self.duty * self.stride
        g = -sweep / 2 + s * sweep - self.ahead
        if s < 0.18:
            pitch = -self.heel * (1 - s / 0.18) ** 2
            pivot = Vector((0, g + HEEL.y, 0))
            ankle = pivot + rot(pitch) @ -HEEL
        elif s < 0.62:
            pitch = 0.0
            ankle = Vector((0, g, ANKLE))
        else:
            pitch = self.toe * ((s - 0.62) / 0.38) ** 1.6
            pivot = Vector((0, g + BALL.y, 0))
            ankle = pivot + rot(pitch) @ -BALL
        return ankle, pitch

    def foot(self, phase, side):
        """(ankle position, foot rotation in degrees, planted, toe) of foot side at its phase of the cycle."""
        phase %= 1.0
        x = self.width if side == "L" else -self.width
        yaw = 6.0 if side == "L" else -6.0
        if phase < self.duty:
            ankle, pitch = self._stance(phase / self.duty)
            return (x, ankle.y, ankle.z), (pitch, 0.0, yaw), True, (0.0 if pitch < 0 else "flat")
        u = (phase - self.duty) / (1 - self.duty)
        a0, p0 = self._stance(1.0)
        a1, p1 = self._stance(0.0)
        w = smooth(u)
        y = a0.y + (a1.y - a0.y) * w + self.kick * math.sin(math.pi * u) * (1 - u) ** 1.5
        z = a0.z + (a1.z - a0.z) * u + self.lift * math.sin(math.pi * min(1.0, u * 1.12)) ** 0.85
        pitch = p0 + (p1 - p0) * smooth(u * 1.3)
        toe = -p0 * (1 - smooth(u * 2.5)) + 8.0 * bump(u, 0.3, 0.9)
        return (x, y, z), (pitch, 0.0, yaw), False, toe


def gait_key(base, gait, t, hips_z, bob, lean, pelvis_yaw=6.0, chest_yaw=4.0, sway=0.012, roll=2.0):
    """A walking or running key at t from base: the feet from gait, the hips bobbing twice a cycle (bob metres,
    lowest as each foot strikes), the body leaning lean degrees, the pelvis and the chest turning against each
    other."""
    k = merge(base)
    c = math.cos(math.tau * t)
    z = hips_z - bob * (0.5 + 0.5 * math.cos(math.tau * 2 * t))
    k["hips"] = {"at": (sway * math.sin(math.tau * t + 0.3), 0.0, z),
                 "rot": (lean * 0.4, roll * math.sin(math.tau * t), -pelvis_yaw * c)}
    k["spine"] = (lean * 0.3, 0.0, pelvis_yaw * c * 0.4)
    k["chest"] = (lean * 0.3, 0.0, (pelvis_yaw * 0.6 + chest_yaw) * c)
    k["neck"] = (-lean * 0.5, 0.0, -chest_yaw * c * 0.5)
    k["head"] = (-lean * 0.3, 0.0, -chest_yaw * c * 0.5)
    legs = {}
    for side, offset in (("L", 0.0), ("R", 0.5)):
        ankle, foot, planted, toe = gait.foot(t + offset, side)
        legs[side] = {"ankle": ankle, "foot": foot, "pole": (0.12 if side == "L" else -0.12, -1.0, 0.0),
                      "free": not planted, "toe": toe}
    k["legs"] = legs
    return k


def swing_arms(k, t, amount, elbow=-18.0, elbow_swing=-10.0, sides="LR"):
    """Arms hanging and swinging against the legs (the left arm back as the left foot strikes)."""
    c = math.cos(math.tau * t)
    arms = dict(k["arms"])
    for side in sides:
        s = 1 if side == "L" else -1
        a = amount * c * s
        arms[side] = {"mode": "fk", "upper": (a, -7.0 * s, 0.0),
                      "fore": (elbow + elbow_swing * max(0.0, -a / max(amount, 1e-6)), 0.0, 0.0),
                      "hand": (0.0, 0.0, 0.0)}
    k["arms"] = arms
    return k


# ---------------------------------------------------------------- whole clips

def idle(m, name="idle", frames=60, crouch=0.025, stagger=0.04, width=0.12):
    """Standing, breathing, the weight shifting a little."""
    def fn(t):
        k = stand_key(width=width, stagger=stagger, crouch=crouch)
        b = anim.wave(t)
        k["hips"] = {"at": (0.012 * anim.wave(t, 1, 0.25), 0.0, HIPS_Z + 0.01 - crouch - 0.006 * b),
                     "rot": (1.0, 1.0 * anim.wave(t, 1, 0.25), 2.0 * anim.wave(t, 1, 0.1))}
        k["spine"] = (1.0 + 0.8 * b, 0.0, 0.0)
        k["chest"] = (0.8 * b, 0.0, -1.5 * anim.wave(t, 1, 0.1))
        k["neck"] = (0.0, 0.0, 4.0 * anim.wave(t, 1, 0.6))
        k["head"] = (-1.0 * b, 0.0, 3.0 * anim.wave(t, 1, 0.6))
        return pose(m.rig, k)
    return anim.record(m, name, frames, fn)


def walk(m, name="walk", frames=26, speed=None, duty=0.6, lift=0.07, lean=4.0, bob=0.018, hips_z=0.965,
         arm_swing=18.0):
    """A walk cycle at speed m/s (default: the spec's clips[name]["speed"], else 1.4)."""
    speed = speed or m.spec["clips"][name].get("speed", 1.4)
    gait = Gait(speed, frames / m.fps, duty, lift, heel=20.0, toe=40.0)
    base = stand_key()
    return anim.record(m, name, frames, lambda t: pose(m.rig, swing_arms(
        gait_key(base, gait, t, hips_z, bob, lean), t, arm_swing)))


def run(m, name="run", frames=20, speed=None, duty=0.36, lift=0.14, kick=0.22, lean=13.0, bob=0.035, hips_z=0.95,
        arm_swing=34.0):
    """A run cycle at speed m/s (default: the spec's clips[name]["speed"], else 3.0); feet leave the ground."""
    speed = speed or m.spec["clips"][name].get("speed", 3.0)
    gait = Gait(speed, frames / m.fps, duty, lift, kick=kick, heel=6.0, toe=34.0, width=0.085)
    base = stand_key()

    def fn(t):
        k = gait_key(base, gait, t, hips_z, 0.0, lean, pelvis_yaw=8.0, chest_yaw=6.0, sway=0.008)
        x, y, z = k["hips"]["at"]
        k["hips"]["at"] = (x, y, z - bob * (0.5 + 0.5 * math.cos(math.tau * 2 * (t - duty / 2))))
        return pose(m.rig, swing_arms(k, t, arm_swing, elbow=-70.0, elbow_swing=-15.0))
    return anim.record(m, name, frames, fn)
