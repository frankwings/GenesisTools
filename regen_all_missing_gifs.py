"""Regenerate all missing GIF/MP4 assets deleted by git filter-repo."""
import sys
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

import shutil
from pathlib import Path
from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

BASE     = Path("/home/kingy/Projects/Genesis/GenesisTools")
RESULTS  = BASE / "results"
ASSETS_R = BASE / "docs/assets"


def frames(scene):
    d = RESULTS / scene / "frames"
    return sorted(d.glob("frame_*.png"), key=lambda p: int(p.stem.split("_")[1]))

def assets(scene):
    d = ASSETS_R / scene
    d.mkdir(parents=True, exist_ok=True)
    return d

def report(p):
    mb = Path(p).stat().st_size / 1e6
    print(f"  OK {Path(p).name}  {mb:.1f} MB")

def skip(p):
    print(f"  -- {Path(p).name}  (exists)")


# ─── 1. arctic_midnight_sun_v57: combined.gif only ───────────────────────────
print("\n=== arctic_midnight_sun_v57 ===")
s = "arctic_midnight_sun_v57"
f = frames(s); a = assets(s)
out = a / "arctic_v57_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)


# ─── 2. arctic_midnight_sun_v58: all 3 ───────────────────────────────────────
print("\n=== arctic_midnight_sun_v58 ===")
s = "arctic_midnight_sun_v58"
f = frames(s); a = assets(s)
out = a / "arctic_v58_walkthrough.gif"
if not out.exists():
    create_gif(f, out, duration=int(1000/12))
    report(out)
else:
    skip(out)
out = a / "arctic_v58_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "arctic_v58_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 3. coastal_road_standard_v2: walkthrough.gif only ───────────────────────
print("\n=== coastal_road_standard_v2 ===")
s = "coastal_road_standard_v2"
f = frames(s); a = assets(s)
out = a / "coastal_road_standard_v2_walkthrough.gif"
if not out.exists():
    create_gif(f, out, duration=int(1000/12))
    report(out)
else:
    skip(out)


# ─── 4. coastal_road_terrain_v1: walkthrough.gif + combined.gif ──────────────
print("\n=== coastal_road_terrain_v1 ===")
s = "coastal_road_terrain_v1"
f = frames(s); a = assets(s)
out = a / "coastal_road_terrain_v1_walkthrough.gif"
if not out.exists():
    create_gif(f, out, duration=int(1000/12))
    report(out)
else:
    skip(out)
out = a / "coastal_road_terrain_v1_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)


# ─── 5. coastal_road_terrain_v2: combined.gif + combined.mp4 ─────────────────
print("\n=== coastal_road_terrain_v2 ===")
s = "coastal_road_terrain_v2"
f = frames(s); a = assets(s)
out = a / "coastal_road_terrain_v2_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "coastal_road_terrain_v2_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 6. forest_paths_terrain_v1: combined.gif + combined.mp4 ─────────────────
print("\n=== forest_paths_terrain_v1 ===")
s = "forest_paths_terrain_v1"
f = frames(s); a = assets(s)
out = a / "forest_paths_terrain_v1_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "forest_paths_terrain_v1_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 7. in_the_park_terrain_v1: combined.gif + combined.mp4 ──────────────────
print("\n=== in_the_park_terrain_v1 ===")
s = "in_the_park_terrain_v1"
f = frames(s); a = assets(s)
out = a / "in_the_park_terrain_v1_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "in_the_park_terrain_v1_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 8. summer_coastline_v1: combined.gif + combined.mp4 ─────────────────────
print("\n=== summer_coastline_v1 ===")
s = "summer_coastline_v1"
f = frames(s); a = assets(s)
out = a / "summer_coastline_v1_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "summer_coastline_v1_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 9. summer_coastline_v58: walkthrough.gif + combined.gif + combined.mp4 ──
print("\n=== summer_coastline_v58 ===")
s = "summer_coastline_v58"
f = frames(s); a = assets(s)
out = a / "summer_coastline_v58_walkthrough.gif"
if not out.exists():
    create_gif(f, out, duration=int(1000/12))
    report(out)
else:
    skip(out)
out = a / "summer_coastline_v58_walkthrough_combined.gif"
if not out.exists():
    make_combined_gif(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_gif=out, fps=12, step=3, output_scale=0.5)
    report(out)
else:
    skip(out)
out = a / "summer_coastline_v58_walkthrough_combined.mp4"
if not out.exists():
    make_combined_mp4(f, path_npz=RESULTS/s/"path.npz", terrain_npz=RESULTS/s/"terrain_snake.npz",
                      output_mp4=out, fps=6, step=1, output_scale=1.0)
    report(out)
else:
    skip(out)


# ─── 10. the_hideaway_standard v1/v2/v3: walkthrough.gif ─────────────────────
for v in ("v1", "v2", "v3"):
    print(f"\n=== the_hideaway_standard_{v} ===")
    s = f"the_hideaway_standard_{v}"
    f = frames(s); a = assets(s)
    out = a / f"the_hideaway_standard_{v}_walkthrough.gif"
    if not out.exists():
        create_gif(f, out, duration=int(1000/12))
        report(out)
    else:
        skip(out)


# ─── 11. ai33 aerial GIFs: v41/v42 (new dirs) + v43-v53b (existing dirs) ─────
AI33_VERSIONS = [
    ("v41", "ai33_v41_aerial.gif"),
    ("v42", "ai33_v42_aerial.gif"),
    ("v43", "ai33_v43_aerial.gif"),
    ("v44", "ai33_v44_aerial.gif"),
    ("v46", "ai33_v46_aerial.gif"),
    ("v47", "ai33_v47_aerial.gif"),
    ("v48", "ai33_v48_aerial.gif"),
    ("v49", "ai33_v49_aerial.gif"),
    ("v50", "ai33_v50_aerial.gif"),
    ("v51", "ai33_v51_aerial.gif"),
    ("v52", "ai33_v52_aerial.gif"),
    ("v53", "ai33_v53_aerial.gif"),
    ("v53b", "ai33_v53b_aerial.gif"),
]

for ver, gif_name in AI33_VERSIONS:
    scene = f"ai33_001_walkthrough_{ver}"
    print(f"\n=== {scene} ===")
    f = frames(scene)
    a = assets(scene)
    out = a / gif_name
    if not out.exists():
        create_gif(f, out, duration=int(1000/12))
        report(out)
        # Copy debug images if available
        for name in ("debug_top.png", "debug_side.png"):
            src = RESULTS / scene / name
            if src.exists():
                shutil.copy2(src, a / name)
    else:
        skip(out)


print("\n=== ALL DONE ===")
