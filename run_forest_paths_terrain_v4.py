"""forest_paths — terrain v4: 10 BU grid + particle_block_margin=1.0 (walkable forest paths).

Changes from v3 (20 BU grid):
  grid_resolution         20 → 10  (60×60 instead of 30×30, finer cell = less blocked per tree)
  particle_block_margin   1.5 → 1.0 (allows paths between trees without clipping canopy)
  terrain_boundary_margin 1 → 2  (keeps same 20 BU physical edge buffer at 10 BU cell size)

Phase 1 (terrain_snake.npz) is reused from v1 — no re-fit needed.
"""
import sys, json, subprocess, shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND       = "/home/kingy/Foundation/Assets/BlenderScenes/forest_paths/forest paths.blend"
V1_OUT      = Path("/home/kingy/Projects/Genesis/GenesisTools/results/forest_paths_terrain_v1")
OUT_DIR     = Path("/home/kingy/Projects/Genesis/GenesisTools/results/forest_paths_terrain_v4")
ASSETS      = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/forest_paths_terrain_v4")
NPZ         = V1_OUT / "terrain_snake.npz"   # reuse Phase 1 from v1

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/terrain_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# v4 overrides
config["grid_resolution"]         = 10.0
config["particle_block_margin"]   = 1.0
config["terrain_boundary_margin"] = 2

config["terrain_npz"] = str(NPZ)

# --- Phase 2: walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[forest_paths v4] Phase 2 → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# run_terrain_snake reads terrain_snake.npz from OUT_DIR; copy from v1 if not present
if not (OUT_DIR / "terrain_snake.npz").exists():
    shutil.copy2(NPZ, OUT_DIR / "terrain_snake.npz")

# --- Terrain figures ---
from genesis_tools.active_contour.visualize import run_terrain_snake
run_terrain_snake(OUT_DIR)

for p in (OUT_DIR / "viz").glob("*.png"):
    shutil.copy2(p, ASSETS / p.name)

# --- GIF + MP4 ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[forest_paths v4] {len(all_frames)} frames → GIF + MP4")

from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

create_gif(all_frames, ASSETS / "forest_paths_terrain_v4_walkthrough.gif",
           duration=int(1000 / config["fps"]))

make_combined_gif(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_gif=ASSETS / "forest_paths_terrain_v4_walkthrough_combined.gif",
                  fps=config["fps"], step=3, output_scale=0.5)

make_combined_mp4(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_mp4=ASSETS / "forest_paths_terrain_v4_walkthrough_combined.mp4",
                  fps=6, step=1, output_scale=1.0)

print("[forest_paths v4] ALL DONE")
