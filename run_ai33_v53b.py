"""v53b — 6-connected BFS + aerial cam_h=0 + lookahead gaze (vs v53 waypoint gaze)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"
SNAKE   = "/home/kingy/Projects/Genesis/GenesisTools/results/active_contour/AI33_001_280/snake_mesh.npz"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v53b"

config = {
    "snake_npz": SNAKE,
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "path_planner": "theta_star",
    "waypoint_gaze_mode": "free",   # lookahead (vs v53 "waypoint")
    "lookahead_fraction": 0.05,
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

print(f"[v53b] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[v53b] done:", result)
