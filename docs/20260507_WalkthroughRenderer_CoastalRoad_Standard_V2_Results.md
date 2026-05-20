# Coastal Road Walkthrough — Standard v2: Aerial Theta* + Cycles + OptiX

**Scene**: `coastal_road/coastal road.blend`
**Date**: 2026-05-07
**Config**: `configs/standard_scene.json` — aerial, Theta* path, Cycles render
**Run host**: local Linux + pip bpy 4.5 + Windows Blender 4.5.7 LTS (Cycles, OptiX)
**GPU**: NVIDIA GeForce RTX 5090
**Previous run**: [Standard v1 (2026-05-05)](20260505_WalkthroughRenderer_CoastalRoad_Standard_V1_Results.md)

---

## Changes from v1

| | v1 | v2 |
|---|---|---|
| Render engine | Workbench | **Cycles 64 spp** |
| Resolution | 1 280 × 720 | **640 × 480** |
| Denoiser | none | **OPTIX (GPU)** |
| Duration | 100 s (1 200 frames) | **83.3 s (1 000 frames)** |
| Avg frame time | ~1 s | **~3.3 s** |
| GIF size | ~90 MB | ~32 MB (lower res) |
| ScenePreprocessor | not run | scatter vegetation skipped — nothing changed |

v2 trades render speed for photoreal quality (Cycles + denoiser). The 3× slower
per-frame time vs Workbench is expected; Cycles computes full global illumination.

---

## Pipeline

Voxel grid, walkable, path, camera orient, and camera animate all reused from v1
(no geometry changes). Only the render step was re-run with new settings.

**ScenePreprocessor**: detected 1 scatter vegetation object (`Terrain`). Correctly
identified as `OBJECT`/`COLLECTION` scatter type — conversion skipped, vegetation preserved.

---

## Voxel Grid + Walkable (Global Mode, Aerial)

| Parameter | Value |
|-----------|-------|
| Grid resolution | 625.0 BU/voxel |
| Grid size | 80 × 80 × 5 |
| Scene bounds (XY) | [−25 000, −25 000] … [+25 000, +25 000] BU |
| Scene bounds (Z) | −50 … +2 947 BU |
| Walkable voxels (aerial) | **24 984** (all free voxels) |

*Reused from v1 — no changes.*

---

## Path Planning — Theta*

| Parameter | Value |
|-----------|-------|
| Algorithm | Theta* any-angle path |
| Waypoints | 20 (farthest-point sampling, seed 42) |
| Total path points | 1 513 |
| Path Z range | 887.5 … 2 762.5 BU (high-altitude aerial flythrough) |

*Reused from v1 — no changes.*

---

## Render

| Parameter | Value |
|-----------|-------|
| Frames | 1 000 |
| FPS | 12 |
| Duration | 83.3 s |
| Resolution | 640 × 480 |
| Render engine | Cycles |
| Samples | 64 spp + adaptive (threshold 0.01, min 4) |
| Denoiser | **OPTIX** (GPU-side, RTX 5090) |
| Avg frame time (steady-state) | **3.34 s** |
| Walk speed | 2.0 BU/s |
| Camera height | 1.7 BU |
| ScenePreprocessor | scatter vegetation skipped — nothing changed |

---

## Walkthrough GIF

![coastal road standard v2 walkthrough](assets/coastal_road_standard_v2/coastal_road_standard_v2_walkthrough.gif)

*1 000 frames, 12 fps, 640 × 480*

---

## Files

| Content | Path |
|---------|------|
| Voxel grid | `results/coastal_road_standard_v2/voxel_grid.npz` |
| Walkable | `results/coastal_road_standard_v2/walkable.npz` |
| Path | `results/coastal_road_standard_v2/path.npz` |
| Run log | `results/coastal_road_standard_v2/run.log` |
| Walkthrough blend | `results/coastal_road_standard_v2/coastal road_walkthrough.blend` |
| Walkthrough GIF | `docs/assets/coastal_road_standard_v2/coastal_road_standard_v2_walkthrough.gif` |
| Run script | `run_coastal_road_standard_v2.py` |

---

## Notes

- **Frame count fix**: v1 blend had `frame_end=1200` (built before the 83.4 s cap). The
  render step now derives `frame_end = max_duration_seconds × fps = 1000` directly from
  config, ignoring the blend's stored value. GIF rebuilt from first 1 000 frames.
- **Coastal road is faster than forest paths** (~3.3 s vs ~4.8 s per frame) because it
  has only one scatter particle object (`Terrain`) vs two in forest paths, meaning fewer
  BVH rebuilds per frame.
- **No combined GIF/MP4**: coastal road uses the standard (non-terrain) pipeline which
  does not generate a path-overlay composite.
