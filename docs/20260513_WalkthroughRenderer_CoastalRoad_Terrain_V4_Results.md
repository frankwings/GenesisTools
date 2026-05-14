# Walkthrough Renderer — Coastal Road Terrain V4 Results

**Date**: 2026-05-13
**Commit**: `e6975d1`
**Scene**: `coastal road.blend` (50 km × 50 km open coastal scene)
**Script**: `run_coastal_road_terrain_v2.py` (v4 render — exact origin camera fix)

---

## What Changed from V3

V3 still had a position discrepancy at frame 1: the camera's world position differed from the original scene camera by ~55 BU (Y, voxel quantization) and ~116 BU (Z, TerrainSnake settled above original camera due to tree canopy).

| Defect | Root Cause | Fix |
|--------|-----------|-----|
| Frame 1 position ≠ original camera | `cam_pos = terrain_z + cam_h` ignores original Z; voxel grid XY quantized to 277.78 BU/cell | Blend from `camera_xyz` (exact origin) at t=0 to `terrain_z + cam_h` at t=t1 (second waypoint) |

**Implementation** (`camera_animate.py`):
- Loads `camera_xyz = [1259, -362, 462]` from `terrain_snake.npz`
- Reads `t1 = wp_schedule[1][0]` (arc-length fraction of second waypoint)
- For `t ∈ [0, t1]`: `cam_pos = lerp(camera_xyz, terrain_z+cam_h, alpha=t/t1)`
- For `t > t1`: pure `terrain_z + cam_h` as before

This produces a smooth, continuous camera path with no discontinuity at frame 2.

---

## 1. Input

| Field | Value |
|-------|-------|
| Blend file | `coastal road.blend` |
| Scene AABB | 50 000 × 50 000 BU |
| Solid objects | 303 mesh objects |
| Camera | `Camera006` @ (1259, −362, 462), lookat = (0.017, 1.000) |
| Terrain snake resolution | 277.78 BU/cell (180 × 180) |
| Grid resolution | `"auto"` → iter 1, uses fine res directly |
| `mark_particle_instances` | `False` |
| `camera_height` | 10.0 BU |

---

## 2. Phase 1 — Terrain Snake (reused from V2)

| Stat | Value |
|------|-------|
| Grid | 180 × 180, res = 277.78 BU/cell |
| Coverage | 32 400 / 32 400 (100%) |
| Convergence | 200 iterations |

Reused unchanged from V2/V3.

---

## 3. Phase 2 — Voxel Grid + Path (reused from V2)

| Step | Result |
|------|--------|
| Voxel grid | 180 × 180, res = 278 m/cell |
| Walkable cells | 31 684 green / 716 excluded |
| wp0 | Camera cell (94, 88, iz=2) — forced via `force_camera_walkable` |
| Tour | 20 waypoints, Held-Karp |
| Path points | 3 287 |

---

## 4. Camera Orient (reused from V3)

`wp_schedule.json` reused — wp0 orientation from `camera_lookat (0.017, 1.000)`.

---

## 5. Camera Animate (new — V4 fix)

Frame 1 now uses the exact original camera position `(1259, -362, 462)` BU from `camera_xyz` in `terrain_snake.npz`. Between frame 1 (t=0) and the second waypoint (t=t1), all three coordinates blend linearly toward the normal `terrain_z + cam_h` path. From wp1 onward the camera follows terrain as in V3.

```
camera_xyz = [1259, -362, 462]   ← from terrain_snake.npz
t1         = wp_schedule[1]["t"] ← arc fraction of second waypoint
alpha      = t / t1              ← goes 0→1 from frame 1 to wp1

cam_pos.x = camera_xyz[0] * (1-alpha) + path_x * alpha
cam_pos.y = camera_xyz[1] * (1-alpha) + path_y * alpha
cam_pos.z = camera_xyz[2] * (1-alpha) + (terrain_z + cam_h) * alpha
```

Log output:
```
[CameraAnimate] Original camera position: (1259.0, -362.0, 462.0) BU — frame 1 will use this exactly
```

---

## 6. Render

| Setting | Value |
|---------|-------|
| Engine | Cycles (GPU) |
| GPU | NVIDIA GeForce RTX 5090 (OPTIX) |
| Samples | 64 + OPTIX denoiser |
| Frames | 1 000 |
| Avg frame time | ~3.3 s |
| Total render time | ~55 min |

### Walkthrough GIF

![Walkthrough](../docs/assets/coastal_road_terrain_v2/coastal_road_terrain_v2_walkthrough.gif)

### Combined Walkthrough GIF (path overlay)

![Combined Walkthrough](../docs/assets/coastal_road_terrain_v2/coastal_road_terrain_v2_walkthrough_combined.gif)

**MP4**: `docs/assets/coastal_road_terrain_v2/coastal_road_terrain_v2_walkthrough_combined.mp4`

---

## 7. Summary

### Pipeline Config (V4 changes highlighted)

| Parameter | V3 | V4 |
|-----------|----|----|
| `camera_height` | 10.0 BU | 10.0 BU |
| `grid_resolution` | `"auto"` | `"auto"` |
| `mark_particle_instances` | `False` | `False` |
| `force_camera_walkable` | `True` | `True` |
| `fps` | 6 | 6 |
| ground_z source (terrain mode) | heightmap first | heightmap first |
| wp0 orientation | from camera_lookat | from camera_lookat |
| **frame 1 position** | terrain_z + cam_h | **camera_xyz exact (1259,−362,462)** |
| **frame 1→wp1 transition** | step discontinuity | **smooth lerp** |

### Output File Tree

```
results/coastal_road_terrain_v2/
├── terrain_snake.npz        (reused from V2)
├── voxel_grid.npz           (reused from V2)
├── walkable.npz             (reused from V2)
├── path.npz                 (reused from V2)
├── wp_schedule.json         (reused from V3)
├── coastal road_walkthrough.blend  ← regenerated (V4 camera_animate)
├── frames/
│   └── frame_0001.png … frame_1000.png  ← re-rendered
└── viz/  (terrain figures, unchanged)

docs/assets/coastal_road_terrain_v2/
├── coastal_road_terrain_v2_walkthrough.gif          (regenerated — V4 frames)
├── coastal_road_terrain_v2_walkthrough_combined.gif (regenerated — V4 frames)
├── coastal_road_terrain_v2_walkthrough_combined.mp4 (regenerated — V4 frames)
└── figure_*.png
```

### Known Issues

- `_snap_path_to_floor` in `path_plan` is still a no-op in terrain mode (ray fires from below terrain surface). No visual impact — camera_animate corrects via heightmap lookup. Future fix: fire ray from `max_z + 10` instead of `voxel_center_Z + probe_height`.
- Water-area cells still routed over open water (Z ≈ 442 BU). Future improvement: exclude open-water cells from walkable candidates.
