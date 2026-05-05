"""v2 — jungle_swamp coarse scene walkthrough.

Scene: infinigen coarse, unit_scale=1.0 (1 BU = 1m), 3600m × 3600m.
Strategy: global mode covering full scene, 20m/voxel (3600/180=20),
          floor snap for terrain-following path, capped at 120s.
"""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/jungle_swamp/coarse_scene.blend"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/jungle_swamp_v2"

config = {
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,
    "grid_resolution": 20.0,       # 20m/voxel, fits 3600m scene in 180 cells
    "max_grid_cells_xy": 180,
    "max_grid_cells_z": 30,        # 30 × ~8m = ~240m vertical (full scene height)
    "fps": 12,
    "max_duration_seconds": 120,   # cap at 2 min = 1440 frames
    "walk_speed_mps": 5.0,         # faster traverse across large outdoor scene
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "aerial": False,
}

print(f"[jungle_swamp_v2] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[jungle_swamp_v2] done:", result)
