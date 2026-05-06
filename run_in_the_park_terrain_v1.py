"""in_the_park — terrain config v1: two-pass TerrainSnake + Held-Karp walkthrough."""
import sys, json, subprocess, shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Foundation/Assets/BlenderScenes/in_the_park/in the park.blend"
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/in_the_park_terrain_v1")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/in_the_park_terrain_v1")
NPZ     = OUT_DIR / "terrain_snake.npz"
BLENDER    = "/home/kingy/blender/blender"
FIT_SCRIPT = "/home/kingy/Projects/Genesis/GenesisTools/genesis_tools/active_contour/fit_terrain_contour.py"

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/terrain_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# --- Phase 1: terrain snake ---
if not NPZ.exists():
    print("[in_the_park terrain] Phase 1: fitting terrain snake …")
    subprocess.run([
        BLENDER, "--background", BLEND,
        "--python-exit-code", "1", "--python", FIT_SCRIPT, "--",
        "--blend", BLEND, "--output-dir", str(OUT_DIR),
        "--grid-resolution",          str(config["grid_resolution"]),
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
else:
    print(f"[in_the_park terrain] Reusing {NPZ}")

config["terrain_npz"] = str(NPZ)

# --- Phase 2: walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[in_the_park terrain] Phase 2 → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# --- Terrain figures ---
from genesis_tools.active_contour.visualize import run_terrain_snake
run_terrain_snake(OUT_DIR)

# --- Copy figures to assets ---
for p in (OUT_DIR / "viz").glob("*.png"):
    shutil.copy2(p, ASSETS / p.name)

# --- GIF + MP4 ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[in_the_park terrain] {len(all_frames)} frames → GIF + MP4")

from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

create_gif(all_frames, ASSETS / "in_the_park_terrain_v1_walkthrough.gif",
           duration=int(1000 / config["fps"]))

make_combined_gif(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_gif=ASSETS / "in_the_park_terrain_v1_walkthrough_combined.gif",
                  fps=config["fps"], step=3, output_scale=0.5)

make_combined_mp4(all_frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=NPZ,
                  output_mp4=ASSETS / "in_the_park_terrain_v1_walkthrough_combined.mp4",
                  fps=6, step=1, output_scale=1.0)

print("[in_the_park terrain] ALL DONE")
