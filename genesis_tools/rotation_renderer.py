"""High-level Python API for Blender rotation rendering.

Wraps render_rotation.py (single GLB object) and render_scene_rotation.py
(full .blend scene) Blender scripts, orchestrating subprocess calls and
converting frame sequences to GIFs via genesis_tools.gif_generator.

Usage example::

    from genesis_tools.rotation_renderer import (
        render_object_rotation_gifs,
        render_scene_rotation_gif,
    )

    # Single GLB object — produces Y and X rotation GIFs
    result = render_object_rotation_gifs(
        glb_path="chair.glb",
        output_dir="output/chair_rotation",
        frames=30,
        blender_command="blender",
    )
    print(result["y_rotation"])  # Path to *_y_rotation.gif
    print(result["x_rotation"])  # Path to *_x_rotation.gif

    # Full .blend scene — orbit camera GIF
    gif = render_scene_rotation_gif(
        blend_path="scene.blend",
        output_dir="output/scene_rotation",
        frames=24,
    )
"""
import subprocess
from pathlib import Path
from typing import Union

from genesis_tools.gif_generator import create_gif, create_pingpong_gif

# Blender script paths bundled inside this package
_SCRIPTS_DIR = Path(__file__).parent / "scripts"
RENDER_ROTATION_SCRIPT = _SCRIPTS_DIR / "render_rotation.py"
RENDER_SCENE_ROTATION_SCRIPT = _SCRIPTS_DIR / "render_scene_rotation.py"


def render_object_rotation_gifs(
    glb_path: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    frames: int = 30,
    resolution: int = 512,
    blender_command: str = "blender",
    duration: int = 80,
) -> dict:
    """Render Y-axis and X-axis rotation GIFs for a single GLB object.

    Calls Blender headlessly to render *frames* PNG frames per axis, then
    assembles them into two GIFs using genesis_tools.gif_generator.

    Args:
        glb_path:        Path to the input GLB file.
        output_dir:      Directory to store frames and GIFs.
        frames:          Number of frames per rotation axis (default 30).
        resolution:      Render resolution in pixels (square, default 512).
        blender_command: Path to the Blender executable (default 'blender').
        duration:        Frame duration in milliseconds for each GIF (default 80).

    Returns:
        dict with keys:
          - ``y_rotation``: Path to the Y-axis rotation GIF.
          - ``x_rotation``: Path to the X-axis rotation GIF.
          - ``frames_dir``: Path to the rendered PNG frames directory.
    """
    glb_path = Path(glb_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    cmd = [
        blender_command,
        "--background",
        "--python", str(RENDER_ROTATION_SCRIPT),
        "--",
        str(glb_path),
        str(frames_dir),
        "--frames", str(frames),
        "--resolution", str(resolution),
    ]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout.decode(errors="replace"))

    basename = glb_path.stem

    # Y-axis GIF (forward loop)
    y_frames = sorted(frames_dir.glob(f"{basename}_y_*.png"))
    y_gif = output_dir / f"{basename}_y_rotation.gif"
    create_gif(y_frames, y_gif, duration=duration)

    # X-axis GIF (ping-pong for smoother tumble effect)
    x_gif = output_dir / f"{basename}_x_rotation.gif"
    if not create_pingpong_gif(frames_dir, f"{basename}_x_*.png", x_gif, duration=duration):
        # Fallback: plain forward loop if ping-pong helper returns None
        x_frames = sorted(frames_dir.glob(f"{basename}_x_*.png"))
        create_gif(x_frames, x_gif, duration=duration)

    return {
        "y_rotation": y_gif,
        "x_rotation": x_gif,
        "frames_dir": frames_dir,
    }


def render_scene_rotation_gif(
    blend_path: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    frames: int = 24,
    resolution: int = 640,
    elevation: int = 25,
    blender_command: str = "blender",
    duration: int = 80,
) -> Path:
    """Render an orbit camera GIF for a full .blend scene.

    Opens the .blend file in Blender, adds an orbit camera around the scene
    bounding box, renders *frames* PNG frames at the given *elevation* angle,
    and assembles them into a looping GIF.

    Args:
        blend_path:      Path to the .blend file.
        output_dir:      Directory to store frames and the GIF.
        frames:          Number of orbit frames (default 24).
        resolution:      Render resolution in pixels (square, default 640).
        elevation:       Camera elevation angle in degrees (default 25).
        blender_command: Path to the Blender executable (default 'blender').
        duration:        Frame duration in milliseconds (default 80).

    Returns:
        Path to the output GIF file.
    """
    blend_path = Path(blend_path)
    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        blender_command,
        "--background",
        str(blend_path),
        "--python", str(RENDER_SCENE_ROTATION_SCRIPT),
        "--",
        str(frames_dir),
        "--frames", str(frames),
        "--resolution", str(resolution),
        "--elevation", str(elevation),
    ]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout.decode(errors="replace"))

    scene_frames = sorted(frames_dir.glob("scene_y_*.png"))
    gif_path = output_dir / "scene_rotation.gif"
    create_gif(scene_frames, gif_path, duration=duration)
    return gif_path
