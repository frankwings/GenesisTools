"""Generate GIF and copy debug images for v43 walkthrough."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

import shutil
from pathlib import Path
from genesis_tools.gif_generator import create_gif

RESULTS   = Path("/home/kingy/Projects/Genesis/GenesisTools/results/ai33_001_walkthrough_v43")
ASSETS    = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/ai33_001_walkthrough_v43")
FRAMES    = RESULTS / "frames"

ASSETS.mkdir(parents=True, exist_ok=True)

# Collect frames in order
frames = sorted(FRAMES.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))
print(f"[GIF] {len(frames)} frames")

gif_path = ASSETS / "ai33_v43_aerial.gif"
fps = 12
duration_ms = int(1000 / fps)
create_gif(frames, gif_path, duration=duration_ms)
print(f"[GIF] -> {gif_path}  ({gif_path.stat().st_size / 1e6:.1f} MB)")

# Copy debug images
for name in ("debug_top.png", "debug_side.png"):
    src = RESULTS / name
    dst = ASSETS / name
    shutil.copy2(src, dst)
    print(f"[Copy] {src.name} -> {dst}")

print("Done.")
