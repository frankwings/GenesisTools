"""Render debug_viz.blend for v40 and v41 results (top + side views)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")
import bpy
from mathutils import Vector, Euler
import math

# Scene bounds (same for all runs): X(-360,1039) Y(-1298,702) Z(-21,779)
cx, cy, cz = 340.0, -298.0, 379.0

def render_views(blend_path, out_dir):
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    scene = bpy.context.scene
    scene.render.engine           = "BLENDER_WORKBENCH"
    scene.render.resolution_x     = 1920
    scene.render.resolution_y     = 1080
    scene.render.film_transparent = False

    # Convert bevel curves to meshes
    for obj in list(bpy.data.objects):
        if obj.type == "CURVE" and obj.data.bevel_depth > 0:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.ops.object.convert(target="MESH")

    # Hide non-debug objects
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

    # Top-down orthographic
    cd = bpy.data.cameras.new("OrthoTop")
    cd.type = "ORTHO"; cd.ortho_scale = 2300.0
    cd.clip_start = 1.0; cd.clip_end = 10000.0
    co = bpy.data.objects.new("OrthoTop", cd)
    scene.collection.objects.link(co)
    co.location = Vector((cx, cy, cz + 4000))
    co.rotation_euler = Euler((0, 0, 0), "XYZ")
    scene.camera = co
    scene.render.filepath = f"{out_dir}/debug_top.png"
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(co, do_unlink=True); bpy.data.cameras.remove(cd)
    print(f"[Render] -> {out_dir}/debug_top.png")

    # Side view (XZ)
    cd2 = bpy.data.cameras.new("OrthoSide")
    cd2.type = "ORTHO"; cd2.ortho_scale = 1000.0
    cd2.clip_start = 1.0; cd2.clip_end = 10000.0
    co2 = bpy.data.objects.new("OrthoSide", cd2)
    scene.collection.objects.link(co2)
    co2.location = Vector((cx, cy - 4000, cz))
    co2.rotation_euler = Euler((math.radians(90), 0, 0), "XYZ")
    scene.camera = co2
    scene.render.filepath = f"{out_dir}/debug_side.png"
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(co2, do_unlink=True); bpy.data.cameras.remove(cd2)
    print(f"[Render] -> {out_dir}/debug_side.png")


ROOT = "/home/kingy/Projects/Genesis/GenesisTools/results"

for version in ("v40", "v41"):
    out = f"{ROOT}/ai33_001_walkthrough_{version}"
    blend = f"{out}/debug_viz.blend"
    print(f"\n=== {version} ===")
    render_views(blend, out)

print("\nDone.")
