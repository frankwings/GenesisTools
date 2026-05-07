"""the_hideaway — standard config v2: finer grid (2.5m/voxel) + Cycles.

v1 issues:
  1. Grid too coarse (6.25m/voxel) — walls thinner than 6.25m invisible to
     voxel grid, causing the path to walk straight through them.
  2. Workbench render — no lighting.
  3. No path visualization.

v2 fixes:
  1. max_grid_cells_xy/z increased to 200/60 → 2.5m/voxel (better wall detection).
  2. Render switched to Cycles 640×480, 64spp, OIDN.
  3. Debug viz blend generated (voxel grid + walkable + path layers).
"""
import sys, json, shutil, subprocess
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Foundation/Assets/BlenderScenes/the_hideaway/the hideaway.blend"
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/the_hideaway_standard_v2")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/the_hideaway_standard_v2")
BPY_PY  = "/home/kingy/blender/4.5/python/bin/python3.11"

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/standard_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# v2 overrides: finer voxels + Cycles
config.update({
    "max_grid_cells_xy": 200,
    "max_grid_cells_z":  60,
    "render_engine":     "CYCLES",
    "render_width":      640,
    "render_height":     480,
    "render_samples":    64,
    "use_denoise":       True,
})

# --- Walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[the_hideaway v2] Walkthrough → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# --- Debug visualization blend ---
print("[the_hideaway v2] Generating debug viz blend …")
import tempfile, os
tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump(config, tf); tf.close()
walkthrough_blend = next(OUT_DIR.glob("*.blend"))
viz_blend = OUT_DIR / "the_hideaway_debug_viz.blend"
subprocess.run([
    BPY_PY, "-m", "genesis_tools.walkthrough_renderer.visualize",
    "--blend",      BLEND,
    "--output",     str(viz_blend),
    "--voxel-grid", str(OUT_DIR / "voxel_grid.npz"),
    "--walkable",   str(OUT_DIR / "walkable.npz"),
    "--path",       str(OUT_DIR / "path.npz"),
    "--camera",     str(walkthrough_blend),
    "--config",     tf.name,
], check=True)
os.unlink(tf.name)

# --- GIF ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[the_hideaway v2] {len(all_frames)} frames → GIF")

from genesis_tools.gif_generator import create_gif
create_gif(all_frames, ASSETS / "the_hideaway_standard_v2_walkthrough.gif",
           duration=int(1000 / config["fps"]))

print("[the_hideaway v2] ALL DONE")
