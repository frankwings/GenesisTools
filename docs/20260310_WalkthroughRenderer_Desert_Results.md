# Walkthrough Renderer — Desert Scene Results

**Date**: 2026-03-10
**Tool**: `genesis_tools.walkthrough_renderer` (GenesisTools commit `4001544`)
**Scene**: Code2Worlds Scene Stream — Desert (`scene_fine.blend`, 3.0 GB)
**Environment**: Local WSL2, Intel Core + NVIDIA RTX 5090 (headless, WORKBENCH = Mesa LLVMpipe)

---

## 1. Input

| Field | Value |
|-------|-------|
| Scene file | `GenesisExp/GenesisCode2Worlds/outputs/scene_desert/scene_fine.blend` |
| Scene size | 150 × 150 m footprint |
| Object count | 1,380 mesh objects |
| Triangle count | ~96 M triangles (avg 69K/object) |
| File size | 3.0 GB |
| Scene origin | Infinigen procedural generation (2026-03-09) |

**Call parameters used**:

```python
render_scene_walkthrough(
    blend_path  = "outputs/scene_desert/scene_fine.blend",
    output_dir  = "outputs/scene_desert/walkthrough",
    render_engine        = "WORKBENCH",
    num_waypoints        = 12,
    fps                  = 8,
    max_duration_seconds = 30.0,
    max_grid_cells_xy    = 80,
    max_grid_cells_z     = 40,
    grid_resolution      = 0.5,   # minimum voxel size (m); actual = 1.875 m after scale-up
    camera_height        = 1.7,
    blender_command      = "/home/kingy/blender/blender-wsl",
)
```

---

## 2. Voxel Grid & Path Planning

### Grid parameters

| Parameter | Value |
|-----------|-------|
| Requested grid resolution (min) | 0.5 m |
| Effective voxel size (after cap) | 1.875 m |
| Grid dimensions | 80 × 80 × 17 cells |
| Total raycasts | ~9,000 |
| Solid voxels | 16,282 |
| Walkable (free floor) cells | 10,458 |
| Interesting look-at objects | 1,356 |

**Before fix** (grid count scaled with scene): 299 × 300 × 67 = **~130,000 raycasts** (14× more).
**After fix**: capped at `max_grid_cells_xy=80`, voxel size scales up to fit — raycasts fixed at ~9K regardless of scene size.

### Path planning output

| Metric | Value |
|--------|-------|
| Waypoints requested | 12 |
| Smooth path sample points | 1,889 |
| Path length (estimated) | ~1,800 m |
| Auto-calculated duration | ~1,500 s (25 min) |
| Capped duration (`max_duration_seconds=30.0`) | 30 s |

---

## 3. Render

| Metric | Value |
|--------|-------|
| Render engine | WORKBENCH (Mesa LLVMpipe — no GPU in headless WSL2) |
| Frame count | 240 |
| Frame rate | 8 fps |
| Resolution | 1280 × 720 |
| Frame size | ~642 KB each |

**Sample frame (frame_0001)**:

![frame 001](../results/scene_desert_walkthrough/frames/frame_0001.png)

**Walkthrough GIF** (240 frames, 8 fps, 4.9 MB):

![walkthrough GIF](../results/scene_desert_walkthrough/scene_fine_walkthrough.gif)

---

## 4. Timing Breakdown

### Final successful run (with `max_duration_seconds=30.0`)

| Phase | Duration | CPU Cores | Root Cause |
|-------|----------|-----------|------------|
| Blender file load | ~5 min | 17 | `.blend` decompression — multi-threaded |
| BVH + depsgraph evaluation | ~40 min | 12 | Ray-cast BVH for 96M triangles — dominant cost |
| Python voxel loop | <1 min | 1 | GIL-bound; 9K rays after grid cap fix |
| WORKBENCH render (240 frames) | ~5 min | 5 | Mesa LLVMpipe software rasterizer |
| GIF assembly | <10 s | 1 | Pillow frame concatenation |
| **Total** | **~51 min** | | |

### Aborted run (before `max_duration_seconds` fix)

| Phase | Estimated Duration | Note |
|-------|-------------------|------|
| File load + BVH | ~45 min | Same as above |
| WORKBENCH render (13,000+ frames) | **~2.5 hours** | 1800m / 1.2 m·s⁻¹ = 1500s × 8fps |
| **Total (projected)** | **~3+ hours** | Killed manually |

---

## 5. Summary

### Output files

```
GenesisTools/results/scene_desert_walkthrough/
├── scene_fine_walkthrough.gif            (4.9 MB, 240 frames, 8 fps)
└── frames/
    └── frame_0001.png                    (sample, 1280×720)

GenesisExp/GenesisCode2Worlds/outputs/scene_desert/walkthrough/
├── scene_fine_walkthrough.gif            (4.9 MB — source)
├── scene_fine_walkthrough.blend          (3.0 GB — animated camera)
└── frames/
    ├── frame_0001.png … frame_0240.png   (1280×720, ~642 KB each)
```

### Pipeline config

| Key | Value |
|-----|-------|
| GenesisTools commit | `4001544` (feat: voxel grid + path improvements) |
| Blender | 4.5.0 (`/home/kingy/blender/blender-wsl`) |
| GPU | RTX 5090 (headless WSL2 — CUDA available but not used by WORKBENCH) |
| Render engine | WORKBENCH (LLVMpipe) |
| Platform | WSL2, Linux 6.6.87.2 |

### Bugs fixed during this session

| # | Bug | Fix |
|---|-----|-----|
| 1 | Grid voxel count scaled with scene size (130K → 9K raycasts) | Cap at `max_grid_cells_xy/z`; scale voxel *size* instead of count |
| 2 | Duration runaway: 150m scene → 13,000+ frames (2.5h render) | Add `max_duration_seconds=60.0` default; cap auto-calculated duration |

### Known Limitations

- **WORKBENCH renders flat grey geometry** — no materials, no lighting. Mesa LLVMpipe has no GPU OpenGL passthrough in headless WSL2. Use `render_engine="CYCLES"` + CUDA for material-quality frames (~1.1s/frame estimate).
- **BVH dominates runtime** (~40 min unavoidable for 96M triangles). Inherent to Blender's ray-cast on large outdoor scenes.
- **Voxel size = 1.875 m at 80-cell cap** — coarse for a 150m scene. Frame 240 shows slight camera clipping into terrain slope. Increase `max_grid_cells_xy` or reduce scene scale for better accuracy.
- **`libSM.so.6` / `libICE.so.6`** must be re-extracted to `/tmp/deb_extract/` after every WSL2 reboot.

### Next Steps

- Test with `render_engine="CYCLES"` for material-quality output (GPU required)
- Raise `camera_height=3.0` to reduce terrain clipping on large-voxel scenes
- Test on a smaller indoor scene (e.g., bedroom) where BVH build is fast and CYCLES quality is visible

---

## 6. Algorithm Reference

### 6.1 Voxel Grid Construction (Global Mode)

**Tri-axial sweep voxelisation** — marks solid voxels without building an explicit mesh representation.

```
Scene bounding box
    │
    ├── Z sweep (top → down)   : detects floors, terrain, tabletops, ceilings
    ├── X sweep (left → right) : detects walls facing ±X
    └── Y sweep (front → back) : detects walls facing ±Y
```

Each sweep fires one ray per grid row. Each ray calls `scene.ray_cast()` repeatedly, stepping 5 cm past each surface hit to find the next one (`_cast_all_hits`). This captures multi-layer structures (mezzanines, furniture stacks on shelves).

**Ray count**: `O(nx·ny + ny·nz + nx·nz)` rays. With `max_grid_cells_xy=80, max_grid_cells_z=40`: worst-case `80×80 + 80×40 + 80×40 = 9,600` initial rays, each potentially spawning 2–10 `ray_cast()` calls depending on scene density.

**Voxel size scaling**: `res = max(grid_resolution, span_x / max_xy, span_y / max_xy, span_z / max_z)`. For a 150m desert with defaults: `res = max(0.5, 150/80) = 1.875 m`.

### 6.2 Walkable Voxel Detection

A voxel `(ix, iy, iz)` is **walkable** (camera feet position) when:
1. `(ix, iy, iz-1)` is solid — floor surface directly below
2. `(ix, iy, iz)` through `(ix, iy, iz + ceil(camera_height/res) - 1)` are all **not** solid — full headroom clearance

The world-space floor height is `min_z + iz * res`. Camera eye height is `floor_z + camera_height`.

### 6.3 Coverage Path Generation

```
walkable cells
    │
    ├── _bfs_largest_component()      — keep only the largest 4-connected region
    │                                   (±1 Z allowed for terrain slopes)
    ├── _farthest_point_sample(n=12)  — spread n waypoints maximally apart (XY distance)
    ├── _greedy_tsp_tour()            — nearest-neighbour tour, closes the loop
    ├── _bfs_path() per segment       — wall-free shortest path between each pair
    ├── Laplacian smooth (5 passes)   — XY only; Z re-snapped to floor after each pass
    └── 4× linear upsample           — dense per-frame samples for smooth camera motion
```

**Farthest-point sampling**: iteratively picks the cell furthest from all already-selected cells. Ensures even spatial coverage rather than clustering waypoints in one area.

**Greedy TSP**: nearest-neighbour heuristic starting from waypoint[0]. Not optimal but fast and good enough for short paths.

**Constrained Laplacian**: smooths XY independently from Z. After each XY move, Z is re-resolved by looking up `walkable_xy[(ix, iy)]` — the floor level at the smoothed XY position. This prevents the path from floating above or sinking below the terrain.

### 6.4 Camera Steering

**Rotation mode**: `QUATERNION` — avoids gimbal lock that occurs with Euler angles when the camera pitches vertically.

**Gaze state machine** (per-frame):

```
State: FORWARD
  │  no nearby object with LOS → look ahead along path (t + 0.15)
  │
  └─→ found interesting object within look_range AND has_line_of_sight()
        │
        └─→ State: GLANCING (hold for glance_duration = fps × 3 frames)
                  │
                  └─→ cooldown[object] = 4 × glance_duration
                      (prevents re-visiting same object too soon)
                      → back to FORWARD
```

**Object scoring**: objects are pre-filtered by name (exclude "floor", "wall", "ceiling", etc.) and volume (> 0.001 m³, < 30m dimension). Nearest eligible object within `look_range` that has clear line-of-sight wins.

**Line-of-sight**: `scene.ray_cast()` from camera eye to object centre. If any geometry is hit before reaching the target, LOS is blocked.

**Rotation smoothing**: first-order low-pass SLERP filter applied every frame:
```
α = 1 - exp(-1 / (fps × rotation_smooth_seconds))
q_current = SLERP(q_prev, q_target, α)
```
With `rotation_smooth_seconds=2.0` at `fps=8`: `α ≈ 0.06` → camera reaches 63% of target rotation after 2s. Higher τ = slower, more cinematic rotation.

**F-curves**: all keyframes set to `LINEAR` interpolation. Combined with the per-frame SLERP smoothing, this gives smooth motion without Blender's default Bezier overshooting.
