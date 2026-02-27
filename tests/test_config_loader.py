"""Unit tests for genesis_tools.config_loader module."""
import json
from pathlib import Path

import pytest

from genesis_tools.config_loader import load_config


class TestLoadConfig:
    def test_load_config_basic(self, tmp_path: Path):
        config_data = {"model_version": "v1", "max_iterations": 5}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        result = load_config(config_file)
        assert result == config_data

    def test_load_config_env_override_string(self, tmp_path: Path, monkeypatch):
        config_data = {"model_version": "v1"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        monkeypatch.setenv("GENESIS_MODEL_VERSION", "v2")
        result = load_config(config_file)
        assert result["model_version"] == "v2"

    def test_load_config_env_override_int(self, tmp_path: Path, monkeypatch):
        config_data = {"max_iterations": 5}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        monkeypatch.setenv("GENESIS_MAX_ITERATIONS", "10")
        result = load_config(config_file)
        assert result["max_iterations"] == 10
        assert isinstance(result["max_iterations"], int)

    def test_load_config_env_override_bool(self, tmp_path: Path, monkeypatch):
        config_data = {"verbose": False}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        monkeypatch.setenv("GENESIS_VERBOSE", "true")
        result = load_config(config_file)
        assert result["verbose"] is True
        assert isinstance(result["verbose"], bool)

    def test_load_config_nested_override(self, tmp_path: Path, monkeypatch):
        config_data = {"generation": {"quality": "high"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        monkeypatch.setenv("GENESIS_GENERATION__QUALITY", "low")
        result = load_config(config_file)
        assert result["generation"]["quality"] == "low"

    def test_load_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_load_config_invalid_json(self, tmp_path: Path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("{ this is not valid json }", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_config(config_file)
