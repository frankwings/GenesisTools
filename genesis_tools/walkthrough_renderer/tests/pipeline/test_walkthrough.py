"""Tests for walkthrough.py orchestrator -- mocks subprocess and file I/O."""
import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


class TestWalkthroughRun:
    """Test the implicit-resume orchestrator."""

    def _write_fake_npz(self, path, **arrays):
        np.savez_compressed(path, **arrays)

    def _make_vg_file(self, path):
        np.savez_compressed(
            path,
            solid=np.empty((0,3), dtype=np.int32),
            candidates=np.array([[1,0,0],[2,0,0]], dtype=np.int32),
            nx=np.int32(5), ny=np.int32(5), nz=np.int32(5),
            res=np.float64(0.5),
            bounds=np.array([0.0,0.0,2.5,2.5,0.0,2.5]),
            unit_scale=np.float64(1.0),
            mode=np.array("global"),
        )

    def _make_wk_file(self, path):
        np.savez_compressed(path, walkable=np.array([[1,0,0],[2,0,0]], dtype=np.int32))

    def _make_pd_file(self, path):
        np.savez_compressed(
            path,
            waypoints=np.array([[1,0,0],[2,0,0]], dtype=np.int32),
            path_points=np.array([[0.75,0.25,0],[1.25,0.25,0]], dtype=np.float64),
            tour=np.array([0,1], dtype=np.int32),
            camera_height=np.float64(1.7),
            bounds=np.array([0.0,0.0,2.5,2.5,0.0,2.5]),
        )

    def _make_orient_file(self, path):
        with open(path, "w") as f:
            json.dump([], f)

    def test_resume_all_steps_existing(self, tmp_path):
        """When all output files exist, no subprocess is called."""
        out = tmp_path / "out"
        out.mkdir()
        self._make_vg_file(out / "voxel_grid.npz")
        self._make_wk_file(out / "walkable.npz")
        self._make_pd_file(out / "path.npz")
        self._make_orient_file(out / "wp_schedule.json")
        (out / "scene_walkthrough.blend").write_text("fake blend")

        config = {"camera_height": 1.7, "grid_resolution": 0.5, "fps": 12,
                  "num_waypoints": 5, "seed": 42}

        with patch("genesis_tools.walkthrough_renderer.walkthrough._run_bpy_module") as mock_run:
            from genesis_tools.walkthrough_renderer.walkthrough import run
            result = run("scene.blend", config, str(out))

        mock_run.assert_not_called()
        assert "blend_output" in result

    def test_missing_voxel_grid_triggers_step1(self, tmp_path):
        """When voxel_grid.npz is missing, step 1 subprocess is called."""
        out = tmp_path / "out"
        out.mkdir()

        config = {"camera_height": 1.7, "grid_resolution": 0.5, "fps": 12,
                  "num_waypoints": 5, "seed": 42}

        def fake_run(module, args):
            # Simulate step 1 creating its output file
            if "voxel_grid" in module:
                vg_out = next(a for i, a in enumerate(args) if args[i-1] == "--output")
                self._make_vg_file(Path(vg_out))
            elif "walkable" in module:
                pass  # will use in-process build
            elif "path_plan" in module:
                pd_out = next(a for i, a in enumerate(args) if args[i-1] == "--output")
                self._make_pd_file(Path(pd_out))
            elif "camera_orient" in module:
                orient_out = next(a for i, a in enumerate(args) if args[i-1] == "--output")
                self._make_orient_file(Path(orient_out))
            elif "camera_animate" in module:
                blend_out = next(a for i, a in enumerate(args) if args[i-1] == "--output-blend")
                Path(blend_out).write_text("fake blend")

        with patch("genesis_tools.walkthrough_renderer.walkthrough._run_bpy_module",
                   side_effect=fake_run):
            from genesis_tools.walkthrough_renderer.walkthrough import run
            result = run("scene.blend", config, str(out))

        assert (out / "voxel_grid.npz").exists()
        assert "blend_output" in result

    def test_step_outputs_in_result(self, tmp_path):
        """Result dict contains step_outputs with correct paths."""
        out = tmp_path / "out"
        out.mkdir()
        self._make_vg_file(out / "voxel_grid.npz")
        self._make_wk_file(out / "walkable.npz")
        self._make_pd_file(out / "path.npz")
        self._make_orient_file(out / "wp_schedule.json")
        (out / "scene_walkthrough.blend").write_text("fake blend")

        config = {"camera_height": 1.7, "grid_resolution": 0.5, "fps": 12,
                  "num_waypoints": 5, "seed": 42}

        with patch("genesis_tools.walkthrough_renderer.walkthrough._run_bpy_module"):
            from genesis_tools.walkthrough_renderer.walkthrough import run
            result = run("scene.blend", config, str(out))

        assert "step_outputs" in result
        assert "voxel_grid" in result["step_outputs"]
        assert "walkable"   in result["step_outputs"]
        assert "path"       in result["step_outputs"]
