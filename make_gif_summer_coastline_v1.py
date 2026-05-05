"""Generate walkthrough GIF for summer_coastline v1 (Phase 1+2)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from pathlib import Path
from genesis_tools.gif_generator import create_gif

RESULTS = Path("/home/kingy/Projects/Genesis/GenesisTools/results/summer_coastline_v1")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/summer_coastline_v1")
FRAMES  = RESULTS / "frames"

ASSETS.mkdir(parents=True, exist_ok=True)

all_frames = sorted(FRAMES.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))
frames = all_frames[::3]
print(f"[GIF] {len(all_frames)} total frames → using {len(frames)} (every 3rd)")

gif_path = ASSETS / "summer_coastline_v1_walkthrough.gif"
create_gif(frames, gif_path, duration=int(1000 / 12))
size_mb = gif_path.stat().st_size / 1e6
print(f"[GIF] -> {gif_path}  ({size_mb:.1f} MB)")

print("Done.")
