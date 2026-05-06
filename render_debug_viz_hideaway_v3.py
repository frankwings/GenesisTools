"""Render debug_viz.blend for hideaway standard v3 — top (XY) + side (XZ) views."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")
import bpy
from mathutils import Vector, Euler
import math

BLEND    = "/home/kingy/Projects/Genesis/GenesisTools/results/the_hideaway_standard_v3/the_hideaway_debug_viz.blend"
OUT_TOP  = "/home/kingy/Projects/Genesis/GenesisTools/docs/assets/the_hideaway_standard_v3/debug_top.png"
OUT_SIDE = "/home/kingy/Projects/Genesis/GenesisTools/docs/assets/the_hideaway_standard_v3/debug_side.png"

# Scene bounds: X [-250,250], Y [-250,250], Z [-9.5, 163]
cx, cy, cz = 0.0, 0.0, 76.75

bpy.ops.wm.open_mainfile(filepath=BLEND)
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.film_transparent = False
scene.render.image_settings.file_format = "PNG"

# Convert any curve objects to mesh
for obj in list(bpy.data.objects):
    if obj.type == "CURVE" and obj.data.bevel_depth > 0:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.convert(target="MESH")

# Hide all non-DebugViz collections and objects
debug_names = {"DebugViz", "DebugViz_Spheres", "DebugViz_Wireframes"}
for col in bpy.data.collections:
    if col.name not in debug_names:
        col.hide_render = True
debug_objs = set()
for col in bpy.data.collections:
    if col.name in debug_names:
        for o in col.objects:
            debug_objs.add(o.name)
for obj in bpy.data.objects:
    if obj.name not in debug_objs:
        obj.hide_render = True

# --- Top view (XY, looking down from +Z) ---
cd = bpy.data.cameras.new("OrthoTop")
cd.type = "ORTHO"
cd.ortho_scale = 600.0   # covers 500 BU scene width with margin
cd.clip_start = 1.0
cd.clip_end = 10000.0
co = bpy.data.objects.new("OrthoTop", cd)
bpy.context.scene.collection.objects.link(co)
co.location = Vector((cx, cy, 163.0 + 4000.0))
co.rotation_euler = Euler((0, 0, 0), "XYZ")
scene.camera = co
scene.render.filepath = OUT_TOP
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(co, do_unlink=True)
bpy.data.cameras.remove(cd)
print(f"[Render] -> {OUT_TOP}")

# --- Side view (XZ, looking from -Y toward +Y) ---
cd2 = bpy.data.cameras.new("OrthoSide")
cd2.type = "ORTHO"
cd2.ortho_scale = 600.0  # covers 500 BU X range; 172.5 BU Z range visible in height
cd2.clip_start = 1.0
cd2.clip_end = 10000.0
co2 = bpy.data.objects.new("OrthoSide", cd2)
bpy.context.scene.collection.objects.link(co2)
co2.location = Vector((cx, -250.0 - 4000.0, cz))
co2.rotation_euler = Euler((math.radians(90), 0, 0), "XYZ")
scene.camera = co2
scene.render.filepath = OUT_SIDE
bpy.ops.render.render(write_still=True)
bpy.data.objects.remove(co2, do_unlink=True)
bpy.data.cameras.remove(cd2)
print(f"[Render] -> {OUT_SIDE}")
print("Done.")
