"""Unit tests for genesis_tools.walkthrough_renderer.

All tests mock subprocess.run and create_gif — no real Blender or PIL required.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from genesis_tools.walkthrough_renderer import render_scene_walkthrough, RENDER_WALKTHROUGH_SCRIPT


# Helpers -----------------------------------------------------------------

def _make_result(**kwargs):
    """Return encoded subprocess stdout bytes containing WALKTHROUGH_RESULT."""
    payload = {
        "status": "success",
        "blend_output": "/out/scene_walkthrough.blend",
        "frames_dir": "/out/frames",
        "path_points_count": 100,
        "free_cells_count": 400,
        "interesting_objects_count": 5,
        **kwargs,
    }
    line = "WALKTHROUGH_RESULT:" + json.dumps(payload)
    return line.encode()


def _run_mock(stdout_bytes):
    mock = MagicMock()
    mock.stdout = stdout_bytes
    return mock


# Tests -------------------------------------------------------------------

@patch("genesis_tools.walkthrough_renderer.create_gif")
class TestRenderSceneWalkthrough(unittest.TestCase):
    """All tests patch both subprocess.run and create_gif."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".blend", delete=False)
        self._tmp.close()
        self.blend_path = self._tmp.name

    def tearDown(self):
        os.unlink(self._tmp.name)

    # ------------------------------------------------------------------
    # 1. Happy path — result dict has expected keys + gif key present
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_default_params_returns_result_dict(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(_make_result())
        result = render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        self.assertIn("blend_output", result)
        self.assertIn("path_points_count", result)
        self.assertIn("free_cells_count", result)
        self.assertIn("interesting_objects_count", result)
        self.assertIn("gif", result)
        self.assertEqual(result["status"], "success")

    # ------------------------------------------------------------------
    # 2. Output .blend filename uses stem + "_walkthrough"
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_blend_output_stem_naming(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(_make_result())
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        cmd = mock_run.call_args[0][0]
        idx = cmd.index("--output-blend")
        output_blend_arg = cmd[idx + 1]
        stem = Path(self.blend_path).stem
        self.assertTrue(
            output_blend_arg.endswith(f"{stem}_walkthrough.blend"),
            f"Expected stem '{stem}_walkthrough.blend', got: {output_blend_arg}",
        )

    # ------------------------------------------------------------------
    # 3. Config JSON written and path passed after --config
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_config_json_written_and_path_passed(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(_make_result())
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out", seed=99)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--config", cmd)
        config_path = cmd[cmd.index("--config") + 1]
        self.assertTrue(config_path.endswith(".json"), config_path)

    # ------------------------------------------------------------------
    # 4. render is always True in config (GIF requires frames)
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_render_always_true_in_config(self, mock_run, mock_gif):
        captured_config = {}

        def capture_run(cmd, **kwargs):
            config_path = cmd[cmd.index("--config") + 1]
            with open(config_path) as fh:
                captured_config.update(json.load(fh))
            return _run_mock(_make_result())

        mock_run.side_effect = capture_run
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        self.assertTrue(captured_config.get("render"), "render must always be True")

    # ------------------------------------------------------------------
    # 5. --render-engine is passed in the command
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_render_engine_passed_in_cmd(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(_make_result())
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out", render_engine="WORKBENCH")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--render-engine", cmd)
        idx = cmd.index("--render-engine")
        self.assertEqual(cmd[idx + 1], "WORKBENCH")

    # ------------------------------------------------------------------
    # 6. WALKTHROUGH_RESULT line is correctly parsed
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_result_line_parsed_correctly(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(
            b"Blender startup noise\n"
            b"WALKTHROUGH_RESULT:" + json.dumps({
                "status": "success",
                "blend_output": "/x/y_walkthrough.blend",
                "frames_dir": "/x/frames",
                "path_points_count": 42,
                "free_cells_count": 200,
                "interesting_objects_count": 3,
            }).encode()
        )
        result = render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        self.assertEqual(result["path_points_count"], 42)
        self.assertEqual(result["free_cells_count"], 200)

    # ------------------------------------------------------------------
    # 7. Missing WALKTHROUGH_RESULT raises RuntimeError
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_missing_result_line_raises_runtime_error(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(b"Blender crash log\nNo result here\n")
        with self.assertRaises(RuntimeError):
            render_scene_walkthrough(self.blend_path, "/tmp/wt_out")

    # ------------------------------------------------------------------
    # 8. Temp config file deleted after successful run
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_temp_file_cleaned_up_on_success(self, mock_run, mock_gif):
        saved_path = []

        def capture_and_succeed(cmd, **kwargs):
            saved_path.append(cmd[cmd.index("--config") + 1])
            return _run_mock(_make_result())

        mock_run.side_effect = capture_and_succeed
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        self.assertFalse(os.path.exists(saved_path[0]))

    # ------------------------------------------------------------------
    # 9. Temp config file deleted even on subprocess failure
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_temp_file_cleaned_up_on_failure(self, mock_run, mock_gif):
        saved_path = []

        def capture_and_fail(cmd, **kwargs):
            saved_path.append(cmd[cmd.index("--config") + 1])
            raise OSError("blender not found")

        mock_run.side_effect = capture_and_fail
        with self.assertRaises(OSError):
            render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        self.assertFalse(os.path.exists(saved_path[0]))

    # ------------------------------------------------------------------
    # 10. RENDER_WALKTHROUGH_SCRIPT is inside the sub-package
    # ------------------------------------------------------------------
    def test_render_walkthrough_script_is_inside_subpackage(self, mock_gif):
        self.assertTrue(RENDER_WALKTHROUGH_SCRIPT.exists())
        self.assertEqual(RENDER_WALKTHROUGH_SCRIPT.name, "render_walkthrough.py")

    # ------------------------------------------------------------------
    # 11. create_gif is called with PNG frames from frames_dir
    # ------------------------------------------------------------------
    @patch("genesis_tools.walkthrough_renderer.subprocess.run")
    def test_create_gif_called_after_render(self, mock_run, mock_gif):
        mock_run.return_value = _run_mock(_make_result(frames_dir="/out/frames"))
        render_scene_walkthrough(self.blend_path, "/tmp/wt_out")
        mock_gif.assert_called_once()
        # Second positional arg is the gif output path
        gif_out = mock_gif.call_args[0][1]
        stem = Path(self.blend_path).stem
        self.assertTrue(str(gif_out).endswith(f"{stem}_walkthrough.gif"))


if __name__ == "__main__":
    unittest.main()
