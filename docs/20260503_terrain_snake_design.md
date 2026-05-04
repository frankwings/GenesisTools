# Terrain Snake Design

**Date**: 2026-05-03
**Status**: Approved

## Problem

Outdoor scenes (e.g. infinigen jungle, swamp) cannot use the existing indoor snake because
the indoor snake contracts from the convex hull inward to find enclosed interior space. Outdoor
scenes have no enclosed interior — the snake has nothing to converge on.

The global voxel flood-fill + floor filter also fails because:
- A 3600m scene at 20m/voxel produces 180×180 cells with sparse ray coverage
- Plants, trees, and fog meshes are marked as solid alongside the actual terrain
- The floor filter (solid below) becomes unreliable at coarse resolution

## Core Insight

CSF (Cloth Simulation Filter) and the indoor active contour are the **same energy model**,
just applied in a different direction:

| | Indoor snake | Terrain snake |
|---|---|---|
| Initial shape | Convex hull (outside scene) | Flat plane at z_max (above scene) |
| Motion | Contracts inward | Falls downward (-Z) |
| Internal energy | Laplacian smoothness | Laplacian smoothness (same) |
| External energy | Attract to nearest surface point | Constant gravity (-Z) |
| Stopping | Tight fit to interior walls | Hard floor per column (terrain hit) |
| Vegetation bypass | Bypasses small protrusions | Bridges over isolated tree hits |

The existing `Snake3D.step()` / `fit()` logic is reused directly.

---

## Data Flow

```
fit_terrain_contour.py
  Input:  blend_path, config
  Steps:
    1. Shoot downward rays (-Z) for every (ix, iy) grid column
    2. Collect all Z hits per column
    3. Global percentile filter: drop hits below env_sphere_percentile
       (env spheres, background domes sit far below real terrain)
    4. terrain_z_floor[ix, iy] = lowest remaining hit per column
       (NaN if no valid hit → column treated as unwalkable)
    5. Initialize TerrainSnake: flat grid at z_max
    6. snake.fit()
    7. Save terrain_snake.npz
  Output: terrain_snake.npz

terrain_snake.npz contents:
  heightmap  (nx, ny) float32  — final cloth Z per grid cell
  bounds     (6,)     float64  — (min_x, min_y, max_x, max_y, min_z, max_z)
  res        scalar   float64  — grid resolution in BU

voxel_grid.py  mode="terrain"
  Input:  config["terrain_npz"] path
  Steps:
    1. Load terrain_snake.npz
    2. For each (ix, iy) with valid heightmap value:
         iz = round((heightmap[ix,iy] - min_z) / res)
         candidates.add((ix, iy, iz))
  Output: VoxelGridData with mode="terrain", candidates = terrain voxels
          (one walkable voxel per column, following terrain surface)

Downstream pipeline: walkable → path_plan → camera_orient → camera_animate → render
(unchanged — terrain mode is transparent to all steps after voxel_grid)
```

---

## TerrainSnake Class

**File**: `genesis_tools/active_contour/terrain_snake.py`

```python
class TerrainSnake:
    def __init__(
        self,
        terrain_z_floor: np.ndarray,   # (nx, ny) float, NaN = no valid hit
        bounds: tuple,                  # (min_x, min_y, max_x, max_y, min_z, max_z)
        res: float,
        alpha: float = 0.5,            # Laplacian smoothness weight (rigidity)
        gravity: float = 0.1,          # downward force magnitude per step
        dt: float = 1.0,               # integration step size
        max_iterations: int = 200,
        convergence_threshold: float = 1e-3,
        plateau_window: int = 20,
        plateau_rtol: float = 0.02,
    )
```

**Vertices**: `(nx * ny, 3)` — XY fixed to grid cell centres, only Z is updated.

**Neighbors**: Regular 4-connected grid `(ix±1, iy), (ix, iy±1)` — vectorised, no
adjacency list needed. Boundary vertices have 2–3 neighbors.

**step()**:
```python
# Laplacian: pull each Z toward mean of 4 neighbors
lap_z = mean(neighbor_z) - current_z        # smoothness / rigidity

# Gravity: constant downward force
F_z = alpha * lap_z - gravity

# Update Z only (XY fixed)
vertices[:, 2] += dt * F_z

# Hard floor constraint: cloth cannot go below terrain hit
vertices[:, 2] = np.maximum(vertices[:, 2], terrain_z_floor.ravel())
# NaN columns: no constraint (cloth falls to min_z)
```

**fit()**: identical convergence logic to `Snake3D.fit()` — stop when
`max_displacement < convergence_threshold` OR displacement plateau detected.

**to_heightmap()**: reshape `vertices[:, 2]` → `(nx, ny)` float array.

---

## fit_terrain_contour.py

**File**: `genesis_tools/active_contour/fit_terrain_contour.py`

Interface:
```python
def fit_terrain_contour(
    blend_path: str,
    output_dir: str,
    grid_resolution: float = 5.0,      # metres per voxel (configurable)
    max_grid_cells_xy: int = 200,       # caps effective resolution
    env_sphere_percentile: float = 5.0, # Z hits below this % treated as env sphere
    ray_samples: int = 1,              # rays per grid cell (1 = centre, 3×3 = 9)
    alpha: float = 0.5,                # TerrainSnake rigidity
    gravity: float = 0.1,              # TerrainSnake gravity
    dt: float = 1.0,
    max_iterations: int = 200,
    convergence_threshold: float = 1e-3,
)
```

Uses bpy `scene.ray_cast` (same as existing pipeline — runs under bpy Python).

---

## Config Keys (walkthrough pipeline)

When `config["terrain_npz"]` is set, `voxel_grid.py` uses `mode="terrain"`:

```json
{
  "terrain_npz": "/path/to/terrain_snake.npz",

  "grid_resolution": 5.0,
  "max_grid_cells_xy": 200,
  "env_sphere_percentile": 5.0,
  "terrain_ray_samples": 1,

  "terrain_alpha": 0.5,
  "terrain_gravity": 0.1,
  "terrain_dt": 1.0,
  "terrain_max_iterations": 200,
  "terrain_convergence_threshold": 1e-3
}
```

All `terrain_*` keys are optional with the defaults shown above.
`terrain_npz` is analogous to `snake_npz` for indoor scenes.

---

## Files Changed / Created

| Action | File |
|--------|------|
| Create | `genesis_tools/active_contour/terrain_snake.py` |
| Create | `genesis_tools/active_contour/fit_terrain_contour.py` |
| Modify | `genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py` — add `mode="terrain"` branch |
| Create | `genesis_tools/active_contour/tests/test_terrain_snake.py` |

---

## What Is NOT in Scope

- Visualisation of the terrain heightmap (no Blender overlay for now)
- Multi-layer terrain (bridges, tunnels) — one walkable voxel per column only
- Integration with fine_adjust_path — terrain mode uses standard path_plan

