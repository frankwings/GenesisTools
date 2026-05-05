"""Benchmark: Windows Blender + WORKBENCH, first 20 frames of v41 animated blend."""
import json
import subprocess
import tempfile
import time
from pathlib import Path

BLENDER_WIN  = "/mnt/c/Program Files/Blender Foundation/Blender 4.5/blender.exe"
BLEND        = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v41/AI33_001_280_walkthrough.blend"
OUT_DIR      = Path("/home/kingy/Projects/Genesis/GenesisTools/results/bench_workbench")
RENDER_SCRIPT = Path("/home/kingy/Projects/Genesis/GenesisTools/genesis_tools/walkthrough_renderer/pipeline/_render_frames.py")

def wslpath(p):
    r = subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True)
    return r.stdout.strip()

OUT_DIR.mkdir(parents=True, exist_ok=True)
frames_dir = OUT_DIR / "frames"
frames_dir.mkdir(exist_ok=True)

win_tmp = Path("/mnt/c/tmp/genesis_render")
win_tmp.mkdir(parents=True, exist_ok=True)
cfg_path = win_tmp / "bench_config.json"

config = {
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "panoramic": False,
    "fps": 12,
    "frames_dir": wslpath(str(frames_dir)),
    "_windows_blender": True,
}
cfg_path.write_text(json.dumps(config))

# Limit to frames 1-20 via frame_start/end override — inject via a tiny wrapper
wrapper = win_tmp / "bench_wrapper.py"
wrapper.write_text(f"""
import bpy, json, sys

config_path = None
for i, arg in enumerate(sys.argv):
    if arg == "--config" and i + 1 < len(sys.argv):
        config_path = sys.argv[i + 1]
        break

with open(config_path) as f:
    config = json.load(f)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end   = 20

scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = config["render_width"]
scene.render.resolution_y = config["render_height"]
sep = "\\\\"
scene.render.filepath = config["frames_dir"] + sep + "frame_"
scene.render.image_settings.file_format = "PNG"
scene.render.use_persistent_data = True

print("[Bench] Windows Blender + WORKBENCH, frames 1-20")
bpy.ops.render.render(animation=True)
""")

cmd = [
    BLENDER_WIN, "--background", wslpath(BLEND),
    "--python", wslpath(str(wrapper)),
    "--", "--config", wslpath(str(cfg_path)),
]

print(f"[Bench] Starting Windows Blender + WORKBENCH benchmark (20 frames)...")
t0 = time.time()
result = subprocess.run(cmd, capture_output=False)
elapsed = time.time() - t0

rendered = sorted(frames_dir.glob("frame_*.png"))
n = len(rendered)
if n > 0:
    per_frame = elapsed / n
    print(f"\n[Bench] Done: {n} frames in {elapsed:.1f}s → {per_frame:.2f}s/frame")
    print(f"[Bench] Projected 1012 frames: {1012 * per_frame / 60:.1f} min")
else:
    print(f"[Bench] No frames rendered (exit {result.returncode})")
