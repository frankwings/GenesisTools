"""the_hideaway — standard config v3: vertex-based solid detection + Cycles.

v1 issues:
  1. Grid too coarse (6.25m/voxel) — thin walls invisible to ray casting.
  2. Workbench render — no lighting.
  3. No path visualization.

v2 approach: finer grid (2.5m/voxel). This resolves some walls but not all
thin geometry, and is much slower to compute.

v3 fix (the correct approach): supplement ray-cast solid voxels by marking any
voxel that contains at least one mesh vertex as solid. Thin walls whose faces
never intersect a ray axis are still caught because their vertices land in a
voxel. Uses the original standard config grid size (80×80×40).
"""
import sys, json
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Foundation/Assets/BlenderScenes/the_hideaway/the hideaway.blend"
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/the_hideaway_standard_v3")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/the_hideaway_standard_v3")

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/standard_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# v3: switch to Cycles, keep standard grid size (vertex fix handles thin walls)
config.update({
    "render_engine":  "CYCLES",
    "render_width":   640,
    "render_height":  480,
    "render_samples": 64,
    "use_denoise":    True,
})

from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[the_hideaway v3] Walkthrough → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[the_hideaway v3] {len(all_frames)} frames → GIF")

from genesis_tools.gif_generator import create_gif
create_gif(all_frames, ASSETS / "the_hideaway_standard_v3_walkthrough.gif",
           duration=int(1000 / config["fps"]))

print("[the_hideaway v3] ALL DONE")
