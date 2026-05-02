"""Run AI33 v43 path step only + segment length analysis."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run
import numpy as np

BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"
SNAKE   = "/home/kingy/Projects/Genesis/GenesisTools/results/active_contour/AI33_001_280/snake_mesh.npz"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v43"

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

print(f"[v43 path-only] output -> {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=False)
print("[v43 path-only] done:", result)

# Segment length analysis
path_npz = np.load(f"{OUT_DIR}/path.npz")
pts = path_npz["path_points"]
print(f"\n[Analysis] Path points: {len(pts)}")
diffs = np.diff(pts, axis=0)
seg_lens = np.linalg.norm(diffs, axis=1)
unit_scale = 0.01
res = 0.5 / unit_scale  # BU
print(f"Segment lengths (BU):")
print(f"  min={seg_lens.min():.2f}  max={seg_lens.max():.2f}  median={np.median(seg_lens):.2f}  mean={seg_lens.mean():.2f}")
print(f"  ratio max/min = {seg_lens.max()/seg_lens.min():.1f}x")
print(f"  >10 BU: {(seg_lens > 10).sum()}  >20 BU: {(seg_lens > 20).sum()}  >39 BU: {(seg_lens > 39).sum()}")
dz = np.abs(diffs[:, 2])
print(f"dZ (BU): min={dz.min():.2f}  max={dz.max():.2f}  median={np.median(dz):.2f}")
