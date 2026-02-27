"""Config-driven Python environment path resolution."""
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, Union


class PathResolver:
    """Resolve Python interpreter paths for tool scripts based on config.

    Config format (JSON):
    {
        "conda_base": "/path/to/miniconda3/envs",  // optional, auto-detected
        "blender_command": "/usr/local/bin/blender",  // optional
        "tool_environments": {
            "tools/blender/exec.py": "blender",
            "tools/sam3d/sam_worker.py": "sam"
        }
    }
    """

    def __init__(self, config: Union[str, Path, Dict]) -> None:
        """Initialize from a config file path or dict.

        Args:
            config: Path to JSON config file, or dict with config values.
        """
        if isinstance(config, dict):
            self._config = config
        else:
            import json
            with open(config, "r", encoding="utf-8") as f:
                self._config = json.load(f)

        self._conda_base = self._config.get("conda_base") or self._detect_conda_base()
        self._blender_command = self._config.get("blender_command") or self._detect_blender()
        self._tool_environments: Dict[str, str] = self._config.get("tool_environments", {})

    @staticmethod
    def _detect_conda_base() -> str:
        """Auto-detect conda environments base path."""
        env_val = os.environ.get("GENESIS_CONDA_BASE")
        if env_val:
            return env_val
        if sys.platform == "win32":
            return os.path.join(os.path.expanduser("~"), "miniconda3", "envs")
        return os.path.join(os.path.expanduser("~"), "miniconda3", "envs")

    @staticmethod
    def _detect_blender() -> str:
        """Auto-detect Blender command."""
        env_val = os.environ.get("GENESIS_BLENDER_PATH")
        if env_val:
            return env_val
        if sys.platform == "win32":
            return r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
        return "/usr/local/bin/blender"

    def get_python_path(self, env_name: str) -> str:
        """Get Python interpreter path for a conda environment.

        Args:
            env_name: Name of the conda environment.

        Returns:
            Path to the Python interpreter.
        """
        if sys.platform == "win32":
            conda_python = os.path.join(self._conda_base, env_name, "python.exe")
        else:
            conda_python = os.path.join(self._conda_base, env_name, "bin", "python")

        if os.path.exists(conda_python):
            return conda_python

        python_path = shutil.which("python3") or shutil.which("python")
        return python_path or "python"

    def get_tool_command(self, tool_script: str) -> str:
        """Get the Python command for a tool script based on its environment mapping.

        Args:
            tool_script: Relative path to the tool script (e.g., 'tools/sam3d/sam_worker.py').

        Returns:
            Path to the appropriate Python interpreter.

        Raises:
            KeyError: If tool_script is not in the environment mapping.
        """
        env_name = self._tool_environments[tool_script]
        return self.get_python_path(env_name)

    @property
    def blender_command(self) -> str:
        """Get the Blender executable path."""
        return self._blender_command

    @property
    def conda_base(self) -> str:
        """Get the conda environments base directory."""
        return self._conda_base
