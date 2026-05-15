# Walkthrough Renderer — Coastal Road Terrain V5 Results

**Date**: 2026-05-14
**Commits**: `e6975d1` (camera_animate position fix) + `ce84e99` (camera_orient orientation fix)
**Scene**: `coastal road.blend` (50 km × 50 km open coastal scene)
**Script**: `run_coastal_road_terrain_v2.py` (v5 render — exact origin camera position + orientation)

---

## What Changed from V4

V4 fixed frame 1 position but not orientation. Frame 1 orientation was still wrong because:
1. `camera_lookat` in `terrain_snake.npz` only stores the XY-projected forward direction — vertical tilt and roll are lost
2. `_dir_to_quat` applies a fixed `-0.3` downward tilt that doesn't match the actual camera
3. `wp_schedule.json` was reused from V3 (stale orientation data)

| Defect | Root Cause | Fix |
|--------|-----------|-----|
| Frame 1 position ≠ original camera | `cam_pos = terrain_z + cam_h` ignores original Z; voxel XY quantized to 277.78 BU | Lerp from `camera_xyz` at t=0 to `terrain_z + cam_h` at wp1 *(V4)* |
| Frame 1 orientation ≠ original camera | `camera_lookat` is XY-only (loses pitch/roll); `_dir_to_quat` fixed tilt doesn't match | Override `wp_schedule[0]["quat"]` with `obj.matrix_world.to_quaternion()` *(V5)* |

---

## 1. Input

| Field | Value |
|-------|-------|
| Blend file | `coastal road.blend` |
| Scene AABB | 50 000 × 50 000 BU |
| Solid objects | 303 mesh objects |
| Camera | `Camera006` @ (1259, −362, 462), world rotation quat (w=0.8141, x=0.5807, y=−0.0051, z=−0.0071) |
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

## 4. Camera Orient (regenerated — V5 fix)

`wp_schedule.json` regenerated. `camera_orient` now reads the actual scene camera's world rotation quaternion from `obj.matrix_world.to_quaternion()` and overrides `wp_schedule[0]["quat"]` directly:

```
[CameraOrient] wp0 orientation overridden from terrain camera_lookat (0.017, 1.000)
[CameraOrient] wp0 quat overridden with actual camera world rotation (w=0.8141 x=0.5807 y=-0.0051 z=-0.0071)
```

The second override supersedes the first. Frame 1 now uses the exact original camera rotation.

---

## 5. Camera Animate (V4 + V5 fixes)

Frame 1 uses both:
- **Position** (V4): `camera_xyz = [1259, -362, 462]` directly at t=0; lerp to `terrain_z + cam_h` by wp1
- **Orientation** (V5): `wp_schedule[0]` now holds the actual camera world rotation quaternion

```
[CameraAnimate] Original camera position: (1259.0, -362.0, 462.0) BU — frame 1 will use this exactly
```

From wp1 onward: normal terrain+cam_h position with waypoint-slerped orientation.

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

**MP4**: `docs/assets/coastal_road_terrain_v2/coastal_road_terrain_v2_walkthrough_combined.mp4` (36 MB)

---

## 7. Summary

### Pipeline Config (full history)

| Parameter | V2 | V3 | V4 | V5 |
|-----------|----|----|----|----|
| `camera_height` | 1.7 BU | 10.0 BU | 10.0 BU | 10.0 BU |
| ground_z source (terrain) | ray_cast first | heightmap first | heightmap first | heightmap first |
| wp0 orientation | toward wp1 | from `camera_lookat` (XY only) | from `camera_lookat` (XY only) | **actual camera quat** |
| frame 1 position | terrain_z+cam_h | terrain_z+cam_h | **camera_xyz exact** | camera_xyz exact |
| frame 1→wp1 transition | n/a | n/a | **smooth lerp** | smooth lerp |

### Frame 1 Before/After

| | V3 | V5 |
|-|----|----|
| Position X | ~1250 (−9 BU voxel error) | **1259.0** (exact) |
| Position Y | ~−417 (+55 BU voxel error) | **−362.0** (exact) |
| Position Z | terrain_z+cam_h ≈ 578 BU | **462.0** (exact) |
| Orientation | XY lookat + fixed −0.3 tilt | **actual camera world rotation** |

### Output File Tree

```
results/coastal_road_terrain_v2/
├── terrain_snake.npz        (reused from V2)
├── voxel_grid.npz           (reused from V2)
├── walkable.npz             (reused from V2)
├── path.npz                 (reused from V2)
├── wp_schedule.json         ← regenerated (V5 actual camera quat)
├── coastal road_walkthrough.blend  ← regenerated (V4+V5 camera fixes)
├── frames/
│   └── frame_0001.png … frame_1000.png  ← re-rendered
└── viz/  (terrain figures, unchanged)

docs/assets/coastal_road_terrain_v2/
├── coastal_road_terrain_v2_walkthrough.gif          (42 MB, re-generated)
├── coastal_road_terrain_v2_walkthrough_combined.gif (14 MB, re-generated)
├── coastal_road_terrain_v2_walkthrough_combined.mp4 (36 MB, re-generated)
└── figure_*.png
```

### Known Issues

- `_snap_path_to_floor` in `path_plan` is still a no-op in terrain mode. No visual impact — camera_animate corrects Z via heightmap. Future fix: fire ray from `max_z + 10` instead of `voxel_center_Z + probe_height`.
- Water-area cells still routed over open water. Future improvement: exclude open-water cells from walkable candidates.
