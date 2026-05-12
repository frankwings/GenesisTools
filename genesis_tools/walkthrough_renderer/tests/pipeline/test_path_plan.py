"""Tests for pipeline/path_plan.py -- pure Python, no bpy needed."""
import numpy as np
import pytest

from genesis_tools.walkthrough_renderer.pipeline.path_plan import (
    PathData,
    _bfs_largest_component,
    _bfs_path,
    _farthest_point_sample,
    _greedy_tsp_tour,
    build,
    load,
    save,
)
from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import VoxelGridData
from genesis_tools.walkthrough_renderer.pipeline.walkable import WalkableData


def _make_line_vg(length=10):
    """VoxelGridData for a 10x1x1 corridor along X."""
    solid: set = set()
    return VoxelGridData(
        solid=np.empty((0,3), dtype=np.int32),
        candidates=np.empty((0,3), dtype=np.int32),
        nx=length, ny=1, nz=1,
        res=0.5, bounds=(0.0, 0.0, length*0.5, 0.5, 0.0, 0.5),
        unit_scale=1.0, mode="global", hits=None,
    )


def _line_wk(length=10):
    cells = np.array([(i, 0, 0) for i in range(length)], dtype=np.int32)
    return WalkableData(walkable=cells)


# ---------------------------------------------------------------------------
# _bfs_largest_component
# ---------------------------------------------------------------------------

class TestBfsLargestComponent:
    def test_single_component(self):
        cells = {(0,0,0),(1,0,0),(2,0,0)}
        result = _bfs_largest_component(cells)
        assert result == cells

    def test_two_components_returns_larger(self):
        # Component A: (0..4, 0, 0)  Component B: (10, 0, 0) isolated
        a = {(i,0,0) for i in range(5)}
        b = {(10,0,0)}
        result = _bfs_largest_component(a | b)
        assert result == a

    def test_z_connectivity(self):
        # Two XY positions connected via Z step
        cells = {(0,0,0),(0,0,1),(1,0,1)}
        result = _bfs_largest_component(cells)
        assert result == cells

    def test_empty_input(self):
        assert _bfs_largest_component(set()) == set()


# ---------------------------------------------------------------------------
# _farthest_point_sample
# ---------------------------------------------------------------------------

class TestFarthestPointSample:
    def test_fewer_than_n_returns_all(self):
        cells = {(0,0,0),(1,0,0)}
        result = _farthest_point_sample(cells, 10, 42)
        assert set(result) == cells

    def test_returns_n_samples(self):
        cells = {(i,0,0) for i in range(20)}
        result = _farthest_point_sample(cells, 5, 42)
        assert len(result) == 5
        assert all(c in cells for c in result)

    def test_fixed_first_is_first(self):
        cells = {(i,0,0) for i in range(20)}
        fixed = (19, 0, 0)
        result = _farthest_point_sample(cells, 5, 42, fixed_first=fixed)
        assert result[0] == fixed

    def test_no_duplicates(self):
        cells = {(i,0,0) for i in range(10)}
        result = _farthest_point_sample(cells, 5, 42)
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# _greedy_tsp_tour
# ---------------------------------------------------------------------------

class TestGreedyTspTour:
    def test_visits_all(self):
        waypoints = [(0,0,0),(5,0,0),(10,0,0),(5,5,0)]
        result = _greedy_tsp_tour(waypoints)
        assert set(result) == set(waypoints)
        assert len(result) == len(waypoints)

    def test_empty(self):
        assert _greedy_tsp_tour([]) == []

    def test_single(self):
        assert _greedy_tsp_tour([(1,2,3)]) == [(1,2,3)]


# ---------------------------------------------------------------------------
# _bfs_path
# ---------------------------------------------------------------------------

class TestBfsPath:
    def test_direct_neighbour(self):
        walkable = {(0,0,0),(1,0,0)}
        path = _bfs_path((0,0,0),(1,0,0), walkable)
        assert path == [(0,0,0),(1,0,0)]

    def test_longer_path(self):
        walkable = {(i,0,0) for i in range(5)}
        path = _bfs_path((0,0,0),(4,0,0), walkable)
        assert path[0] == (0,0,0)
        assert path[-1] == (4,0,0)
        assert len(path) == 5

    def test_same_start_goal(self):
        assert _bfs_path((1,2,3),(1,2,3),{(1,2,3)}) == [(1,2,3)]

    def test_unreachable_returns_start_goal(self):
        walkable = {(0,0,0),(5,0,0)}
        path = _bfs_path((0,0,0),(5,0,0), walkable)
        assert path[0] == (0,0,0)
        assert path[-1] == (5,0,0)


# ---------------------------------------------------------------------------
# build() -- runs without bpy (falls back to voxel-centre path)
# ---------------------------------------------------------------------------

class TestBuild:
    def test_basic_line(self):
        vg = _make_line_vg(10)
        wk = _line_wk(10)
        config = {"num_waypoints": 3, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5}
        result = build(vg, wk, config)
        assert isinstance(result, PathData)
        assert len(result.waypoints) > 0
        assert len(result.path_points) > 0
        assert result.path_points.dtype == np.float64
        assert result.waypoints.dtype == np.int32

    def test_empty_walkable(self):
        vg = _make_line_vg(5)
        wk = WalkableData(walkable=np.empty((0,3), dtype=np.int32))
        config = {"num_waypoints": 3, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5}
        result = build(vg, wk, config)
        assert len(result.waypoints) == 0
        assert len(result.path_points) == 0

    def test_bounds_preserved(self):
        vg = _make_line_vg(10)
        wk = _line_wk(10)
        config = {"num_waypoints": 3, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5}
        result = build(vg, wk, config)
        assert result.bounds == vg.bounds


# ---------------------------------------------------------------------------
# laplacian_iters config key
# ---------------------------------------------------------------------------

def _make_grid_vg(w=5, h=5):
    """VoxelGridData for a 5×5×1 flat grid."""
    return VoxelGridData(
        solid=np.empty((0, 3), dtype=np.int32),
        candidates=np.empty((0, 3), dtype=np.int32),
        nx=w, ny=h, nz=1,
        res=0.5, bounds=(0.0, 0.0, w*0.5, h*0.5, 0.0, 0.5),
        unit_scale=1.0, mode="global", hits=None,
    )


def _grid_wk(w=5, h=5):
    cells = np.array([(x, y, 0) for x in range(w) for y in range(h)], dtype=np.int32)
    return WalkableData(walkable=cells)


class TestLaplacianItersConfig:
    def test_theta_star_default_zero_iters_produces_path(self):
        vg = _make_grid_vg()
        wk = _grid_wk()
        config = {"num_waypoints": 4, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5, "path_planner": "theta_star"}
        result = build(vg, wk, config)
        assert len(result.path_points) > 0

    def test_theta_star_explicit_zero_same_as_default(self):
        """laplacian_iters=0 is the same as omitting the key in theta_star mode."""
        vg = _make_grid_vg()
        wk = _grid_wk()
        base = {"num_waypoints": 4, "seed": 42, "camera_height": 1.7,
                "grid_resolution": 0.5, "path_planner": "theta_star"}
        r1 = build(vg, wk, {**base})
        r2 = build(vg, wk, {**base, "laplacian_iters": 0})
        np.testing.assert_array_equal(r1.path_points, r2.path_points)

    def test_theta_star_nonzero_iters_falls_back_to_bfs_without_bpy(self):
        """laplacian_iters>0 falls back to pure BFS gracefully when bpy is absent."""
        vg = _make_grid_vg()
        wk = _grid_wk()
        config = {"num_waypoints": 4, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5, "path_planner": "theta_star",
                  "laplacian_iters": 5}
        result = build(vg, wk, config)
        assert len(result.path_points) > 0

    def test_theta_star_nonzero_iters_produces_valid_path(self):
        """laplacian_iters>0 always produces a valid float64 path (smoothed if bpy available,
        pure BFS fallback otherwise)."""
        vg = _make_grid_vg()
        wk = _grid_wk()
        config = {"num_waypoints": 4, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5, "path_planner": "theta_star",
                  "laplacian_iters": 5}
        result = build(vg, wk, config)
        assert len(result.path_points) > 0
        assert result.path_points.dtype == np.float64

    def test_default_planner_zero_iters_produces_path(self):
        """Default planner with laplacian_iters=0 still produces a valid path."""
        vg = _make_line_vg(10)
        wk = _line_wk(10)
        config = {"num_waypoints": 3, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5, "laplacian_iters": 0}
        result = build(vg, wk, config)
        assert len(result.path_points) > 0

    def test_theta_star_path_is_upsampled_4x(self):
        """theta_star produces 4× upsampled path — many more points than BFS cells."""
        vg = _make_line_vg(10)
        wk = _line_wk(10)
        config = {"num_waypoints": 3, "seed": 42, "camera_height": 1.7,
                  "grid_resolution": 0.5, "path_planner": "theta_star"}
        result = build(vg, wk, config)
        # BFS on a 10-cell corridor with 3 waypoints visits most cells; 4× upsample
        # means path_points >> num cells (at least 4× the waypoint count)
        assert len(result.path_points) >= len(result.waypoints) * 4


# ---------------------------------------------------------------------------
# Camera-voxel forcing: iz lookup + component injection
# ---------------------------------------------------------------------------

def _write_terrain_npz(tmp_path, camera_xyz, hm, camera_lookat=None):
    """Write a terrain_snake.npz and return its path string."""
    nx, ny = hm.shape
    bounds = np.array([0.0, 0.0, float(nx), float(ny), 0.0, float(nx)])
    arrays = dict(camera_xyz=np.array(camera_xyz, dtype=np.float64),
                  heightmap=hm.astype(np.float64), bounds=bounds,
                  res=np.float64(1.0), unit_scale=np.float64(1.0))
    if camera_lookat is not None:
        arrays["camera_lookat"] = np.array(camera_lookat, dtype=np.float64)
    path = str(tmp_path / "terrain.npz")
    np.savez_compressed(path, **arrays)
    return path


def _grid_wk_terrain(cam_ix, cam_iy, w=8, h=8, cam_iz_in_set=None):
    """Walkable cells: flat iz=0 grid from (1,1) to (w-2,h-2), minus camera XY.

    cam_iz_in_set: if given, add (cam_ix, cam_iy, cam_iz_in_set) to the set.
    """
    cells = [(x, y, 0)
             for x in range(1, w - 1)
             for y in range(1, h - 1)
             if not (x == cam_ix and y == cam_iy)]
    if cam_iz_in_set is not None:
        cells.append((cam_ix, cam_iy, cam_iz_in_set))
    return WalkableData(walkable=np.array(cells, dtype=np.int32))


def _terrain_vg(nx=8, ny=8, nz=8, res=1.0):
    return VoxelGridData(
        solid=np.empty((0, 3), dtype=np.int32),
        candidates=np.empty((0, 3), dtype=np.int32),
        nx=nx, ny=ny, nz=nz, res=res,
        bounds=(0.0, 0.0, nx * res, ny * res, 0.0, nz * res),
        unit_scale=1.0, mode="terrain", hits=None,
    )


class TestCamIzFromWalkableSet:
    """iz used in fixed_first comes from walkable_set lookup, not raw heightmap."""

    def test_iz_from_walkable_set_not_heightmap(self, tmp_path):
        """When (cam_ix, cam_iy, iz=5) is in walkable_set but heightmap gives iz=1,
        fixed_first uses iz=5 (the walkable_set value)."""
        cam_ix, cam_iy = 3, 3
        hm = np.full((8, 8), 1.0)   # heightmap fallback would give iz=1
        npz = _write_terrain_npz(tmp_path, [3.5, 3.5, 0.0], hm)
        vg  = _terrain_vg()
        # walkable_set includes (3,3,5) — camera cell at unusual height
        wk  = _grid_wk_terrain(cam_ix, cam_iy, cam_iz_in_set=5)
        cfg = {"terrain_npz": npz, "num_waypoints": 3, "seed": 42,
               "camera_height": 1.7, "grid_resolution": 1.0,
               "force_camera_walkable": True}
        result = build(vg, wk, cfg)
        # fixed_first should use iz=5 (from walkable_set), not iz=1 (from heightmap)
        assert tuple(result.waypoints[0]) == (cam_ix, cam_iy, 5)

    def test_iz_from_heightmap_when_not_in_walkable_set(self, tmp_path):
        """When no (cam_ix, cam_iy, *) in walkable_set, iz is from heightmap patch."""
        cam_ix, cam_iy = 3, 3
        hm = np.full((8, 8), 3.0)   # heightmap gives iz=3
        npz = _write_terrain_npz(tmp_path, [3.5, 3.5, 0.0], hm)
        vg  = _terrain_vg()
        # No camera-XY cell in walkable_set (cam_iz_in_set=None)
        wk  = _grid_wk_terrain(cam_ix, cam_iy, cam_iz_in_set=None)
        cfg = {"terrain_npz": npz, "num_waypoints": 3, "seed": 42,
               "camera_height": 1.7, "grid_resolution": 1.0,
               "force_camera_walkable": True}
        result = build(vg, wk, cfg)
        # fixed_first iz comes from heightmap: int((3.0 - 0.0) / 1.0) = 3
        assert tuple(result.waypoints[0]) == (cam_ix, cam_iy, 3)


class TestForceCameraWalkableInComponent:
    """force_camera_walkable injects camera cell as wp0; lookat march used otherwise."""

    def test_force_true_injects_camera_cell(self, tmp_path):
        """force_camera_walkable=True: camera cell (not in component) is injected → wp0."""
        cam_ix, cam_iy = 3, 3
        hm = np.full((8, 8), 2.0)   # iz=2
        npz = _write_terrain_npz(tmp_path, [3.5, 3.5, 0.0], hm)
        vg  = _terrain_vg()
        wk  = _grid_wk_terrain(cam_ix, cam_iy, cam_iz_in_set=None)
        cfg = {"terrain_npz": npz, "num_waypoints": 3, "seed": 42,
               "camera_height": 1.7, "grid_resolution": 1.0,
               "force_camera_walkable": True}
        result = build(vg, wk, cfg)
        assert tuple(result.waypoints[0]) == (cam_ix, cam_iy, 2)

    def test_force_false_uses_lookat_march(self, tmp_path):
        """force_camera_walkable=False + lookat → first walkable cell along lookat is wp0."""
        cam_ix, cam_iy = 3, 3
        # heightmap gives iz=0 so march looks for (x,y,0) cells
        hm = np.full((8, 8), 0.5)   # iz = int(0.5/1.0) = 0
        # lookat=(1,0,0) → march in +x from (3,3)
        # first reachable walkable cell in +x is (4,3,0) (since (3,3) excluded from wk)
        npz = _write_terrain_npz(tmp_path, [3.5, 3.5, 0.0], hm,
                                 camera_lookat=[1.0, 0.0, 0.0])
        vg  = _terrain_vg()
        wk  = _grid_wk_terrain(cam_ix, cam_iy, cam_iz_in_set=None)
        cfg = {"terrain_npz": npz, "num_waypoints": 3, "seed": 42,
               "camera_height": 1.7, "grid_resolution": 1.0,
               "force_camera_walkable": False}
        result = build(vg, wk, cfg)
        # March finds (4,3,0) as first walkable cell along +x
        assert tuple(result.waypoints[0]) == (4, cam_iy, 0)

    def test_force_false_no_lookat_falls_back_to_inject(self, tmp_path):
        """force_camera_walkable=False, no lookat key → no march → inject camera cell."""
        cam_ix, cam_iy = 3, 3
        hm = np.full((8, 8), 1.0)   # iz=1
        # no camera_lookat in terrain_npz
        npz = _write_terrain_npz(tmp_path, [3.5, 3.5, 0.0], hm)
        vg  = _terrain_vg()
        wk  = _grid_wk_terrain(cam_ix, cam_iy, cam_iz_in_set=None)
        cfg = {"terrain_npz": npz, "num_waypoints": 3, "seed": 42,
               "camera_height": 1.7, "grid_resolution": 1.0,
               "force_camera_walkable": False}
        result = build(vg, wk, cfg)
        # No lookat → fallback inject → (3,3,1) is wp0
        assert tuple(result.waypoints[0]) == (cam_ix, cam_iy, 1)


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        data = PathData(
            waypoints=np.array([[0,0,0],[5,0,0]], dtype=np.int32),
            path_points=np.array([[0.25,0.25,0.0],[2.5,0.25,0.0]], dtype=np.float64),
            tour=np.array([0,1], dtype=np.int32),
            camera_height=1.7,
            bounds=(0.0, 0.0, 5.0, 1.0, 0.0, 1.0),
        )
        path = str(tmp_path / "path.npz")
        save(data, path)
        loaded = load(path)
        np.testing.assert_array_equal(loaded.waypoints, data.waypoints)
        np.testing.assert_array_almost_equal(loaded.path_points, data.path_points)
        np.testing.assert_array_equal(loaded.tour, data.tour)
        assert abs(loaded.camera_height - data.camera_height) < 1e-9
        assert loaded.bounds == data.bounds
