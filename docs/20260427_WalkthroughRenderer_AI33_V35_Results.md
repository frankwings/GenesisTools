# AI33_001 Walkthrough — Active Contour Snake Mode + Modular Pipeline (v35)

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-04-27
**Commit**: `3ea09cd`

---

## Algorithm Changes vs v34

### 1. Active Contour Snake Mode (Voxel Grid)

v34 used local BFS flood-fill to classify free voxels. v35 replaces the local voxel-buildfrom-scratch approach with an **active contour snake mode**: the walkable volume is determined by a pre-computed snake mesh (closed surface) instead of scene ray-casting.

**Input files:**
- `results/active_contour/AI33_001_280/snake_mesh.npz` — active contour output: vertices (3,058 × 3) + faces (6,112 × 3) triangulated mesh representing the traversable interior surface
- `results/active_contour/AI33_001_280/voxel_grid.npz` — pre-computed voxel grid from the active contour run: centers (13,267 × 3), `voxel_size`, `grid_shape` [30 × 43 × 17]

**Classification:** `voxel_grid.py` imports the snake mesh into a temporary Blender scene, uses `bpy` ray-cast from each voxel center in ±Z to determine whether it lies inside the snake surface (solid) or outside (free). Free voxels adjacent to solid ones become walkable candidates.

| Config key | Value | Meaning |
|---|---|---|
| `snake_npz` | `results/active_contour/.../snake_mesh.npz` | Pre-computed snake surface |
| `voxel_grid_npz` | `results/active_contour/.../voxel_grid.npz` | Pre-computed voxel grid |
| `grid_resolution` | 0.5 | Target voxel size (m); overridden by snake grid in snake mode |
| `max_grid_cells_xy` | 80 | Upper bound on grid XY extent |
| `max_grid_cells_z` | 40 | Upper bound on grid Z extent |

The actual voxel resolution used is **45.70 BU = 45.7 cm** (inherited from the active contour grid).

### 2. Modular Pipeline (new)

v35 is the first run using the new 6-step modular pipeline replacing the monolithic `render_walkthrough.py` (3,008 lines):

| Step | Module | Output |
|------|--------|--------|
| 1 | `voxel_grid.py` | `voxel_grid.npz` |
| 2 | `walkable.py` | `walkable.npz` |
| 3 | `path_plan.py` | `path.npz` |
| 4 | `camera_orient.py` | `wp_schedule.json` |
| 5 | `camera_animate.py` | `*_walkthrough.blend` |
| 6 | `render.py` | `frames/frame_*.png` |

Each step saves its output as an NPZ/JSON file. `walkthrough.run()` checks for existing files — completed steps are skipped automatically (implicit resume).

### 3. Camera Duration Fix

v34 computed path duration as `path_length_BU / walk_speed_mps`, inflating duration 100× for cm-scale scenes. v35 converts units before dividing:

```python
path_length_m = path_length * unit_scale   # BU → metres
raw_dur = max(5.0, path_length_m / walk_speed)
```

Path: 11,470 BU = 114.7 m → 114.7 / 1.2 m/s = **95.6 s** (vs 9,558 s from the bug).

---

## Config

```python
config = {
    "snake_npz":              "results/active_contour/AI33_001_280/snake_mesh.npz",
    "voxel_grid_npz":         "results/active_contour/AI33_001_280/voxel_grid.npz",
    "camera_height":          1.7,
    "num_waypoints":          20,
    "seed":                   42,
    "waypoint_gaze_mode":     "free",
    "rotation_smooth_seconds": 2.0,
    "grid_resolution":        0.5,
    "max_grid_cells_xy":      80,
    "max_grid_cells_z":       40,
    "fps":                    12,
    "render_engine":          "WORKBENCH",
    "render_width":           1280,
    "render_height":          720,
    "render_samples":         32,
    "panoramic":              False,
}
```

---

## Result

| Metric | Value |
|--------|-------|
| Resolution | 1280×720 |
| Render engine | WORKBENCH |
| Voxel mode | **snake** (active contour) |
| Grid | 30 × 43 × 17 |
| Voxel size | 45.70 BU (45.7 cm) |
| Solid voxels | 12,597 |
| Walkable candidates | 7,522 |
| Waypoints | 20 |
| Path points | 817 |
| Path length | 11,470 BU (114.7 m) |
| Camera height | 1.7 m |
| Frames | 1,147 |
| Duration | 95.6 s (1.6 min) |
| Min frame size | 91 KB |
| Max frame size | 896 KB |
| Median frame size | 343 KB |

**GIF** (1,147 frames, 12 fps):

![v35](assets/ai33_001_walkthrough_v35/AI33_001_280_walkthrough.gif)

---

## Observations

- **Snake mode**: 12,597 solid voxels and 7,522 walkable candidates — solid count is 3.6× higher than v34 (3,494) because the active contour mesh fills the interior of the architectural scene rather than relying on ray-cast from above only. This gives a more complete 3D occupancy map.
- **Duration fix**: The cm-scale unit conversion bug would have produced 114,708 frames (9,558 s); after the fix the animation is 95.6 s / 1,147 frames at 12 fps — a realistic walking-speed flythrough.
- **Modular pipeline**: implicit resume worked correctly — re-running from a partially completed state skips finished steps without recomputation.
- **Smooth rotation**: `rotation_smooth_seconds=2.0` + `waypoint_gaze_mode=free` produces a fluid forward-looking camera without sudden snaps.

## Files

- **GIF**: `results/ai33_001_walkthrough_v35/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v35/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v35/frames/` (1,147 × 1280×720 PNG)
- **Intermediates**: `voxel_grid.npz`, `walkable.npz`, `path.npz`, `wp_schedule.json`
- **Run script**: `GenesisTools/run_ai33_v35.py`
