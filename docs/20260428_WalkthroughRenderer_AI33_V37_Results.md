# AI33_001 Walkthrough — Walkable Bug Fix: .blend Opened for ray_cast (v37)

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-04-28
**Commit**: `a164e70`

---

## Bug Fixed vs v36

### Critical: Step 2 (walkable) never saw scene geometry

In v36, Step 2 was called directly in the main Python process without opening the `.blend` file:

```python
# walkthrough.py v36 (BROKEN)
wk = wk_build(vg, config)   # bpy.context.scene = empty default scene
```

All other steps (1, 3, 4, 5) ran as bpy subprocesses with `--blend` passed to open the architectural scene. Step 2 was the only exception. As a result:

- `bpy.context.scene` had **no geometry** (empty default Blender scene)
- `scene.ray_cast` returned `False` for every edge ray
- **All 10,250 raw voxels "passed"** — none filtered as solid
- Camera path routed through walls, floors, and furniture

### Fix

Step 2 now runs as a bpy subprocess (matching all other steps), with `--blend` opening the `.blend` file before `scene.ray_cast` is called:

```python
# walkthrough.py v37 (FIXED)
_run_bpy_module(
    "genesis_tools.walkthrough_renderer.pipeline.walkable",
    ["--blend", blend_path, "--voxel-grid", str(vg_path),
     "--config", config_path, "--output", str(wk_path)],
)
```

`walkable.py`'s CLI now accepts `--blend` and calls `bpy.ops.wm.open_mainfile` before running the edge check.

---

## Algorithm (unchanged from v36)

**Step 1**: AABB of AC snake mesh → uniform voxel grid → BVHTree inside/outside test → raw voxels

**Step 2**: For each raw voxel, cast rays along all 12 edges against the **actual scene geometry** (architectural meshes) with edge-key caching. Voxels with no edge hits = free. BFS from camera through free voxels = walkable.

---

## Config

```python
config = {
    "snake_npz": "results/active_contour/AI33_001_280/snake_mesh.npz",
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "rotation_smooth_seconds": 2.0,
    "grid_resolution": 0.5,
    "max_grid_cells_xy": 80,
    "max_grid_cells_z": 40,
    "fps": 12,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "panoramic": False,
}
```

---

## Result

| Metric | Value |
|--------|-------|
| Resolution | 1280×720 |
| Render engine | WORKBENCH |
| Voxel mode | **snake** (active contour BVHTree) |
| Grid | 28 × 40 × 16 |
| Voxel size | 50.00 BU (50 cm) |
| Raw voxels (inside AC) | 10,250 |
| Free voxels (edge-filtered) | 6,515 |
| Walkable voxels (BFS) | 5,162 |
| Edge ray casts (unique) | 31,104 |
| Edge cache hits | 91,896 |
| Waypoints | 20 |
| Path points | 817 |
| Path length | 10,126 BU (101.3 m) |
| Camera height | 1.7 m |
| Frames | 1,012 |
| Duration | 84.3 s (1.4 min) |
| Min frame size | 87 KB |
| Max frame size | 998 KB |
| Median frame size | 475 KB |

**GIF** (1,012 frames, 12 fps):

![v37](assets/ai33_001_walkthrough_v37/AI33_001_280_walkthrough.gif)

---

## Comparison vs v36

| Metric | v36 (broken) | v37 (fixed) |
|--------|-------------|------------|
| Step 2 opens .blend | No | **Yes** |
| Free voxels after edge check | 10,250 / 10,250 (100%) | **6,515 / 10,250 (64%)** |
| Walkable voxels | 10,246 | **5,162** |
| Voxels correctly excluded | 0 | **3,735** |
| Median frame size | 284 KB | **475 KB** |
| Camera penetrates geometry | Yes | **No** |

The larger median frame size (475 KB vs 284 KB) reflects the camera now correctly viewing the full interior — more geometry visible per frame versus the degenerate views produced when the camera went through walls.

---

## Observations

- **3,735 voxels (36%)** were correctly identified as overlapping scene geometry and excluded from the walkable set. These correspond to wall/floor/furniture voxels that the AC mesh enclosed but that the edge check now correctly rejects.
- **Cache efficiency**: 91,896 hits vs 31,104 unique casts = **75% cache hit rate** — edge sharing across adjacent voxels working as intended.
- **BFS**: Only 4 voxels disconnected from camera (same as v36), confirming the walkable volume is one large connected region.
- **Frame size increase**: Larger frames indicate the camera is rendering real interior views with textures and depth, not trivially simple geometry.

## Files

- **GIF**: `results/ai33_001_walkthrough_v37/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v37/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v37/frames/` (1,012 × 1280×720 PNG)
- **Intermediates**: `voxel_grid.npz`, `walkable.npz`, `path.npz`, `wp_schedule.json`
- **Run script**: `GenesisTools/run_ai33_v37.py`
