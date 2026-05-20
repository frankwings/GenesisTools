# Forest Paths Walkthrough — Terrain v2: Particle-Aware Voxels + OptiX

**Scene**: `forest_paths/forest paths.blend` (334 MB)
**Date**: 2026-05-07
**Config**: `configs/terrain_scene.json` — TerrainSnake Phase 1+2, Held-Karp path, Cycles render
**Run host**: local Linux + pip bpy 4.5 + Windows Blender 4.5.7 LTS (Cycles, OptiX)
**GPU**: NVIDIA GeForce RTX 5090
**Previous run**: [Terrain v1 (2026-05-05)](20260505_WalkthroughRenderer_ForestPaths_Terrain_V1_Results.md)

---

## Changes from v1

| | v1 | v2 |
|---|---|---|
| Walkable candidates | 824 | **699** (−125 scatter-blocked) |
| Path points | 537 | 505 |
| ScenePreprocessor | converted 2 particle objs → mesh (vegetation erased) | scatter vegetation skipped — **vegetation preserved** |
| GPU backend | CUDA/user prefs | OptiX (forced) |
| Denoiser | OpenImageDenoise (CPU) | **OPTIX (GPU)** |
| Avg frame time | ~7.0 s | **~4.8 s** |
| MP4 | failed (odd dimensions) | **fixed** (macro_block_size=2) |

---

## Pipeline

Two-phase pipeline. Phase 1 reused cached `terrain_snake.npz`. Phase 2 rebuilt
from voxel_grid step with the new particle-aware terrain filter.

**ScenePreprocessor**: detected 2 scatter vegetation objects (`terrain`, `background`).
Previously these were erroneously converted to static mesh (erasing all vegetation).
The fix classifies `OBJECT`/`COLLECTION` particle render types as scatter and skips
conversion — geometry unchanged, vegetation visible.

---

## Voxel Grid + Walkable (Terrain Mode)

| Parameter | Value |
|-----------|-------|
| Grid resolution | 20.0 BU/voxel |
| Grid size | 30 × 30 × 2 |
| Scene bounds (XY) | [−300, −300] … [+300, +300] BU |
| Scene bounds (Z) | −3.8 … +27.0 BU |
| Raw terrain candidates | 824 |
| Scatter-blocked columns | **−125** (camera-eye column intersects tree instances) |
| Walkable candidates | **699** |

Particle filter: for each terrain column, checks all voxels in
`[iz, iz + camera_height_voxels]` against scatter instance bounding boxes.
Columns where the camera would clip through a tree trunk are removed.

---

## Path Planning — Held-Karp

| Parameter | Value |
|-----------|-------|
| Algorithm | Held-Karp exact open-path TSP |
| Waypoints | 20 (farthest-point sampling, seed 42) |
| Path connectivity | 26-connected BFS |
| Total path points | 505 |
| Path Z range | 13.3 … 30.6 BU |
| Solve time | 7.6 s |

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
| Avg frame time (steady-state) | **4.80 s** |
| Walk speed | 5.0 BU/s |
| Camera height | 1.7 BU |
| ScenePreprocessor | scatter vegetation skipped — nothing changed |

---

## Figures

### Figure 0 — Initial vs Final Snake

![figure_0](assets/forest_paths_terrain_v1/figure_0_initial_vs_final.png)

### Figure 1 — Top-Down Walkable + Path

![figure_1](assets/forest_paths_terrain_v1/figure_1_top_down.png)

### Figure 2 — Side Profiles

![figure_2](assets/forest_paths_terrain_v1/figure_2_side_profiles.png)

### Figure 3 — Bridging Demo

![figure_3](assets/forest_paths_terrain_v1/figure_3_bridging_demo.png)

### Figure 4 — Convergence

![figure_4](assets/forest_paths_terrain_v1/figure_4_convergence.png)

### Figure 5 — Walkthrough Path

![figure_5](assets/forest_paths_terrain_v1/figure_5_walkthrough_path.png)

---

## Walkthrough GIF

![forest_paths terrain v2 walkthrough](assets/forest_paths_terrain_v1/forest_paths_terrain_v1_walkthrough.gif)

*1 000 frames, 12 fps*

## Combined GIF (path overlay)

![forest_paths terrain v2 combined](assets/forest_paths_terrain_v1/forest_paths_terrain_v1_walkthrough_combined.gif)

---

## Files

| Content | Path |
|---------|------|
| Voxel grid | `results/forest_paths_terrain_v1/voxel_grid.npz` |
| Terrain snake | `results/forest_paths_terrain_v1/terrain_snake.npz` |
| Walkable | `results/forest_paths_terrain_v1/walkable.npz` |
| Path | `results/forest_paths_terrain_v1/path.npz` |
| Run log | `results/forest_paths_terrain_v1/run.log` |
| Walkthrough blend | `results/forest_paths_terrain_v1/forest paths_walkthrough.blend` |
| Walkthrough GIF | `docs/assets/forest_paths_terrain_v1/forest_paths_terrain_v1_walkthrough.gif` |
| Combined GIF | `docs/assets/forest_paths_terrain_v1/forest_paths_terrain_v1_walkthrough_combined.gif` |
| Combined MP4 | `docs/assets/forest_paths_terrain_v1/forest_paths_terrain_v1_walkthrough_combined.mp4` |
| Run script | `run_forest_paths_terrain_v1.py` |

---

## Notes

- **Vegetation fix**: v1 renders had all scatter vegetation (trees, bushes) silently erased
  by `bpy.ops.object.convert()` in background mode. v2 preserves the scene as-is.
- **Particle filter effect**: 125/824 columns (15%) removed — these are positions directly
  under tree canopy where the camera would clip through trunk/foliage at eye height.
- **BVH rebuild per frame**: scatter particle objects still trigger a per-frame BVH rebuild
  (depsgraph marks them dirty unconditionally). OptiX reduces each rebuild from ~5–6 s to
  ~1–2 s. Actual 64 spp render is ~0.3 s/frame; BVH remains the dominant cost.
