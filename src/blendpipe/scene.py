"""The Blender scene the pipeline builds in: a clean start, empties, trees of objects."""
import bpy

from . import materials, textures

FPS = 30


def reset(fps=FPS):
    """Empties the scene and every datablock a build makes, so a build starts from nothing (and --factory-startup's
    cube, camera and light are gone). Sets the frame rate before anything is keyed."""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.actions, bpy.data.armatures, bpy.data.images,
                 bpy.data.lights, bpy.data.cameras, bpy.data.curves, bpy.data.worlds):
        for block in list(coll):
            coll.remove(block)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    materials.reset()
    textures.reset()
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_set(0)


def empty(name, parent=None, loc=(0, 0, 0)):
    """An empty; the glTF export keeps it as a node and its custom properties as the node's extras."""
    o = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(o)
    o.empty_display_size = 0.1
    o.location = loc
    o.parent = parent
    return o


def descendants(o):
    out = []
    for c in o.children:
        out.append(c)
        out.extend(descendants(c))
    return out


def tree(root):
    return [root, *descendants(root)]


def triangles(objs):
    """How many triangles the meshes among objs have."""
    return sum(len(p.vertices) - 2 for o in objs if o.type == "MESH" for p in o.data.polygons)
