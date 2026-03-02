"""Unit tests for genesis_tools.gemini_cli.GeminiCLI.

All tests mock subprocess.run — no real gemini binary required.
"""
from unittest.mock import MagicMock, patch

import pytest

from genesis_tools.gemini_cli import GeminiCLI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(stdout="ok", returncode=0):
    """Build a mock CompletedProcess."""
    r = MagicMock()
    r.returncode = returncode
    r.stderr = ""
    r.stdout = stdout
    return r


def _patch_run(stdout="ok", returncode=0):
    """Patch subprocess.run to return a fake result."""
    return patch(
        "genesis_tools.gemini_cli.subprocess.run",
        return_value=_make_result(stdout, returncode),
    )


# ---------------------------------------------------------------------------
# TestCall
# ---------------------------------------------------------------------------

class TestCall:
    def test_text_only_empty_stdin(self):
        """No images → stdin is empty string."""
        with _patch_run() as mock_run:
            cli = GeminiCLI()
            cli.call("hello")
            _, kwargs = mock_run.call_args
            assert kwargs["input"] == ""

    def test_images_build_at_stdin(self):
        """Images list → stdin is '@path1 @path2'."""
        with _patch_run() as mock_run:
            cli = GeminiCLI()
            cli.call("hello", images=["/tmp/a.png", "/tmp/b.png"])
            _, kwargs = mock_run.call_args
            assert kwargs["input"] == "@/tmp/a.png @/tmp/b.png"

    def test_model_flag_added(self):
        """model='gemini-2.0-flash' → ['-m', 'gemini-2.0-flash'] in cmd."""
        with _patch_run() as mock_run:
            cli = GeminiCLI(model="gemini-2.0-flash")
            cli.call("hello")
            cmd = mock_run.call_args[0][0]
            assert "-m" in cmd
            assert "gemini-2.0-flash" in cmd

    def test_no_model_flag_when_none(self):
        """model=None → no '-m' flag in cmd."""
        with _patch_run() as mock_run:
            cli = GeminiCLI(model=None)
            cli.call("hello")
            cmd = mock_run.call_args[0][0]
            assert "-m" not in cmd

    def test_system_prompt_prepended(self):
        """system_prompt is prepended to prompt in the -p flag."""
        with _patch_run() as mock_run:
            cli = GeminiCLI()
            cli.call("user msg", system_prompt="sys msg")
            cmd = mock_run.call_args[0][0]
            p_idx = cmd.index("-p")
            combined = cmd[p_idx + 1]
            assert "sys msg" in combined
            assert "user msg" in combined
            assert combined.index("sys msg") < combined.index("user msg")

    def test_long_response_triggers_retry(self):
        """Response longer than max_response_chars triggers retry."""
        long_output = "x" * 3000
        short_output = "table"
        results = [
            _make_result(stdout=long_output),
            _make_result(stdout=short_output),
        ]
        with patch("genesis_tools.gemini_cli.subprocess.run", side_effect=results):
            cli = GeminiCLI(max_retries=3)
            result = cli.call("hello", max_response_chars=100)
            assert result == short_output

    def test_nonzero_returncode_retries(self):
        """Non-zero returncode triggers retry; raises RuntimeError on exhaustion."""
        fail = _make_result(returncode=1)
        with patch("genesis_tools.gemini_cli.subprocess.run", return_value=fail):
            cli = GeminiCLI(max_retries=2)
            with pytest.raises(RuntimeError):
                cli.call("hello")

    def test_returns_stripped_output(self):
        """Output is stripped of leading/trailing whitespace."""
        with _patch_run(stdout="  table  "):
            cli = GeminiCLI()
            result = cli.call("hello")
            assert result == "table"


# ---------------------------------------------------------------------------
# TestCallJson
# ---------------------------------------------------------------------------

class TestCallJson:
    def test_parses_valid_json(self):
        """Valid JSON response → dict returned."""
        with _patch_run(stdout='{"key": "value"}'):
            cli = GeminiCLI()
            result = cli.call_json("give me json")
            assert result == {"key": "value"}

    def test_strips_markdown_fences(self):
        """Response wrapped in ```json...``` → still parsed."""
        with _patch_run(stdout='```json\n{"a": 1}\n```'):
            cli = GeminiCLI()
            result = cli.call_json("give me json")
            assert result == {"a": 1}

    def test_appends_json_instruction(self):
        """'Return ONLY valid JSON' is appended to the prompt."""
        with patch("genesis_tools.gemini_cli.subprocess.run",
                   return_value=_make_result(stdout='{"x": 1}')) as mock_run:
            cli = GeminiCLI()
            cli.call_json("base prompt")
            cmd = mock_run.call_args[0][0]
            p_idx = cmd.index("-p")
            prompt_used = cmd[p_idx + 1]
            assert "valid JSON" in prompt_used

    def test_retries_on_parse_error(self):
        """Invalid JSON on first attempt → retries and returns valid JSON."""
        results = [
            _make_result(stdout="not json at all"),
            _make_result(stdout='{"fixed": true}'),
        ]
        with patch("genesis_tools.gemini_cli.subprocess.run", side_effect=results):
            cli = GeminiCLI(max_retries=3)
            result = cli.call_json("prompt")
            assert result == {"fixed": True}
