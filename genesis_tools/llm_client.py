"""Multi-provider LLM client with retry logic.

Supports OpenAI, Claude, Gemini, Groq, and Qwen via the OpenAI-compatible API.
All API keys are loaded from environment variables.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI


# Provider configuration: model name patterns -> (env key for API key, env key for base URL, default base URL)
_PROVIDERS = {
    "gpt": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "groq": ("GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    "llama": ("GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    "mixtral": ("GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    "meta-llama": ("GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    "qwen": (None, "QWEN_BASE_URL", "http://localhost:8000/v1"),
}


def _resolve_provider(model_name: str) -> tuple:
    """Resolve provider config from model name.

    Returns:
        Tuple of (api_key_env, base_url_env, default_base_url).

    Raises:
        ValueError: If model name doesn't match any known provider.
    """
    model_lower = model_name.lower()
    for pattern, config in _PROVIDERS.items():
        if pattern in model_lower:
            return config
    raise ValueError(
        f"Unknown model: {model_name}. "
        f"Supported patterns: {', '.join(_PROVIDERS.keys())}"
    )


def get_model_info(model_name: str) -> Dict[str, str]:
    """Get API key and base URL for the specified model.

    Args:
        model_name: Model identifier (e.g., 'gpt-4o', 'claude-3-opus').

    Returns:
        Dict with 'api_key' and 'base_url' keys.
    """
    api_key_env, base_url_env, default_base_url = _resolve_provider(model_name)

    api_key = os.environ.get(api_key_env, "") if api_key_env else "not_used"
    base_url = os.environ.get(base_url_env, default_base_url)

    return {"api_key": api_key, "base_url": base_url}


def build_client(model_name: str) -> OpenAI:
    """Build an OpenAI-compatible client for the specified model.

    API keys are read from environment variables:
    - OPENAI_API_KEY for GPT models
    - ANTHROPIC_API_KEY for Claude models
    - GEMINI_API_KEY for Gemini models
    - GROQ_API_KEY for Groq/Llama/Mixtral models
    - QWEN_BASE_URL for Qwen models (local, no key needed)

    Args:
        model_name: Model identifier (e.g., 'gpt-4o', 'claude-3-opus').

    Returns:
        Configured OpenAI client instance.
    """
    info = get_model_info(model_name)
    return OpenAI(api_key=info["api_key"], base_url=info["base_url"])


def get_model_response(
    client: OpenAI,
    chat_args: Dict[str, Any],
    num_candidates: int = 1,
    max_retries: int = 5,
    initial_delay: float = 30.0,
    max_delay: float = 120.0,
) -> List[Any]:
    """Get model responses with retry logic and exponential backoff.

    Args:
        client: OpenAI client instance.
        chat_args: Chat completion arguments (model, messages, etc.).
        num_candidates: Number of candidate responses to generate.
        max_retries: Maximum retries per candidate.
        initial_delay: Initial retry delay in seconds.
        max_delay: Maximum retry delay in seconds.

    Returns:
        List of candidate response objects.

    Raises:
        RuntimeError: If all retries fail for all candidates.
    """
    candidate_responses = []
    for _ in range(num_candidates):
        retries_left = max_retries
        retry_delay = initial_delay
        while retries_left > 0:
            try:
                response = client.chat.completions.create(**chat_args)
                candidate_responses.append(response)
                break
            except Exception as e:
                logging.error(f"API call failed: {e}")
                logging.error(f"Model: {chat_args.get('model')}")
                retries_left -= 1
                if retries_left > 0:
                    logging.info(
                        f"Retrying in {retry_delay:.0f}s... ({retries_left} retries left)"
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, max_delay)

    if not candidate_responses:
        raise RuntimeError("Failed to get any model response after all retries")
    return candidate_responses


def get_meshy_info() -> Dict[str, str]:
    """Get Meshy API key and VA API key from environment variables.

    Returns:
        Dict with 'meshy_api_key' and 'va_api_key' keys.
    """
    return {
        "meshy_api_key": os.environ.get("MESHY_API_KEY", ""),
        "va_api_key": os.environ.get("VA_API_KEY", ""),
    }
