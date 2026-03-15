# Walkthrough Renderer

Automatically generates a patrol-style camera walkthrough GIF/video inside any Blender `.blend` scene — no manual camera setup required.

## How It Works

1. **Floor detection** — Raycasts detect traversable floor surfaces (normal filter: upward-facing only)
2. **Voxel grid** — Capsule-style occupancy grid with 3-height horizontal sweeps for obstacle avoidance
3. **Path planning** — Farthest-point sampling → greedy TSP tour → Catmull-Rom spline smoothing
4. **Camera animation** — QUATERNION rotation mode, smart look-at with line-of-sight scoring
5. **Render** — PNG frames rendered by Blender (Cycles GPU by default), assembled into GIF

## Basic Usage

```python
from genesis_tools import render_scene_walkthrough

result = render_scene_walkthrough(
    blend_path="scene.blend",
    output_dir="output/walkthrough",
    camera_height=1.7,
    num_waypoints=12,
    blender_command="/path/to/blender",
)
print(result["gif"])           # path to walkthrough GIF
print(result["blend_output"])  # path to animated .blend
```

## All Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `blend_path` | — | Input `.blend` file |
| `output_dir` | — | Output directory for frames, GIF, and `.blend` |
| `camera_height` | `1.7` | Camera height above floor in metres |
| `grid_resolution` | `0.5` | Minimum voxel size in metres |
| `max_grid_cells_xy` | `80` | Max grid cells along X and Y |
| `max_grid_cells_z` | `40` | Max grid cells along Z |
| `obstacle_radius` | `0.5` | Horizontal clearance radius in metres |
| `fps` | `12` | Frames per second |
| `duration_seconds` | `None` | Walkthrough duration. `None` = auto from path length |
| `max_duration_seconds` | `60.0` | Hard cap on auto duration |
| `walk_speed_mps` | `2.5` | Walking speed for auto duration calculation |
| `num_waypoints` | `20` | Number of coverage waypoints |
| `look_range` | `15.0` | Max distance for look-at targets in metres |
| `rotation_smooth_seconds` | `2.0` | Camera rotation time constant (larger = smoother) |
| `gif_frame_duration` | `80` | Milliseconds per GIF frame (80 ≈ 12.5 fps) |
| `render_engine` | `"CYCLES"` | Render engine: `"CYCLES"`, `"EEVEE"`, `"WORKBENCH"` |
| `render_width` | `1280` | Frame width in pixels |
| `render_height` | `720` | Frame height in pixels |
| `render_samples` | `32` | Cycles sample count per frame (ignored for EEVEE/WORKBENCH) |
| `seed` | `42` | RNG seed for reproducible path sampling |
| `local_area_ratio` | `None` | Local mode: grid radius = ratio × min(scene_span). `None` = global mode |
| `local_height` | `8.0` | Local mode: voxel grid height in metres |
| `waypoint_gaze_mode` | `"free"` | Gaze mode: `"free"`, `"force_only"`, `"constrained"` |
| `debug_viz` | `False` | Add debug geometry to `.blend` (see Debug Mode below) |
| `panoramic` | `False` | 360° equirectangular render (Cycles only, see below) |
| `blender_command` | `"blender"` | Path to Blender executable |

## Debug Mode (`debug_viz=True`)

Adds visible debug geometry to the output `.blend` file so you can inspect the path planning result in Blender's viewport.

```python
result = render_scene_walkthrough(
    blend_path="scene.blend",
    output_dir="output/walkthrough",
    debug_viz=True,
)
```

All debug objects are placed in a **`DebugViz` collection** and rendered with flat solid colors (no emission — avoids dark frames).

### Debug Objects

| Object | Color | Description |
|--------|-------|-------------|
| Voxel spheres | Blue | Walkable voxel centers (`radius = res × 0.12`) |
| Waypoint spheres | Green | Farthest-point sampled waypoints (`radius = res × 0.25`) |
| Path line | Pink | Camera path at camera height (`thickness = res × 0.05`) |
| Camera axes | Red/Green/Blue | Camera orientation arrows per second (R=right, G=up, B=forward) |

### Sphere Placement

Each voxel/waypoint sphere uses a **per-point downward `ray_cast`** to find the real floor surface, then places the sphere at `floor_z + camera_height`. This ensures debug objects align with the actual camera trajectory even when the voxel grid Z doesn't precisely match the floor geometry.

> The camera trajectory itself is **not modified** — it uses a constant `z_correction` offset.

### Clip Start

The camera's `clip_start` is automatically set slightly larger than the largest debug sphere diameter. This means the camera clips through nearby debug geometry and they are invisible from the camera's perspective — they appear only when viewing the scene from an external viewpoint in Blender's viewport.

### Why Not `hide_render`?

In Blender Cycles headless mode, `Collection.hide_render=True` alone does **not** prevent debug geometry from affecting the render. Setting `clip_start > sphere_diameter` is simpler and more reliable.

## 360° Panoramic Mode (`panoramic=True`)

Renders a full 360° equirectangular walkthrough. The output frames can be viewed as spherical panoramas (VR-compatible).

```python
result = render_scene_walkthrough(
    blend_path="scene.blend",
    output_dir="output/walkthrough_360",
    panoramic=True,
    render_width=2048,
    render_height=1024,   # 2:1 ratio required for equirectangular
    render_samples=32,
    render_engine="CYCLES",  # required — EEVEE does not support panoramic
)
```

> **Note**: `panoramic=True` only works with `render_engine="CYCLES"`. EEVEE does not support equirectangular projection.

### Recommended Settings

| Use case | `render_samples` | `render_width` × `render_height` | Est. time / frame |
|----------|-----------------|----------------------------------|-------------------|
| Preview | `32` | `2048 × 1024` | ~2s (GPU) |
| Standard | `128` | `2048 × 1024` | ~13s (GPU) |
| Production | `512` | `4096 × 2048` | ~60s+ (GPU) |

### Combining debug_viz + panoramic

Both modes can be used together — the debug spheres will be visible in the 360° render when viewed from outside the camera frustum:

```python
result = render_scene_walkthrough(
    blend_path="scene.blend",
    output_dir="output/walkthrough_360_debug",
    debug_viz=True,
    panoramic=True,
    render_width=2048,
    render_height=1024,
)
```

## Local vs Global Mode

| Mode | Parameter | Description |
|------|-----------|-------------|
| **Global** | `local_area_ratio=None` (default) | Voxel grid covers the full scene |
| **Local** | `local_area_ratio=0.3` | Grid covers a ratio of the scene around the camera position |

Local mode is faster and more suitable for large scenes where only a portion needs to be explored.

## GPU Rendering

Cycles renders automatically use the GPU (CUDA) when available. The renderer calls `_enable_cycles_gpu()` which sets `compute_device_type = "CUDA"` and enables all available devices. Falls back to CPU if no GPU is found.

## Dependencies

- Blender 4.2+ (installed separately — not via pip)
- `libsm6`, `libice6` on headless Linux (`sudo apt-get install -y libsm6 libice6`)
- `genesis_tools.gif_generator` (PIL/Pillow)
