# Walkthrough Renderer — Usage Guide

Automatically plans a first-person camera path through any Blender scene and
renders it as a walkthrough video / GIF.

---

## Two scene types

| Type | When to use | Config template |
|------|-------------|-----------------|
| **Terrain** | Large outdoor scenes (arctic, coastline, forest, park) | `configs/terrain_scene.json` |
| **Standard** | Indoor or compact scenes (rooms, objects) | `configs/standard_scene.json` |

---

## Terrain scene (two phases)

### Phase 1 — fit terrain surface

Runs under system Blender (requires `bpy` access to the raw mesh):

```bash
BLEND=/path/to/scene.blend
OUT=/path/to/results/my_scene_v1

/home/kingy/blender/blender --background "$BLEND" \
  --python-exit-code 1 \
  --python genesis_tools/active_contour/fit_terrain_contour.py \
  -- \
  --blend "$BLEND" \
  --output-dir "$OUT" \
  --grid-resolution 20.0 \
  --max-grid-cells-xy 180
```

Output: `$OUT/terrain_snake.npz`

### Phase 2 — plan path + render

```python
import sys, json
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from pathlib import Path
from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/path/to/scene.blend"
OUT_DIR = "/path/to/results/my_scene_v1"
NPZ     = f"{OUT_DIR}/terrain_snake.npz"

with open("configs/terrain_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)
config["terrain_npz"] = NPZ      # point to Phase 1 output

run(BLEND, config, OUT_DIR, render=True)
```

Rendered frames land in `$OUT_DIR/frames/frame_0001.png …`

---

## Standard (indoor) scene — single phase

No terrain fitting needed. Path planning uses the raw geometry directly.

```python
import sys, json
sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

from genesis_tools.walkthrough_renderer.walkthrough import run

BLEND   = "/path/to/room.blend"
OUT_DIR = "/path/to/results/my_room_v1"

with open("configs/standard_scene.json") as f:
    config = json.load(f)
config.pop("_description", None)

run(BLEND, config, OUT_DIR, render=True)
```

---

## Key config parameters

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `fps` | 12 | Playback speed |
| `max_duration_seconds` | 83.4 | Length of walkthrough (→ ~1000 frames at 12 fps) |
| `walk_speed_mps` | 5.0 (terrain) / 2.0 (standard) | How fast camera moves |
| `num_waypoints` | 20 | Number of path waypoints sampled |
| `seed` | 42 | Random seed for reproducible waypoint selection |
| `render_engine` | CYCLES / WORKBENCH | CYCLES for photoreal, WORKBENCH for fast previews |
| `render_width/height` | 640×480 / 1280×720 | Output resolution |
| `render_samples` | 64 / 32 | CYCLES quality (higher = slower) |
| `camera_origin_hold_frames` | 0 | Frames to hold at start position before moving |
| `grid_resolution` | 20.0 (terrain) / 0.5 (standard) | Voxel cell size in Blender units |

---

## Generate GIFs after rendering

```python
from pathlib import Path
from genesis_tools.gif_generator import create_gif
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4

OUT_DIR = Path("/path/to/results/my_scene_v1")
ASSETS  = Path("docs/assets/my_scene_v1")
ASSETS.mkdir(parents=True, exist_ok=True)

frames = sorted((OUT_DIR / "frames").glob("frame_*.png"),
                key=lambda p: int(p.stem.split("_")[1]))

# Plain walkthrough GIF (keep under 1000 frames to stay < 50 MB)
create_gif(frames[:999], ASSETS / "my_scene_walkthrough.gif",
           duration=int(1000 / 12))   # duration per frame in ms

# Combined GIF: rendered frame + live path-on-map overlay
make_combined_gif(frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=OUT_DIR / "terrain_snake.npz",
                  output_gif=ASSETS / "my_scene_walkthrough_combined.gif",
                  fps=12, step=3, output_scale=0.5)

# Combined MP4
make_combined_mp4(frames, path_npz=OUT_DIR / "path.npz",
                  terrain_npz=OUT_DIR / "terrain_snake.npz",
                  output_mp4=ASSETS / "my_scene_walkthrough_combined.mp4",
                  fps=6, step=1, output_scale=1.0)
```

`make_combined_gif` requires `terrain_snake.npz` — for standard scenes omit
it and use `create_gif` only.

---

## Resume behaviour

Each pipeline step writes a checkpoint file. Re-running `run()` skips any step
whose checkpoint already exists:

| Step | Checkpoint file |
|------|----------------|
| Build voxel grid | `voxel_grid.npz` |
| Extract walkable | `walkable.npz` |
| Plan path | `path.npz` |
| Orient camera | `wp_schedule.json` |
| Animate camera | `*_walkthrough.blend` |
| Render frames | `frames/` directory |

To re-run from a specific step, delete that checkpoint and all later ones.

---

## GIF size rules (gitignore)

| Condition | Action |
|-----------|--------|
| GIF > 50 MB **and** > 1000 frames | Add to `.gitignore` |
| GIF ≤ 50 MB or ≤ 1000 frames | Commit to git normally |
| MP4 > 50 MB | Add to `.gitignore` |

---

## Run script template

Copy `run_forest_paths_terrain_v4.py` as a starting point for terrain scenes,
or `run_the_hideaway_standard_v1.py` for standard scenes. Each run script
captures Phase 1 + Phase 2 + GIF generation in one file.
