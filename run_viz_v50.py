"""Generate debug visualization .blend for v50 (pure BFS) walkthrough results."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.visualize import visualize

RESULTS = "/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v50"
BLEND   = "/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"

config = {
    "grid_resolution":  0.5,
    "camera_height":    1.7,
    "fps":              12,
    "_unit_scale":      0.01,
}

visualize(
    blend_path    = BLEND,
    output_blend  = f"{RESULTS}/debug_viz.blend",
    voxel_grid    = f"{RESULTS}/voxel_grid.npz",
    walkable      = f"{RESULTS}/walkable.npz",
    path          = f"{RESULTS}/path.npz",
    camera_blend  = f"{RESULTS}/AI33_001_280_walkthrough.blend",
    config        = config,
)
print("Done.")
