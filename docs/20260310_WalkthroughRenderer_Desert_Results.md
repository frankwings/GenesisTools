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
