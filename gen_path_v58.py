"""Visualize Held-Karp TSP path for arctic_midnight_sun v58.

Reuses v57 terrain_snake.npz / voxel_grid.npz / walkable.npz (same terrain,
same waypoint count, same seed).  Only the TSP step changes: v57 used 2-opt
greedy; v58 uses exact Held-Karp DP.

Steps:
  1. Create results/arctic_midnight_sun_v58/
  2. Re-run path_plan.build() → path.npz (Held-Karp)
  3. Copy terrain_snake.npz from v57 so figure loading works
  4. Generate figure_5_walkthrough_path.png
"""
import sys
import shutil
import json
import time
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.pipeline import voxel_grid as vg_mod
from genesis_tools.walkthrough_renderer.pipeline import walkable as wk_mod
from genesis_tools.walkthrough_renderer.pipeline import path_plan

V57 = Path("/home/kingy/Projects/Genesis/GenesisTools/results/arctic_midnight_sun_v57")
V58 = Path("/home/kingy/Projects/Genesis/GenesisTools/results/arctic_midnight_sun_v58")
V58.mkdir(parents=True, exist_ok=True)
(V58 / "viz").mkdir(exist_ok=True)

# 1. Copy terrain_snake.npz so visualize._load_terrain_data() finds it in v58
terrain_src = V57 / "terrain_snake.npz"
terrain_dst = V58 / "terrain_snake.npz"
if not terrain_dst.exists():
    shutil.copy2(terrain_src, terrain_dst)
    print(f"Copied terrain_snake.npz → {terrain_dst}")
else:
    print(f"terrain_snake.npz already in v58")

# 2. Load v57 voxel grid + walkable data
print("[v58] Loading voxel_grid.npz …")
vg = vg_mod.load(str(V57 / "voxel_grid.npz"))
print("[v58] Loading walkable.npz …")
wk = wk_mod.load(str(V57 / "walkable.npz"))

# 3. Config (same as v57, terrain_npz points to v57 — camera_xyz is the same)
config = {
    "terrain_npz": str(terrain_src),
    "grid_resolution": 20.0,
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "aerial": False,
    "path_planner": "theta_star",   # use BFS path stitching (no bpy available)
    "laplacian_iters": 0,
}

# 4. Build path with Held-Karp TSP
print("[v58] Running path_plan.build() with Held-Karp TSP …")
t0 = time.time()
pd = path_plan.build(vg, wk, config)
elapsed = time.time() - t0
print(f"[v58] Path built: {len(pd.path_points)} points, {len(pd.waypoints)} waypoints, {elapsed:.1f}s")

# 5. Save path.npz
path_out = str(V58 / "path.npz")
path_plan.save(pd, path_out)

# 6. Generate figure_5
print("[v58] Generating figure_5_walkthrough_path.png …")
from genesis_tools.active_contour.visualize import terrain_figure_5, _load_terrain_data
td = _load_terrain_data(V58)
terrain_figure_5(td, V58 / "viz")

print(f"\nDone. Results in {V58}")
print(f"  path.npz:                {V58 / 'path.npz'}")
print(f"  figure_5:                {V58 / 'viz' / 'figure_5_walkthrough_path.png'}")
