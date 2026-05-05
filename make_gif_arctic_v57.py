"""Generate walkthrough GIFs for arctic_midnight_sun v57 (Phase 2)."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from pathlib import Path
from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif

RESULTS = Path("/home/kingy/Projects/Genesis/GenesisTools/results/arctic_midnight_sun_v57")
ASSETS  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets/arctic_midnight_sun_v57")
FRAMES  = RESULTS / "frames"

ASSETS.mkdir(parents=True, exist_ok=True)

all_frames = sorted(FRAMES.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))
print(f"[GIF] {len(all_frames)} total frames")

# Plain walkthrough GIF (all frames)
gif_path = ASSETS / "arctic_v57_walkthrough.gif"
create_gif(all_frames, gif_path, duration=int(1000 / 12))
print(f"[GIF] -> {gif_path}  ({gif_path.stat().st_size / 1e6:.1f} MB)")

# Combined GIF: rendered frame + live XY map
combined_gif_path = ASSETS / "arctic_v57_walkthrough_combined.gif"
make_combined_gif(
    frames=all_frames,
    path_npz=RESULTS / "path.npz",
    terrain_npz=RESULTS / "terrain_snake.npz",
    output_gif=combined_gif_path,
    fps=12, step=3, output_scale=0.5,
)

print("Done.")
