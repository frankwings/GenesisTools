"""Unit tests for genesis_tools.path_resolver."""
import json
import os
from unittest.mock import patch

import pytest

from genesis_tools.path_resolver import PathResolver


# ---------- __init__ ----------


def test_init_from_dict():
    """Create PathResolver with a dict config, verify conda_base and blender_command properties."""
    config = {
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
        "tool_environments": {},
    }
    resolver = PathResolver(config)

    assert resolver.conda_base == "/opt/conda/envs"
    assert resolver.blender_command == "/usr/bin/blender"


def test_init_from_file(tmp_path):
    """Create JSON config in tmp_path, create PathResolver from file path, verify properties."""
    config = {
        "conda_base": "/home/user/miniconda3/envs",
        "blender_command": "/snap/bin/blender",
        "tool_environments": {
            "tools/sam3d/sam_worker.py": "sam",
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    resolver = PathResolver(str(config_file))

    assert resolver.conda_base == "/home/user/miniconda3/envs"
    assert resolver.blender_command == "/snap/bin/blender"


# ---------- get_python_path ----------


@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_get_python_path_exists(mock_exists, mock_sys):
    """Mock os.path.exists to return True, verify returns conda env python path."""
    mock_sys.platform = "linux"
    mock_exists.return_value = True

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
    })

    result = resolver.get_python_path("sam")

    assert result == os.path.join("/opt/conda/envs", "sam", "bin", "python")
    mock_exists.assert_called_with(os.path.join("/opt/conda/envs", "sam", "bin", "python"))


@patch("genesis_tools.path_resolver.shutil.which")
@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_get_python_path_fallback(mock_exists, mock_sys, mock_which):
    """Mock os.path.exists to return False, mock shutil.which to return path, verify fallback."""
    mock_sys.platform = "linux"
    mock_exists.return_value = False
    mock_which.side_effect = lambda name: "/usr/bin/python3" if name == "python3" else None

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
    })

    result = resolver.get_python_path("nonexistent")

    assert result == "/usr/bin/python3"


@patch("genesis_tools.path_resolver.shutil.which")
@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_get_python_path_ultimate_fallback(mock_exists, mock_sys, mock_which):
    """Mock both os.path.exists and shutil.which to return False/None, verify returns 'python'."""
    mock_sys.platform = "linux"
    mock_exists.return_value = False
    mock_which.return_value = None

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
    })

    result = resolver.get_python_path("missing")

    assert result == "python"


# ---------- get_tool_command ----------


@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_get_tool_command(mock_exists, mock_sys):
    """Create PathResolver with tool_environments mapping, verify correct env is resolved."""
    mock_sys.platform = "linux"
    mock_exists.return_value = True

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
        "tool_environments": {
            "tools/sam3d/sam_worker.py": "sam",
            "tools/blender/exec.py": "blender",
        },
    })

    result = resolver.get_tool_command("tools/sam3d/sam_worker.py")

    expected = os.path.join("/opt/conda/envs", "sam", "bin", "python")
    assert result == expected


def test_get_tool_command_unknown():
    """Verify KeyError for unknown tool script."""
    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
        "tool_environments": {},
    })

    with pytest.raises(KeyError):
        resolver.get_tool_command("tools/unknown/script.py")


# ---------- environment variable detection ----------


def test_detect_conda_base_env_var(monkeypatch):
    """Set GENESIS_CONDA_BASE env var, verify it's used."""
    monkeypatch.setenv("GENESIS_CONDA_BASE", "/custom/conda/envs")

    resolver = PathResolver({
        "blender_command": "/usr/bin/blender",
    })

    assert resolver.conda_base == "/custom/conda/envs"


def test_detect_blender_env_var(monkeypatch):
    """Set GENESIS_BLENDER_PATH env var, verify it's used."""
    monkeypatch.setenv("GENESIS_BLENDER_PATH", "/custom/blender")

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
    })

    assert resolver.blender_command == "/custom/blender"


# ---------- platform detection ----------


@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_platform_detection_windows(mock_exists, mock_sys):
    """Test that Windows paths use python.exe (no bin/ subdirectory)."""
    mock_sys.platform = "win32"
    mock_exists.return_value = True

    resolver = PathResolver({
        "conda_base": r"C:\Users\dev\miniconda3\envs",
        "blender_command": r"C:\Program Files\Blender\blender.exe",
    })

    result = resolver.get_python_path("sam")

    expected = os.path.join(r"C:\Users\dev\miniconda3\envs", "sam", "python.exe")
    assert result == expected
    assert "bin" not in result


@patch("genesis_tools.path_resolver.sys")
@patch("genesis_tools.path_resolver.os.path.exists")
def test_platform_detection_linux(mock_exists, mock_sys):
    """Test that Linux paths use bin/python (no .exe extension)."""
    mock_sys.platform = "linux"
    mock_exists.return_value = True

    resolver = PathResolver({
        "conda_base": "/opt/conda/envs",
        "blender_command": "/usr/bin/blender",
    })

    result = resolver.get_python_path("sam")

    expected = os.path.join("/opt/conda/envs", "sam", "bin", "python")
    assert result == expected
    assert "bin" in result
    assert not result.endswith(".exe")
