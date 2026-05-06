# The Hideaway Walkthrough — Standard v2: Finer Grid + Cycles

**Scene**: `the_hideaway/the hideaway.blend` (108 MB)
**Date**: 2026-05-05
**Config**: `configs/standard_scene.json` + overrides — finer grid, Cycles render
**Run host**: local Linux + pip bpy 4.5 + Windows Blender 4.5.7 LTS (Cycles)
**Commit**: `ac2deb9`

---

## Changes vs v1

| Issue in v1 | v2 Fix |
|-------------|--------|
| 6.25 BU/voxel grid — thin walls invisible to ray casting | Increased to 200×200×60 cells → 2.87 BU/voxel |
| Workbench render — no lighting | Switched to Cycles 640×480, 64 spp, OIDN |
| No path visualisation | Debug viz `.blend` generated |

Note: the wall-clipping root cause is ray casting missing thin geometry.
The finer grid reduces but does not eliminate this.  See v3 for the definitive
vertex-based fix.

---

## Voxel Grid + Walkable

| Parameter | Value |
|-----------|-------|
| Grid resolution | 2.87 BU/voxel |
| Grid size | 174 × 174 × 60 |
| Scene bounds (XY) | [−250, −250] … [+250, +250] BU |
| Scene bounds (Z) | −9.5 … +163.0 BU |
| Solid detection | Ray casting only (no vertex check) |
| Walkable voxels (aerial) | **1 645 069** (all free voxels) |

---

## Path Planning — Held-Karp

| Parameter | Value |
|-----------|-------|
| Algorithm | Held-Karp exact open-path TSP |
| Waypoints | 20 (farthest-point sampling, seed 42) |
| Path connectivity | 26-connected BFS |
| Total path points | 4 269 |
| Path Z range | 3.5 … 161.6 BU |
| TSP solve time | 8.8 s |
| BFS time | 106.6 s *(1.6M walkable voxels — large search space)* |

---

## Render

| Parameter | Value |
|-----------|-------|
| Frames | 1 200 |
| FPS | 12 |
| Duration | 100 s |
| Resolution | 640 × 480 |
| Render engine | Cycles |
| Samples | 64 |
| Denoiser | OpenImageDenoise |
| Walk speed | 2.0 BU/s |
| Camera height | 1.7 BU |

---

## Walkthrough GIF

![the_hideaway standard v2 walkthrough](assets/the_hideaway_standard_v2/the_hideaway_standard_v2_walkthrough.gif)

*1 200 frames, 12 fps*

---

## Files

| Content | Path |
|---------|------|
| Voxel grid | `results/the_hideaway_standard_v2/voxel_grid.npz` |
| Walkable | `results/the_hideaway_standard_v2/walkable.npz` |
| Path | `results/the_hideaway_standard_v2/path.npz` |
| Run log | `results/the_hideaway_standard_v2/run.log` |
| Walkthrough blend | `results/the_hideaway_standard_v2/the hideaway_walkthrough.blend` |
| Debug viz blend | `results/the_hideaway_standard_v2/the_hideaway_debug_viz.blend` |
| Walkthrough GIF | `docs/assets/the_hideaway_standard_v2/the_hideaway_standard_v2_walkthrough.gif` |
| Run script | `run_the_hideaway_standard_v2.py` |

---

## Notes

- **BFS bottleneck**: With 1.6 M walkable voxels the BFS path expansion took
  107 s — significantly slower than v1 (9 s at 153 k voxels).  The finer grid
  multiplied the search space by ~10×.
- **Still some wall clipping**: The finer grid catches more walls but ray
  casting can still miss faces that are exactly parallel to all three ray
  directions.  Vertex-based solid detection (v3) eliminates this entirely.
- **Debug viz blend**: A debug `.blend` with coloured voxel spheres (solid /
  walkable / path layers) was generated for visual inspection.
