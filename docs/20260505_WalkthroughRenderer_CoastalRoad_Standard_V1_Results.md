# Coastal Road Walkthrough — Standard v1: Aerial Theta* + Workbench

**Scene**: `coastal_road/coastal road.blend`
**Date**: 2026-05-05
**Config**: `configs/standard_scene.json` — aerial, Theta* path, Workbench render
**Run host**: local Linux + pip bpy 4.5 + Windows Blender 4.5.7 LTS (Workbench)
**Commit**: `ac2deb9`

---

## Pipeline

No Phase 1 (terrain snake fitting).  Walkable voxels built directly from the
blend geometry at standard resolution.  Aerial mode: all free voxels (not
occupied by geometry) are walkable — the camera flies freely through the full
3D volume.

---

## Voxel Grid + Walkable

| Parameter | Value |
|-----------|-------|
| Grid resolution | 625.00 BU/voxel |
|  | *(standard max_grid_cells_xy=80 clamps the 50 000 BU scene to 625 BU/voxel)* |
| Grid size | 80 × 80 × 5 |
| Scene bounds (XY) | [−25 000, −25 000] … [+25 000, +25 000] BU |
| Scene bounds (Z) | −50 … +2 947 BU |
| Walkable voxels (aerial) | **24 984** (all free voxels) |

---

## Path Planning — Held-Karp

| Parameter | Value |
|-----------|-------|
| Algorithm | Held-Karp exact open-path TSP |
| Waypoints | 20 (farthest-point sampling, seed 42) |
| Path connectivity | 26-connected BFS |
| Total path points | 1 513 |
| Path Z range | 887.5 … 2 762.5 BU (high-altitude aerial flythrough) |
| Solve time | 8.0 s |

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

---

## Walkthrough GIF

![coastal_road standard v1 walkthrough](assets/coastal_road_standard_v1/coastal_road_standard_v1_walkthrough.gif)

*1 200 frames, 12 fps*

---

## Files

| Content | Path |
|---------|------|
| Voxel grid | `results/coastal_road_standard_v1/voxel_grid.npz` |
| Walkable | `results/coastal_road_standard_v1/walkable.npz` |
| Path | `results/coastal_road_standard_v1/path.npz` |
| Run log | `results/coastal_road_standard_v1/run.log` |
| Walkthrough blend | `results/coastal_road_standard_v1/coastal road_walkthrough.blend` |
| Walkthrough GIF | `docs/assets/coastal_road_standard_v1/coastal_road_standard_v1_walkthrough.gif` |
| Run script | `run_coastal_road_standard_v1.py` |

---

## Notes

- **Wrong config for this scene**: The coastal road scene spans 50 000 BU.
  The standard config caps the grid at 80 × 80 cells, yielding 625 BU/voxel —
  far too coarse to see roads, walls, or any detail.  The path flies at
  887–2 762 BU altitude, well above the terrain.  Use `terrain_scene.json`
  (see `coastal_road_terrain_v1`) for a meaningful ground-level walkthrough.
- **No terrain figures**: standard config has no TerrainSnake Phase 1.
- **Workbench render**: no lighting simulation; fast (~0.5 s/frame).
