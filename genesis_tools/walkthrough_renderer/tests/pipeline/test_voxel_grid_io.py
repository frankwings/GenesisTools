"""Tests for pipeline/voxel_grid.py save/load and helper utilities."""
import numpy as np
import pytest

from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
    VoxelGridData,
    _build_terrain_candidates,
    _flood_fill_candidates,
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
