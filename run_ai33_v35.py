"""Run AI33_001_280 walkthrough v35 — new modular pipeline, snake mode."""
import sys, os
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from pathlib import Path
from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"
SNAKE   = "/home/kingy/Projects/Genesis/GenesisTools/results/active_contour/AI33_001_280/snake_mesh.npz"
VG_NPZ  = "/home/kingy/Projects/Genesis/GenesisTools/results/active_contour/AI33_001_280/voxel_grid.npz"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v35"

config = {
    # snake voxel grid (pre-computed active contour)
    "snake_npz":      SNAKE,
    "voxel_grid_npz": VG_NPZ,

    # camera & path
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "rotation_smooth_seconds": 2.0,

    # grid params (used for walkable flood-fill; res drives snake mode too)
    "grid_resolution": 0.5,
    "max_grid_cells_xy": 80,
    "max_grid_cells_z": 40,

    # render
    "fps": 12,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "panoramic": False,
}

print(f"[v35] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[v35] done:", result)
