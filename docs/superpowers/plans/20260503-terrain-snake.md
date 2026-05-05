# Terrain Snake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a terrain-snake mode to the walkthrough pipeline so outdoor scenes (jungle, swamp, etc.) get a camera-walkable ground surface computed by cloth simulation falling from above.

**Architecture:** A new `TerrainSnake` class (pure NumPy, no bpy) runs a cloth-simulation energy loop: flat grid at z_max falls under gravity, Laplacian smoothness bridges vegetation, per-column hard floors from downward ray-casting stop the cloth at terrain hits. `fit_terrain_contour.py` (bpy-required) casts rays and saves `terrain_snake.npz`. `voxel_grid.py` gets a new `_build_terrain_candidates()` helper that reads the npz and produces one walkable voxel per column. `walkable.py` gets a terrain branch that uses those candidates directly (no flood fill / floor filter needed — the snake already found the surface).

**Tech Stack:** NumPy, bpy (only for ray-casting step), existing Snake3D energy conventions, pytest.

---

## File Map

| Action | File |
|--------|------|
| Create | `genesis_tools/active_contour/terrain_snake.py` |
| Create | `genesis_tools/active_contour/fit_terrain_contour.py` |
| Modify | `genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py` |
| Modify | `genesis_tools/walkthrough_renderer/pipeline/walkable.py` |
| Modify | `genesis_tools/active_contour/__init__.py` |
| Create | `genesis_tools/active_contour/tests/test_terrain_snake.py` |
| Modify | `genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py` |
| Create | `run_jungle_swamp_v3.py` |

---

## Task 1: TerrainSnake class

**Files:**
- Create: `genesis_tools/active_contour/terrain_snake.py`
- Test: `genesis_tools/active_contour/tests/test_terrain_snake.py`

- [ ] **Step 1: Write the failing tests**

```python
# genesis_tools/active_contour/tests/test_terrain_snake.py
"""Unit tests for TerrainSnake — pure NumPy, no bpy dependency."""
import numpy as np
import pytest

from genesis_tools.active_contour.terrain_snake import TerrainSnake


BOUNDS = (0.0, 0.0, 10.0, 10.0, 0.0, 20.0)  # (min_x, min_y, max_x, max_y, min_z, max_z)
RES = 1.0


def _flat_floor(nx: int, ny: int, z: float) -> np.ndarray:
    return np.full((nx, ny), z, dtype=np.float64)


def _make(floor, bounds=BOUNDS, res=RES, **kw):
    return TerrainSnake(terrain_z_floor=floor, bounds=bounds, res=res, **kw)


class TestInit:
    def test_vertices_shape(self):
        snake = _make(_flat_floor(4, 5, 2.0))
        assert snake.vertices.shape == (4 * 5, 3)

    def test_initial_z_at_max_z(self):
        snake = _make(_flat_floor(4, 5, 2.0))
        assert np.allclose(snake.vertices[:, 2], 20.0)

    def test_xy_fixed_to_grid_centres(self):
        floor = _flat_floor(2, 3, 0.0)
        bounds = (0.0, 0.0, 2.0, 3.0, 0.0, 10.0)
        snake = TerrainSnake(floor, bounds=bounds, res=1.0)
        xs = set(np.round(snake.vertices[:, 0], 6))
        ys = set(np.round(snake.vertices[:, 1], 6))
        assert xs == {0.5, 1.5}
        assert ys == {0.5, 1.5, 2.5}

    def test_iterations_run_starts_zero(self):
        assert _make(_flat_floor(3, 3, 1.0)).iterations_run == 0


class TestStep:
    def test_gravity_drops_z(self):
        """No floor (NaN everywhere) + zero alpha → pure gravity drop."""
        floor = np.full((3, 3), np.nan, dtype=np.float64)
        snake = _make(floor, gravity=0.1, dt=1.0, alpha=0.0)
        z_before = snake.vertices[:, 2].copy()
        snake.step()
        assert np.all(snake.vertices[:, 2] < z_before)

    def test_floor_constraint_holds(self):
        """Z cannot go below terrain_z_floor."""
        floor = _flat_floor(4, 4, 15.0)
        snake = _make(floor, gravity=1.0, dt=1.0, alpha=0.0, max_iterations=100)
        for _ in range(50):
            snake.step()
        assert np.all(snake.vertices[:, 2] >= 15.0 - 1e-9)

    def test_nan_columns_clipped_to_min_z(self):
        """NaN columns (no terrain hit) are clipped to min_z, never NaN."""
        floor = np.full((3, 3), np.nan, dtype=np.float64)
        bounds = (0.0, 0.0, 3.0, 3.0, 5.0, 20.0)
        snake = TerrainSnake(floor, bounds=bounds, res=1.0,
                             gravity=1.0, dt=1.0, alpha=0.0, max_iterations=200)
        snake.fit()
        assert not np.any(np.isnan(snake.vertices[:, 2]))
        assert np.all(snake.vertices[:, 2] >= 5.0 - 1e-9)

    def test_max_displacement_returned_nonneg(self):
        snake = _make(_flat_floor(3, 3, 1.0))
        d = snake.step()
        assert isinstance(d, float) and d >= 0.0

    def test_iterations_count_increments(self):
        snake = _make(_flat_floor(3, 3, 1.0))
        snake.step(); snake.step()
        assert snake.iterations_run == 2


class TestFit:
    def test_runs_and_returns_self(self):
        snake = _make(_flat_floor(3, 3, 1.0), max_iterations=10)
        assert snake.fit() is snake

    def test_iterations_run_positive(self):
        snake = _make(_flat_floor(5, 5, 3.0), max_iterations=50)
        snake.fit()
        assert snake.iterations_run > 0

    def test_flat_floor_converges_at_floor_z(self):
        """Flat floor → cloth settles at that Z level."""
        floor = _flat_floor(5, 5, 7.0)
        bounds = (0.0, 0.0, 5.0, 5.0, 0.0, 20.0)
        snake = TerrainSnake(floor, bounds=bounds, res=1.0,
                             alpha=0.5, gravity=0.1, dt=1.0, max_iterations=300)
        snake.fit()
        assert np.allclose(snake.to_heightmap(), 7.0, atol=0.5)

    def test_displacements_recorded(self):
        snake = _make(_flat_floor(4, 4, 2.0), max_iterations=20)
        snake.fit()
        assert len(snake.max_displacements) > 0


class TestToHeightmap:
    def test_shape(self):
        hm = _make(_flat_floor(6, 8, 0.0)).to_heightmap()
        assert hm.shape == (6, 8)

    def test_all_values_at_least_min_z(self):
        floor = np.full((4, 4), np.nan, dtype=np.float64)
        bounds = (0.0, 0.0, 4.0, 4.0, 2.0, 20.0)
        snake = TerrainSnake(floor, bounds=bounds, res=1.0, max_iterations=50)
        snake.fit()
        assert np.all(snake.to_heightmap() >= 2.0 - 1e-9)

    def test_returns_copy(self):
        snake = _make(_flat_floor(3, 3, 5.0))
        hm = snake.to_heightmap()
        hm[:] = 0.0
        # Modifying the returned array must not affect snake state
        assert not np.all(snake.to_heightmap() == 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/active_contour/tests/test_terrain_snake.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'genesis_tools.active_contour.terrain_snake'`

- [ ] **Step 3: Write TerrainSnake implementation**

```python
# genesis_tools/active_contour/terrain_snake.py
from __future__ import annotations
import numpy as np


class TerrainSnake:
    """Cloth-simulation snake for outdoor terrain surface detection.

    Starts as a flat grid at z_max, falls under gravity (-Z), Laplacian
    smoothness bridges vegetation gaps, per-column hard floors stop descent.
    XY coordinates are fixed to grid cell centres; only Z is updated.
    """

    def __init__(
        self,
        terrain_z_floor: np.ndarray,   # (nx, ny) float64, NaN = no valid hit
        bounds: tuple,                  # (min_x, min_y, max_x, max_y, min_z, max_z)
        res: float,
        alpha: float = 0.5,            # Laplacian smoothness weight
        gravity: float = 0.1,          # downward force per step
        dt: float = 1.0,               # integration step size
        max_iterations: int = 200,
        convergence_threshold: float = 1e-3,
        plateau_window: int = 20,
        plateau_rtol: float = 0.02,
    ) -> None:
        self.terrain_z_floor = np.asarray(terrain_z_floor, dtype=np.float64)
        self.bounds = bounds
        self.res = float(res)
        self.alpha = alpha
        self.gravity = gravity
        self.dt = dt
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold
        self.plateau_window = plateau_window
        self.plateau_rtol = plateau_rtol

        self.nx, self.ny = self.terrain_z_floor.shape
        min_x, min_y, max_x, max_y, min_z, max_z = bounds

        xs = min_x + (np.arange(self.nx) + 0.5) * self.res
        ys = min_y + (np.arange(self.ny) + 0.5) * self.res
        XX, YY = np.meshgrid(xs, ys, indexing="ij")
        z_init = np.full((self.nx, self.ny), float(max_z), dtype=np.float64)

        # vertices: (nx*ny, 3) — XY fixed, only Z updated
        self.vertices = np.column_stack([XX.ravel(), YY.ravel(), z_init.ravel()])
        self.min_z = float(min_z)
        self.max_z = float(max_z)
        self.max_displacements: list[float] = []
        self.iterations_run: int = 0

    def _laplacian_force_z(self) -> np.ndarray:
        """Pull each Z toward the mean of its 4 grid neighbours."""
        Z = self.vertices[:, 2].reshape(self.nx, self.ny)
        lap = np.zeros_like(Z)
        n = np.zeros_like(Z)
        lap[:, :-1] += Z[:, 1:];  n[:, :-1] += 1
        lap[:, 1:]  += Z[:, :-1]; n[:, 1:]  += 1
        lap[:-1, :] += Z[1:, :];  n[:-1, :] += 1
        lap[1:, :]  += Z[:-1, :]; n[1:, :]  += 1
        with np.errstate(invalid="ignore"):
            mean_nbrs = np.where(n > 0, lap / n, Z)
        return (mean_nbrs - Z).ravel()

    def step(self) -> float:
        """One iteration. Returns max absolute Z displacement."""
        lap_z = self._laplacian_force_z()
        F_z = self.alpha * lap_z - self.gravity
        delta_z = self.dt * F_z
        self.vertices[:, 2] += delta_z

        # Hard floor: cloth cannot pass through terrain
        floor = self.terrain_z_floor.ravel()
        valid = ~np.isnan(floor)
        self.vertices[valid, 2] = np.maximum(self.vertices[valid, 2], floor[valid])
        # Safety lower bound for NaN (sky-only) columns
        self.vertices[:, 2] = np.maximum(self.vertices[:, 2], self.min_z)

        self.iterations_run += 1
        max_d = float(np.max(np.abs(delta_z)))
        self.max_displacements.append(max_d)
        return max_d

    def fit(self) -> "TerrainSnake":
        """Run until convergence or plateau. Returns self."""
        for _ in range(self.max_iterations):
            max_d = self.step()
            if max_d < self.convergence_threshold:
                break
            pw = self.plateau_window
            if len(self.max_displacements) >= pw * 2:
                w = self.max_displacements
                older = sum(w[-pw * 2:-pw]) / pw
                recent = sum(w[-pw:]) / pw
                if abs(older - recent) / (older + 1e-12) < self.plateau_rtol:
                    break
        return self

    def to_heightmap(self) -> np.ndarray:
        """Return (nx, ny) float64 array of final cloth Z per cell."""
        return self.vertices[:, 2].reshape(self.nx, self.ny).copy()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/active_contour/tests/test_terrain_snake.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add genesis_tools/active_contour/terrain_snake.py \
        genesis_tools/active_contour/tests/test_terrain_snake.py
git commit -m "feat: TerrainSnake cloth-simulation for outdoor terrain surface"
```

---

## Task 2: fit_terrain_contour.py

**Files:**
- Create: `genesis_tools/active_contour/fit_terrain_contour.py`

No pure-Python unit tests — requires bpy ray_cast. Integration verified by running on a blend file.

- [ ] **Step 1: Write the implementation**

```python
# genesis_tools/active_contour/fit_terrain_contour.py
"""Fit a TerrainSnake to a Blender outdoor scene and save terrain_snake.npz.

Must be run under bpy Python (uses scene.ray_cast).

Usage (standalone bpy script)
-----
    blender --background scene.blend --python fit_terrain_contour.py -- \\
        --output-dir /path/to/output [--grid-resolution 5.0] ...

Or call fit_terrain_contour() from another bpy Python script:

    from genesis_tools.active_contour.fit_terrain_contour import fit_terrain_contour
    path = fit_terrain_contour(blend_path, output_dir, grid_resolution=5.0)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from genesis_tools.active_contour.terrain_snake import TerrainSnake


def fit_terrain_contour(
    blend_path: str,
    output_dir: str,
    grid_resolution: float = 5.0,
    max_grid_cells_xy: int = 200,
    env_sphere_percentile: float = 5.0,
    ray_samples: int = 1,
    alpha: float = 0.5,
    gravity: float = 0.1,
    dt: float = 1.0,
    max_iterations: int = 200,
    convergence_threshold: float = 1e-3,
) -> str:
    """Fit terrain snake to blend_path, save terrain_snake.npz, return output path."""
    import bpy
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=blend_path)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    unit_scale = bpy.context.scene.unit_settings.scale_length or 1.0

    # --- Scene bounds ---
    xs, ys, zs = [], [], []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    if not xs:
        raise RuntimeError("No mesh objects in scene.")
    min_x, min_y = min(xs), min(ys)
    max_x, max_y = max(xs), max(ys)
    min_z, max_z = min(zs), max(zs)

    # --- Grid resolution ---
    res_bu = grid_resolution / unit_scale
    span_x, span_y = max_x - min_x, max_y - min_y
    res_bu = max(res_bu, span_x / max_grid_cells_xy, span_y / max_grid_cells_xy)
    nx = max(1, int(math.ceil(span_x / res_bu)))
    ny = max(1, int(math.ceil(span_y / res_bu)))
    print(f"[TerrainSnake] Grid {nx}×{ny}, res={res_bu:.2f} BU — casting rays …")

    # --- Step 1: downward ray-cast per column ---
    ray_span_z = (max_z - min_z) + 4.0
    step_past = 0.05
    all_hits_flat: list[float] = []
    column_hits: dict[tuple, list[float]] = {}

    for ix in range(nx):
        for iy in range(ny):
            hits_z: list[float] = []
            for sx in range(ray_samples):
                for sy in range(ray_samples):
                    x = min_x + (ix + (sx + 0.5) / ray_samples) * res_bu
                    y = min_y + (iy + (sy + 0.5) / ray_samples) * res_bu
                    cur = Vector((x, y, max_z + 2.0))
                    direction = Vector((0.0, 0.0, -1.0))
                    rem = ray_span_z
                    while rem > step_past:
                        hit, loc, _n, *_ = scene.ray_cast(
                            depsgraph, cur, direction, distance=rem)
                        if not hit:
                            break
                        hits_z.append(loc.z)
                        all_hits_flat.append(loc.z)
                        rem -= (loc - cur).length + step_past
                        cur = loc + direction * step_past
            column_hits[(ix, iy)] = hits_z

    # --- Step 2: global percentile filter to remove env sphere hits ---
    z_threshold = (np.percentile(all_hits_flat, env_sphere_percentile)
                   if all_hits_flat else min_z)
    print(f"[TerrainSnake] env-sphere threshold (p{env_sphere_percentile})"
          f" = {z_threshold:.2f}")

    terrain_z_floor = np.full((nx, ny), np.nan, dtype=np.float64)
    for ix in range(nx):
        for iy in range(ny):
            valid = [z for z in column_hits[(ix, iy)] if z > z_threshold]
            if valid:
                terrain_z_floor[ix, iy] = min(valid)

    n_valid = int(np.sum(~np.isnan(terrain_z_floor)))
    print(f"[TerrainSnake] {n_valid}/{nx*ny} columns have valid terrain hits")

    # --- Step 3: fit TerrainSnake ---
    bounds = (min_x, min_y, max_x, max_y, min_z, max_z)
    snake = TerrainSnake(
        terrain_z_floor=terrain_z_floor,
        bounds=bounds,
        res=res_bu,
        alpha=alpha,
        gravity=gravity,
        dt=dt,
        max_iterations=max_iterations,
        convergence_threshold=convergence_threshold,
    )
    snake.fit()
    print(f"[TerrainSnake] converged in {snake.iterations_run} iterations")

    # --- Step 4: save ---
    heightmap = snake.to_heightmap()
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = str(output_dir_path / "terrain_snake.npz")
    np.savez_compressed(
        out_path,
        heightmap=heightmap.astype(np.float32),
        bounds=np.array(bounds, dtype=np.float64),
        res=np.float64(res_bu),
        unit_scale=np.float64(unit_scale),
    )
    print(f"[TerrainSnake] Saved → {out_path}")
    return out_path


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--grid-resolution", type=float, default=5.0)
    p.add_argument("--max-grid-cells-xy", type=int, default=200)
    p.add_argument("--env-sphere-percentile", type=float, default=5.0)
    p.add_argument("--ray-samples", type=int, default=1)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--gravity", type=float, default=0.1)
    p.add_argument("--dt", type=float, default=1.0)
    p.add_argument("--max-iterations", type=int, default=200)
    p.add_argument("--convergence-threshold", type=float, default=1e-3)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    fit_terrain_contour(
        blend_path=args.blend,
        output_dir=args.output_dir,
        grid_resolution=args.grid_resolution,
        max_grid_cells_xy=args.max_grid_cells_xy,
        env_sphere_percentile=args.env_sphere_percentile,
        ray_samples=args.ray_samples,
        alpha=args.alpha,
        gravity=args.gravity,
        dt=args.dt,
        max_iterations=args.max_iterations,
        convergence_threshold=args.convergence_threshold,
    )
```

- [ ] **Step 2: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add genesis_tools/active_contour/fit_terrain_contour.py
git commit -m "feat: fit_terrain_contour bpy script for outdoor terrain snake"
```

---

## Task 3: voxel_grid.py — terrain mode

**Files:**
- Modify: `genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py`
- Modify: `genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py`:

```python
# Add to existing imports at the top:
# from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
#     ..., _build_terrain_candidates,
# )

class TestTerrainMode:
    def test_basic_candidates(self, tmp_path):
        """_build_terrain_candidates maps each valid heightmap cell to one voxel."""
        nx, ny = 4, 5
        heightmap = np.full((nx, ny), 3.0, dtype=np.float32)
        bounds = np.array([0.0, 0.0, 4.0, 5.0, 0.0, 10.0])
        npz_path = str(tmp_path / "terrain.npz")
        np.savez_compressed(npz_path, heightmap=heightmap, bounds=bounds,
                            res=np.float64(1.0), unit_scale=np.float64(1.0))

        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
            _build_terrain_candidates,
        )
        vg = _build_terrain_candidates({"terrain_npz": npz_path})
        assert vg.mode == "terrain"
        assert len(vg.candidates) == nx * ny
        assert vg.nx == nx and vg.ny == ny

    def test_nan_columns_excluded(self, tmp_path):
        """NaN heightmap cells produce no candidate voxel."""
        nx, ny = 3, 3
        heightmap = np.full((nx, ny), np.nan, dtype=np.float32)
        heightmap[1, 1] = 2.0  # one valid cell
        bounds = np.array([0.0, 0.0, 3.0, 3.0, 0.0, 10.0])
        npz_path = str(tmp_path / "terrain_nan.npz")
        np.savez_compressed(npz_path, heightmap=heightmap, bounds=bounds,
                            res=np.float64(1.0), unit_scale=np.float64(1.0))

        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
            _build_terrain_candidates,
        )
        vg = _build_terrain_candidates({"terrain_npz": npz_path})
        assert len(vg.candidates) == 1
        assert tuple(vg.candidates[0]) == (1, 1, 2)  # iz = round((2.0-0.0)/1.0) = 2

    def test_candidates_within_grid_bounds(self, tmp_path):
        """All candidate iz values are within [0, nz-1]."""
        nx, ny = 3, 3
        heightmap = np.array(
            [[0.5, 1.0, 9.9], [2.0, 5.0, 7.0], [8.0, 9.0, 0.1]], dtype=np.float32
        )
        bounds = np.array([0.0, 0.0, 3.0, 3.0, 0.0, 10.0])
        npz_path = str(tmp_path / "terrain_b.npz")
        np.savez_compressed(npz_path, heightmap=heightmap, bounds=bounds,
                            res=np.float64(1.0), unit_scale=np.float64(1.0))

        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
            _build_terrain_candidates,
        )
        vg = _build_terrain_candidates({"terrain_npz": npz_path})
        assert np.all(vg.candidates[:, 2] >= 0)
        assert np.all(vg.candidates[:, 2] < vg.nz)

    def test_mode_roundtrip(self, tmp_path):
        """terrain mode string is preserved through save/load."""
        data = _make_vg(mode="terrain")
        path = str(tmp_path / "vg_terrain.npz")
        save(data, path)
        loaded = load(path)
        assert loaded.mode == "terrain"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py::TestTerrainMode -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name '_build_terrain_candidates'`

- [ ] **Step 3: Add `_build_terrain_candidates` and terrain branch to voxel_grid.py**

Add this function just before the `build()` function in `genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py`:

```python
def _build_terrain_candidates(config: dict) -> VoxelGridData:
    """Load terrain_snake.npz and map heightmap Z → one walkable voxel per column.

    No bpy required — reads the pre-computed terrain_snake.npz produced by
    genesis_tools.active_contour.fit_terrain_contour.
    """
    data = np.load(config["terrain_npz"])
    heightmap = data["heightmap"].astype(np.float64)   # (nx, ny)
    bounds = tuple(float(b) for b in data["bounds"])   # 6-tuple
    res = float(data["res"])
    unit_scale = float(data["unit_scale"]) if "unit_scale" in data else 1.0

    nx, ny = heightmap.shape
    min_z = bounds[4]
    max_z = bounds[5]
    nz = max(1, int(math.ceil((max_z - min_z) / res)))

    candidates = []
    for ix in range(nx):
        for iy in range(ny):
            z_val = float(heightmap[ix, iy])
            if not math.isnan(z_val):
                iz = int(round((z_val - min_z) / res))
                iz = max(0, min(nz - 1, iz))
                candidates.append((ix, iy, iz))

    candidates_arr = (np.array(sorted(candidates), dtype=np.int32)
                      if candidates else np.empty((0, 3), dtype=np.int32))
    print(f"[VoxelGrid] Terrain mode: {len(candidates)}/{nx*ny} columns have "
          f"walkable voxels ({nx}×{ny}×{nz} grid, res={res:.2f} BU)")
    return VoxelGridData(
        solid=np.empty((0, 3), dtype=np.int32),
        candidates=candidates_arr,
        nx=nx, ny=ny, nz=nz,
        res=res,
        bounds=bounds,
        unit_scale=unit_scale,
        mode="terrain",
        hits=None,
    )
```

Then modify the top of `build()` to check terrain mode BEFORE importing bpy:

```python
def build(blend_path: str, config: dict) -> VoxelGridData:
    """Build VoxelGridData from a .blend file using pip bpy.

    Must be called under /home/kingy/blender/4.5/python/bin/python3.11.
    """
    if config.get("terrain_npz"):
        return _build_terrain_candidates(config)

    import bpy
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    # ... rest of function unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py -v
```

Expected: all tests PASS (including the new TestTerrainMode class).

- [ ] **Step 5: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add genesis_tools/walkthrough_renderer/pipeline/voxel_grid.py \
        genesis_tools/walkthrough_renderer/tests/pipeline/test_voxel_grid_io.py
git commit -m "feat: voxel_grid terrain mode — load terrain_snake.npz as walkable candidates"
```

---

## Task 4: walkable.py — terrain branch

**Files:**
- Modify: `genesis_tools/walkthrough_renderer/pipeline/walkable.py`

The existing `else` branch (local/global) runs `_check_walkable_v2` which filters to cells with solid directly below. For terrain mode there is no solid, so that filter would discard everything. Terrain candidates are already the correct ground surface — use them directly.

- [ ] **Step 1: Add terrain branch at the top of `build()` in walkable.py**

In `genesis_tools/walkthrough_renderer/pipeline/walkable.py`, in the `build()` function, add terrain mode handling before the `if vg.mode == "snake":` check:

```python
def build(vg, config: dict, camera_ijk: tuple | None = None) -> WalkableData:
    """Build WalkableData from a VoxelGridData."""
    if vg.mode == "terrain":
        # Terrain mode: candidates are already the walkable ground-surface voxels
        # produced by TerrainSnake (one per column). No flood fill or floor filter
        # needed — the snake already found the surface.
        walkable_set = {tuple(r) for r in vg.candidates}
        print(f"[Walkable] Terrain mode: {len(walkable_set)} walkable voxels "
              f"(one per grid column)")
    elif vg.mode == "snake":
        # ... existing snake branch unchanged
```

- [ ] **Step 2: Run the full walkthrough test suite to verify nothing broke**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/walkthrough_renderer/tests/ -v --tb=short
```

Expected: all existing tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add genesis_tools/walkthrough_renderer/pipeline/walkable.py
git commit -m "feat: walkable terrain branch — use snake candidates directly as walkable"
```

---

## Task 5: Export TerrainSnake from __init__.py

**Files:**
- Modify: `genesis_tools/active_contour/__init__.py`

- [ ] **Step 1: Update __init__.py**

Replace the content of `genesis_tools/active_contour/__init__.py` with:

```python
"""genesis_tools.active_contour — 3D Active Contour (Snake) module.

Exports
-------
sample_mesh_surface : area-weighted point sampling from triangle mesh faces.
subdivide_mesh      : midpoint subdivision of a triangle mesh.
Snake3D             : 3D snake that contracts to the minimal smooth surface.
TerrainSnake        : cloth-simulation snake for outdoor terrain surfaces.
"""

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
    subdivide_mesh,
)
from genesis_tools.active_contour.terrain_snake import TerrainSnake

__all__ = ["Snake3D", "sample_mesh_surface", "subdivide_mesh", "TerrainSnake"]
```

- [ ] **Step 2: Verify import works**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -c "from genesis_tools.active_contour import TerrainSnake; print(TerrainSnake)"
```

Expected: `<class 'genesis_tools.active_contour.terrain_snake.TerrainSnake'>`

- [ ] **Step 3: Run full test suite**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -m pytest genesis_tools/active_contour/tests/ \
                 genesis_tools/walkthrough_renderer/tests/pipeline/ -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add genesis_tools/active_contour/__init__.py
git commit -m "feat: export TerrainSnake from active_contour __init__"
```

---

## Task 6: Integration run script for jungle_swamp

**Files:**
- Create: `run_jungle_swamp_v3.py`

This script calls `fit_terrain_contour` (bpy step) then `run` the walkthrough pipeline with `terrain_npz` in config. Both steps run sequentially — the bpy step saves the npz, then the walkthrough runner loads it.

- [ ] **Step 1: Write the run script**

```python
# run_jungle_swamp_v3.py
"""v3 — jungle_swamp terrain-snake walkthrough.

Two-phase pipeline:
  Phase 1 (bpy): fit_terrain_contour → terrain_snake.npz
  Phase 2 (pip bpy walkthrough): use terrain_npz → one walkable voxel per column

Scene: infinigen coarse, unit_scale=1.0, 3600m × 3600m.
Grid: 20m/voxel → 180×180 columns. Gravity + Laplacian bridges vegetation.
"""
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

BLEND   = "/home/kingy/Projects/Genesis/GenesisExp/GenesisCode2Worlds/results/jungle_swamp/coarse_scene.blend"
OUT_DIR = "/home/kingy/Projects/Genesis/GenesisTools/results/jungle_swamp_v3"
NPZ     = f"{OUT_DIR}/terrain_snake.npz"

BLENDER = "/home/kingy/blender/blender"   # adjust if blender is elsewhere
FIT_SCRIPT = str(
    Path("/home/kingy/Projects/Genesis/GenesisTools")
    / "genesis_tools/active_contour/fit_terrain_contour.py"
)

# --- Phase 1: terrain snake (must run under system Blender's Python) ---
if not os.path.exists(NPZ):
    print("[v3] Phase 1: fitting terrain snake …")
    cmd = [
        BLENDER, "--background", BLEND,
        "--python", FIT_SCRIPT,
        "--",
        "--blend", BLEND,
        "--output-dir", OUT_DIR,
        "--grid-resolution", "20.0",
        "--max-grid-cells-xy", "180",
        "--env-sphere-percentile", "5.0",
        "--ray-samples", "1",
        "--alpha", "0.5",
        "--gravity", "0.1",
        "--dt", "1.0",
        "--max-iterations", "200",
        "--convergence-threshold", "1e-3",
    ]
    result = subprocess.run(cmd, check=True)
    print(f"[v3] terrain_snake.npz saved → {NPZ}")
else:
    print(f"[v3] Reusing existing {NPZ}")

# --- Phase 2: walkthrough pipeline (pip bpy) ---
from genesis_tools.walkthrough_renderer.walkthrough import run

config = {
    "terrain_npz": NPZ,

    # TerrainSnake params (used in Phase 1 above; echoed here for reference)
    "grid_resolution": 20.0,
    "max_grid_cells_xy": 180,
    "env_sphere_percentile": 5.0,
    "terrain_ray_samples": 1,
    "terrain_alpha": 0.5,
    "terrain_gravity": 0.1,
    "terrain_dt": 1.0,
    "terrain_max_iterations": 200,
    "terrain_convergence_threshold": 1e-3,

    # Camera / path
    "camera_height": 1.7,
    "num_waypoints": 20,
    "seed": 42,
    "waypoint_gaze_mode": "free",
    "lookahead_fraction": 0.05,
    "rotation_smooth_seconds": 2.0,

    # Render
    "fps": 12,
    "max_duration_seconds": 120,
    "walk_speed_mps": 5.0,
    "render_engine": "WORKBENCH",
    "render_width": 1280,
    "render_height": 720,
    "render_samples": 32,
    "aerial": False,
}

print(f"[v3] Phase 2: walkthrough → {OUT_DIR}")
result = run(BLEND, config, OUT_DIR, render=True)
print("[v3] done:", result)
```

- [ ] **Step 2: Verify the script syntax is valid**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
python -c "import ast; ast.parse(open('run_jungle_swamp_v3.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /home/kingy/Projects/Genesis/GenesisTools
git add run_jungle_swamp_v3.py
git commit -m "feat: run_jungle_swamp_v3 — terrain-snake two-phase walkthrough"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|-----------------|------|
| TerrainSnake class with all params | Task 1 |
| step() — gravity + Laplacian + hard floor | Task 1 |
| fit() — same convergence logic as Snake3D | Task 1 |
| to_heightmap() | Task 1 |
| fit_terrain_contour.py — downward ray-cast | Task 2 |
| Global percentile filter for env spheres | Task 2 |
| terrain_snake.npz output format | Task 2 |
| voxel_grid mode="terrain" | Task 3 |
| One walkable voxel per column | Task 3 |
| NaN columns → excluded | Task 3 |
| All terrain_* config keys optional with defaults | Tasks 2, 6 |
| Downstream pipeline unchanged | Tasks 4 (terrain branch returns directly) |
| test_terrain_snake.py | Task 1 |

### Type consistency
- `TerrainSnake.fit()` returns `"TerrainSnake"` (self) — matches usage in Task 2 (`snake.fit()`) and Task 1 tests (`assert result is snake`) ✓
- `to_heightmap()` returns `np.ndarray` (nx, ny) float64 — matches `heightmap.astype(np.float32)` save in Task 2 ✓
- `_build_terrain_candidates()` returns `VoxelGridData` with `mode="terrain"` — matches walkable.py terrain branch check `vg.mode == "terrain"` ✓
- npz keys: `heightmap`, `bounds`, `res`, `unit_scale` — consistent between Task 2 (save) and Task 3 (load) ✓
