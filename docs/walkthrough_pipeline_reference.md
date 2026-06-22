# GenesisTools Walkthrough Pipeline — Complete Parameter Reference

> Generated: 2026-06-22 | Cross-platform verified (WSL + GCP, bit-exact match)

---

## Overview

The walkthrough pipeline generates camera flythrough videos from `.blend` scene files. It consists of two phases:

1. **Snake Fitting** — Compute the walkable volume boundary (Active Contour / Snake3D)
2. **Walkthrough** — Generate voxel grid → walkable map → path → camera orientation → camera animation → render

```
blend file ──► fit_scene_contour ──► snake_mesh.npz
                                          │
blend file ──► voxel_grid ──► walkable ──► path_plan ──► camera_orient ──► camera_animate ──► render
               (step 1)      (step 2)     (step 3)      (step 4)          (step 5)           (step 6)
```

---

## Phase 1: Snake Fitting (`fit_scene_contour.py`)

Fits a 3D Active Contour (Snake) from the convex hull of sampled mesh surfaces inward, defining the walkable interior volume.

### Python API

```python
from genesis_tools.active_contour.fit_scene_contour import fit_scene_active_contour
from pathlib import Path

result = fit_scene_active_contour(
    blend_path=Path("/path/to/scene.blend"),
    output_dir=Path("results/active_contour/my_scene"),
    alpha=0.7,              # smoothness weight (Laplacian energy)
    beta=0.25,              # attraction weight (nearest-point pull)
    dt=0.05,                # integration step size
    sampling_resolution=0.5, # surface sampling spacing (world units)
    max_iter=300,            # max snake iterations
    subdivision_levels=2,    # convex hull subdivision BEFORE iteration (CRITICAL)
    max_tris=500_000,        # max triangles for Blender mesh extraction
    blender_command="/home/kingy/blender/blender",
    reuse_npz=False,         # skip Blender extraction if meshes.npz exists
)
```

### CLI

```bash
python3 -m genesis_tools.active_contour.fit_scene_contour \
    --blend /path/to/scene.blend \
    --output-dir results/active_contour/my_scene \
    --alpha 0.7 \
    --beta 0.25 \
    --dt 0.05 \
    --sampling-res 0.5 \
    --max-iter 300 \
    --subdivision-levels 2 \
    --max-tris 500000 \
    --blender /home/kingy/blender/blender \
    --reuse-npz
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `alpha` | float | 0.6 | Smoothness weight — higher = smoother snake, retains more vertices |
| `beta` | float | 0.3 | Attraction weight — pull toward sampled surface points |
| `dt` | float | 0.05 | Integration step size per iteration |
| `sampling_resolution` | float | 0.5 | Target sample spacing in world units; smaller = more points |
| `max_iter` | int | 300 | Max iterations; usually converges early via plateau detection |
| `subdivision_levels` | int | 0 | **CRITICAL**: Number of times to subdivide the convex hull mesh before iteration. `0` = use raw hull (~400 verts); `2` = ~6000+ verts. **Use 2 for production.** |
| `max_tris` | int | 500,000 | Max triangles for Blender mesh extraction (decimation target) |
| `reuse_npz` | bool | False | Skip Blender extraction if `meshes.npz` already exists |

### Recommended Parameters

| Scenario | alpha | beta | subdivision_levels | Notes |
|----------|-------|------|--------------------|-------|
| Indoor rooms | 0.7 | 0.25 | 2 | Original proven params |
| Indoor rooms (new defaults) | 0.6 | 0.3 | 2 | Equivalent quality when subdiv=2 |
| Quick test | 0.6 | 0.3 | 0 | Fast but coarse (400 verts vs 6000+) |

### Output Files

| File | Description |
|------|-------------|
| `meshes.npz` | Extracted mesh data from Blender (verts_N, faces_N arrays) |
| `snake_mesh.npz` | Final snake mesh: `vertices` (N,3) float32, `faces` (M,3) int32 |
| `summary.json` | Run metadata: params, timing, vertex/face counts |
| `figure_1_pointcloud.png` | Sampled surface point cloud visualization |
| `figure_2_contour.png` | Initial hull vs final contour overlay |
| `figure_3_slices.png` | Inside/outside classification slices |
| `figure_4_convergence.png` | Energy convergence curve |

### Snake3D Internal Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `convergence_threshold` | 1e-4 | Early stop threshold |
| `plateau_window` | 20 | Window for plateau detection |
| `plateau_rtol` | 0.02 | 2% relative change threshold |

---

## Phase 2: Walkthrough Pipeline

### Quick Start — Full Pipeline via `scene_render.py`

```python
from genesis_tools.scene_render import render

result = render(
    blend_path="/path/to/scene.blend",
    output_dir="results/my_walkthrough",
    mode="indoor",               # "auto" | "object" | "indoor" | "outdoor"
    render_engine="BLENDER_WORKBENCH",  # "CYCLES" | "BLENDER_WORKBENCH" | "BLENDER_EEVEE"
    render_width=480,
    render_height=360,
    render_samples=16,
    fps=12,
    max_duration_seconds=10,
    num_waypoints=20,
    blender="/home/kingy/blender/blender",
)
```

### Quick Start — Direct Walkthrough Runner

```python
import json
from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run

with open("configs/standard_scene.json") as f:
    config = json.load(f)

config.update({
    "aerial": True,
    "snake_npz": "results/active_contour/my_scene/snake_mesh.npz",
    "waypoint_gaze_mode": "smooth_adaptive",
    "render_engine": "BLENDER_WORKBENCH",
    "render_width": 480,
    "render_height": 360,
    "render_samples": 16,
    "fps": 12,
    "max_duration_seconds": 10,
})

wt_run(
    blend_path="/path/to/scene.blend",
    config=config,
    output_dir="results/my_walkthrough",
    render=True,
)
```

---

### `scene_render.render()` — Full Parameter List

```python
def render(
    blend_path,
    output_dir,
    *,
    mode="auto",                           # Scene mode detection
    # ── Object mode ──
    obj_frames=36,                         # Number of rotation frames
    obj_resolution=720,                    # Render resolution (px)
    obj_elevation=25,                      # Camera elevation (degrees)
    obj_duration_ms=60,                    # Per-frame duration in GIF (ms)
    # ── Indoor / Outdoor shared ──
    render_engine="CYCLES",                # CYCLES | BLENDER_WORKBENCH | BLENDER_EEVEE
    render_width=1280,
    render_height=720,
    render_samples=64,
    use_denoise=True,
    fps=12,
    max_duration_seconds=60.0,
    num_waypoints=20,
    # ── Indoor-specific ──
    indoor_grid_resolution=0.5,            # Metres per voxel
    indoor_max_grid_cells_xy=80,
    indoor_max_grid_cells_z=40,
    indoor_camera_height=1.7,              # Metres
    indoor_walk_speed=2.0,                 # m/s
    # ── Outdoor-specific ──
    outdoor_camera_height=None,            # None = auto-detect
    outdoor_walk_speed=5.0,
    outdoor_mark_particles=True,
    outdoor_particle_block_margin=1.5,
    outdoor_terrain_boundary_margin=1,
    terrain_npz=None,                      # Pre-computed terrain snake
    # ── System ──
    blender="/home/kingy/blender/blender",
    force_rerender=False,
)
```

### Auto-Detection Thresholds (`mode="auto"`)

| Threshold | Value | Rule |
|-----------|-------|------|
| `_OBJECT_SIZE_MB` | 50 | File < 50 MB → `object` |
| `_SKIP_BOUNDS_MB` | 1500 | File > 1500 MB → `outdoor` (skip bounds check) |
| `_FLAT_RATIO` | 5.0 | max(X,Y) / Z > 5.0 → `outdoor`; else → `indoor` |

---

### `standard_scene.json` — Default Config

```json
{
    "_description": "Canonical config for indoor / standard non-terrain scenes.",
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "aerial": true,
    "path_planner": "theta_star",
    "laplacian_iters": 0,
    "grid_resolution": 0.5,
    "max_grid_cells_xy": 80,
    "max_grid_cells_z": 40,
    "waypoint_gaze_mode": "free",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,
    "fps": 12,
    "max_duration_seconds": 83.4,
    "walk_speed_mps": 2.0,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "use_denoise": false,
    "panoramic": false
}
```

---

### Step 1: Voxel Grid (`voxel_grid.py`)

Converts the scene into a 3D occupancy grid. Determines which voxels are empty (air) vs solid (geometry).

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `snake_npz` | str | — | Path to snake_mesh.npz; triggers "snake" mode |
| `terrain_npz` | str | — | Path to terrain snake; triggers "terrain" mode |
| `grid_resolution` | float/"auto" | 0.5 | Voxel size in metres; "auto" = halving loop |
| `max_grid_cells_xy` | int | 80 | Max cells per XY axis |
| `max_grid_cells_z` | int | 40 | Max cells in Z axis |
| `voxel_ray_samples` | int | 3 | Ray sub-samples per voxel edge |
| `mark_particle_instances` | bool | True | Include scatter particles as solid |
| `particle_block_margin` | float | 1.0 | Scale factor on particle half-size |
| `terrain_boundary_margin` | int | 1 | Coarse cells to strip from boundary |
| `force_camera_walkable` | bool | True | Force camera cell into candidates |
| `surface_normal_z_threshold` | float | 0.1 | Min abs(normal.z) for floor detection |
| `camera_height` | float | 1.7 | Eye height in metres |
| `debug_viz` | bool | False | Store ray hit positions for debugging |

#### Build Modes

| Mode | Trigger | Description |
|------|---------|-------------|
| `terrain` | `terrain_npz` set | Uses terrain heightmap for floor |
| `snake` | `snake_npz` set | Uses snake mesh for inside/outside test |
| `local` | `local_area_ratio` set | AABB fraction around camera |
| `global` | none of above | Full scene bounds |

#### CLI

```bash
/path/to/bpy_python -m genesis_tools.walkthrough_renderer.pipeline.voxel_grid \
    --blend /path/to/scene.blend \
    --config /path/to/config.json \
    --output results/voxel_grid.npz
```

#### Output: `voxel_grid.npz`

| Key | Shape | Description |
|-----|-------|-------------|
| `candidates` | (K, 3) int32 | Walkable candidate voxel indices |
| `solid` | (N, 3) int32 | Solid (blocked) voxel indices |
| `nx`, `ny`, `nz` | scalar | Grid dimensions |
| `res` | scalar float | Voxel size in Blender units |
| `bounds` | (6,) float | [min_x, min_y, max_x, max_y, min_z, max_z] |
| `unit_scale` | scalar float | Metres per Blender unit |
| `mode` | str | Build mode used |

---

### Step 2: Walkable (`walkable.py`)

Filters voxel candidates to only those reachable from the camera via flood-fill (BFS).

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `aerial` | bool | False | If True, skip floor filter — all candidates are walkable |

#### CLI

```bash
/path/to/bpy_python -m genesis_tools.walkthrough_renderer.pipeline.walkable \
    --voxel-grid results/voxel_grid.npz \
    --config /path/to/config.json \
    --output results/walkable.npz \
    --blend /path/to/scene.blend
```

#### Output: `walkable.npz`

| Key | Shape | Description |
|-----|-------|-------------|
| `walkable` | (W, 3) int32 | Walkable voxel indices (BFS-connected to camera) |

---

### Step 3: Path Planning (`path_plan.py`)

Generates waypoints via farthest-point sampling, solves TSP tour, then builds smooth path.

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `num_waypoints` | int | 20 | Number of waypoints to sample |
| `seed` | int | 42 | RNG seed for farthest-point sampling |
| `path_planner` | str | — | `"theta_star"` = BFS+LOS; else = Laplacian smooth |
| `laplacian_iters` | int | 0 (theta_star) / 5 (default) | Smoothing iterations |
| `aerial` | bool | False | 3D farthest-point + XYZ TSP; skip floor raycast |
| `camera_height` | float | 1.7 | Eye height in metres |
| `terrain_npz` | str | — | Heightmap for floor clamping |
| `particle_block_margin` | float | 1.5 | Sub-voxel particle detection margin |

#### Key Internal: `_best_z(wx, wy, lin_z)`

- **Aerial mode**: Skips downward raycast (avoids hitting roof), applies heightmap clamp only
- **Non-aerial mode**: Fires downward raycast for exact floor Z; falls back to heightmap

#### Key Internal: `_build_smooth_path(tour, walkable, config, bounds)`

Steps: BFS corridor → Laplacian passes (with voxel-Z clamp + LOS check) → particle deflection → 4× upsample with `_best_z` snap.

#### CLI

```bash
/path/to/bpy_python -m genesis_tools.walkthrough_renderer.pipeline.path_plan \
    --voxel-grid results/voxel_grid.npz \
    --walkable results/walkable.npz \
    --blend /path/to/scene.blend \
    --config /path/to/config.json \
    --output results/path.npz
```

#### Output: `path.npz`

| Key | Shape | Description |
|-----|-------|-------------|
| `waypoints` | (W, 3) int32 | Waypoint grid indices |
| `path_points` | (P, 3) float64 | World-space path positions |
| `tour` | (T,) int32 | Ordered waypoint visit indices |
| `camera_height` | scalar | Camera height used |
| `bounds` | (6,) float | Scene bounds |
| `res` | scalar | Voxel resolution |

---

### Step 4: Camera Orientation (`camera_orient.py`)

Computes per-waypoint gaze quaternions based on future path direction.

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `aerial` | bool | False | True = full 3D gaze; False = horizontal only with -0.3 tilt |
| `camera_height` | float | 1.7 | Eye height in metres |
| `force_camera_walkable` | bool | True | Override wp0 orientation from scene camera |

#### Gaze Computation

- **Aerial**: Full 3D direction vector → quaternion via `to_track_quat("-Z", "Y")`
- **Walking**: Flatten to XY plane, apply fixed -0.3 downward pitch

#### CLI

```bash
/path/to/bpy_python -m genesis_tools.walkthrough_renderer.pipeline.camera_orient \
    --blend /path/to/scene.blend \
    --path results/path.npz \
    --config /path/to/config.json \
    --output results/wp_schedule.json
```

#### Output: `wp_schedule.json`

```json
[
    {"t": 0.0, "quat": [w, x, y, z]},
    {"t": 0.15, "quat": [w, x, y, z]},
    ...
]
```

---

### Step 5: Camera Animation (`camera_animate.py`)

Creates keyframed camera animation in a Blender file. Interpolates position along path and orientation based on gaze mode.

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `waypoint_gaze_mode` | str | `"smooth_adaptive"` (aerial) / `"free"` (non-aerial) | Gaze mode |
| `fps` | int | 12 | Frames per second |
| `walk_speed_mps` | float | 1.2 | Walking speed (m/s) for duration calc |
| `max_duration_seconds` | float | — | Cap on auto-computed duration |
| `duration_seconds` | float | auto | Override computed duration |
| `camera_origin_hold_frames` | int | 0 | Extra stationary frames at start |
| `rotation_smooth_seconds` | float | 3.5 | EMA slerp time constant |
| `lookahead_fraction` | float | 0.05 | Fractional arc-length lookahead (free/eye_level) |
| `camera_lens` | float | 35.0 | Fallback lens mm |
| `camera_sensor_width` | float | 36.0 | Fallback sensor width mm |
| `camera_clip_end` | float | 10000.0 | Fallback clip end |

#### Gaze Modes

| Mode | Config Value | Behavior |
|------|-------------|----------|
| **Smooth Adaptive** | `"smooth_adaptive"` | Offline bidirectional Gaussian-smoothed yaw + pitch from path tangent. **Default for aerial.** Best for flythrough. |
| **Waypoint** | `"waypoint"` | Slerp between precomputed per-waypoint quaternions from wp_schedule |
| **Eye Level** | `"eye_level"` | Look-ahead along path but forced horizontal (current eye height) |
| **Free** | `"free"` (or any other) | Full 3D look-ahead including Z delta. **Default for non-aerial.** |

#### Smooth Adaptive Sub-Parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `smooth_pitch_lookahead_m` | float | 15.0 | Look-ahead distance for pitch estimation (metres) |
| `smooth_pitch_min_deg` | float | -15.0 | Pitch clamp minimum (degrees, negative = look down) |
| `smooth_pitch_max_deg` | float | 8.0 | Pitch clamp maximum (degrees, positive = look up) |
| `smooth_yaw_sigma_s` | float | 1.5 | Gaussian sigma for yaw smoothing (seconds) |
| `smooth_pitch_sigma_s` | float | 0.8 | Gaussian sigma for pitch smoothing (seconds) |

#### Slerp Smoothing (all modes except smooth_adaptive)

```python
slerp_alpha = 1.0 - exp(-1.0 / max(1, fps * rotation_smooth_seconds))
```

#### CLI

```bash
/path/to/bpy_python -m genesis_tools.walkthrough_renderer.pipeline.camera_animate \
    --blend /path/to/scene.blend \
    --path results/path.npz \
    --orient results/wp_schedule.json \
    --config /path/to/config.json \
    --output-blend results/scene_walkthrough.blend
```

---

### Step 6: Render (`_render_frames.py`)

Renders each frame from the animated `.blend` file. Uses Windows Blender if available (GPU), falls back to Linux Blender.

#### Render Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `render_engine` | str | "WORKBENCH" | CYCLES / BLENDER_WORKBENCH / BLENDER_EEVEE |
| `render_width` | int | 1280 | Output width (px) |
| `render_height` | int | 720 | Output height (px) |
| `render_samples` | int | 32 | Ray samples (CYCLES only) |
| `use_denoise` | bool | False | Enable denoising (CYCLES only) |

#### Output

```
results/my_walkthrough/
├── frames/
│   ├── frame_0001.png
│   ├── frame_0002.png
│   └── ...
├── scene_indoor_walkthrough.gif
└── scene_indoor_walkthrough.mp4
```

---

## Complete Example Scripts

### Indoor Walkthrough (Low-Res Test)

```python
#!/usr/bin/env python3
"""Quick indoor walkthrough test at low resolution."""
import json, sys
sys.path.insert(0, ".")
from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run

with open("configs/standard_scene.json") as f:
    config = json.load(f)

config.update({
    "aerial": True,
    "render_engine": "BLENDER_WORKBENCH",
    "render_width": 480,
    "render_height": 360,
    "render_samples": 16,
    "fps": 12,
    "max_duration_seconds": 10,
    "snake_npz": "results/active_contour/AI33_001_280_newparams_subdiv2/snake_mesh.npz",
    "waypoint_gaze_mode": "smooth_adaptive",
})

wt_run(
    "/path/to/AI33_001_280.blend",
    config,
    "results/ai33_lowres_test",
    render=True,
)
```

### Snake Fitting + Walkthrough (End-to-End)

```python
#!/usr/bin/env python3
"""End-to-end: fit snake → generate walkthrough."""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from genesis_tools.active_contour.fit_scene_contour import fit_scene_active_contour
from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run

BLEND = Path("/path/to/scene.blend")
BLENDER = "/home/kingy/blender/blender"

# Phase 1: Fit snake
snake_dir = Path("results/active_contour") / BLEND.stem
snake_result = fit_scene_active_contour(
    BLEND, snake_dir,
    alpha=0.7, beta=0.25,
    subdivision_levels=2,
    blender_command=BLENDER,
)
print(f"Snake: {snake_result['snake_vertices']} verts, {snake_result['snake_faces']} faces")

# Phase 2: Walkthrough
with open("configs/standard_scene.json") as f:
    config = json.load(f)

config.update({
    "aerial": True,
    "snake_npz": str(snake_dir / "snake_mesh.npz"),
    "waypoint_gaze_mode": "smooth_adaptive",
    "render_engine": "BLENDER_WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "fps": 12,
    "max_duration_seconds": 30,
})

wt_run(str(BLEND), config, f"results/{BLEND.stem}_walkthrough", render=True)
```

### Compare All 4 Gaze Modes

```python
#!/usr/bin/env python3
"""Render all 4 gaze modes for visual comparison."""
import json, sys, shutil
from pathlib import Path
sys.path.insert(0, ".")
from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run

BLEND = "/path/to/scene.blend"
SNAKE = "results/active_contour/my_scene/snake_mesh.npz"
MODES = ["smooth_adaptive", "waypoint", "eye_level", "free"]

with open("configs/standard_scene.json") as f:
    base_config = json.load(f)

base_config.update({
    "aerial": True,
    "snake_npz": SNAKE,
    "render_engine": "BLENDER_WORKBENCH",
    "render_width": 480,
    "render_height": 360,
    "render_samples": 16,
    "fps": 12,
    "max_duration_seconds": 10,
})

for mode in MODES:
    out = f"results/gaze_compare/{mode}"
    config = base_config.copy()
    config["waypoint_gaze_mode"] = mode

    # Reuse steps 1-3 from first run
    if mode != MODES[0]:
        Path(out).mkdir(parents=True, exist_ok=True)
        first = f"results/gaze_compare/{MODES[0]}"
        for f in ["voxel_grid.npz", "walkable.npz", "path.npz"]:
            src = Path(first) / f
            if src.exists():
                shutil.copy2(src, Path(out) / f)

    print(f"\n{'='*40}\nGaze mode: {mode}\n{'='*40}")
    wt_run(BLEND, config, out, render=True)
```

---

## Environment Requirements

| Component | Local WSL Path | GCP Alternative |
|-----------|---------------|-----------------|
| Blender | `/home/kingy/blender/blender` | `/opt/blender/blender` (install from blender.org tar.xz) |
| Blender Python (bpy) | `/home/kingy/blender/4.5/python/bin/python3.11` | Install `pip install bpy` in Blender's Python |
| Python deps | numpy, scipy, Pillow | Same |
| GPU (render only) | NVIDIA RTX 5090 (OPTIX) | Not required for path computation |

### GCP Notes

- Steps 1–4 (voxel_grid → camera_orient) produce **bit-exact identical results** on GCP vs local WSL
- Step 5 (camera_animate) fails on pip bpy 5.0.1 due to `fcurves` API change — use Blender 4.5 binary instead
- Step 6 (render) requires GPU for CYCLES; WORKBENCH works on CPU

---

## Debug & Visualization

### Debug Script (`scripts/debug_walkthrough.py`)

One-command debug runner that executes every step individually with full intermediate output, timing, and a summary report.

```bash
# Basic debug run (low-res, no render)
python3 scripts/debug_walkthrough.py \
    --blend /path/to/scene.blend \
    --snake results/active_contour/my_scene/snake_mesh.npz \
    --output results/debug_run \
    --no-render

# Full debug run with visualization overlay
python3 scripts/debug_walkthrough.py \
    --blend /path/to/scene.blend \
    --snake results/active_contour/my_scene/snake_mesh.npz \
    --output results/debug_run \
    --width 480 --height 360 --samples 16 \
    --fps 12 --duration 10 \
    --gaze smooth_adaptive \
    --visualize

# Resume a partially-completed run (skip existing outputs)
python3 scripts/debug_walkthrough.py \
    --blend /path/to/scene.blend \
    --snake results/active_contour/my_scene/snake_mesh.npz \
    --output results/debug_run \
    --resume
```

#### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--blend` | required | Input .blend scene file |
| `--snake` | required | Path to snake_mesh.npz |
| `--output` | required | Output directory for all intermediate files |
| `--width` | 480 | Render width (px) |
| `--height` | 360 | Render height (px) |
| `--samples` | 16 | Render samples |
| `--fps` | 12 | Frames per second |
| `--duration` | 10 | Max walkthrough duration (seconds) |
| `--gaze` | smooth_adaptive | Gaze mode: smooth_adaptive / waypoint / eye_level / free |
| `--engine` | BLENDER_WORKBENCH | Render engine: BLENDER_WORKBENCH / CYCLES / BLENDER_EEVEE |
| `--config` | standard_scene.json | Base config JSON path |
| `--no-render` | False | Skip the render step (steps 1–5 only) |
| `--visualize` | False | Generate debug .blend with all visualization layers |
| `--resume` | False | Skip steps whose output files already exist |

#### Output Structure

```
results/debug_run/
├── _config.json                         # Full config used
├── voxel_grid.npz                       # Step 1: 3D occupancy grid
├── walkable.npz                         # Step 2: BFS-reachable walkable voxels
├── path.npz                             # Step 3: waypoints + smooth path
├── wp_schedule.json                     # Step 4: per-waypoint camera orientations
├── scene_walkthrough.blend              # Step 5: animated camera Blender file
├── frames/                              # Step 6: rendered PNG frames
│   ├── frame_0001.png
│   ├── frame_0002.png
│   └── ...
├── scene_debug_viz.blend                # (--visualize) debug overlay Blender file
└── debug_dump.json                      # Machine-readable summary for comparison
```

#### Summary Report

The script prints a summary at the end:
- **Timings** per step (seconds)
- **File sizes** for all outputs
- **Voxel grid stats** — grid dimensions, resolution, candidate/solid counts
- **Walkable count** — BFS-connected voxels
- **Path stats** — waypoints, path points, XYZ ranges, total path length
- **Camera orientations** — waypoint quaternions
- **Frame count and resolution**

#### Cross-Platform Comparison

`debug_dump.json` contains machine-readable data for comparing results across environments:

```python
# Compare two debug dumps (e.g. local vs GCP)
import json
with open("results/local/debug_dump.json") as f:
    local = json.load(f)
with open("results/gcp/debug_dump.json") as f:
    gcp = json.load(f)

assert local == gcp, "Results differ!"
```

---

### 3D Visualization (`visualize.py`)

Overlays debug geometry from each pipeline step onto the original `.blend` scene. Open the output in Blender to inspect.

#### Color Scheme

| Layer | Color | Data Source |
|-------|-------|-------------|
| Solid voxels | 🔴 Red | voxel_grid.npz — geometry-occupied cells |
| Free voxels | 🟡 Yellow | voxel_grid.npz — empty but unreachable cells |
| Candidate voxels | 🔵 Blue | voxel_grid.npz — flood-fill reachable, not walkable |
| Walkable voxels | 🔵 Cyan | walkable.npz — BFS-connected to camera |
| Waypoints | 🟢 Green | path.npz — sampled navigation waypoints |
| Path line | 🩷 Pink | path.npz — smooth interpolated path |
| Camera axes | 🔴🟢🔵 RGB | walkthrough.blend — per-frame camera pose (X=red, Y=green, Z=blue) |

#### Standalone CLI

```bash
/home/kingy/blender/4.5/python/bin/python3.11 -m \
    genesis_tools.walkthrough_renderer.visualize \
    --blend /path/to/scene.blend \
    --output results/debug_viz.blend \
    --voxel-grid results/voxel_grid.npz \
    --walkable results/walkable.npz \
    --path results/path.npz \
    --camera results/scene_walkthrough.blend \
    --config results/_config.json
```

Each `--flag` is optional — pass only the layers you want to inspect. For example, to inspect just the voxel grid:

```bash
/home/kingy/blender/4.5/python/bin/python3.11 -m \
    genesis_tools.walkthrough_renderer.visualize \
    --blend /path/to/scene.blend \
    --output results/voxel_only.blend \
    --voxel-grid results/voxel_grid.npz
```

#### Python API

```python
from genesis_tools.walkthrough_renderer.visualize import visualize

visualize(
    blend_path="/path/to/scene.blend",
    output_blend="results/debug_viz.blend",
    voxel_grid="results/voxel_grid.npz",     # optional
    walkable="results/walkable.npz",          # optional (requires voxel_grid)
    path="results/path.npz",                  # optional
    camera_blend="results/scene_wt.blend",    # optional
    config={"fps": 12, "grid_resolution": 0.5},
)
```

---

### Combined View GIF/MP4 (`combined_gif.py`)

Side-by-side view: rendered walkthrough frames (left) + live XY map (right) showing path progress, camera position, heading arrow, and FOV cone.

#### Python API

```python
from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif, make_combined_mp4
from pathlib import Path

frames = sorted(Path("results/frames").glob("frame_*.png"))

# GIF (every 3rd frame, 50% scale — keeps file size manageable)
make_combined_gif(
    frames=frames,
    path_npz="results/path.npz",
    terrain_npz="results/snake_mesh.npz",   # or terrain_snake.npz for outdoor
    output_gif="results/combined_view.gif",
    fps=12,
    map_px=480,        # map panel width in pixels
    step=3,            # use every 3rd frame
    output_scale=0.5,  # 50% of original resolution
    fov_deg=35.7,      # camera horizontal FOV
)

# MP4 (all frames, full resolution — better quality, smaller file)
make_combined_mp4(
    frames=frames,
    path_npz="results/path.npz",
    terrain_npz="results/snake_mesh.npz",
    output_mp4="results/combined_view.mp4",
    fps=6,
    map_px=480,
    step=1,
    output_scale=1.0,
)
```

---

### Reading Intermediate Files Directly

Every step outputs `.npz` or `.json` files that can be inspected with plain Python:

```python
import numpy as np
import json

# Step 1: Voxel Grid
vg = np.load("results/voxel_grid.npz", allow_pickle=True)  # trusted local data
print(f"Grid: {vg['nx']}x{vg['ny']}x{vg['nz']}, res={vg['res']:.1f} BU")
print(f"Candidates: {vg['candidates'].shape[0]}, Solid: {vg['solid'].shape[0]}")
print(f"Bounds: {vg['bounds']}")

# Step 2: Walkable
wk = np.load("results/walkable.npz", allow_pickle=True)  # trusted local data
print(f"Walkable voxels: {wk['walkable'].shape[0]}")

# Step 3: Path
pd = np.load("results/path.npz", allow_pickle=True)  # trusted local data
pp = pd["path_points"]
print(f"Waypoints: {pd['waypoints'].shape[0]}")
print(f"Path points: {pp.shape[0]}")
print(f"Tour order: {pd['tour']}")
print(f"Z range: [{pp[:,2].min():.1f}, {pp[:,2].max():.1f}]")
# Total path length
diffs = np.diff(pp, axis=0)
print(f"Total length: {np.linalg.norm(diffs, axis=1).sum():.1f} BU")

# Step 4: Camera Orient
with open("results/wp_schedule.json") as f:
    wps = json.load(f)
for w in wps[:3]:
    print(f"  t={w['t']:.3f}  quat={w['quat']}")
```

---

## Key Findings & Known Issues

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Snake only ~400 verts (coarse) | `subdivision_levels` default changed from 2 to 0 | Use `subdivision_levels=2` |
| White/gray frames in aerial mode | `_best_z()` raycast hits roof from above | Aerial mode skips raycast, uses linear Z |
| Camera looking at ceiling (aerial) | `smooth_adaptive` was disabled for aerial | Removed `not config.get("aerial")` gate |
| Aerial default gaze was `free` | `free` mode tilts wildly between floors | Changed default to `smooth_adaptive` for aerial |
| pip bpy 5.0.1 `fcurves` error | Blender 5.0 API change | Use Blender 4.5 binary Python, not pip bpy |

---

— Hani · Zengyn42
