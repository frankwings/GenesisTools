"""v58 — summer_coastline walkthrough with Held-Karp exact TSP.

Reuses v1 terrain_snake.npz (same terrain, same snake config).
Runs full pipeline: voxel_grid → walkable → Held-Karp path →
camera_orient → camera_animate → render → viz figures → GIF/MP4.
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/summer_coastline/fine_scene.blend"
V1      = Path("/home/kingy/Projects/Genesis/GenesisTools/results/summer_coastline_v1")
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/summer_coastline_v58")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/summer_coastline_v58")
OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

# Reuse v1 terrain snake — skip Phase 1 (fitting takes ~10 min)
terrain_dst = OUT_DIR / "terrain_snake.npz"
if not terrain_dst.exists():
    shutil.copy2(V1 / "terrain_snake.npz", terrain_dst)
    print(f"Copied terrain_snake.npz from v1")
else:
    print("terrain_snake.npz already present")

from genesis_tools.walkthrough_renderer.walkthrough import run

config = {
    "terrain_npz": str(terrain_dst),

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

    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "waypoint",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,

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

print(f"[summer_coastline v58] Walkthrough pipeline → {OUT_DIR}")
result = run(BLEND, config, str(OUT_DIR), render=True)
print("[summer_coastline v58] pipeline done:", result)

# --- Terrain visualizations (figures 0-5) ---
print("[summer_coastline v58] Generating terrain figures …")
from genesis_tools.active_contour.visualize import run_terrain_snake
run_terrain_snake(OUT_DIR)

# --- GIF + MP4 ---
frames_dir = OUT_DIR / "frames"
all_frames = sorted(frames_dir.glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[summer_coastline v58] {len(all_frames)} frames → GIF + MP4")

from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

path_npz    = OUT_DIR / "path.npz"
terrain_npz = OUT_DIR / "terrain_snake.npz"

gif_plain = ASSETS / "summer_coastline_v58_walkthrough.gif"
create_gif(all_frames, gif_plain, duration=int(1000 / 12))
print(f"[summer_coastline v58] plain GIF → {gif_plain}  ({gif_plain.stat().st_size/1e6:.1f} MB)")

make_combined_gif(
    frames=all_frames,
    path_npz=path_npz,
    terrain_npz=terrain_npz,
    output_gif=ASSETS / "summer_coastline_v58_walkthrough_combined.gif",
    fps=12, step=3, output_scale=0.5,
)

make_combined_mp4(
    frames=all_frames,
    path_npz=path_npz,
    terrain_npz=terrain_npz,
    output_mp4=ASSETS / "summer_coastline_v58_walkthrough_combined.mp4",
    fps=6, step=1, output_scale=1.0,
)

print("[summer_coastline v58] ALL DONE")
