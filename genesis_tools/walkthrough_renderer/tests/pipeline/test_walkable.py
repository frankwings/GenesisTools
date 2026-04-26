"""Tests for pipeline/walkable.py — pure Python, no bpy needed."""
import numpy as np
import pytest

from genesis_tools.walkthrough_renderer.pipeline.walkable import (
    WalkableData,
    _check_walkable_v2,
    _flood_fill_free_from_camera,
    build,
    load,
    save,
)
from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import VoxelGridData


def _make_vg(solid_set, nx=5, ny=5, nz=5, candidates=None):
    solid_arr = np.array(sorted(solid_set), dtype=np.int32) if solid_set else np.empty((0, 3), dtype=np.int32)
    if candidates is None:
        cand = np.empty((0, 3), dtype=np.int32)
    else:
        cand = np.array(sorted(candidates), dtype=np.int32)
    return VoxelGridData(
        solid=solid_arr, candidates=cand,
        nx=nx, ny=ny, nz=nz,
        res=0.5, bounds=(0, 0, 2.5, 2.5, 0, 2.5),
        unit_scale=1.0, mode="global", hits=None,
    )


# ---------------------------------------------------------------------------
# _flood_fill_free_from_camera
# ---------------------------------------------------------------------------

class TestFloodFill:
    def test_open_box_fills_interior(self):
        # 3×3×3 grid, no solid voxels → all 27 reachable from center
        result = _flood_fill_free_from_camera(set(), (1, 1, 1), 3, 3, 3)
        assert len(result) == 27

    def test_wall_blocks_fill(self):
        # A full XY wall at z=2 separates the grid into two halves
        solid = {(x, y, 2) for x in range(3) for y in range(3)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 3, 3, 4)
        # z=0 and z=1 reachable (9+9=18), z=2 solid (wall), z=3 not reachable
        assert all(k <= 1 for _, _, k in result)
        assert len(result) == 18

    def test_camera_in_solid_snaps(self):
        # Only one free voxel at (2,2,2) in a 3×3×3 grid
        solid = {(x, y, z) for x in range(3) for y in range(3) for z in range(3)
                 if (x, y, z) != (2, 2, 2)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 3, 3, 3)
        assert result == {(2, 2, 2)}

    def test_all_solid_returns_empty(self):
        solid = {(x, y, z) for x in range(2) for y in range(2) for z in range(2)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 2, 2, 2)
        assert result == set()


# ---------------------------------------------------------------------------
# _check_walkable_v2
# ---------------------------------------------------------------------------

class TestCheckWalkable:
    def test_returns_all_candidates(self):
        candidates = {(0, 0, 0), (1, 0, 0), (2, 0, 0)}
        result = _check_walkable_v2(candidates, (0, 0, 3, 3, 0, 3), {})
        assert result == candidates

    def test_empty_candidates(self):
        result = _check_walkable_v2(set(), (0, 0, 3, 3, 0, 3), {})
        assert result == set()


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_basic(self):
        # 3×3×3 grid, no solid → all voxels walkable
        vg = _make_vg(set(), nx=3, ny=3, nz=3)
        result = build(vg, {})
        assert isinstance(result, WalkableData)
        assert result.walkable.shape[1] == 3
        assert len(result.walkable) == 27

    def test_build_with_solid(self):
        # Solid wall cuts off part of grid
        solid = {(x, y, 2) for x in range(3) for y in range(3)}
        vg = _make_vg(solid, nx=3, ny=3, nz=4)
        result = build(vg, {}, camera_ijk=(1, 1, 0))
        # z=0,1 reachable (18 cells), not z=2 (solid) or z=3 (disconnected)
        assert len(result.walkable) == 18
        assert all(k <= 1 for _, _, k in result.walkable)

    def test_build_explicit_camera_ijk(self):
        vg = _make_vg(set(), nx=2, ny=2, nz=2)
        result = build(vg, {}, camera_ijk=(0, 0, 0))
        assert len(result.walkable) == 8

    def test_build_returns_int32(self):
        vg = _make_vg(set(), nx=2, ny=2, nz=2)
        result = build(vg, {})
        assert result.walkable.dtype == np.int32


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        data = WalkableData(walkable=np.array([[1, 2, 3], [4, 5, 6]], dtype=np.int32))
        path = str(tmp_path / "walkable.npz")
        save(data, path)
        loaded = load(path)
        np.testing.assert_array_equal(loaded.walkable, data.walkable)
        assert loaded.walkable.dtype == np.int32

    def test_empty_roundtrip(self, tmp_path):
        data = WalkableData(walkable=np.empty((0, 3), dtype=np.int32))
        path = str(tmp_path / "walkable_empty.npz")
        save(data, path)
        loaded = load(path)
        assert loaded.walkable.shape == (0, 3)
