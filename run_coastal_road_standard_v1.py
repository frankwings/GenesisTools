"""coastal_road — standard (indoor) config v1: Theta* aerial walkthrough."""
import sys, json, shutil
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Foundation/Assets/BlenderScenes/coastal_road/coastal road.blend"
OUT_DIR = Path("/home/kingy/Projects/Genesis/GenesisTools/results/coastal_road_standard_v1")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/coastal_road_standard_v1")

OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(parents=True, exist_ok=True)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/standard_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

# --- Walkthrough + render ---
from genesis_tools.walkthrough_renderer.walkthrough import run
print(f"[coastal_road standard] Walkthrough → {OUT_DIR}")
run(BLEND, config, str(OUT_DIR), render=True)

# --- GIF ---
all_frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
print(f"[coastal_road standard] {len(all_frames)} frames → GIF")

from genesis_tools.gif_generator import create_gif
create_gif(all_frames, ASSETS / "coastal_road_standard_v1_walkthrough.gif",
           duration=int(1000 / config["fps"]))

print("[coastal_road standard] ALL DONE")
