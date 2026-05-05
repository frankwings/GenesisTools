"""v1 — jungle_swamp coarse scene walkthrough.

Scene: infinigen coarse, unit_scale=1.0 (1 BU = 1m), 3600m × 3600m.
Strategy: local mode (5% of scene = 180m area), 2m/voxel, default planner
          with floor-snap so camera follows terrain surface.
"""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/jungle_swamp/coarse_scene.blend"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/jungle_swamp_v1"

config = {
    "camera_height": 1.7,       # 1.7m eye height
    "num_waypoints": 15,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,
    "grid_resolution": 2.0,     # 2m per voxel (outdoor terrain)
    "max_grid_cells_xy": 80,    # 80 × 2m = 160m local area
    "max_grid_cells_z": 20,     # 20 × 2m = 40m vertical
    "local_area_ratio": 0.05,   # 5% of scene = 180m × 180m focus area
    "local_height": 30.0,       # ±15m vertical exploration window
    "fps": 12,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "aerial": False,
}

print(f"[jungle_swamp_v1] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[jungle_swamp_v1] done:", result)
