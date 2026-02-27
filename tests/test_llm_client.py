"""Unit tests for genesis_tools.llm_client module.

All external dependencies (OpenAI client, environment variables) are mocked.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from genesis_tools.llm_client import (
    build_client,
    get_meshy_info,
    get_model_info,
    get_model_response,
)


# ---------------------------------------------------------------------------
# build_client tests
# ---------------------------------------------------------------------------


@patch("genesis_tools.llm_client.OpenAI")
def test_build_client_gpt(mock_openai_cls, monkeypatch):
    """build_client('gpt-4o') should create an OpenAI client with the correct
    API key and default OpenAI base URL."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123")
    # Remove any override so the default URL is used
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    build_client("gpt-4o")

    mock_openai_cls.assert_called_once_with(
        api_key="sk-test-key-123",
        base_url="https://api.openai.com/v1",
    )


@patch("genesis_tools.llm_client.OpenAI")
def test_build_client_claude(mock_openai_cls, monkeypatch):
    """build_client('claude-3') should use the Anthropic API key and base URL."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key-456")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    build_client("claude-3")

    mock_openai_cls.assert_called_once_with(
        api_key="ant-key-456",
        base_url="https://api.anthropic.com/v1",
    )


@patch("genesis_tools.llm_client.OpenAI")
def test_build_client_gemini(mock_openai_cls, monkeypatch):
    """build_client('gemini-pro') should use the Gemini API key and base URL."""
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key-789")
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)

    build_client("gemini-pro")

    mock_openai_cls.assert_called_once_with(
        api_key="gem-key-789",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


@patch("genesis_tools.llm_client.OpenAI")
def test_build_client_groq(mock_openai_cls, monkeypatch):
    """build_client('groq/llama-3') should use the Groq API key and base URL."""
    monkeypatch.setenv("GROQ_API_KEY", "groq-key-abc")
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)

    build_client("groq/llama-3")

    mock_openai_cls.assert_called_once_with(
        api_key="groq-key-abc",
        base_url="https://api.groq.com/openai/v1",
    )


@patch("genesis_tools.llm_client.OpenAI")
def test_build_client_qwen(mock_openai_cls, monkeypatch):
    """build_client('qwen-7b') should not require an API key and use localhost."""
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)

    build_client("qwen-7b")

    mock_openai_cls.assert_called_once_with(
        api_key="not_used",
        base_url="http://localhost:8000/v1",
    )


def test_build_client_unknown():
    """build_client with an unrecognised model name should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown model"):
        build_client("totally-unknown-model")


# ---------------------------------------------------------------------------
# get_model_info tests
# ---------------------------------------------------------------------------


def test_get_model_info(monkeypatch):
    """get_model_info should return the correct api_key and base_url from env."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-info-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    info = get_model_info("gpt-4o")

    assert info["api_key"] == "sk-info-key"
    assert info["base_url"] == "https://api.openai.com/v1"


def test_get_model_info_custom_base_url(monkeypatch):
    """get_model_info should respect a custom base URL override from env."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-custom")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.proxy/v1")

    info = get_model_info("gpt-4o")

    assert info["base_url"] == "https://custom.proxy/v1"


# ---------------------------------------------------------------------------
# get_model_response tests
# ---------------------------------------------------------------------------


def test_get_model_response_success():
    """A successful API call should return a list with one response."""
    mock_client = MagicMock()
    fake_response = MagicMock()
    mock_client.chat.completions.create.return_value = fake_response

    chat_args = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}

    result = get_model_response(mock_client, chat_args, num_candidates=1)

    assert len(result) == 1
    assert result[0] is fake_response
    mock_client.chat.completions.create.assert_called_once_with(**chat_args)


@patch("genesis_tools.llm_client.time.sleep")
def test_get_model_response_retry(mock_sleep):
    """If the API call fails twice then succeeds, we should get a response
    and time.sleep should have been called for the two retries."""
    mock_client = MagicMock()
    fake_response = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        RuntimeError("fail 1"),
        RuntimeError("fail 2"),
        fake_response,
    ]

    chat_args = {"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}]}

    result = get_model_response(
        mock_client,
        chat_args,
        num_candidates=1,
        max_retries=5,
        initial_delay=1.0,
        max_delay=10.0,
    )

    assert len(result) == 1
    assert result[0] is fake_response
    assert mock_sleep.call_count == 2


@patch("genesis_tools.llm_client.time.sleep")
def test_get_model_response_all_fail(mock_sleep):
    """If every retry fails, get_model_response should raise RuntimeError."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("always fails")

    chat_args = {"model": "gpt-4o", "messages": [{"role": "user", "content": "test"}]}

    with pytest.raises(RuntimeError, match="Failed to get any model response"):
        get_model_response(
            mock_client,
            chat_args,
            num_candidates=1,
            max_retries=3,
            initial_delay=0.1,
            max_delay=1.0,
        )

    # sleep is called (max_retries - 1) times because the last failure has no sleep
    assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# get_meshy_info tests
# ---------------------------------------------------------------------------


def test_get_meshy_info(monkeypatch):
    """get_meshy_info should return MESHY_API_KEY and VA_API_KEY from env."""
    monkeypatch.setenv("MESHY_API_KEY", "meshy-key-xyz")
    monkeypatch.setenv("VA_API_KEY", "va-key-999")

    info = get_meshy_info()

    assert info["meshy_api_key"] == "meshy-key-xyz"
    assert info["va_api_key"] == "va-key-999"


def test_get_meshy_info_missing_keys(monkeypatch):
    """get_meshy_info should return empty strings when env vars are absent."""
    monkeypatch.delenv("MESHY_API_KEY", raising=False)
    monkeypatch.delenv("VA_API_KEY", raising=False)

    info = get_meshy_info()

    assert info["meshy_api_key"] == ""
    assert info["va_api_key"] == ""
