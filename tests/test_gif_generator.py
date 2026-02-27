"""Unit tests for genesis_tools.gif_generator."""
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from genesis_tools.gif_generator import create_gif, create_pingpong_gif


# ---------- create_gif ----------


@patch("genesis_tools.gif_generator.Image")
def test_create_gif_basic(mock_image_module):
    """Mock Image.open to return mock images, verify save() is called with correct args."""
    mock_img_0 = MagicMock(name="img0")
    mock_img_1 = MagicMock(name="img1")
    mock_img_2 = MagicMock(name="img2")
    mock_image_module.open.side_effect = [mock_img_0, mock_img_1, mock_img_2]

    frames = ["frame0.png", "frame1.png", "frame2.png"]
    result = create_gif(frames, "output.gif", duration=100, loop=1)

    assert result == Path("output.gif")
    assert mock_image_module.open.call_count == 3

    mock_img_0.save.assert_called_once_with(
        str(Path("output.gif")),
        save_all=True,
        append_images=[mock_img_1, mock_img_2],
        duration=100,
        loop=1,
    )


def test_create_gif_empty_frames():
    """Verify ValueError is raised when no frames are provided."""
    with pytest.raises(ValueError, match="No frames provided"):
        create_gif([], "output.gif")


# ---------- create_pingpong_gif ----------


@patch("genesis_tools.gif_generator.Image")
@patch("genesis_tools.gif_generator.Path.glob")
def test_create_pingpong_gif_basic(mock_glob, mock_image_module):
    """Mock Path.glob to return sorted frames, verify ping-pong sequence."""
    # Simulate 4 sorted frame paths returned by glob
    frame_paths = [Path(f"/frames/frame_{i:03d}.png") for i in range(4)]
    mock_glob.return_value = frame_paths  # already sorted

    # Create distinct mock images for each frame
    mock_images = [MagicMock(name=f"img{i}") for i in range(4)]
    mock_image_module.open.side_effect = mock_images

    result = create_pingpong_gif("/frames", "frame_*.png", "/out/pingpong.gif", duration=50)

    assert result == Path("/out/pingpong.gif")

    # Ping-pong sequence: forward [0,1,2,3] + reverse-minus-endpoints [2,1]
    # So append_images should be images[1:] of the pingpong list
    # pingpong = [img0, img1, img2, img3, img2, img1]
    expected_append = [
        mock_images[1],
        mock_images[2],
        mock_images[3],
        mock_images[2],
        mock_images[1],
    ]

    mock_images[0].save.assert_called_once_with(
        str(Path("/out/pingpong.gif")),
        save_all=True,
        append_images=expected_append,
        duration=50,
        loop=0,
    )


@patch("genesis_tools.gif_generator.Path.glob")
def test_create_pingpong_gif_no_frames(mock_glob):
    """Verify returns None when no frames match the glob pattern."""
    mock_glob.return_value = []

    result = create_pingpong_gif("/empty", "*.png", "/out/nope.gif")

    assert result is None
