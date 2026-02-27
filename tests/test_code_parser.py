"""Unit tests for genesis_tools.code_parser module."""
import json
from pathlib import Path

import pytest

from genesis_tools.code_parser import (
    extract_code_pieces,
    parse_groq_tool_call,
    save_thought_process,
)


# ---------------------------------------------------------------------------
# extract_code_pieces tests
# ---------------------------------------------------------------------------


class TestExtractCodePieces:
    def test_extract_code_pieces_single_block(self):
        text = (
            "Here is some code:\n"
            "```python\n"
            "print('hello')\n"
            "```\n"
            "That's it."
        )
        result = extract_code_pieces(text)
        assert result == "print('hello')"

    def test_extract_code_pieces_multiple_blocks(self):
        text = (
            "First block:\n"
            "```python\n"
            "x = 1\n"
            "```\n"
            "Second block:\n"
            "```python\n"
            "y = 2\n"
            "```\n"
        )
        result = extract_code_pieces(text, concat=True)
        assert "x = 1" in result
        assert "y = 2" in result
        # concat=True joins with double newline
        assert result == "x = 1\n\ny = 2"

    def test_extract_code_pieces_no_concat(self):
        text = (
            "```python\n"
            "a = 10\n"
            "```\n"
            "```python\n"
            "b = 20\n"
            "```\n"
        )
        result = extract_code_pieces(text, concat=False)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == "a = 10"
        assert result[1] == "b = 20"

    def test_extract_code_pieces_no_code(self):
        text = "There is no code here, just plain text."
        assert extract_code_pieces(text, concat=True) == ""
        assert extract_code_pieces(text, concat=False) == []

    def test_extract_code_pieces_unclosed_block(self):
        text = (
            "Unclosed block:\n"
            "```python\n"
            "print('no closing fence')\n"
        )
        result = extract_code_pieces(text)
        assert "print('no closing fence')" in result


# ---------------------------------------------------------------------------
# parse_groq_tool_call tests
# ---------------------------------------------------------------------------


class TestParseGroqToolCall:
    def test_parse_groq_tool_call_standard(self):
        content = '<function=myTool={"key": "value"}>'
        result = parse_groq_tool_call(content)
        assert result is not None
        assert result["name"] == "myTool"
        assert result["arguments"] == {"key": "value"}

    def test_parse_groq_tool_call_space_format(self):
        content = '<function=myTool {"key": "value"}>'
        result = parse_groq_tool_call(content)
        assert result is not None
        assert result["name"] == "myTool"
        assert result["arguments"] == {"key": "value"}

    def test_parse_groq_tool_call_none(self):
        assert parse_groq_tool_call(None) is None

    def test_parse_groq_tool_call_empty(self):
        assert parse_groq_tool_call("") is None

    def test_parse_groq_tool_call_no_match(self):
        assert parse_groq_tool_call("regular text") is None


# ---------------------------------------------------------------------------
# save_thought_process tests
# ---------------------------------------------------------------------------


class TestSaveThoughtProcess:
    def test_save_thought_process(self, tmp_path: Path):
        memory = [{"role": "assistant", "content": "thinking..."}]
        output_file = tmp_path / "thoughts.json"

        save_thought_process(memory, str(output_file))

        assert output_file.exists()
        with open(output_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == memory

    def test_save_thought_process_with_round(self, tmp_path: Path):
        memory = [{"step": 1, "note": "round 2 data"}]
        thought_dir = tmp_path / "thoughts"
        thought_dir.mkdir()

        save_thought_process(memory, str(thought_dir), current_round=2)

        expected_file = thought_dir / "3.json"
        assert expected_file.exists()
        with open(expected_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == memory
