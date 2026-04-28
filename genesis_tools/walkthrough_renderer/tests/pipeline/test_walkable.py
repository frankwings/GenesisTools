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
    def test_iz0_always_passes(self):
        # iz=0 passes regardless of solid (scene-bottom boundary)
        candidates = {(0, 0, 0), (1, 0, 0), (2, 0, 0)}
        result = _check_walkable_v2(candidates, set(), (0, 0, 3, 3, 0, 3), {})
        assert result == candidates

    def test_mid_air_excluded_when_floor_exists(self):
        # iz=1 without solid below is excluded when floor-level voxels exist
        solid = set()
        candidates = {(0, 0, 0), (1, 0, 1)}  # (0,0,0) is iz=0 (floor), (1,0,1) is mid-air
        result = _check_walkable_v2(candidates, solid, (0, 0, 3, 3, 0, 3), {})
        assert result == {(0, 0, 0)}          # mid-air excluded; iz=0 passes

    def test_solid_below_passes(self):
        # iz=2 with solid at iz=1 directly below passes
        solid = {(0, 0, 1)}
        candidates = {(0, 0, 2)}
        result = _check_walkable_v2(candidates, solid, (0, 0, 3, 3, 0, 3), {})
        assert result == candidates

    def test_floor_filter_mixed(self):
        # iz=0 passes, iz=1 passes if solid below, iz=2 without solid excluded
        solid = {(0, 0, 0)}        # floor at iz=0 for column (0,0)
        candidates = {
            (0, 0, 0),             # iz=0 → passes (iz==0)
            (0, 0, 1),             # iz=1, solid at (0,0,0) → passes
            (0, 0, 2),             # iz=2, solid at (0,0,1)? No → excluded
            (1, 0, 1),             # iz=1, solid at (1,0,0)? No → excluded
        }
        result = _check_walkable_v2(candidates, solid, (0, 0, 3, 3, 0, 3), {})
        assert result == {(0, 0, 0), (0, 0, 1)}

    def test_fallback_on_empty_result(self):
        # If no floor-level voxels found, returns all candidates
        candidates = {(0, 0, 3), (1, 0, 3)}   # iz=3, no solid below
        result = _check_walkable_v2(candidates, set(), (0, 0, 3, 3, 0, 3), {})
        assert result == candidates             # fallback

    def test_empty_candidates(self):
        result = _check_walkable_v2(set(), set(), (0, 0, 3, 3, 0, 3), {})
        assert result == set()


# ---------------------------------------------------------------------------
# build()
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_basic_no_solid(self):
        # 3×3×3 grid, no solid → only iz=0 voxels pass floor filter (9 cells)
        vg = _make_vg(set(), nx=3, ny=3, nz=3)
        result = build(vg, {})
        assert isinstance(result, WalkableData)
        assert result.walkable.shape[1] == 3
        walkable_set = {tuple(r) for r in result.walkable}
        assert all(iz == 0 for _, _, iz in walkable_set)
        assert len(result.walkable) == 9

    def test_build_with_floor_solid(self):
        # Floor solid at iz=0 → iz=1 voxels are walkable (standing on floor)
        solid = {(x, y, 0) for x in range(3) for y in range(3)}   # solid floor
        vg = _make_vg(solid, nx=3, ny=3, nz=3)
        result = build(vg, {}, camera_ijk=(1, 1, 1))
        walkable_set = {tuple(r) for r in result.walkable}
        # iz=1 voxels have solid below (iz=0 is solid) → all 9 pass
        assert all(iz == 1 for _, _, iz in walkable_set)
        assert len(result.walkable) == 9

    def test_build_wall_blocks_bfs(self):
        # Solid wall at z=2 cuts off z=3; only z=0 from floor filter (no solid floor)
        solid = {(x, y, 2) for x in range(3) for y in range(3)}
        vg = _make_vg(solid, nx=3, ny=3, nz=4)
        result = build(vg, {}, camera_ijk=(1, 1, 0))
        # BFS reaches z=0,1 (18 cells); floor filter: only iz=0 passes (no solid below z=0-1)
        assert len(result.walkable) == 9
        assert all(iz == 0 for _, _, iz in result.walkable)

    def test_build_explicit_camera_ijk(self):
        # 2×2×2, no solid → only iz=0 (4 cells)
        vg = _make_vg(set(), nx=2, ny=2, nz=2)
        result = build(vg, {}, camera_ijk=(0, 0, 0))
        assert len(result.walkable) == 4

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
