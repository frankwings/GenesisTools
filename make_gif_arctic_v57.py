"""Generate walkthrough GIF for arctic_midnight_sun v57 (Phase 2)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

import shutil
from pathlib import Path
from genesis_tools.gif_generator import create_gif

RESULTS = Path("/home/kingy/Projects/Genesis/GenesisTools/results/arctic_midnight_sun_v57")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/arctic_midnight_sun_v57")
FRAMES  = RESULTS / "frames"

ASSETS.mkdir(parents=True, exist_ok=True)

all_frames = sorted(FRAMES.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))
# Subsample: every 3rd frame → ~333 frames at 12 fps = 27.7 s GIF
frames = all_frames[::3]
print(f"[GIF] {len(all_frames)} total frames → using {len(frames)} (every 3rd)")

gif_path = ASSETS / "arctic_v57_walkthrough.gif"
create_gif(frames, gif_path, duration=int(1000 / 12))
size_mb = gif_path.stat().st_size / 1e6
print(f"[GIF] -> {gif_path}  ({size_mb:.1f} MB)")

# Copy terrain viz figures
viz_dir = RESULTS / "viz"
if viz_dir.exists():
    for fig in viz_dir.glob("figure_*.png"):
        shutil.copy2(fig, ASSETS / fig.name)
        print(f"[Copy] {fig.name}")

print("Done.")
