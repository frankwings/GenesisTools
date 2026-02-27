"""JSON config loading with environment variable overrides."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union


def load_config(
    config_path: Union[str, Path],
    env_prefix: str = "GENESIS_",
) -> Dict[str, Any]:
    """Load a JSON configuration file with environment variable overrides.

    Environment variables matching {env_prefix}{UPPER_KEY} override config values.
    For example, GENESIS_MAX_ITERATIONS=10 overrides config["max_iterations"].

    Nested keys use double underscore: GENESIS_GENERATION__QUALITY=high
    overrides config["generation"]["quality"].

    Args:
        config_path: Path to the JSON config file.
        env_prefix: Prefix for environment variable overrides.

    Returns:
        Configuration dictionary.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        json.JSONDecodeError: If config file is invalid JSON.
    """
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    _apply_env_overrides(config, env_prefix)
    return config


def _apply_env_overrides(
    config: Dict[str, Any],
    env_prefix: str,
    current_path: str = "",
) -> None:
    """Apply environment variable overrides to a config dict (in-place)."""
    for key, value in list(config.items()):
        env_key = f"{env_prefix}{current_path}{key}".upper()
        env_val = os.environ.get(env_key)

        if isinstance(value, dict):
            _apply_env_overrides(value, env_prefix, f"{current_path}{key}__")
        elif env_val is not None:
            # Type-coerce based on original value type
            if isinstance(value, bool):
                config[key] = env_val.lower() in ("true", "1", "yes")
            elif isinstance(value, int):
                try:
                    config[key] = int(env_val)
                except ValueError:
                    config[key] = env_val
            elif isinstance(value, float):
                try:
                    config[key] = float(env_val)
                except ValueError:
                    config[key] = env_val
            else:
                config[key] = env_val
