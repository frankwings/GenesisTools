"""Blender --background render helper for pipeline/render.py.

Called by BlenderRunner. Scene .blend is pre-loaded by blender --background.
"""
import json
import sys
import bpy

# Parse --config argument
config_path = None
for i, arg in enumerate(sys.argv):
    if arg == "--config" and i + 1 < len(sys.argv):
        config_path = sys.argv[i + 1]
        break

if config_path is None:
    raise SystemExit("--config not provided")

with open(config_path) as f:
    config = json.load(f)

scene = bpy.context.scene
engine = config.get("render_engine", "CYCLES").upper()

if engine == "WORKBENCH":
    scene.render.engine = "BLENDER_WORKBENCH"
elif engine in ("EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
else:
    scene.render.engine = "CYCLES"
    scene.cycles.samples = config.get("render_samples", 32)
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.adaptive_min_samples = 4
    scene.view_layers[0].cycles.use_denoising = True
    # GPU device is set via --cycles-device CLI arg by render.py

if config.get("panoramic"):
    cam_data = scene.camera.data
    cam_data.type = "PANO"
    cam_data.panorama_type = "EQUIRECTANGULAR"

scene.render.resolution_x = config.get("render_width", 1280)
scene.render.resolution_y = config.get("render_height", 720)
scene.render.filepath = config["frames_dir"] + "/frame_"
scene.render.image_settings.file_format = "PNG"
scene.render.use_persistent_data = True

bpy.ops.render.render(animation=True)
