# run_arctic_midnight_sun_v57.py
"""v57 — arctic_midnight_sun walkthrough on the two-pass terrain snake fit.

Reuses the v57 `terrain_snake.npz` produced earlier (Phase 1 already done
in `results/arctic_midnight_sun_v57/`); this run only executes Phase 2:
walkthrough planning + Cycles render at 640×480, 64 samples, 1000 frames.

Two-phase pipeline (Phase 1 auto-skipped if NPZ exists):
  Phase 1 (bpy): fit_terrain_contour → terrain_snake.npz (two-pass refine)
  Phase 2 (pip bpy walkthrough): use terrain_npz → one walkable voxel per
                                 column → camera path → render

Scene: infinigen fine scene, arctic midnight sun.
Grid:  20 m/voxel pass 1; ~6 m/voxel pass 2 (tight bbox refine).
"""
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/arctic_midnight_sun/fine_scene.blend"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/arctic_midnight_sun_v57"
NPZ     = f"{OUT_DIR}/terrain_snake.npz"

BLENDER    = "/home/kingy/blender/blender"
FIT_SCRIPT = str(
    Path("/home/kingy/Projects/Genesis/GenesisTools")
    / "genesis_tools/active_contour/fit_terrain_contour.py"
)

# --- Phase 1: terrain snake (must run under system Blender's Python) ---
if not os.path.exists(NPZ):
    print("[arctic v57] Phase 1: fitting terrain snake (two-pass) …")
    cmd = [
        BLENDER, "--background", BLEND,
        "--python-exit-code", "1",
        "--python", FIT_SCRIPT,
        "--",
        "--blend", BLEND,
        "--output-dir", OUT_DIR,
        "--grid-resolution", "20.0",
        "--max-grid-cells-xy", "180",
        "--env-sphere-percentile", "5.0",
        "--ray-samples", "1",
        "--alpha", "0.5",
        "--gravity", "0.1",
        "--dt", "1.0",
        "--max-iterations", "200",
        "--convergence-threshold", "1e-3",
        "--start-height", "1.7",
        "--refine-pad-cells", "2",
    ]
    subprocess.run(cmd, check=True)
    print(f"[arctic v57] terrain_snake.npz saved → {NPZ}")
else:
    print(f"[arctic v57] Reusing existing {NPZ}")

# --- Phase 2: walkthrough pipeline (pip bpy) ---
from genesis_tools.walkthrough_renderer.walkthrough import run

config = {
    "terrain_npz": NPZ,

    # TerrainSnake params (echoed for reference)
    "grid_resolution": 20.0,
    "max_grid_cells_xy": 180,
    "env_sphere_percentile": 5.0,
    "terrain_ray_samples": 1,
    "terrain_alpha": 0.5,
    "terrain_gravity": 0.1,
    "terrain_dt": 1.0,
    "terrain_max_iterations": 200,
    "terrain_convergence_threshold": 1e-3,
    "terrain_start_height": 1.7,

    # Camera / path
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "waypoint",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,

    # Render — 1000 frames @ 12 fps × 83.4 s = 1000.8 → int → 1000
    "fps": 12,
    "max_duration_seconds": 83.4,
    "walk_speed_mps": 5.0,
    "render_engine": "CYCLES",
    "render_width": 640,
    "render_height": 480,
    "render_samples": 64,
    "use_denoise": True,
    "aerial": False,
}

print(f"[arctic v57] Phase 2: walkthrough → {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[arctic v57] done:", result)
