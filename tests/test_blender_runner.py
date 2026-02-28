"""Unit tests for genesis_tools.blender_runner module.

All tests mock subprocess and filesystem interactions — no real Blender
executable is required.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from genesis_tools.blender_runner import BlenderRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_blend(tmp_path: Path) -> Path:
    """Create a fake .blend file and return its path."""
    blend = tmp_path / "test_scene.blend"
    blend.write_bytes(b"FAKE BLEND DATA")
    return blend


def _make_runner(tmp_path: Path, **kwargs) -> BlenderRunner:
    """Create a BlenderRunner with a fake .blend file in tmp_path."""
    blend = _make_blend(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    return BlenderRunner(blend, work_dir, blender_command="blender", **kwargs)


def _make_subprocess_side_effect(stdout_content: str, stderr_content: str = ""):
    """Return a side_effect function that writes stdout/stderr to the files
    opened by _execute (positional args to open() in the subprocess.run call)."""
    def _side_effect(cmd, stdout, stderr, env, shell, timeout):
        # stdout and stderr are real file objects opened by _execute.
        stdout.write(stdout_content)
        stderr.write(stderr_content)
    return _side_effect


# ---------------------------------------------------------------------------
# Tests: find_blender()
# ---------------------------------------------------------------------------

class TestFindBlender:
    def test_find_blender_env_var(self, monkeypatch):
        monkeypatch.setenv("GENESIS_BLENDER_PATH", "/custom/blender")
        result = BlenderRunner.find_blender()
        assert result == "/custom/blender"

    def test_find_blender_which_fallback(self, monkeypatch):
        monkeypatch.delenv("GENESIS_BLENDER_PATH", raising=False)
        with patch("genesis_tools.blender_runner.os.path.isfile", return_value=False), \
             patch("genesis_tools.blender_runner.shutil.which", return_value="/usr/bin/blender"):
            result = BlenderRunner.find_blender()
        assert result == "/usr/bin/blender"

    def test_find_blender_ultimate_fallback(self, monkeypatch):
        monkeypatch.delenv("GENESIS_BLENDER_PATH", raising=False)
        with patch("genesis_tools.blender_runner.os.path.isfile", return_value=False), \
             patch("genesis_tools.blender_runner.shutil.which", return_value=None):
            result = BlenderRunner.find_blender()
        assert result == "blender"


# ---------------------------------------------------------------------------
# Tests: __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_creates_dirs(self, tmp_path: Path):
        blend = _make_blend(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        BlenderRunner(blend, work_dir, blender_command="blender")

        assert (work_dir / "scripts").is_dir()
        assert (work_dir / "renders").is_dir()
        assert (work_dir / "snapshots").is_dir()

    def test_init_takes_snapshot(self, tmp_path: Path):
        blend = _make_blend(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        BlenderRunner(blend, work_dir, blender_command="blender")

        snapshot = work_dir / "snapshots" / "0.blend"
        assert snapshot.exists()
        assert snapshot.read_bytes() == b"FAKE BLEND DATA"

    def test_init_missing_blend_raises(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.blend"
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="blend_file not found"):
            BlenderRunner(missing, work_dir, blender_command="blender")


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_success(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        result_payload = json.dumps({"status": "success", "renders": []})
        stdout_content = f"some blender output\nGENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            result = runner.run("print('hello')")

        assert result["status"] == "success"
        assert result["renders"] == []
        assert "stdout" in result
        # count should have incremented from 0 to 1
        assert runner._count == 1

    def test_run_error_from_genesis_result(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        result_payload = json.dumps({"status": "error", "message": "bad code"})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            result = runner.run("raise ValueError('bad code')")

        assert result["status"] == "error"
        assert "bad code" in result["message"]
        # count must NOT increment on error
        assert runner._count == 0

    def test_run_missing_genesis_result(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        stdout_content = "No result line here at all\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            result = runner.run("print('nothing')")

        assert result["status"] == "error"
        assert "No GENESIS_RESULT line found" in result["message"]
        assert runner._count == 0

    def test_run_subprocess_failure(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "blender"),
        ):
            result = runner.run("print('hello')")

        assert result["status"] == "error"
        assert runner._count == 0

    def test_run_script_write_failure(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = runner.run("print('hello')")

        assert result["status"] == "error"
        assert runner._count == 0

    def test_run_increments_count_only_on_success(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        assert runner._count == 0

        success_payload = json.dumps({"status": "success", "renders": []})
        stdout_ok = f"GENESIS_RESULT:{success_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_ok),
        ):
            runner.run("pass")

        assert runner._count == 1

        error_payload = json.dumps({"status": "error", "message": "oops"})
        stdout_err = f"GENESIS_RESULT:{error_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_err),
        ):
            runner.run("raise")

        # Count must remain at 1 — not incremented on error.
        assert runner._count == 1


# ---------------------------------------------------------------------------
# Tests: run_and_render()
# ---------------------------------------------------------------------------

class TestRunAndRender:
    def test_run_and_render_returns_render_paths(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        # Blender reports it wrote frame0001.png inside the render dir.
        result_payload = json.dumps({"status": "success", "renders": ["frame0001.png"]})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            result = runner.run_and_render("bpy.ops.render.render(write_still=True)")

        assert result["status"] == "success"
        assert len(result["renders"]) == 1
        render_path = result["renders"][0]
        # Must be an absolute path ending with the filename.
        assert os.path.isabs(render_path)
        assert render_path.endswith("frame0001.png")

    def test_run_and_render_error_no_renders_key_rewrite(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        result_payload = json.dumps({"status": "error", "message": "script crashed"})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            result = runner.run_and_render("bad()")

        assert result["status"] == "error"
        # On error, renders should NOT be rewritten to absolute paths
        # (the implementation only rewrites when status == "success").
        assert "renders" not in result or result.get("renders") != []

    def test_run_and_render_creates_render_subdir(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        result_payload = json.dumps({"status": "success", "renders": []})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            runner.run_and_render("pass")

        # render subdir "0" should have been created before calling _execute.
        expected_render_dir = runner._work_dir / "renders" / "0"
        assert expected_render_dir.is_dir()


# ---------------------------------------------------------------------------
# Tests: undo()
# ---------------------------------------------------------------------------

class TestUndo:
    def test_undo_at_zero_returns_error(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        assert runner._count == 0

        result = runner.undo()

        assert result["status"] == "error"
        assert "Nothing to undo" in result["message"]

    def test_undo_restores_snapshot(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        # Perform a successful run to create snapshot 1 and increment count.
        result_payload = json.dumps({"status": "success", "renders": []})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_make_subprocess_side_effect(stdout_content),
        ):
            runner.run("pass")

        assert runner._count == 1

        # Modify the blend file so we can verify it gets restored.
        runner._blend_file.write_bytes(b"MODIFIED BLEND DATA")

        result = runner.undo()

        assert result["status"] == "success"
        # The blend file should now match snapshot 0 (original content).
        assert runner._blend_file.read_bytes() == b"FAKE BLEND DATA"
        assert runner._count == 0

    def test_undo_missing_snapshot_returns_error(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        # Manually bump the count without creating a snapshot file.
        runner._count = 2

        result = runner.undo()

        assert result["status"] == "error"
        assert "Snapshot not found" in result["message"]

    def test_undo_multiple_times(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        result_payload = json.dumps({"status": "success", "renders": []})
        stdout_content = f"GENESIS_RESULT:{result_payload}\n"

        # Perform two successful runs.
        for _ in range(2):
            with patch(
                "genesis_tools.blender_runner.subprocess.run",
                side_effect=_make_subprocess_side_effect(stdout_content),
            ):
                runner.run("pass")

        assert runner._count == 2

        result = runner.undo()
        assert result["status"] == "success"
        assert runner._count == 1

        result = runner.undo()
        assert result["status"] == "success"
        assert runner._count == 0

        # Third undo should fail — back at initial state.
        result = runner.undo()
        assert result["status"] == "error"
        assert runner._count == 0


# ---------------------------------------------------------------------------
# Tests: get_scene_info()
# ---------------------------------------------------------------------------

class TestGetSceneInfo:
    def test_get_scene_info_success(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        sample_scene = {
            "objects": [{"name": "Cube", "type": "MESH", "location": [0.0, 0.0, 0.0]}],
            "materials": ["Material"],
            "camera": {"count": 1, "names": ["Camera"]},
            "light_count": 1,
        }

        def _side_effect_write_scene_info(cmd, stdout, stderr, env, shell, timeout):
            # The last positional arg in cmd is the output_path.
            # cmd is a list on Linux/Mac.
            output_path = cmd[-1]
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(sample_scene, fh)
            # stdout/stderr are real file objects.
            stdout.write("")
            stderr.write("")

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_side_effect_write_scene_info,
        ):
            result = runner.get_scene_info()

        assert result["status"] == "success"
        assert "scene" in result
        assert result["scene"]["objects"][0]["name"] == "Cube"
        assert result["scene"]["camera"]["count"] == 1

    def test_get_scene_info_subprocess_failure(self, tmp_path: Path):
        runner = _make_runner(tmp_path)

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=OSError("blender not found"),
        ):
            result = runner.get_scene_info()

        assert result["status"] == "error"
        assert "blender not found" in result["message"]

    def test_get_scene_info_no_output_file(self, tmp_path: Path):
        """Subprocess succeeds but does not write the scene info file."""
        runner = _make_runner(tmp_path)

        def _side_effect_no_file(cmd, stdout, stderr, env, shell, timeout):
            # Do not create the output file.
            stdout.write("")
            stderr.write("some blender error\n")

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_side_effect_no_file,
        ):
            result = runner.get_scene_info()

        assert result["status"] == "error"
        assert "not produced" in result["message"]

    def test_get_scene_info_invalid_json(self, tmp_path: Path):
        """Subprocess writes malformed JSON to the output file."""
        runner = _make_runner(tmp_path)

        def _side_effect_bad_json(cmd, stdout, stderr, env, shell, timeout):
            output_path = cmd[-1]
            with open(output_path, "w") as fh:
                fh.write("{ not valid json }")
            stdout.write("")
            stderr.write("")

        with patch(
            "genesis_tools.blender_runner.subprocess.run",
            side_effect=_side_effect_bad_json,
        ):
            result = runner.get_scene_info()

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: internal helpers / edge cases
# ---------------------------------------------------------------------------

class TestBuildCmd:
    def test_build_cmd_returns_list_on_linux(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        # Ensure we're testing the non-Windows branch.
        with patch("genesis_tools.blender_runner.sys.platform", "linux"):
            cmd = runner._build_cmd("/tmp/runner.py", ["arg1", "arg2"])
        assert isinstance(cmd, list)
        assert cmd[0] == "blender"
        assert "--background" in cmd
        assert "--python" in cmd
        assert "--" in cmd
        assert "arg1" in cmd
        assert "arg2" in cmd

    def test_build_env_sets_al_lib_loglevel(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        env = runner._build_env()
        assert env.get("AL_LIB_LOGLEVEL") == "0"

    def test_build_env_sets_cuda_when_gpu_devices(self, tmp_path: Path):
        blend = _make_blend(tmp_path)
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        runner = BlenderRunner(blend, work_dir, blender_command="blender", gpu_devices="0,1")
        env = runner._build_env()
        assert env.get("CUDA_VISIBLE_DEVICES") == "0,1"

    def test_build_env_no_cuda_when_gpu_devices_none(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        original_env = os.environ.copy()
        # Ensure CUDA_VISIBLE_DEVICES is not set in current env.
        original_env.pop("CUDA_VISIBLE_DEVICES", None)
        with patch("genesis_tools.blender_runner.os.environ", original_env):
            env = runner._build_env()
        assert "CUDA_VISIBLE_DEVICES" not in env


class TestParseResult:
    def test_parse_result_valid_success(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        payload = json.dumps({"status": "success", "renders": ["frame.png"]})
        stdout = f"blender noise\nGENESIS_RESULT:{payload}\nmore noise\n"
        result = runner._parse_result(stdout)
        assert result["status"] == "success"
        assert result["renders"] == ["frame.png"]

    def test_parse_result_valid_error(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        payload = json.dumps({"status": "error", "message": "oops"})
        stdout = f"GENESIS_RESULT:{payload}\n"
        result = runner._parse_result(stdout)
        assert result["status"] == "error"
        assert result["message"] == "oops"

    def test_parse_result_no_line(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        result = runner._parse_result("just some blender output\nno result here\n")
        assert result["status"] == "error"
        assert "No GENESIS_RESULT line found" in result["message"]

    def test_parse_result_invalid_json(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        result = runner._parse_result("GENESIS_RESULT:NOT_VALID_JSON\n")
        assert result["status"] == "error"
        assert "Could not parse GENESIS_RESULT JSON" in result["message"]

    def test_parse_result_uses_first_matching_line(self, tmp_path: Path):
        runner = _make_runner(tmp_path)
        first = json.dumps({"status": "success", "renders": []})
        second = json.dumps({"status": "error", "message": "second"})
        stdout = f"GENESIS_RESULT:{first}\nGENESIS_RESULT:{second}\n"
        result = runner._parse_result(stdout)
        # Should return the first GENESIS_RESULT encountered.
        assert result["status"] == "success"
