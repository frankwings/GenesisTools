"""coastal_road — terrain config v2.

Changes from v1:
  Phase 1  — re-fit terrain snake (new terrain_snake.npz now saves camera_lookat)
  Phase 2  — auto-resolution (grid_resolution="auto", start 20 BU, cap 14400 cells)
             force_camera_walkable=True (in terrain_scene.json default)
             cam_iz lookup from walkable_set (path_plan fix)
  Viz      — terrain_figure_6 (voxel walkability overlay) added
"""
import sys, json, subprocess, shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND      = "/home/kingy/Foundation/Assets/BlenderScenes/coastal_road/coastal road.blend"
OUT_DIR    = Path("/home/kingy/Projects/Genesis/GenesisTools/results/coastal_road_terrain_v2")
ASSETS     = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/coastal_road_terrain_v2")
NPZ        = OUT_DIR / "terrain_snake.npz"
BLENDER    = "/home/kingy/blender/blender"
FIT_SCRIPT = "/home/kingy/Projects/Genesis/GenesisTools/genesis_tools/active_contour/fit_terrain_contour.py"

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

# Load canonical terrain config
with open("/home/kingy/Projects/Genesis/GenesisTools/configs/terrain_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# v2: enable auto-resolution
config["grid_resolution"] = "auto"

# Coastal road is open terrain — no scatter vegetation to filter, and mesh parity
# check on 32400 candidates × 303 mesh objects takes hours with no effect (v1 showed
# all cells walkable). Skip the bpy particle/mesh passes entirely.
config["mark_particle_instances"] = False

# 10 BU eye height above TerrainSnake cloth surface.  1.7 (human height) is
# technically correct but produces a water-level view in coastal/low-elevation
# cells and clips inside vegetation canopies.  10 BU clears most tree canopies
# and gives a low-aerial perspective suited to this 50 km × 50 km scene.
config["camera_height"] = 10.0

# --- Phase 1: terrain snake (re-fit if not present) ---
if NPZ.exists():
    print(f"[coastal_road terrain v2] Phase 1: reusing {NPZ}")
else:
    print("[coastal_road terrain v2] Phase 1: fitting terrain snake …")
    subprocess.run([
        BLENDER, "--background", BLEND,
        "--python-exit-code", "1", "--python", FIT_SCRIPT, "--",
        "--blend", BLEND, "--output-dir", str(OUT_DIR),
        "--grid-resolution",          str(config.get("terrain_snake_resolution", 2.0)),
        "--max-grid-cells-xy",        str(config["max_grid_cells_xy"]),
        "--env-sphere-percentile",    str(config["env_sphere_percentile"]),
        "--ray-samples",              str(config["terrain_ray_samples"]),
        "--alpha",                    str(config["terrain_alpha"]),
        "--gravity",                  str(config["terrain_gravity"]),
        "--dt",                       str(config["terrain_dt"]),
        "--max-iterations",           str(config["terrain_max_iterations"]),
        "--convergence-threshold",    str(config["terrain_convergence_threshold"]),
        "--start-height",             str(config["terrain_start_height"]),
        "--refine-pad-cells",         str(config["refine_pad_cells"]),
    ], check=True)

config["terrain_npz"] = str(NPZ)

# --- Phase 2: walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[coastal_road terrain v2] Phase 2 → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# --- Terrain figures (includes new figure_6 voxel walkability overlay) ---
from genesis_tools.active_contour.visualize import run_terrain_snake
if not (OUT_DIR / "terrain_snake.npz").exists():
    shutil.copy2(NPZ, OUT_DIR / "terrain_snake.npz")
run_terrain_snake(OUT_DIR)

for p in (OUT_DIR / "viz").glob("*.png"):
    shutil.copy2(p, ASSETS / p.name)

# --- GIF + MP4 ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[coastal_road terrain v2] {len(all_frames)} frames → GIF + MP4")

from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

create_gif(all_frames, ASSETS / "coastal_road_terrain_v2_walkthrough.gif",
           duration=int(1000 / config["fps"]))

make_combined_gif(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_gif=ASSETS / "coastal_road_terrain_v2_walkthrough_combined.gif",
                  fps=config["fps"], step=3, output_scale=0.5)

make_combined_mp4(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_mp4=ASSETS / "coastal_road_terrain_v2_walkthrough_combined.mp4",
                  fps=6, step=1, output_scale=1.0)

print("[coastal_road terrain v2] ALL DONE")
