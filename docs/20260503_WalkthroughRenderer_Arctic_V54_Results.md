# Arctic Midnight Sun Walkthrough — v54: TerrainSnake Outdoor Mode

**Scene**: `arctic_midnight_sun/fine_scene.blend` (917 MB, unit_scale=1.0, 1 BU = 1 m)
**Date**: 2026-05-03
**Render**: Windows Blender 4.5 + WORKBENCH (D3D GPU, ~0.28s/frame)

---

## What's New: TerrainSnake

This is the first outdoor scene walkthrough using the new `TerrainSnake` mode. Previous
walkthroughs (v1–v53) used the indoor snake: convex-hull → contract → flood-fill, which
requires an enclosed interior. Outdoor scenes (arctic, jungle, swamp) have no enclosed
interior — the indoor snake cannot converge.

The terrain-snake is a cloth-simulation approach analogous to CSF (Cloth Simulation Filter)
for lidar ground extraction:

- Flat grid cloth initialised at `z_max` above the entire scene
- Falls under constant gravity (−Z)
- Laplacian smoothness bridges gaps (vegetation, sparse ray hits)
- Per-column hard floor: downward ray-cast hits stop the cloth

The result is one walkable voxel per grid column — one ground-level cell for the camera to
travel through.

---

## Phase 1: Terrain Snake Fitting

**Script**: `run_arctic_midnight_sun_v1.py` → runs `fit_terrain_contour.py` under system Blender

| Parameter | Value |
|-----------|-------|
| Grid resolution | 20.0 m/voxel |
| Grid size | 180 × 180 cells |
| Scene XY span | ±1800 m (3600 m × 3600 m) |
| Z range | −500 m … +130 m |
| env-sphere percentile | p5 = −116.36 m (env-sphere dome filtered) |
| Valid terrain columns | 32,400 / 32,400 (100%) |
| Terrain Z (all columns) | 110.02 m |
| Snake iterations | 200 (hit max — cloth at flat floor) |
| Output | `terrain_snake.npz` |

The arctic scene has a perfectly flat ground plane at Z ≈ 110 m. All downward rays from
32,400 grid columns hit the same elevation — consistent with arctic tundra geometry.

---

## Phase 2: Walkthrough Pipeline

| Step | Output |
|------|--------|
| voxel_grid (terrain mode) | 32,400 walkable voxels — one per column, 180×180×32 grid |
| walkable | 32,400 ground voxels (no flood-fill; snake found surface directly) |
| path | 5,729 path points, 20 waypoints, spanning ±1790 m XY |
| camera_animate | 1,440 frames @ 12 fps = 120 s walkthrough |
| render | WORKBENCH, 1280×720, ~0.28 s/frame |

**Camera**: height 1.7 m above ground, lookahead gaze (`waypoint_gaze_mode="free"`),
walk speed 5.0 m/s.

---

## GIF

![arctic v1 walkthrough](assets/arctic_midnight_sun_v1/arctic_v1_walkthrough.gif)

*(120 frames sampled every 12th frame, 83 ms/frame ≈ 12 fps)*

---

## Bugs Fixed During This Run

Four bugs were discovered and fixed during this run:

**1. scipy import via `__init__.py`** — Importing `TerrainSnake` through the
`genesis_tools.active_contour` package triggers `__init__.py` which imports `snake_3d`,
which requires `scipy`. Blender's bundled Python does not have scipy.
Fix: load `terrain_snake.py` directly via `importlib.util.spec_from_file_location`,
bypassing `__init__.py`.

**2. Blender exits 0 on Python errors** — By default, Blender exits with code 0 even when
a `--python` script fails. `subprocess.run(check=True)` did not detect Phase 1 failure.
Fix: add `--python-exit-code 1` to the Blender command.

**3. `sys.argv` argparse confusion** — When Blender runs a script with
`--python script.py -- --arg value`, `sys.argv` contains `['script.py', '--', '--arg', 'value']`.
`argparse.parse_args()` sees the bare `--` and misinterprets the remaining arguments.
Fix: strip everything before `--` before passing to `parse_args`.

**4. `round()` in terrain voxel mapping → camera above scene** — `_build_terrain_candidates`
used `iz = int(round((z - min_z) / res))`. For arctic terrain at Z=110 m with res=20 m,
this rounded 30.5 → iz=31, placing the walkable voxel at the very top of the scene
(center Z=130 m = max_z). The camera at max_z sees only sky — white empty frames.
Fix: use `int(...)` (floor division). iz=30 has center Z=110 m; camera eye at 111.7 m,
1.7 m above the terrain surface.

---

## Files

| Content | Path |
|---------|------|
| GIF | `docs/assets/arctic_midnight_sun_v1/arctic_v1_walkthrough.gif` |
| Run script | `run_arctic_midnight_sun_v1.py` |
| Terrain NPZ | `results/arctic_midnight_sun_v1/terrain_snake.npz` |
| Walkthrough blend | `results/arctic_midnight_sun_v1/fine_scene_walkthrough.blend` |
| Frames (1440) | `results/arctic_midnight_sun_v1/frames/` |
