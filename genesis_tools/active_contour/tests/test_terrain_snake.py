"""Unit tests for TerrainSnake — pure NumPy, no bpy dependency."""
import numpy as np

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
