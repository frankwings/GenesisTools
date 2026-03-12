"""Scene walkthrough renderer for GenesisTools.

Automatically generates a patrol-style camera walkthrough GIF inside any
Blender ``.blend`` scene:

- Raycast floor detection with normal filtering (avoids "roof walking")
- Capsule-style obstacle avoidance (3-height cylinder sweep)
- Coverage path via farthest-point sampling + greedy TSP tour
- Catmull-Rom spline smoothing with post-smooth snap to free cells
- Smart look-at: volume/distance² scoring with per-frame line-of-sight check
- QUATERNION rotation mode to prevent gimbal lock
- PNG frames → GIF assembled via genesis_tools.gif_generator

Usage::

    from genesis_tools import render_scene_walkthrough

    result = render_scene_walkthrough(
        blend_path="scene.blend",
        output_dir="output/walkthrough",
        duration_seconds=10.0,
        num_waypoints=12,
        blender_command="blender",
    )
    print(result["gif"])           # path to walkthrough GIF
    print(result["blend_output"])  # path to animated .blend
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from subprocess import PIPE, STDOUT
from typing import Union

from genesis_tools.gif_generator import create_gif

# Blender script lives alongside this __init__.py inside the sub-package.
RENDER_WALKTHROUGH_SCRIPT = Path(__file__).parent / "render_walkthrough.py"


def render_scene_walkthrough(
    blend_path: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    camera_height: float = 1.7,
    grid_resolution: float = 0.5,
    max_grid_cells_xy: int = 80,
    max_grid_cells_z: int = 40,
    obstacle_radius: float = 0.5,
    fps: int = 12,
    duration_seconds: float = None,
    max_duration_seconds: float = 60.0,
    walk_speed_mps: float = 2.5,
    num_waypoints: int = 20,
    look_range: float = 15.0,
    rotation_smooth_seconds: float = 2.0,
    gif_frame_duration: int = 80,
    render_engine: str = "CYCLES",
    seed: int = 42,
    local_area_ratio: float = None,
    local_height: float = 8.0,
    render_width: int = 1280,
    render_height: int = 720,
    blender_command: str = "blender",
) -> dict:
    """Render a patrol-style walkthrough GIF inside a Blender scene.

    Calls Blender headlessly to:

    1. Auto-detect traversable floor space (raycast + normal filter).
    2. Build a capsule occupancy grid (3-height horizontal sweeps).
    3. Plan a coverage path (farthest-point sampling → greedy tour →
       Catmull-Rom spline + post-smooth snap).
    4. Animate a QUATERNION camera with smart look-at (line-of-sight filtered).
    5. Render PNG frames (EEVEE by default).
    6. Assemble frames into a looping GIF.

    Args:
        blend_path:          Path to the input ``.blend`` file.
        output_dir:          Directory for frames, GIF, and animated ``.blend``.
        camera_height:       Camera height above detected floor in metres (default 1.7).
        grid_resolution:     Minimum voxel size in metres (default 0.5). The actual
                             voxel size is scaled up so the grid never exceeds
                             max_grid_cells_xy × max_grid_cells_xy × max_grid_cells_z,
                             keeping ray-cast count fixed regardless of scene size.
        max_grid_cells_xy:   Maximum grid cells along X and Y axes (default 80).
        max_grid_cells_z:    Maximum grid cells along Z axis (default 40).
        obstacle_radius:     Horizontal clearance radius in metres (default 0.5).
        fps:                 Frames per second rendered by Blender (default 12).
                             Lower = faster render and smaller GIF.
        duration_seconds:    Total walkthrough duration in seconds. ``None`` (default)
                             = auto-calculated from path length / walk_speed_mps,
                             then capped by max_duration_seconds.
        max_duration_seconds: Hard cap on auto-calculated duration in seconds (default 60.0).
                             Prevents multi-hour renders on large outdoor scenes.
                             Set to ``None`` to disable the cap.
        walk_speed_mps:      Walking speed in m/s used for auto duration (default 1.2).
                             Only used when duration_seconds is None.
        num_waypoints:       Number of coverage waypoints (default 20).
        look_range:          Maximum distance in metres for look-at targets (default 15.0).
        rotation_smooth_seconds: Camera rotation time constant in seconds (default 2.0).
                             Larger = slower, more cinematic rotation.
        gif_frame_duration:  Milliseconds per GIF frame (default 80 ≈ 12.5 fps).
        render_engine:       Blender render engine — ``"CYCLES"`` (GPU, default),
                             ``"EEVEE"``, or ``"WORKBENCH"``.
        seed:                RNG seed for reproducible path sampling (default 42).
        render_width:        Rendered frame width in pixels (default 1280).
        render_height:       Rendered frame height in pixels (default 720).
        blender_command:     Path to the Blender executable (default ``"blender"``).

    Returns:
        dict with keys:

        - ``gif``: Path to the assembled walkthrough GIF.
        - ``blend_output``: Path to the animated ``.blend`` file.
        - ``frames_dir``: Path to the rendered PNG frames directory.
        - ``frame_count``: Number of PNG frames rendered.
        - ``path_points_count``: Number of smooth path sample points.
        - ``free_cells_count``: Number of traversable grid cells found.
        - ``interesting_objects_count``: Number of scoreable look-at targets.

    Raises:
        RuntimeError: If Blender produces no ``WALKTHROUGH_RESULT:`` line.
    """
    blend_path = Path(blend_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    blend_output = output_dir / (blend_path.stem + "_walkthrough.blend")

    config = {
        "camera_height": camera_height,
        "grid_resolution": grid_resolution,
        "max_grid_cells_xy": max_grid_cells_xy,
        "max_grid_cells_z": max_grid_cells_z,
        "obstacle_radius": obstacle_radius,
        "fps": fps,
        "duration_seconds": duration_seconds,   # None = auto from path length
        "max_duration_seconds": max_duration_seconds,
        "walk_speed_mps": walk_speed_mps,
        "num_waypoints": num_waypoints,
        "look_range": look_range,
        "rotation_smooth_seconds": rotation_smooth_seconds,
        "render": True,  # always render frames so we can build a GIF
        "render_engine": render_engine,
        "seed": seed,
        "local_area_ratio": local_area_ratio,  # None = global mode; float = ratio × min(span_x,span_y)
        "local_height": local_height,
        "render_width": render_width,
        "render_height": render_height,
    }

    # Windows fix: NamedTemporaryFile stays open until explicitly closed;
    # Blender subprocess cannot read it while the handle is held.
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config, tf)
    tf.close()
    config_path = tf.name

    try:
        cmd = [
            blender_command,
            "--background",
            str(blend_path),
            "--python", str(RENDER_WALKTHROUGH_SCRIPT),
            "--",
            "--config", config_path,
            "--output-blend", str(blend_output),
            "--output-dir", str(output_dir),
            "--render-engine", render_engine.upper(),
        ]
        proc = subprocess.run(cmd, stdout=PIPE, stderr=STDOUT)
        stdout = proc.stdout.decode(errors="replace")
    finally:
        os.unlink(config_path)

    prefix = "WALKTHROUGH_RESULT:"
    result = None
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            result = json.loads(line[len(prefix):])
            break

    if result is None:
        raise RuntimeError(
            f"No WALKTHROUGH_RESULT in Blender output:\n{stdout[-3000:]}"
        )

    if result.get("status") == "error":
        raise RuntimeError(f"Blender script error: {result.get('message')}\n{result.get('traceback', '')}")

    # Assemble rendered PNG frames into a GIF.
    frames_dir = Path(result["frames_dir"])
    png_frames = sorted(frames_dir.glob("frame_*.png"))
    gif_path = output_dir / (blend_path.stem + "_walkthrough.gif")
    create_gif(png_frames, gif_path, duration=gif_frame_duration)

    result["gif"] = str(gif_path)
    result["frame_count"] = len(png_frames)
    return result
