"""Tests for pipeline/voxel_grid.py save/load and helper utilities."""
import numpy as np
import pytest

from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
    VoxelGridData,
    _build_terrain_candidates,
    _flood_fill_candidates,
    _force_camera_walkable,
    load,
    save,
)


def _make_vg(**kwargs):
    defaults = dict(
        solid=np.empty((0, 3), dtype=np.int32),
        candidates=np.empty((0, 3), dtype=np.int32),
        nx=5, ny=5, nz=5,
        res=0.5,
        bounds=(0.0, 0.0, 2.5, 2.5, 0.0, 2.5),
        unit_scale=1.0,
        mode="global",
        hits=None,
    )
    defaults.update(kwargs)
    return VoxelGridData(**defaults)


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip_no_hits(self, tmp_path):
        solid = np.array([[0,0,0],[1,1,1]], dtype=np.int32)
        cand  = np.array([[2,2,2],[3,3,3]], dtype=np.int32)
        data = _make_vg(solid=solid, candidates=cand, nx=4, ny=4, nz=4,
                        res=0.75, bounds=(0.0,0.0,3.0,3.0,0.0,3.0),
                        unit_scale=1.0, mode="local")
        path = str(tmp_path / "vg.npz")
        save(data, path)
        loaded = load(path)

        np.testing.assert_array_equal(loaded.solid, data.solid)
        np.testing.assert_array_equal(loaded.candidates, data.candidates)
        assert loaded.nx == data.nx
        assert loaded.ny == data.ny
        assert loaded.nz == data.nz
        assert abs(loaded.res - data.res) < 1e-9
        assert loaded.bounds == data.bounds
        assert abs(loaded.unit_scale - data.unit_scale) < 1e-9
        assert loaded.mode == data.mode
        assert loaded.hits is None

    def test_roundtrip_with_hits(self, tmp_path):
        hits = np.array([[1.0,2.0,3.0],[4.0,5.0,6.0]], dtype=np.float64)
        data = _make_vg(hits=hits)
        path = str(tmp_path / "vg_hits.npz")
        save(data, path)
        loaded = load(path)
        np.testing.assert_array_almost_equal(loaded.hits, hits)

    def test_roundtrip_snake_mode(self, tmp_path):
        data = _make_vg(mode="snake")
        path = str(tmp_path / "vg_snake.npz")
        save(data, path)
        loaded = load(path)
        assert loaded.mode == "snake"

    def test_empty_arrays(self, tmp_path):
        data = _make_vg()
        path = str(tmp_path / "vg_empty.npz")
        save(data, path)
        loaded = load(path)
        assert loaded.solid.shape == (0, 3)
        assert loaded.candidates.shape == (0, 3)

    def test_bounds_tuple(self, tmp_path):
        bounds = (-1.0, -2.0, 3.0, 4.0, 0.0, 5.5)
        data = _make_vg(bounds=bounds)
        path = str(tmp_path / "vg_bounds.npz")
        save(data, path)
        loaded = load(path)
        assert len(loaded.bounds) == 6
        for a, b in zip(loaded.bounds, bounds):
            assert abs(a - b) < 1e-9


# ---------------------------------------------------------------------------
# _flood_fill_candidates
# ---------------------------------------------------------------------------

class TestFloodFillCandidates:
    def test_open_grid(self):
        result = _flood_fill_candidates(set(), (1,1,1), 3,3,3)
        assert len(result) == 27

    def test_wall_isolates(self):
        solid = {(x,y,2) for x in range(3) for y in range(3)}
        result = _flood_fill_candidates(solid, (0,0,0), 3,3,4)
        assert all(k <= 1 for _,_,k in result)

    def test_all_solid_returns_empty(self):
        solid = {(x,y,z) for x in range(2) for y in range(2) for z in range(2)}
        result = _flood_fill_candidates(solid, (0,0,0), 2,2,2)
        assert len(result) == 0

    def test_returns_int32(self):
        result = _flood_fill_candidates(set(), (0,0,0), 2,2,2)
        assert result.dtype == np.int32


# ---------------------------------------------------------------------------
# Terrain mode
# ---------------------------------------------------------------------------

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
        assert tuple(vg.candidates[0]) == (1, 1, 2)  # iz = round((2.0 - 0.0) / 1.0) = 2

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


# ---------------------------------------------------------------------------
# _force_camera_walkable
# ---------------------------------------------------------------------------

def _make_terrain_npz(tmp_path, camera_xyz, heightmap, res=1.0, unit_scale=1.0,
                      extra_arrays=None):
    """Write a minimal terrain_snake.npz to tmp_path and return its path."""
    nx, ny = heightmap.shape
    bounds = np.array([0.0, 0.0, float(nx) * res, float(ny) * res, 0.0, float(nx) * res * 2])
    arrays = dict(
        camera_xyz=np.array(camera_xyz, dtype=np.float64),
        heightmap=heightmap.astype(np.float64),
        bounds=bounds,
        res=np.float64(res),
        unit_scale=np.float64(unit_scale),
    )
    if extra_arrays:
        arrays.update(extra_arrays)
    path = str(tmp_path / "terrain.npz")
    np.savez_compressed(path, **arrays)
    return path


class TestForceCameraWalkable:
    def test_disabled_returns_vgd_unchanged(self, tmp_path):
        """force_camera_walkable=False → vgd returned unchanged (same object)."""
        hm = np.full((5, 5), 3.0)
        npz = _make_terrain_npz(tmp_path, [2.5, 3.5, 0.0], hm)
        vg = _make_vg(nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": npz, "force_camera_walkable": False})
        assert result is vg

    def test_no_terrain_npz_returns_unchanged(self):
        """No terrain_npz key → vgd returned unchanged."""
        vg = _make_vg()
        result = _force_camera_walkable(vg, {})
        assert result is vg

    def test_no_camera_xyz_in_npz_returns_unchanged(self, tmp_path):
        """terrain_npz without camera_xyz array → vgd returned unchanged."""
        hm = np.full((5, 5), 3.0)
        bounds = np.array([0.0, 0.0, 5.0, 5.0, 0.0, 10.0])
        path = str(tmp_path / "no_cam.npz")
        np.savez_compressed(path, heightmap=hm, bounds=bounds,
                            res=np.float64(1.0), unit_scale=np.float64(1.0))
        vg = _make_vg(nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": path})
        assert result is vg

    def test_camera_already_in_candidates_returns_unchanged(self, tmp_path):
        """Camera (ix,iy) already present in candidates → no-op, vgd unchanged."""
        hm = np.full((5, 5), 3.0)
        npz = _make_terrain_npz(tmp_path, [2.5, 3.5, 0.0], hm)
        # Put camera cell (ix=2, iy=3) already in candidates at any iz
        cands = np.array([[2, 3, 99]], dtype=np.int32)
        vg = _make_vg(candidates=cands, nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": npz})
        assert result is vg

    def test_all_nan_patch_returns_unchanged(self, tmp_path):
        """All-NaN heightmap patch under camera → no terrain data, vgd unchanged."""
        hm = np.full((5, 5), np.nan)
        npz = _make_terrain_npz(tmp_path, [2.5, 3.5, 0.0], hm)
        vg = _make_vg(candidates=np.empty((0, 3), dtype=np.int32),
                      nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": npz})
        assert result is vg

    def test_camera_cell_added_with_correct_iz(self, tmp_path):
        """Camera cell not in candidates → re-inserted at iz from heightmap patch."""
        # camera_xyz=[2.5, 3.5] → cam_ix=2, cam_iy=3 (res=1.0, bounds origin=0)
        # hm[2,3]=5.0, min_z=0.0, res=1.0 → iz = int((5.0-0.0)/1.0) = 5
        hm = np.zeros((5, 5))
        hm[2, 3] = 5.0
        npz = _make_terrain_npz(tmp_path, [2.5, 3.5, 0.0], hm)
        vg = _make_vg(candidates=np.empty((0, 3), dtype=np.int32),
                      nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": npz})
        cands = {tuple(r) for r in result.candidates}
        assert (2, 3, 5) in cands

    def test_iz_from_coarse_patch_average(self, tmp_path):
        """When vg.res > fine_res, iz is derived from the average of the fine patch."""
        # VG res=2.0, terrain fine_res=1.0 → scale=2.0
        # cam_xyz=[1.0,1.0] → cam_ix=0, cam_iy=0 (at res=2.0)
        # fine patch for coarse cell (0,0): hm[0:2, 0:2] = [[4,6],[2,8]] → mean=5.0
        # iz = int((5.0 - 0.0) / 2.0) = 2
        hm = np.array([[4.0, 6.0, 0.0, 0.0],
                       [2.0, 8.0, 0.0, 0.0],
                       [0.0, 0.0, 0.0, 0.0],
                       [0.0, 0.0, 0.0, 0.0]], dtype=np.float64)
        path = str(tmp_path / "fine.npz")
        np.savez_compressed(path,
                            camera_xyz=np.array([1.0, 1.0, 0.0]),
                            heightmap=hm,
                            bounds=np.array([0.0, 0.0, 4.0, 4.0, 0.0, 20.0]),
                            res=np.float64(1.0), unit_scale=np.float64(1.0))
        vg = _make_vg(candidates=np.empty((0, 3), dtype=np.int32),
                      nx=2, ny=2, nz=10, res=2.0,
                      bounds=(0.0, 0.0, 4.0, 4.0, 0.0, 20.0))
        result = _force_camera_walkable(vg, {"terrain_npz": path})
        cands = {tuple(r) for r in result.candidates}
        assert (0, 0, 2) in cands

    def test_forced_cell_is_prepended(self, tmp_path):
        """Forced camera cell is prepended — first in candidates array."""
        hm = np.zeros((5, 5))
        hm[1, 1] = 3.0   # → iz=3
        npz = _make_terrain_npz(tmp_path, [1.5, 1.5, 0.0], hm)
        # Existing candidates at other positions
        existing = np.array([[3, 3, 0], [4, 4, 0]], dtype=np.int32)
        vg = _make_vg(candidates=existing, nx=5, ny=5, nz=10, res=1.0,
                      bounds=(0.0, 0.0, 5.0, 5.0, 0.0, 10.0))
        result = _force_camera_walkable(vg, {"terrain_npz": npz})
        assert tuple(result.candidates[0]) == (1, 1, 3)
        assert len(result.candidates) == len(existing) + 1
