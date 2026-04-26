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
    )
    print(result["gif"])           # path to walkthrough GIF
    print(result["blend_output"])  # path to animated .blend
"""

from pathlib import Path
from typing import Union

from genesis_tools.gif_generator import create_gif


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
    waypoint_gaze_mode: str = "free",
    debug_viz: bool = False,
    panoramic: bool = False,
    render_samples: int = 32,
    snake_npz: Union[str, Path] = None,
    voxel_grid_npz: Union[str, Path] = None,
) -> dict:
    """Render a patrol-style walkthrough GIF inside a Blender scene.

    Runs the modular walkthrough pipeline (implicit resume) and assembles
    rendered frames into a GIF.

    Returns:
        dict with keys: gif, blend_output, frame_count, frames, step_outputs.
    """
    from genesis_tools.walkthrough_renderer.walkthrough import run as _wt_run

    blend_path = Path(blend_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "camera_height": camera_height,
        "grid_resolution": grid_resolution,
        "max_grid_cells_xy": max_grid_cells_xy,
        "max_grid_cells_z": max_grid_cells_z,
        "obstacle_radius": obstacle_radius,
        "fps": fps,
        "duration_seconds": duration_seconds,
        "max_duration_seconds": max_duration_seconds,
        "walk_speed_mps": walk_speed_mps,
        "num_waypoints": num_waypoints,
        "look_range": look_range,
        "rotation_smooth_seconds": rotation_smooth_seconds,
        "render": True,
        "render_engine": render_engine,
        "seed": seed,
        "local_area_ratio": local_area_ratio,
        "local_height": local_height,
        "render_width": render_width,
        "render_height": render_height,
        "waypoint_gaze_mode": waypoint_gaze_mode,
        "debug_viz": debug_viz,
        "panoramic": panoramic,
        "render_samples": render_samples,
        "snake_npz": str(snake_npz) if snake_npz else None,
        "voxel_grid_npz": str(voxel_grid_npz) if voxel_grid_npz else None,
    }

    result = _wt_run(str(blend_path), config, str(output_dir), render=True)

    frames = result.get("frames", [])
    gif_path = output_dir / (blend_path.stem + "_walkthrough.gif")
    if frames:
        create_gif([Path(f) for f in frames], gif_path, duration=gif_frame_duration)

    result["gif"] = str(gif_path)
    result["frame_count"] = len(frames)
    return result
