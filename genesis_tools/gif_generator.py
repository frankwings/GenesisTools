"""GIF generation from rendered frames."""
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image


def create_gif(
    frames: List[Union[str, Path]],
    output_path: Union[str, Path],
    duration: int = 80,
    loop: int = 0,
    step: int = 1,
    output_scale: float = 1.0,
) -> Path:
    """Create a GIF from a list of image file paths.

    Args:
        frames: List of image file paths in order.
        output_path: Where to save the GIF.
        duration: Frame duration in milliseconds.
        loop: Number of loops (0 = infinite).
        step: Use every Nth frame (default 1 = all frames).
        output_scale: Resize factor (default 1.0 = original size).

    Returns:
        Path to the created GIF.
    """
    output_path = Path(output_path)
    if not frames:
        raise ValueError("No frames provided")

    selected = frames[::step]
    images = []
    for f in selected:
        img = Image.open(f)
        if output_scale != 1.0:
            w, h = img.size
            img = img.resize((int(w * output_scale), int(h * output_scale)), Image.LANCZOS)
        images.append(img)

    images[0].save(
        str(output_path),
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=loop,
    )
    return output_path


def create_pingpong_gif(
    frame_dir: Union[str, Path],
    pattern: str,
    output_path: Union[str, Path],
    duration: int = 80,
) -> Optional[Path]:
    """Create a ping-pong GIF (forward then reverse) from frames matching a glob pattern.

    Args:
        frame_dir: Directory containing frame images.
        pattern: Glob pattern to match frames (e.g., '*_y_*.png').
        output_path: Where to save the GIF.
        duration: Frame duration in milliseconds.

    Returns:
        Path to the created GIF, or None if no frames found.
    """
    frames = sorted(Path(frame_dir).glob(pattern))
    if not frames:
        return None

    images = [Image.open(f) for f in frames]
    pingpong = images + images[-2:0:-1]

    output_path = Path(output_path)
    pingpong[0].save(
        str(output_path),
        save_all=True,
        append_images=pingpong[1:],
        duration=duration,
        loop=0,
    )
    return output_path
