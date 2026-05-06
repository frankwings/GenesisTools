"""Blender --background render helper for pipeline/render.py.

Called by BlenderRunner. Scene .blend is pre-loaded by blender --background.
"""
import json
import sys
from pathlib import Path
import bpy

# Ensure genesis_tools is importable when running under an external Blender
# (e.g. Windows Blender) whose Python env doesn't have genesis_tools installed.
# __file__ is .../GenesisTools/genesis_tools/walkthrough_renderer/pipeline/_render_frames.py
# → parents[3] is the GenesisTools root containing the genesis_tools package.
_gt_root = str(Path(__file__).resolve().parents[3])
if _gt_root not in sys.path:
    sys.path.insert(0, _gt_root)

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
use_windows_blender = config.get("_windows_blender", False)

if engine == "WORKBENCH":
    scene.render.engine = "BLENDER_WORKBENCH"
elif engine in ("EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
else:
    scene.render.engine = "CYCLES"
    # Try GPU (OPTIX preferred for NVIDIA, then CUDA, then HIP for AMD,
    # METAL for Apple, ONEAPI for Intel) — fall back to CPU if none enabled.
    prefs = bpy.context.preferences.addons["cycles"].preferences
    enabled_gpu = False
    for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
            prefs.refresh_devices()
            gpu_devices = [d for d in prefs.devices if d.type == backend]
            if gpu_devices:
                for d in prefs.devices:
                    d.use = (d.type == backend)  # enable all of this backend, disable CPU
                scene.cycles.device = "GPU"
                enabled_gpu = True
                names = [d.name for d in gpu_devices]
                print(f"[Cycles] GPU enabled ({backend}): {names}")
                break
        except Exception:
            continue
    if not enabled_gpu:
        scene.cycles.device = "CPU"
        print("[Cycles] No GPU backend available — falling back to CPU")
    scene.cycles.samples = config.get("render_samples", 32)
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.adaptive_min_samples = 4
    # Final-pass denoiser: OpenImageDenoise (best quality, runs on CPU/GPU).
    # Both flags are needed — view_layer.use_denoising marks the layer as
    # denoiseable, scene.cycles.use_denoising actually triggers the pass.
    use_denoise = config.get("use_denoise", True)
    scene.cycles.use_denoising = use_denoise
    if use_denoise:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        scene.cycles.denoising_prefilter = "ACCURATE"
        scene.view_layers[0].cycles.use_denoising = True
        scene.view_layers[0].cycles.denoising_store_passes = True
    else:
        scene.view_layers[0].cycles.use_denoising = False
    print(f"[Cycles] samples={scene.cycles.samples}, denoise={use_denoise}"
          + (f", denoiser={scene.cycles.denoiser}" if use_denoise else ""))

if config.get("panoramic"):
    cam_data = scene.camera.data
    cam_data.type = "PANO"
    cam_data.panorama_type = "EQUIRECTANGULAR"

scene.render.resolution_x = config.get("render_width", 1280)
scene.render.resolution_y = config.get("render_height", 720)
sep = "\\" if use_windows_blender else "/"
scene.render.filepath = config["frames_dir"] + sep + "frame_"
scene.render.image_settings.file_format = "PNG"
scene.render.use_persistent_data = True

# Optional: cap render at frame_end (useful for quick previews)
frame_end_cap = config.get("frame_end")
if frame_end_cap is not None:
    scene.frame_end = min(int(frame_end_cap), scene.frame_end)

if config.get("preprocess_scene", True):
    from genesis_tools.walkthrough_renderer.pipeline.scene_preprocessor import ScenePreprocessor
    ScenePreprocessor().run()

bpy.ops.render.render(animation=True)
