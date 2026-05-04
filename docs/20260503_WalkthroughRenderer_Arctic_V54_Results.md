# Arctic Midnight Sun Walkthrough — v54: TerrainSnake Outdoor Mode

**Scene**: `arctic_midnight_sun/fine_scene.blend` (917 MB, unit_scale=1.0, 1 BU = 1 m)
**Date**: 2026-05-03 (re-run with domain-fix patch, same date)
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
| Raw hit columns | 25,448 / 32,400 (79%) |
| Bridged columns (NaN in terrain_z_floor) | 6,952 (21%) — corners outside terrain disk |
| Valid heightmap columns | 25,448 / 32,400 (78%) — corners now excluded |
| Terrain Z floor (valid columns) | 0.15 … 119.99 m, dominant ~110 m |
| Snake cloth start height | terrain_z_floor + 1.7 m for valid columns |
| Snake iterations | 200 (hit max) |
| Output | `terrain_snake.npz` |

The arctic scene has a circular terrain disk at Z ≈ 110 m. The 4 corners of the 180×180
grid have no geometry (outside the disk) — those 6,952 columns produce NaN in
`terrain_z_floor` (raw max ray-hit) and are **excluded from the walkable set** (see
domain-fix below). Valid columns start the cloth at `terrain_z_floor + 1.7 m`; NaN columns
(corners) start at `z_max = 130 m` and participate only in Laplacian smoothing.

---

## Phase 2: Walkthrough Pipeline

| Step | Output |
|------|--------|
| voxel_grid (terrain mode) | **25,448 walkable voxels** — terrain-disk columns only (corners excluded), 180×180×32 grid |
| walkable | 25,448 ground voxels (no flood-fill; terrain_z_floor NaN mask applied) |
| path | 2,753 path points, 20 waypoints, spanning ±989 m XY |
| camera_animate | 1,440 frames @ 12 fps = 120 s walkthrough |
| render | WORKBENCH, 1280×720, ~0.28 s/frame |

**Camera**: height 1.7 m above ground (eye Z ≈ 111.7 m), lookahead gaze
(`waypoint_gaze_mode="free"`), walk speed 5.0 m/s.

The path covers a smaller XY extent (±989 m vs ±1790 m in the pre-fix run) because
walkable voxels outside the terrain disk are now correctly excluded — the path can only
navigate through the terrain disk, not through the void beyond it.

---

## GIF

![arctic v1 walkthrough](assets/arctic_midnight_sun_v1/arctic_v1_walkthrough.gif)

*(120 frames sampled every 12th frame, 83 ms/frame ≈ 12 fps)*

---

## TerrainSnake Visualizations

### Figure 0 — Initial Cloth vs Final Cloth

Equivalent of the indoor Snake3D "initial hull (green) → final snake (blue)" figure.

![figure 0](assets/arctic_midnight_sun_v1/figure_0_initial_vs_final.png)

- **Left (XY top)**: Blue dots = columns with direct ray-cast hits (circular terrain disk).
  Orange dots = corners bridged by Laplacian (no geometry, NaN hit).
- **Centre/Right (XZ / YZ front+side)**: Orange line = initial cloth, flat at z_max=130 m.
  Blue line = final cloth, settled at terrain Z=110 m. Arrow shows the 20 m free-fall
  (200 steps at gravity=0.1 m/step). Both the initial and final cloths are perfectly flat
  — arctic tundra has no relief.

---

### Figure 1 — Top-Down: Ray Hits vs Snake Heightmap vs Bridged Columns

![figure 1](assets/arctic_midnight_sun_v1/figure_1_top_down.png)

- **Left**: Raw ray-cast coverage — green = valid hit, red = no hit. The terrain is a circular
  disk; the 4 grid corners have no geometry.
- **Centre**: Snake heightmap (uniform yellow = flat Z≈110 m) + camera path (red) + waypoints
  (yellow dots). Path tours the full ±1790 m XY extent.
- **Right**: Bridged columns (orange) — the 6,952 corner cells where the Laplacian filled in
  the NaN gaps left by missing ray hits.

---

### Figure 2 — Side Profiles: Hits vs Cloth vs Camera Eye

![figure 2](assets/arctic_midnight_sun_v1/figure_2_side_profiles.png)

Orange = raw ray hits, blue = snake cloth Z, red = camera eye (cloth + 1.7 m).
Terrain is perfectly flat — all three layers sit on the same horizontal line at Z≈110 m.
Camera eye is consistently 1.7 m above the terrain surface across the full ±1790 m sweep.

---

### Figure 3 — How the Cloth Bridges Vegetation Gaps (synthetic demo)

![figure 3](assets/arctic_midnight_sun_v1/figure_3_bridging_demo.png)

Synthetic 2-D profile demonstrating the core snake behaviour on a scene with varied terrain
and 3 vegetation patches (green shading) where downward rays return no hit:

- **Orange dots**: ray-cast hits (sampling points) — only outside the gap patches.
- **Blue gradient lines**: cloth evolution from iter 0 (flat at top) through iters 5, 20, 80
  as gravity pulls it down toward the floor constraint.
- **Solid blue**: final converged cloth — tracks the terrain on hit columns, smoothly
  interpolates across the gaps using Laplacian energy.
- **Red dashed**: camera eye = cloth + 1.7 m, always just above the surface.

The key relationship: **sampling points are hard floor constraints; the snake cloth is pulled
toward them by gravity and held by the floor, while Laplacian smoothness bridges any gaps**.

---

### Figure 4 — Convergence

![figure 4](assets/arctic_midnight_sun_v1/figure_4_convergence.png)

Max displacement is constant at 0.1 m/iter throughout all 200 iterations — the cloth is in
free-fall the entire run. This is expected: the terrain floor is at Z=110 m, the cloth starts
at Z=130 m (z_max), and with `gravity=0.1, dt=1.0` it takes exactly 200 steps to fall 20 m.
The floor is reached right at the iteration limit.

**Implication**: for this scene, `max_iterations=200` is barely sufficient. Setting it to 400
would give the cloth time to settle after reaching the floor. The plateau guard correctly
suppresses a false early-stop during the constant-velocity free-fall phase.

---

## How the Snake Contour Becomes Walkable Voxels

**Terrain mode** (this scene) and **indoor snake mode** use different strategies:

### Terrain mode (`terrain_npz` set)

No ray-cast into the scene at all. The heightmap already encodes the ground surface:

```
for each (ix, iy) column:
    iz = int((heightmap[ix, iy] - min_z) / res)   # floor division → voxel that contains terrain Z
    → one candidate voxel (ix, iy, iz) per column
```

`walkable.py` uses these candidates directly as the walkable set — no flood-fill, no floor
filter. The snake already found the surface; there is no solid array to check against.

### Indoor snake mode (`snake_npz` set)

The fitted snake mesh is loaded and turned into a BVHTree. For every voxel centre in the
snake's AABB grid, a +X ray is fired through the BVHTree:

```
ray hits snake surface N times:
  N odd  → voxel centre is inside the snake  → candidate
  N even → voxel centre is outside           → discard
```

`walkable.py` then applies the floor filter: keep only candidates that have a solid
(scene-geometry) voxel directly below them — i.e. standing on a floor, not floating
inside empty space.

---

## Bugs Fixed During This Run

Seven bugs were discovered and fixed across two sub-runs:

### Original four fixes

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

### Domain-fix patch (same-day re-run)

**5. `min(valid hits)` in terrain floor detection picks env-sphere inner surface** —
`fit_terrain_contour.py` took the *minimum* of all ray-cast hits above the p5 threshold.
For the arctic scene the env-sphere inner-surface produces hits at ~−116 m that lie just
above the −116.36 m p5 cutoff, so `min(valid)` returned −116 m rather than the
terrain at +110 m. The cloth converged underground, giving a correct GIF only because the
cloth had not reached the actual geometry floor in the 200-iteration budget.
Fix: change `min(valid)` to `max(valid)` — the *topmost* valid hit is the first surface
seen from above and is the correct terrain surface for outdoor scenes.

**6. NaN-domain columns (outside terrain disk) became walkable voxels** — The Laplacian
bridged the 6,952 corner columns (outside the circular terrain disk, NaN in
`terrain_z_floor`) toward valid neighbors, giving them a finite cloth height. The terrain
voxel mapper then created walkable voxels for those columns — camera could walk through
empty space beyond the terrain boundary.
Fix: `_build_terrain_candidates` in `voxel_grid.py` loads `terrain_z_floor` from the npz
and skips any column where it is NaN, regardless of the interpolated heightmap value.

**7. Convergence tracking included NaN columns → no early-stop** — `TerrainSnake.step()`
computed `max_displacement` over *all* vertices including NaN corner columns (which start
at z_max and fall slowly under gravity). This masked valid-column convergence and prevented
early termination even after valid columns had fully settled.
Fix: compute `max_d` only over `valid_mask` columns; add `start_height` parameter so valid
columns begin at `terrain_z_floor + start_height` (just above the terrain surface) rather
than at z_max, reducing their fall distance from ~20 m to ~1.7 m.

---

## Files

| Content | Path |
|---------|------|
| GIF | `docs/assets/arctic_midnight_sun_v1/arctic_v1_walkthrough.gif` |
| Fig 0 — initial vs final cloth | `docs/assets/arctic_midnight_sun_v1/figure_0_initial_vs_final.png` |
| Fig 1 — top-down | `docs/assets/arctic_midnight_sun_v1/figure_1_top_down.png` |
| Fig 2 — side profiles | `docs/assets/arctic_midnight_sun_v1/figure_2_side_profiles.png` |
| Fig 3 — bridging demo | `docs/assets/arctic_midnight_sun_v1/figure_3_bridging_demo.png` |
| Fig 4 — convergence | `docs/assets/arctic_midnight_sun_v1/figure_4_convergence.png` |
| Viz script | `visualize_terrain_snake_arctic.py` |
| Run script | `run_arctic_midnight_sun_v1.py` |
| Terrain NPZ | `results/arctic_midnight_sun_v1/terrain_snake.npz` |
| Walkthrough blend | `results/arctic_midnight_sun_v1/fine_scene_walkthrough.blend` |
| Frames (1440) | `results/arctic_midnight_sun_v1/frames/` |
