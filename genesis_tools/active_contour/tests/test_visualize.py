"""Tests for genesis_tools.active_contour.visualize — terrain_figure_6."""
import numpy as np
import pytest

from genesis_tools.active_contour.visualize import TerrainData, terrain_figure_6


def _make_td(nx=4, ny=4, vg_nx=2, vg_ny=2, has_voxels=True, has_path=False,
             walkable_frac=1.0):
    """Construct a minimal TerrainData for figure_6 tests.

    walkable_frac: fraction of coarse cells marked walkable (rest are valid-excluded).
    """
    hm = np.full((nx, ny), 3.0, dtype=np.float64)
    vg_walkable = np.ones((vg_nx, vg_ny), dtype=bool)
    vg_valid    = np.ones((vg_nx, vg_ny), dtype=bool)
    # If walkable_frac < 1, mark some cells as valid-but-excluded
    if walkable_frac < 1.0:
        n_excl = max(1, int(vg_nx * vg_ny * (1.0 - walkable_frac)))
        for k in range(n_excl):
            ix = k % vg_nx
            iy = k // vg_nx % vg_ny
            vg_walkable[ix, iy] = False

    pts = (np.array([[1.0, 1.0, 3.0], [2.5, 2.5, 3.0]], dtype=np.float64)
           if has_path else np.empty((0, 3), dtype=np.float64))
    wps = pts.copy()

    xs = np.arange(nx, dtype=np.float64)
    ys = np.arange(ny, dtype=np.float64)
    XX, YY = np.meshgrid(xs, ys, indexing="ij")

    return TerrainData(
        heightmap=hm,
        floor_raw=hm.copy(),
        disps=np.array([1.0, 0.5], dtype=np.float64),
        bounds=(0.0, 0.0, float(nx), float(ny), 0.0, 10.0),
        res=1.0, nx=nx, ny=ny,
        valid_floor=np.ones((nx, ny), dtype=bool),
        valid_hmap=np.ones((nx, ny), dtype=bool),
        bridged=np.zeros((nx, ny), dtype=bool),
        XX=XX, YY=YY,
        camera_xyz=np.array([2.0, 2.0, 0.0]),
        pts=pts, wps=wps,
        camera_height=1.7,
        has_path=has_path,
        vg_walkable=vg_walkable,
        vg_valid=vg_valid,
        vg_nx=vg_nx, vg_ny=vg_ny, vg_res=2.0,
        vg_bounds=(0.0, 0.0, float(nx), float(ny), 0.0, 10.0),
        has_voxels=has_voxels,
    )


class TestTerrainFigure6:
    def test_skipped_when_no_voxels(self, tmp_path):
        """has_voxels=False → function is a no-op; no figure file written."""
        td = _make_td(has_voxels=False)
        terrain_figure_6(td, tmp_path)
        assert not (tmp_path / "figure_6_voxel_walkability.png").exists()

    def test_creates_file_with_voxels(self, tmp_path):
        """has_voxels=True → figure_6_voxel_walkability.png is created."""
        td = _make_td(has_voxels=True)
        terrain_figure_6(td, tmp_path)
        assert (tmp_path / "figure_6_voxel_walkability.png").exists()

    def test_one_panel_without_path(self, tmp_path):
        """has_path=False → single-panel figure (file still created)."""
        td = _make_td(has_voxels=True, has_path=False)
        terrain_figure_6(td, tmp_path)
        assert (tmp_path / "figure_6_voxel_walkability.png").exists()

    def test_two_panels_with_path(self, tmp_path):
        """has_path=True → two-panel figure (file still created, larger)."""
        td_no_path = _make_td(has_voxels=True, has_path=False)
        td_with_path = _make_td(has_voxels=True, has_path=True)

        out_no  = tmp_path / "no_path.png"
        out_yes = tmp_path / "with_path.png"

        import shutil, pathlib
        # Generate without-path figure
        terrain_figure_6(td_no_path, tmp_path)
        shutil.move(str(tmp_path / "figure_6_voxel_walkability.png"), str(out_no))

        # Generate with-path figure
        terrain_figure_6(td_with_path, tmp_path)
        shutil.move(str(tmp_path / "figure_6_voxel_walkability.png"), str(out_yes))

        # Two-panel figure should be larger on disk than single-panel
        assert out_yes.stat().st_size > out_no.stat().st_size

    def test_green_walkable_cells_only(self, tmp_path):
        """All cells walkable → vg_valid & ~vg_walkable is empty (no red cells)."""
        td = _make_td(has_voxels=True, walkable_frac=1.0)
        n_excl = int((td.vg_valid & ~td.vg_walkable).sum())
        assert n_excl == 0
        terrain_figure_6(td, tmp_path)  # should not raise
        assert (tmp_path / "figure_6_voxel_walkability.png").exists()

    def test_mixed_walkable_excluded(self, tmp_path):
        """Some cells valid-but-excluded → vg_valid & ~vg_walkable is non-empty (red cells)."""
        td = _make_td(has_voxels=True, vg_nx=4, vg_ny=4, walkable_frac=0.5)
        n_excl = int((td.vg_valid & ~td.vg_walkable).sum())
        assert n_excl > 0
        terrain_figure_6(td, tmp_path)  # should not raise
        assert (tmp_path / "figure_6_voxel_walkability.png").exists()
