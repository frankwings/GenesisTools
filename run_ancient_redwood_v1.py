"""Run ancient_redwood_cathedral fine_scene walkthrough v1."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/ancient_redwood_cathedral/fine_scene.blend"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/ancient_redwood_cathedral_v1"

config = {
    "local_area_ratio": 0.02,
    "local_height": 15.0,

    "camera_height": 1.7,
    "num_waypoints": 10,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "rotation_smooth_seconds": 2.0,
    "aerial": True,

    "grid_resolution": 1.0,
    "max_local_cells_xy": 80,
    "max_local_cells_z": 20,

    "max_duration_seconds": 50,   # cap at 500 frames @ 10fps

    "fps": 10,
    "render_engine": "CYCLES",
    "render_width": 640,
    "render_height": 360,
    "render_samples": 16,
    "panoramic": False,
}

print(f"[ancient_redwood v1] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[ancient_redwood v1] done:", result)
