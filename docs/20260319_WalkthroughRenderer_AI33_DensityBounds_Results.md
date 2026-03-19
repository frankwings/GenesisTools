# AI33_001 Walkthrough — Density-Field Bounds + V2 Flood-Fill (v34)

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date**: 2026-03-19

---

## Algorithm Changes vs v33

### 1. Density-Field Scene Bounds (`_compute_scene_density_bounds`)

Previously the voxel grid was built from the raw scene AABB (all objects, including tiny/distant outliers). v34 replaces this with a density-field algorithm:

1. **Collect objects** — all mesh objects with world-space AABB volume + center
2. **Filter micro-objects** — discard objects below `median_volume × min_object_volume_fraction` (default 0.01)
3. **Build coarse 3D density grid** — each object contributes a Gaussian blob weighted by its volume: `density[i,j,k] += volume × exp(-dist² / (2σ²))` where `σ = object_size × sigma_factor`
4. **Flood-fill from camera position** — start at the density grid cell corresponding to the camera, expand 6-connected to neighbors with `density >= threshold × peak_density`
5. **Output AABB** — bounding box of flood-fill region + `density_padding_cells` margin

This naturally excludes small isolated objects (low density bump, not flood-filled) and distant outliers (not connected to camera cell).

| Config key | Default | Meaning |
|---|---|---|
| `density_grid_cells` | 20 | Coarse grid resolution (cells on longest axis) |
| `density_threshold` | 0.05 | Flood-fill cutoff as fraction of peak density |
| `density_sigma_factor` | 1.5 | Gaussian blob radius = `object_size × factor` |
| `min_object_volume_fraction` | 0.01 | Micro-object filter (fraction of median volume) |
| `density_padding_cells` | 2 | AABB outward padding after flood-fill |

### 2. V2-Only Walkable Detection

Standard mode removed. All runs now use V2:
- BFS flood-fill from camera voxel, **6-connectivity only** (no diagonals)
- All BFS-reachable free voxels = walkable (floor detection disabled — interface preserved for future use)

### 3. Edge Tube Debug Geometry

Voxel wireframes and hit markers now rendered as thick square tubes via a Geometry Nodes group (`EdgeToTube`), visible in Blender viewport. `show_render=False` keeps headless renders fast.

---

## Result

| Metric | Value |
|--------|-------|
| Resolution | 1280×720 |
| Render engine | WORKBENCH |
| Mode | local |
| Frames | 720 |
| Dark frames | **0** |
| Min frame size | 149 KB |
| Max frame size | 1,283 KB |
| Median frame size | 659 KB |
| Walkable voxels (cyan) | 30,839 |
| Solid voxels | 3,494 |
| Path points | 1,270 |
| Density bounds computation | 0.1 s |
| Voxel grid build | 5.3 s |
| Path planning | 0.3 s |
| Render | 859.2 s (~14.3 min) |
| Total | 869.0 s (~14.5 min) |

**GIF** (720 frames):

![v34](assets/ai33_001_walkthrough_v34/AI33_001_280_walkthrough.gif)

---

## Observations

- **30,839 cyan voxels** vs ~145 in v28/v29 — the V2 flood-fill from camera covers a much larger connected free-space volume than the old Standard floor-detection method
- Density bounds ran in **0.1 s** — negligible overhead
- No dark frames with WORKBENCH engine
- Edge tube GN modifier (`show_render=False`) does not affect render output

## Files

- **GIF**: `results/ai33_001_walkthrough_v34/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v34/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v34/frames/` (720 × 1280×720 PNG)
