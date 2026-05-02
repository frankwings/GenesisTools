"""Render debug_viz_v2.blend from an overview camera to PNG.

Run under bpy Python:
  /home/kingy/blender/4.5/python/bin/python3.11 render_debug_viz.py
"""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")
import bpy
from mathutils import Vector, Euler
import math

BLEND   = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v42/debug_viz_v2.blend"
OUT_TOP  = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v42/debug_top.png"
OUT_SIDE = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v42/debug_side.png"

bpy.ops.wm.open_mainfile(filepath=BLEND)

scene = bpy.context.scene
scene.render.engine         = "BLENDER_WORKBENCH"
scene.render.resolution_x   = 1920
scene.render.resolution_y   = 1080
scene.render.film_transparent = False

# Convert all bevel curves to meshes so WORKBENCH renders them correctly
import bmesh as _bm
for obj in list(bpy.data.objects):
    if obj.type == "CURVE" and obj.data.bevel_depth > 0:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.convert(target="MESH")

# Hide scene (non-debug) objects so path and camera arrows are clearly visible
debug_names = {"DebugViz", "DebugViz_Spheres", "DebugViz_Wireframes"}
for col in bpy.data.collections:
    if col.name not in debug_names:
        col.hide_render = True
# Also hide top-level scene objects not in any debug collection
debug_objs = set()
for col in bpy.data.collections:
    if col.name in debug_names:
        for o in col.objects:
            debug_objs.add(o.name)
for obj in bpy.data.objects:
    if obj.name not in debug_objs and not obj.name.startswith("OverviewCam") and not obj.name.startswith("OrthoTop") and not obj.name.startswith("OrthoSide"):
        obj.hide_render = True

# Remove any existing overview cameras
for obj in list(bpy.data.objects):
    if obj.name.startswith("OverviewCam"):
        bpy.data.objects.remove(obj, do_unlink=True)

def render_from(location, rotation_euler, output_path):
    cam_data = bpy.data.cameras.new("OverviewCam")
    cam_data.type = "PERSP"
    cam_data.lens = 35
    cam_obj = bpy.data.objects.new("OverviewCam", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    cam_obj.rotation_euler = rotation_euler
    scene.camera = cam_obj

    scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam_obj, do_unlink=True)
    bpy.data.cameras.remove(cam_data)
    print(f"[Render] -> {output_path}")

# Scene bounds: X(-360,1039) Y(-1298,702) Z(-21,779) BU
# Scene center: (340, -298, 379); scene size ~1400 x 2000 x 800 BU
cx, cy, cz = 340.0, -298.0, 379.0

# Scene: X(-360,1039) Y(-1298,702) Z(-21,779)
# Top-down: show XY extent (~1400 x 2000 BU) → ortho_scale = 2100 for Y axis, ratio 16:9
cam_data = bpy.data.cameras.new("OrthoTop")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 2300.0    # vertical extent; horizontal = 2300*(16/9)=4089 → fits X 1400
cam_data.clip_start = 1.0
cam_data.clip_end = 10000.0
cam_obj = bpy.data.objects.new("OrthoTop", cam_data)
bpy.context.scene.collection.objects.link(cam_obj)
cam_obj.location = Vector((cx, cy, cz + 4000))
cam_obj.rotation_euler = Euler((0, 0, 0), "XYZ")   # -Z down
scene.camera = cam_obj
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.filepath = OUT_TOP
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(cam_obj, do_unlink=True)
bpy.data.cameras.remove(cam_data)
print(f"[Render] -> {OUT_TOP}")

# Side (XZ plane): X 1400 BU wide, Z 800 BU tall
# ortho_scale = 1000 (vertical); horizontal = 1000*(16/9) = 1778 → fits X 1400
cam_data2 = bpy.data.cameras.new("OrthoSide")
cam_data2.type = "ORTHO"
cam_data2.ortho_scale = 1000.0
cam_data2.clip_start = 1.0
cam_data2.clip_end = 10000.0
cam_obj2 = bpy.data.objects.new("OrthoSide", cam_data2)
bpy.context.scene.collection.objects.link(cam_obj2)
cam_obj2.location = Vector((cx, cy - 4000, cz))
cam_obj2.rotation_euler = Euler((math.radians(90), 0, 0), "XYZ")   # look +Y
scene.camera = cam_obj2
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.filepath = OUT_SIDE
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(cam_obj2, do_unlink=True)
bpy.data.cameras.remove(cam_data2)
print(f"[Render] -> {OUT_SIDE}")

print("Done.")
