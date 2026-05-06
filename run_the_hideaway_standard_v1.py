"""the_hideaway — standard (indoor) config v1: Theta* aerial walkthrough."""
import sys, json, shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Foundation/Assets/BlenderScenes/the_hideaway/the hideaway.blend"
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/the_hideaway_standard_v1")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/the_hideaway_standard_v1")

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/standard_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# --- Walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[the_hideaway standard] Walkthrough → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# --- GIF + MP4 ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[the_hideaway standard] {len(all_frames)} frames → GIF + MP4")

from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif

create_gif(all_frames, ASSETS / "the_hideaway_standard_v1_walkthrough.gif",
           duration=int(1000 / config["fps"]))

# Combined GIF uses terrain_npz for background — skip for standard scenes
# (no terrain_snake.npz). Use plain GIF only.

print("[the_hideaway standard] ALL DONE")
