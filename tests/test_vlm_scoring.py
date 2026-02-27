"""Unit tests for genesis_tools.vlm_scoring module.

All external dependencies (VLM client, image encoding, filesystem) are mocked.
"""
from unittest.mock import MagicMock, patch

import pytest

from genesis_tools.vlm_scoring import tournament_select_best, vlm_compare_images


# ---------------------------------------------------------------------------
# Helper: build a fake OpenAI-style chat completion response
# ---------------------------------------------------------------------------


def _make_vlm_response(content: str) -> MagicMock:
    """Return a mock object that mimics OpenAI ChatCompletion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


# ---------------------------------------------------------------------------
# vlm_compare_images tests
# ---------------------------------------------------------------------------


@patch("genesis_tools.vlm_scoring.build_client")
@patch("genesis_tools.vlm_scoring.get_image_base64", return_value="data:image/png;base64,AAAA")
def test_vlm_compare_images_returns_1(mock_b64, mock_build):
    """When the VLM responds with '1', vlm_compare_images should return 1."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_vlm_response("1")
    mock_build.return_value = mock_client

    result = vlm_compare_images("img1.png", "img2.png", "target.png")

    assert result == 1
    assert mock_b64.call_count == 3
    mock_client.chat.completions.create.assert_called_once()


@patch("genesis_tools.vlm_scoring.build_client")
@patch("genesis_tools.vlm_scoring.get_image_base64", return_value="data:image/png;base64,AAAA")
def test_vlm_compare_images_returns_2(mock_b64, mock_build):
    """When the VLM responds with '2', vlm_compare_images should return 2."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_vlm_response("2")
    mock_build.return_value = mock_client

    result = vlm_compare_images("img1.png", "img2.png", "target.png")

    assert result == 2


@patch("genesis_tools.vlm_scoring.build_client")
@patch("genesis_tools.vlm_scoring.get_image_base64", return_value="data:image/png;base64,AAAA")
def test_vlm_compare_images_fallback(mock_b64, mock_build):
    """When the VLM returns unexpected text, default to 1."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_vlm_response(
        "I think image number one is better overall"
    )
    mock_build.return_value = mock_client

    result = vlm_compare_images("img1.png", "img2.png", "target.png")

    assert result == 1


@patch("genesis_tools.vlm_scoring.build_client")
@patch("genesis_tools.vlm_scoring.get_image_base64", side_effect=Exception("encoding error"))
def test_vlm_compare_images_exception(mock_b64, mock_build):
    """When an exception occurs during comparison, default to 1."""
    result = vlm_compare_images("img1.png", "img2.png", "target.png")

    assert result == 1


@patch("genesis_tools.vlm_scoring.build_client")
@patch("genesis_tools.vlm_scoring.get_image_base64", return_value="data:image/png;base64,AAAA")
@patch("genesis_tools.vlm_scoring.os.path.exists", return_value=True)
@patch("genesis_tools.vlm_scoring.os.path.isdir", return_value=True)
def test_vlm_compare_images_directory_target(mock_isdir, mock_exists, mock_b64, mock_build):
    """When target_path is a directory, the function should resolve to
    'visprompt1.png' inside it (the first candidate checked)."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_vlm_response("1")
    mock_build.return_value = mock_client

    result = vlm_compare_images("img1.png", "img2.png", "/some/dir")

    assert result == 1

    # The third call to get_image_base64 should use the resolved path
    # First two calls: img1.png, img2.png  --  Third call: the resolved target
    third_call_arg = mock_b64.call_args_list[2][0][0]
    assert "visprompt1.png" in third_call_arg


# ---------------------------------------------------------------------------
# tournament_select_best tests
# ---------------------------------------------------------------------------


def test_tournament_select_best_single():
    """A single candidate should win trivially (index 0)."""
    candidates = [{"image": ["render_0.png"]}]

    result = tournament_select_best(candidates, "target.png")

    assert result == 0


def test_tournament_select_best_empty():
    """An empty candidate list should return 0."""
    result = tournament_select_best([], "target.png")

    assert result == 0


@patch("genesis_tools.vlm_scoring.vlm_compare_images")
def test_tournament_select_best_two(mock_compare):
    """With two candidates, the winner is determined by vlm_compare_images.
    If vlm_compare_images returns 2, the second candidate (index 1) wins."""
    mock_compare.return_value = 2

    candidates = [
        {"image": ["render_0.png"]},
        {"image": ["render_1.png"]},
    ]

    result = tournament_select_best(candidates, "target.png")

    assert result == 1
    mock_compare.assert_called_once_with(
        "render_0.png", "render_1.png", "target.png", "gpt-4o"
    )


@patch("genesis_tools.vlm_scoring.vlm_compare_images")
def test_tournament_select_best_two_first_wins(mock_compare):
    """With two candidates, if vlm_compare_images returns 1, the first
    candidate (index 0) wins."""
    mock_compare.return_value = 1

    candidates = [
        {"image": ["render_0.png"]},
        {"image": ["render_1.png"]},
    ]

    result = tournament_select_best(candidates, "target.png")

    assert result == 0


@patch("genesis_tools.vlm_scoring.vlm_compare_images")
def test_tournament_select_best_no_renders(mock_compare):
    """A candidate with an empty image list should lose to one with renders.
    vlm_compare_images should NOT be called because the empty-list candidate
    is eliminated before comparison."""
    candidates = [
        {"image": []},
        {"image": ["render_1.png"]},
    ]

    result = tournament_select_best(candidates, "target.png")

    assert result == 1
    mock_compare.assert_not_called()


@patch("genesis_tools.vlm_scoring.vlm_compare_images")
def test_tournament_select_best_three_candidates(mock_compare):
    """With three candidates, two compete first, and the winner faces the
    bye candidate. Verifies the tournament bracket logic."""
    # Round 1: candidate 0 vs 1 -> 1 wins; candidate 2 gets a bye
    # Round 2: candidate 1 vs 2 -> 2 wins
    mock_compare.side_effect = [2, 2]

    candidates = [
        {"image": ["r0.png"]},
        {"image": ["r1.png"]},
        {"image": ["r2.png"]},
    ]

    result = tournament_select_best(candidates, "target.png")

    assert result == 2
    assert mock_compare.call_count == 2
