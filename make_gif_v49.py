"""Generate GIF and copy debug images for v49 (Theta*)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

import shutil
from pathlib import Path
from genesis_tools.gif_generator import create_gif

RESULTS = Path("/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v49")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/ai33_001_walkthrough_v49")
FRAMES  = RESULTS / "frames"

ASSETS.mkdir(parents=True, exist_ok=True)

frames = sorted(FRAMES.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))
print(f"[GIF] {len(frames)} frames")

gif_path = ASSETS / "ai33_v49_aerial.gif"
create_gif(frames, gif_path, duration=int(1000/12))
print(f"[GIF] -> {gif_path}  ({gif_path.stat().st_size/1e6:.1f} MB)")

for name in ("debug_top.png", "debug_side.png"):
    shutil.copy2(RESULTS / name, ASSETS / name)
    print(f"[Copy] {name}")

print("Done.")
