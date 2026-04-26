"""Tests for render_scene_walkthrough() — mocks walkthrough.run and create_gif."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

from genesis_tools.walkthrough_renderer import render_scene_walkthrough


def _make_run_result(output_dir, blend_stem, n_frames=3):
    frames = [str(Path(output_dir) / "frames" / f"frame_{i:04d}.png") for i in range(n_frames)]
    return {
        "blend_output": str(Path(output_dir) / f"{blend_stem}_walkthrough.blend"),
        "frames": frames,
        "step_outputs": {
            "voxel_grid": str(Path(output_dir) / "voxel_grid.npz"),
            "walkable":   str(Path(output_dir) / "walkable.npz"),
            "path":       str(Path(output_dir) / "path.npz"),
        },
    }


@patch("genesis_tools.walkthrough_renderer.create_gif")
class TestRenderSceneWalkthrough(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".blend", delete=False)
        self._tmp.close()
        self.blend_path = self._tmp.name
        self.stem = Path(self.blend_path).stem

    def tearDown(self):
        os.unlink(self._tmp.name)

    # ------------------------------------------------------------------
    # 1. Returns expected keys
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_returns_expected_keys(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        result = render_scene_walkthrough(self.blend_path, "/tmp/wt")
        self.assertIn("blend_output", result)
        self.assertIn("gif", result)
        self.assertIn("frame_count", result)
        self.assertIn("step_outputs", result)

    # ------------------------------------------------------------------
    # 2. GIF path uses blend stem
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_gif_path_uses_blend_stem(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        render_scene_walkthrough(self.blend_path, "/tmp/wt")
        gif_out = mock_gif.call_args[0][1]
        self.assertTrue(str(gif_out).endswith(f"{self.stem}_walkthrough.gif"))

    # ------------------------------------------------------------------
    # 3. render=True is always passed to walkthrough.run
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_render_true_passed_to_run(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        render_scene_walkthrough(self.blend_path, "/tmp/wt")
        _, _, _, render_kwarg = mock_run.call_args[0][0], mock_run.call_args[0][1], mock_run.call_args[0][2], True
        # render is the 4th positional arg or keyword
        call_args, call_kwargs = mock_run.call_args
        render_val = call_kwargs.get("render", call_args[3] if len(call_args) > 3 else None)
        self.assertTrue(render_val)

    # ------------------------------------------------------------------
    # 4. Config params forwarded correctly
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_config_params_forwarded(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        render_scene_walkthrough(self.blend_path, "/tmp/wt", seed=99, num_waypoints=7)
        call_args = mock_run.call_args[0]
        config = call_args[1]
        self.assertEqual(config["seed"], 99)
        self.assertEqual(config["num_waypoints"], 7)
        self.assertTrue(config.get("render"))

    # ------------------------------------------------------------------
    # 5. frame_count matches frames list length
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_frame_count_matches_frames(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem, n_frames=5)
        result = render_scene_walkthrough(self.blend_path, "/tmp/wt")
        self.assertEqual(result["frame_count"], 5)

    # ------------------------------------------------------------------
    # 6. create_gif called once with correct output path
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_create_gif_called_once(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        render_scene_walkthrough(self.blend_path, "/tmp/wt")
        mock_gif.assert_called_once()

    # ------------------------------------------------------------------
    # 7. No GIF call when frames list is empty
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_no_gif_when_no_frames(self, mock_run, mock_gif):
        result_data = _make_run_result("/tmp/wt", self.stem, n_frames=0)
        mock_run.return_value = result_data
        result = render_scene_walkthrough(self.blend_path, "/tmp/wt")
        mock_gif.assert_not_called()
        self.assertEqual(result["frame_count"], 0)

    # ------------------------------------------------------------------
    # 8. gif_frame_duration forwarded to create_gif
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.walkthrough.run")
    def test_gif_frame_duration_forwarded(self, mock_run, mock_gif):
        mock_run.return_value = _make_run_result("/tmp/wt", self.stem)
        render_scene_walkthrough(self.blend_path, "/tmp/wt", gif_frame_duration=120)
        _, kwargs = mock_gif.call_args[0], mock_gif.call_args[1]
        self.assertEqual(kwargs.get("duration"), 120)


if __name__ == "__main__":
    unittest.main()
