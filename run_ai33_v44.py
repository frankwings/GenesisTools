"""Run AI33_001_280 walkthrough v44 — aerial + XYZ FPS + XYZ TSP + XYZ Laplacian smoothing."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"
SNAKE   = "/home/kingy/Projects/Genesis/GenesisTools/results/active_contour/AI33_001_280/snake_mesh.npz"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v44"

config = {
    "snake_npz": SNAKE,
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "rotation_smooth_seconds": 2.0,
    "grid_resolution": 0.5,
    "max_grid_cells_xy": 80,
    "max_grid_cells_z": 40,
    "aerial": True,
    "fps": 12,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "panoramic": False,
}

print(f"[v44] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[v44] done:", result)
