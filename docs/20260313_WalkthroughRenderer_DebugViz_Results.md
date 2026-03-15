# AI33_001 Walkthrough Debug Visualization Results

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)

---

# v29b — 360° Equirectangular + Full Voxel Grid (2026-03-14)

**Base**: v29 `.blend` re-rendered with panoramic camera.

## Result

| Metric | Value |
|--------|-------|
| Resolution | 2048×1024 |
| Projection | Equirectangular (360° sphere) |
| Render engine | Cycles GPU (CUDA) |
| Samples | 32 |
| Frames | 720 (all frames, no skip) |
| Frame size | ~2.5 MB |

**GIF** (all 720 frames):

![v29b](../results/ai33_001_walkthrough_v29b/walkthrough_v29b.gif)

## Files

- **GIF**: `results/ai33_001_walkthrough_v29b/walkthrough_v29b.gif`
- **Frames**: `results/ai33_001_walkthrough_v29b/frames/` (720 × 2048×1024 PNG)

---

# v29 — Full Voxel Grid Debug (Red + Blue + Green) (2026-03-14)

**Base**: v28 → v29 adds red spheres for solid (non-walkable) voxels.

## Goal

Show the entire voxel grid at a glance:
- **Red** spheres — solid voxels (geometry: walls, floor, furniture, ceiling)
- **Blue** spheres — walkable voxels (empty, floor below, sufficient clearance)
- **Green** spheres — farthest-point sampled waypoints

## Result

| Metric | Value |
|--------|-------|
| Resolution | 640×480 |
| Render engine | Cycles GPU |
| Samples | 32 |
| Frames | 720 |
| Solid voxels (red) | 873 |
| Walkable voxels (blue) | 145 |
| Waypoints (green) | 8 |

**GIF**:

![v29](../results/ai33_001_walkthrough_v29/walkthrough_v29.gif)

## Red Sphere Placement

Solid voxels are placed at `vz + cam_h` (grid center Z + camera height). Unlike blue spheres, solid voxels do not use `ray_cast` for floor snapping — they are inside geometry where ray casts are unreliable. Placing them at grid Z + cam_h gives a consistent "top-down heat map" at eye level showing where the camera cannot walk.

## Files

- **GIF**: `results/ai33_001_walkthrough_v29/walkthrough_v29.gif`
- **.blend**: `results/ai33_001_walkthrough_v29/AI33_001_280_walkthrough.blend`

---

# v28b — 360° Equirectangular (2026-03-14)

**Base**: v28 (same camera animation, same debug viz) → v28b (panoramic projection, higher resolution)

## Goal

Re-render the v28 walkthrough with a 360° equirectangular camera so the output can be viewed as a full spherical panorama (VR-compatible).

## Result

| Metric | Value |
|--------|-------|
| Resolution | 2048×1024 |
| Projection | Equirectangular (360° sphere) |
| Render engine | Cycles GPU (CUDA) |
| Samples | 32 |
| Frames | 720 |
| Frame size | 2.3–3.1 MB per frame |
| Total render time | ~25 min |

**GIF** (every 3rd frame, 0.5× scale):

![v28b](../results/ai33_001_walkthrough_v28b/walkthrough_v28b.gif)

## Notes

- EEVEE does not support panoramic/equirectangular cameras — Cycles required
- 32 samples sufficient for animation preview; 128+ for production quality
- First 58 frames rendered on CPU before GPU was enabled (same visual quality, slower)
- Camera trajectory and debug geometry identical to v28 — only projection and resolution changed

## Files

- **GIF**: `results/ai33_001_walkthrough_v28b/walkthrough_v28b.gif`
- **Frames**: `results/ai33_001_walkthrough_v28b/frames/` (720 × 2048×1024 PNG)

---

# v28 — Debug Viz at Camera Height (2026-03-14)

**Base**: v27 (debug viz at floor level) → v28 (debug viz at camera height)

## Goal

Add debug geometry to the walkthrough .blend file so the user can inspect:
1. Walkable voxel grid (blue spheres at voxel centers)
2. Farthest-point-sampled waypoints (green spheres)
3. Camera path (pink line passing through voxel grid)
4. Camera orientation per second (RGB arrow triplets: red=right, green=up, blue=forward)

**v28 change**: All debug objects placed at **camera height** (floor_z + cam_h), matching the actual camera trajectory. v27 had debug objects at floor level, making it impossible to visually verify camera-path alignment.

All debug objects must be visible in the .blend viewport AND not cause dark frames in rendered output.

## Result

| Metric | Value |
|--------|-------|
| Resolution | 640×480 |
| Mode | local (`local_area_ratio=0.3`) |
| Frames | 720 |
| Dark frames | **0** |
| Min frame size | 417KB |
| Max frame size | 663KB |
| Walkable voxels | 145 |
| Path points | 258 |
| Waypoints | 8 |
| Camera Z | ~170 BU |
| Voxel sphere Z | ~170.9 BU |
| Path Z | ~170 BU |

**GIF**: ![v28](../results/ai33_001_walkthrough_v28/AI33_001_280_walkthrough.gif)

## Approach: clip_start > debug sphere diameter

Instead of hiding debug objects from render (`hide_render`, `lc.exclude`), set the camera's `clip_start` (near clipping plane) larger than the biggest debug sphere diameter. The camera clips through nearby debug geometry naturally; distant debug objects are visible but tiny.

```
clip_start = wp_r * 2.0 * 1.5    (1.5x largest debug sphere diameter)
```

### Why not hide_render?

| Attempt | Method | Result |
|---------|--------|--------|
| pre1 | `visible_camera=True` + disable shadow/diffuse/glossy | 715/720 dark frames |
| pre2 | `col.hide_render=True` only | 715/720 dark frames (Cycles headless ignores collection-level flag) |
| pre3 | `col.hide_render=True` + `lc.exclude=True` + `obj.hide_render=True` | 0 dark frames, but objects invisible in .blend viewport |
| pre4 | `col.hide_render=True` + `obj.hide_render=True` (no lc.exclude) | 0 dark frames, but overengineered |
| **final** | **clip_start > sphere diameter** | **0 dark frames, fully visible in viewport** |

**Lesson**: In Blender Cycles headless mode, `Collection.hide_render=True` alone is NOT sufficient. The simplest solution is clip_start — no visibility flags needed.

## Debug Geometry Details

### Materials
- **Flat solid color** — `use_nodes=False`, `diffuse_color` only, no emission, no specular
- Previous versions used emission materials which caused the dark frame problem

### Sizes (relative to grid resolution `res`)
| Object | Radius/Thickness | Purpose |
|--------|-----------------|---------|
| Voxel sphere | `res * 0.12` | Blue, walkable voxel center |
| Waypoint sphere | `res * 0.25` | Green, farthest-point sample |
| Path line | `res * 0.05` thickness | Pink, camera-height path through voxels |
| Arrow shaft | `res * 0.015` thickness | RGB, camera orientation |
| Arrow head | `res * 0.05` radius cone | RGB, direction indicator |
| Arrow length | `res * 0.6` | Compact, clear direction |

### Coordinate alignment (v28)
- **Voxel spheres**: Per-voxel `ray_cast` downward to find real floor surface, then placed at `floor_z + cam_h`
- **Waypoint spheres**: Grid indices converted to world coords (`min_x + (ix+0.5)*res, ...`), then per-point `ray_cast` + `cam_h`
- **Path line**: Camera path points + `cam_h` offset — matches actual camera trajectory
- **Camera arrows**: Read directly from `cam_obj.matrix_world` — always correct

### z_correction (camera trajectory only)
Voxel grid has discrete Z levels. The walkable voxel bottom may not align exactly with the real floor surface. `z_correction = actual_floor_z - voxel_floor_z` compensates this offset. Applied to camera path_points for the actual camera trajectory. **NOT** applied to debug viz — debug viz uses per-point `ray_cast` instead.

### Per-point floor snap (`_snap_path_to_floor`)
For debug visualization only, each voxel/waypoint casts a ray downward from `vz + cam_h` to find the real floor surface. The debug sphere is then placed at `hit_z + cam_h`. This ensures debug objects match camera height even when the voxel grid Z doesn't align with the actual floor. The camera trajectory itself is **not modified** — it still uses constant z_correction.

## Blender Setup

### DebugViz Collection
All debug objects are placed in a `DebugViz` collection for organization. No hide flags — fully visible in both viewport and render.

### libSM.so.6 Dependency
Blender's `libMaterialXRenderGlsl.so` and `libusd_ms.so` indirectly depend on `libSM.so.6` and `libICE.so.6` (X11 session management). Missing in pure SSH environments.

**Fix**: `sudo apt-get install -y libsm6 libice6`

## Known Limitations

- **Grid coverage**: `local_area_ratio=0.3` means the voxel grid only covers ~30% of the scene (around camera position). Not a bug — by design for local mode.
- **Distant debug objects**: Small spheres/arrows visible in rendered frames as tiny dots. Visually negligible.

## v27 → v28 Changes

| Aspect | v27 | v28 |
|--------|-----|-----|
| Voxel sphere Z | Floor level (z_correction) | `ray_cast floor_z + cam_h` |
| Waypoint sphere Z | Floor level (world coords) | `ray_cast floor_z + cam_h` |
| Path line Z | Floor level (z_correction) | Camera path + `cam_h` |
| Waypoint coords | Grid indices (bug) | World coords (`min + (idx+0.5)*res`) |
| Camera trajectory | z_correction | z_correction (unchanged) |

## Files

- **GIF**: `results/ai33_001_walkthrough_v28/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v28/AI33_001_280_walkthrough.blend`
