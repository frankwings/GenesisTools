# AI33_001 Walkthrough — Future-Only Waypoint Gaze (v39)

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-04-29
**Commit**: `3a00ba0`

---

## Algorithm Changes vs v38

### Waypoint Gaze: Future-Only LOS

v38 averaged directions toward all other visible waypoints (both visited and unvisited). v39 restricts candidates to **only unvisited future waypoints** in tour order:

- Waypoint at tour position `k` → candidates = `tour[k+1 .. n-1]`
- Last waypoint (position `n-1`) → candidate = `tour[0]` (wraps to first)
- LOS ray_cast filters candidates to those with clear sightlines
- Average the visible directions (fallback to next waypoint if all occluded)

```python
if i < n - 1:
    candidates = list(range(i + 1, n))
else:
    candidates = [0]                    # last → wraps to first

visible = [j for j in candidates if _visible(i, j)]
targets = visible if visible else [candidates[0]]
```

This produces a forward-looking gaze that guides the viewer's attention toward where the camera is heading next, rather than averaging over the entire scene.

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
| Grid | 28 × 40 × 16, voxel 50.00 BU |
| Walkable voxels | 5,162 |
| Waypoints | 20 |
| Path points | 817 |
| Path length | 10,126 BU (101.3 m) |
| Camera height | 1.7 m |
| Frames | 1,012 |
| Duration | 84.3 s (1.4 min) |
| Min frame size | 143 KB |
| Max frame size | 853 KB |
| Median frame size | 421 KB |

**GIF** (1,012 frames, 12 fps):

![v39](assets/ai33_001_walkthrough_v39/AI33_001_280_walkthrough.gif)

---

## Comparison vs v38

| Metric | v38 | v39 |
|--------|-----|-----|
| Gaze candidates | All other waypoints | Future waypoints only |
| Last waypoint gaze | Toward all others | Wraps to first waypoint |
| Median frame size | 371 KB | 421 KB |

## Files

- **GIF**: `results/ai33_001_walkthrough_v39/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v39/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v39/frames/` (1,012 × 1280×720 PNG)
- **Run script**: `GenesisTools/run_ai33_v39.py`
