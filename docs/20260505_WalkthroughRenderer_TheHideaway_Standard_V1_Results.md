# The Hideaway Walkthrough — Standard v1: Aerial Theta* + Workbench

**Scene**: `the_hideaway/the hideaway.blend` (108 MB)
**Date**: 2026-05-05
**Config**: `configs/standard_scene.json` — aerial, Theta* path, Workbench render
**Run host**: local Linux + pip bpy 4.5 + Windows Blender 4.5.7 LTS (Workbench)

---

## Pipeline

No Phase 1 (terrain snake fitting). Walkable voxels are built directly from
the blend geometry at 6.25 BU/voxel resolution. Aerial mode: all free voxels
(not occupied by geometry) are treated as walkable — the camera flies freely
through the full 3D volume.

---

## Voxel Grid + Walkable

| Parameter | Value |
|-----------|-------|
| Grid resolution | 6.25 BU/voxel |
| Grid size | 80 × 80 × 28 |
| Scene bounds (XYZ) | [−250, −250, −9.5] … [+250, +250, +163.0] BU |
| Walkable voxels (aerial) | **156 639** (all free voxels) |

---

## Path Planning — Held-Karp

| Parameter | Value |
|-----------|-------|
| Algorithm | Held-Karp exact open-path TSP |
| Waypoints | 20 (farthest-point sampling, seed 42) |
| Path connectivity | 26-connected BFS (Theta* planner) |
| Total path points | 1 977 |
| Path Z range | 6.1 … 162.4 BU (full vertical extent — aerial flythrough) |

---

## Render

| Parameter | Value |
|-----------|-------|
| Frames | 1 200 |
| FPS | 12 |
| Duration | 100 s |
| Resolution | 1 280 × 720 |
| Render engine | Workbench |
| Samples | 32 |
| Walk speed | 2.0 BU/s |
| Camera height | 1.7 BU |
| Approx time/frame | ~0.5 s |

---

## Walkthrough GIF

![the_hideaway standard v1 walkthrough](assets/the_hideaway_standard_v1/the_hideaway_standard_v1_walkthrough.gif)

*1 200 frames, 12 fps, 30.6 MB*

No combined GIF/MP4 — standard config has no `terrain_snake.npz` for the XY map background.

---

## Files

| Content | Path |
|---------|------|
| Voxel grid | `results/the_hideaway_standard_v1/voxel_grid.npz` |
| Walkable | `results/the_hideaway_standard_v1/walkable.npz` |
| Path | `results/the_hideaway_standard_v1/path.npz` |
| Run log | `results/the_hideaway_standard_v1/run.log` |
| Walkthrough blend | `results/the_hideaway_standard_v1/the hideaway_walkthrough.blend` |
| Walkthrough GIF | `docs/assets/the_hideaway_standard_v1/the_hideaway_standard_v1_walkthrough.gif` |
| Run script | `run_the_hideaway_standard_v1.py` |

---

## Notes

- **Aerial mode**: path Z range spans 6–162 BU, so the walkthrough is a full
  volumetric flythrough rather than a ground-level walk. The scene appears to
  be a large outdoor structure or landscape with significant vertical extent.
- **No terrain figures**: standard config has no TerrainSnake Phase 1, so
  figures 0–5 are not generated.
- **Workbench render**: fast (~0.5 s/frame) but no lighting simulation. For
  photorealistic output, switch `render_engine` to `CYCLES` in the config.
