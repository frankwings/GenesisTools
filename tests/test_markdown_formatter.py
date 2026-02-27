"""Unit tests for genesis_tools.markdown_formatter."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from genesis_tools.markdown_formatter import generate_documentation


def test_generate_documentation_basic():
    """Verify output contains title, description, commit hash, and timestamp."""
    result = generate_documentation(
        title="Test Title",
        algorithm_desc="This is a test algorithm.",
        commit_hash="abc123def",
    )

    assert "# Test Title" in result
    assert "This is a test algorithm." in result
    assert "`abc123def`" in result
    # Timestamp line should contain a UTC date string
    assert "UTC" in result
    assert "**Date**:" in result
    assert "**Commit**:" in result


@patch("genesis_tools.markdown_formatter.subprocess.run")
def test_generate_documentation_auto_hash(mock_run):
    """Mock subprocess.run to return a fake git hash, verify it appears in output."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "deadbeef1234567890\n"
    mock_run.return_value = mock_result

    result = generate_documentation(
        title="Auto Hash Test",
        algorithm_desc="Testing auto-detection of git hash.",
        # commit_hash omitted -- should auto-detect
    )

    assert "`deadbeef1234567890`" in result
    mock_run.assert_called_once_with(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_generate_documentation_with_images():
    """Pass image list, verify they appear as markdown image links."""
    images = [
        "/renders/scene_v1.png",
        Path("/renders/animation.gif"),
    ]

    result = generate_documentation(
        title="Visual Test",
        algorithm_desc="Checking image embedding.",
        commit_hash="img123",
        images=images,
    )

    assert "## Visuals" in result
    assert "![scene_v1](/renders/scene_v1.png)" in result
    assert "![animation](/renders/animation.gif)" in result


def test_generate_documentation_writes_file(tmp_path):
    """Use tmp_path fixture, verify file is written to disk."""
    output_file = tmp_path / "docs" / "report.md"

    result = generate_documentation(
        title="File Write Test",
        algorithm_desc="Testing file output.",
        commit_hash="file456",
        output_path=output_file,
    )

    assert output_file.exists()
    written_content = output_file.read_text(encoding="utf-8")
    assert written_content == result
    assert "# File Write Test" in written_content
