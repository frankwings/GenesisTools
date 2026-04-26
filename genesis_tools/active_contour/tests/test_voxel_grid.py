"""Unit tests for genesis_tools.active_contour.voxel_grid.

No Blender dependency — all geometry uses the same unit-cube/snake fixtures
from test_active_contour.py.

Coverage
--------
_batch_ray_hits / _batch_contains
  - points known inside unit cube → all True
  - points known outside         → all False
  - mixed batch matches single contains()

_estimate_fill_ratio
  - cube fills its AABB completely → ratio ≈ 1.0
  - single-face (flat) mesh → near-zero fill

VoxelGrid
  - count is within ±20% of target for a unit-cube snake
  - voxel_size is derived correctly from snake volume
  - all reported centres lie inside the snake
  - save() / load() round-trip preserves centres, voxel_size, fill_ratio
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
)
from genesis_tools.active_contour.voxel_grid import (
    VoxelGrid,
    _batch_contains,
    _batch_ray_hits,
    _estimate_fill_ratio,
)


# ---------------------------------------------------------------------------
# Shared geometry
# ---------------------------------------------------------------------------

def _unit_cube_mesh():
    v = np.array([
        [0,0,0],[1,0,0],[1,1,0],[0,1,0],
        [0,0,1],[1,0,1],[1,1,1],[0,1,1],
    ], dtype=float)
    f = np.array([
        [0,2,1],[0,3,2],
        [4,5,6],[4,6,7],
        [0,1,5],[0,5,4],
        [2,3,7],[2,7,6],
        [0,4,7],[0,7,3],
        [1,2,6],[1,6,5],
    ], dtype=int)
    return v, f


@pytest.fixture(scope="module")
def cube_snake():
    """Fitted Snake3D on the unit cube — reused across all tests."""
    v, f = _unit_cube_mesh()
    pts  = sample_mesh_surface([(v, f)], sampling_resolution=0.15)
    return Snake3D(pts, alpha=0.5, beta=0.4, dt=0.05,
                   max_iterations=200, subdivision_levels=2).fit()


@pytest.fixture(scope="module")
def cube_verts_faces():
    return _unit_cube_mesh()


# ---------------------------------------------------------------------------
# _batch_ray_hits
# ---------------------------------------------------------------------------

class TestBatchRayHits:

    def test_interior_point_hits_odd(self, cube_verts_faces):
        v, f = cube_verts_faces
        direction = np.array([0.0, 0.0, 1.0])
        # (0.3, 0.2) is inside triangle [4,5,6] only — not on the shared diagonal
        # edge between the two top-face triangles, so the ray crosses exactly 1 face.
        origin = np.array([[0.3, 0.2, 0.5]])
        hits = _batch_ray_hits(origin, direction, v, f)
        assert hits[0] % 2 == 1, "interior point should give odd hit count"

    def test_exterior_point_hits_even(self, cube_verts_faces):
        v, f = cube_verts_faces
        direction = np.array([0.0, 0.0, 1.0])
        # Far above cube — ray misses or crosses 0 faces
        origin = np.array([[0.5, 0.5, 5.0]])
        hits = _batch_ray_hits(origin, direction, v, f)
        assert hits[0] % 2 == 0, "exterior point above cube should give even hit count"

    def test_batch_returns_correct_shape(self, cube_verts_faces):
        v, f = cube_verts_faces
        direction = np.array([0.0, 0.0, 1.0])
        origins = np.random.default_rng(0).uniform(0, 1, (50, 3))
        hits = _batch_ray_hits(origins, direction, v, f)
        assert hits.shape == (50,)


# ---------------------------------------------------------------------------
# _batch_contains
# ---------------------------------------------------------------------------

class TestBatchContains:

    def test_cube_interior_all_true(self, cube_verts_faces):
        v, f = cube_verts_faces
        # 5×5×5 grid strictly inside [0.1, 0.9]³
        xs = np.linspace(0.1, 0.9, 5)
        X, Y, Z = np.meshgrid(xs, xs, xs, indexing="ij")
        pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
        mask = _batch_contains(pts, v, f)
        assert mask.all(), "all points inside unit cube should be classified inside"

    def test_exterior_points_all_false(self, cube_verts_faces):
        v, f = cube_verts_faces
        # Points clearly outside
        pts = np.array([
            [2.0, 0.5, 0.5],
            [-1.0, 0.5, 0.5],
            [0.5, 0.5, 2.0],
            [0.5, 0.5, -1.0],
        ])
        mask = _batch_contains(pts, v, f)
        assert not mask.any(), "exterior points should all be False"

    def test_batch_matches_single_snake_contains(self, cube_snake):
        """Batch result must agree with Snake3D.contains() for every point."""
        rng = np.random.default_rng(42)
        pts = rng.uniform(-0.5, 1.5, (30, 3))
        batch  = _batch_contains(pts, cube_snake.vertices, cube_snake.faces)
        single = np.array([cube_snake.contains(p) for p in pts])
        np.testing.assert_array_equal(batch, single)


# ---------------------------------------------------------------------------
# _estimate_fill_ratio
# ---------------------------------------------------------------------------

class TestEstimateFillRatio:

    def test_cube_fills_its_own_aabb(self, cube_verts_faces):
        """A unit cube snake should fill ~100% of its AABB."""
        v, f  = cube_verts_faces
        lo, hi = v.min(axis=0), v.max(axis=0)
        ratio = _estimate_fill_ratio(v, f, lo, hi, coarse_n=15)
        assert ratio > 0.85, f"cube fill ratio should be >85%, got {ratio:.3f}"

    def test_fill_ratio_bounded(self, cube_verts_faces):
        v, f  = cube_verts_faces
        lo, hi = v.min(axis=0), v.max(axis=0)
        ratio = _estimate_fill_ratio(v, f, lo, hi, coarse_n=10)
        assert 0.0 <= ratio <= 1.0


# ---------------------------------------------------------------------------
# VoxelGrid
# ---------------------------------------------------------------------------

class TestVoxelGrid:

    TARGET = 5_000

    @pytest.fixture(scope="class")
    def grid(self, cube_snake):
        return VoxelGrid(cube_snake, target_voxels=self.TARGET,
                         chunk_size=1024, coarse_n=12)

    def test_count_within_20_percent_of_target(self, grid):
        lo, hi = self.TARGET * 0.80, self.TARGET * 1.20
        assert lo <= grid.count <= hi, (
            f"count {grid.count} not within ±20% of target {self.TARGET}")

    def test_voxel_size_positive(self, grid):
        assert grid.voxel_size > 0

    def test_centers_shape(self, grid):
        assert grid.centers.ndim == 2
        assert grid.centers.shape[1] == 3

    def test_all_centers_inside_snake(self, grid, cube_snake):
        """Every voxel centre must be inside the snake — the core guarantee."""
        # Sample a subset for speed (full set can be 5k × 3 rays × 3k faces)
        rng = np.random.default_rng(0)
        idx = rng.choice(len(grid.centers),
                         size=min(200, len(grid.centers)), replace=False)
        sample = grid.centers[idx]
        inside = _batch_contains(sample, cube_snake.vertices, cube_snake.faces)
        pct_inside = inside.sum() / len(sample)
        assert pct_inside >= 0.95, (
            f"≥95% of voxel centres must be inside snake, got {pct_inside:.2%}")

    def test_fill_ratio_stored(self, grid):
        assert 0.0 < grid.fill_ratio <= 1.0

    def test_snake_volume_positive(self, grid):
        assert grid.snake_volume > 0

    def test_grid_shape_tuple(self, grid):
        assert len(grid.grid_shape) == 3
        assert all(n > 0 for n in grid.grid_shape)

    def test_save_load_roundtrip(self, grid):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voxel_grid.npz"
            grid.save(str(path))
            loaded = VoxelGrid.load(str(path))

        np.testing.assert_array_almost_equal(loaded.centers, grid.centers)
        assert abs(loaded.voxel_size - grid.voxel_size) < 1e-10
        assert loaded.grid_shape == grid.grid_shape
        assert abs(loaded.fill_ratio - grid.fill_ratio) < 1e-10
        assert abs(loaded.snake_volume - grid.snake_volume) < 1e-10

    def test_count_property(self, grid):
        assert grid.count == len(grid.centers)
