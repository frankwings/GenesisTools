# AI33_001 Walkthrough — LOS-Based Waypoint Orientations + Path Interpolation (v38)

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-04-29
**Commit**: `93969d9`

---

## Algorithm Changes vs v37

### Camera Orientation: LOS-Based Waypoint Gaze

v37 used travel-direction gaze (camera always looks 15% ahead along the path). v38 assigns a meaningful orientation at each waypoint using line-of-sight (LOS) visibility:

**Step 4 (`camera_orient.py`)** — now always runs regardless of `waypoint_gaze_mode`:

1. For each waypoint, elevate to eye height (`camera_height / unit_scale`)
2. Ray-cast from each eye to every other waypoint eye — if no scene geometry blocks the line, the pair is mutually visible
3. For waypoint `i`: average the horizontal unit vectors toward all visible waypoints `j`
4. Convert the averaged direction to a camera quaternion (`-Z` track, `Y` up)

Result: 20 waypoints each with a quaternion pointing toward the open, visible region of the scene from that position.

**Step 5 (`camera_animate.py`)** — always uses `wp_schedule` when non-empty:

- Maps each waypoint to its closest path point index → normalised time `t ∈ [0, 1]`
- At each frame, slerp between the two bracketing waypoint quaternions to get a base orientation
- Applies exponential rotation smoothing (`rotation_smooth_seconds=2.0`) on top

```
t_frame → bracket [wp_k, wp_{k+1}] → slerp(quat_k, quat_{k+1}, frac)
       → slerp(prev_quat, target_quat, alpha)   # alpha ≈ 1/(fps × tau)
```

Previously "free" mode returned `wp_schedule=[]` and camera just tracked the travel direction. Now every waypoint provides a suggested gaze direction, and the camera smoothly interpolates between them.

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
| Voxel mode | snake (active contour BVHTree) |
| Grid | 28 × 40 × 16 |
| Voxel size | 50.00 BU (50 cm) |
| Walkable voxels | 5,162 |
| Waypoints | 20 |
| Waypoint orientations | LOS-averaged (all 20) |
| Path points | 817 |
| Path length | 10,126 BU (101.3 m) |
| Camera height | 1.7 m |
| Frames | 1,012 |
| Duration | 84.3 s (1.4 min) |
| Min frame size | 95 KB |
| Max frame size | 738 KB |
| Median frame size | 371 KB |

**GIF** (1,012 frames, 12 fps):

![v38](assets/ai33_001_walkthrough_v38/AI33_001_280_walkthrough.gif)

---

## Comparison vs v37

| Metric | v37 | v38 |
|--------|-----|-----|
| Waypoint orientations | None (empty schedule) | LOS-averaged (20 waypoints) |
| Camera gaze mode | Travel direction (t+0.15) | Waypoint slerp interpolation |
| Median frame size | 475 KB | 371 KB |
| Frames | 1,012 | 1,012 |

The lower median frame size in v38 reflects the camera looking toward visible open areas rather than always facing forward — some frames now show longer vistas with less dense foreground geometry.

---

## Files

- **GIF**: `results/ai33_001_walkthrough_v38/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v38/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v38/frames/` (1,012 × 1280×720 PNG)
- **Intermediates**: `voxel_grid.npz`, `walkable.npz`, `path.npz`, `wp_schedule.json`
- **Run script**: `GenesisTools/run_ai33_v38.py`
