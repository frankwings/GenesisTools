"""Generate a debug visualization .blend for the v42 walkthrough results.

Layers included:
  - voxel_grid  (red=solid, yellow=free)
  - walkable    (blue=candidate, cyan=walkable)
  - path        (green=waypoints, pink=path line)
  - camera      (RGB axes every 1 second)

Run under bpy Python:
  /home/kingy/blender/4.5/python/bin/python3.11 run_viz_v42.py
"""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.visualize import visualize

RESULTS = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v42"
BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"

config = {
    "grid_resolution":  0.5,
    "camera_height":    1.7,
    "fps":              12,
    "_unit_scale":      0.01,
}

visualize(
    blend_path    = BLEND,
    output_blend  = f"{RESULTS}/debug_viz_v2.blend",
    voxel_grid    = f"{RESULTS}/voxel_grid.npz",
    walkable      = f"{RESULTS}/walkable.npz",
    path          = f"{RESULTS}/path.npz",
    camera_blend  = f"{RESULTS}/AI33_001_280_walkthrough.blend",
    config        = config,
)
print("Done. Open debug_viz_v2.blend in Blender to inspect.")
