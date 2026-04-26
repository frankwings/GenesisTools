"""Tests for visualize.py -- mocks bpy file I/O and verifies layer dispatch."""
from unittest.mock import MagicMock, patch, call
import numpy as np
import pytest

# bpy is already mocked by conftest.py
import bpy  # noqa: F401 -- ensure mock is in place

from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import VoxelGridData
from genesis_tools.walkthrough_renderer.pipeline.walkable import WalkableData
from genesis_tools.walkthrough_renderer.pipeline.path_plan import PathData


def _make_vg():
    return VoxelGridData(
        solid=np.array([[0,0,0]], dtype=np.int32),
        candidates=np.array([[1,0,0],[2,0,0]], dtype=np.int32),
        nx=4, ny=4, nz=4, res=0.5,
        bounds=(0.0,0.0,2.0,2.0,0.0,2.0),
        unit_scale=1.0, mode="global", hits=None,
    )


def _make_wk():
    return WalkableData(walkable=np.array([[1,0,0],[2,0,0]], dtype=np.int32))


def _make_pd():
    return PathData(
        waypoints=np.array([[1,0,0],[2,0,0]], dtype=np.int32),
        path_points=np.array([[0.75,0.25,0.0],[1.25,0.25,0.0]], dtype=np.float64),
        tour=np.array([0,1], dtype=np.int32),
        camera_height=1.7,
        bounds=(0.0,0.0,2.0,2.0,0.0,2.0),
    )


class TestVisualize:
    def test_no_layers_opens_and_saves(self, tmp_path):
        """visualize() with no data files just opens and saves the blend."""
        from genesis_tools.walkthrough_renderer import visualize as viz_mod
        import bpy

        bpy.ops.wm.open_mainfile.reset_mock()
        bpy.ops.wm.save_as_mainfile.reset_mock()

        out = str(tmp_path / "debug.blend")
        viz_mod.visualize("scene.blend", out)

        bpy.ops.wm.open_mainfile.assert_called_once_with(filepath="scene.blend")
        bpy.ops.wm.save_as_mainfile.assert_called_once_with(filepath=out)

    def test_voxel_grid_layer_called(self, tmp_path):
        """Passing voxel_grid triggers add_voxel_grid_layer."""
        from genesis_tools.walkthrough_renderer import visualize as viz_mod

        vg = _make_vg()
        vg_path = str(tmp_path / "vg.npz")
        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import save as vg_save
        vg_save(vg, vg_path)

        with patch(
            "genesis_tools.walkthrough_renderer.viz.layers.add_voxel_grid_layer"
        ) as mock_layer:
            viz_mod.visualize("scene.blend", str(tmp_path / "out.blend"),
                              voxel_grid=vg_path)
        mock_layer.assert_called_once()

    def test_walkable_layer_requires_voxel_grid(self, tmp_path, capsys):
        """Passing walkable without voxel_grid prints warning, no crash."""
        from genesis_tools.walkthrough_renderer import visualize as viz_mod

        wk = _make_wk()
        wk_path = str(tmp_path / "wk.npz")
        from genesis_tools.walkthrough_renderer.pipeline.walkable import save as wk_save
        wk_save(wk, wk_path)

        viz_mod.visualize("scene.blend", str(tmp_path / "out.blend"),
                          walkable=wk_path)
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_path_layer_called(self, tmp_path):
        """Passing path triggers add_path_layer."""
        from genesis_tools.walkthrough_renderer import visualize as viz_mod

        pd = _make_pd()
        pd_path = str(tmp_path / "path.npz")
        from genesis_tools.walkthrough_renderer.pipeline.path_plan import save as pd_save
        pd_save(pd, pd_path)

        with patch(
            "genesis_tools.walkthrough_renderer.viz.layers.add_path_layer"
        ) as mock_layer:
            viz_mod.visualize("scene.blend", str(tmp_path / "out.blend"),
                              path=pd_path)
        mock_layer.assert_called_once()

    def test_all_layers_together(self, tmp_path):
        """Passing all three data files triggers all three layer functions."""
        from genesis_tools.walkthrough_renderer import visualize as viz_mod

        vg = _make_vg()
        vg_path = str(tmp_path / "vg.npz")
        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import save as vg_save
        vg_save(vg, vg_path)

        wk = _make_wk()
        wk_path = str(tmp_path / "wk.npz")
        from genesis_tools.walkthrough_renderer.pipeline.walkable import save as wk_save
        wk_save(wk, wk_path)

        pd = _make_pd()
        pd_path = str(tmp_path / "path.npz")
        from genesis_tools.walkthrough_renderer.pipeline.path_plan import save as pd_save
        pd_save(pd, pd_path)

        with patch("genesis_tools.walkthrough_renderer.viz.layers.add_voxel_grid_layer") as m1, \
             patch("genesis_tools.walkthrough_renderer.viz.layers.add_walkable_layer") as m2, \
             patch("genesis_tools.walkthrough_renderer.viz.layers.add_path_layer") as m3:
            viz_mod.visualize("scene.blend", str(tmp_path / "out.blend"),
                              voxel_grid=vg_path, walkable=wk_path, path=pd_path)

        m1.assert_called_once()
        m2.assert_called_once()
        m3.assert_called_once()
