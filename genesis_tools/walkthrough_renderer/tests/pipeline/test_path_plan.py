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
