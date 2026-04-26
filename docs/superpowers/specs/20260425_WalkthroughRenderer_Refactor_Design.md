# Walkthrough Renderer Refactor — Design Spec

**Date:** 2026-04-25  
**Status:** Approved for implementation

---

## Overview

Refactor `render_walkthrough.py` (currently ~2800 lines, monolithic Blender headless script) into a modular pipeline where:

1. Each pipeline step is an **importable Python module** with a clean function API
2. Each step saves its output to an **intermediate file** (.npz / .json)
3. A **visualization CLI** reads any combination of step outputs and adds debug geometry to a .blend
4. A **walkthrough CLI** orchestrates the full pipeline; skips steps whose output files already exist in `--output-dir` (implicit resume — delete a file to re-run from that step)
5. All steps except rendering run via **pip bpy 4.5** (`/home/kingy/blender/4.5/python/bin/python3.11`) — no `blender --background` needed
6. Rendering is a separate optional step using `blender --background` via `BlenderRunner`

---

## Runtime Environment

| Task | Python | bpy |
|------|--------|-----|
| Pipeline steps (voxel_grid, walkable, path, camera) | `/home/kingy/blender/4.5/python/bin/python3.11` | `pip install bpy==4.5.0` |
| Visualization | same | same |
| Rendering | `blender --background` via `BlenderRunner` | bundled |

**Verified:** pip bpy 4.5 supports `bpy.ops.wm.open_mainfile`, `evaluated_depsgraph_get()`, and `scene.ray_cast()` on this system.

---

## File Structure

```
genesis_tools/walkthrough_renderer/
├── __init__.py                  # public API (unchanged surface)
├── walkthrough.py               # orchestrator — importable run() + CLI
├── visualize.py                 # visualization — importable visualize() + CLI
├── pipeline/
│   ├── __init__.py
│   ├── voxel_grid.py            # Step 1: ray_cast → solid voxel grid (AABB local/global or snake)
│   ├── walkable.py              # Step 2: flood fill → reachable + walkable cells
│   ├── path_plan.py             # Step 3: waypoints + smooth path (pure Python)
│   ├── camera_orient.py         # Step 4: waypoint gaze orientations (needs bpy LOS)
│   ├── camera_animate.py        # Step 5: write camera keyframes into .blend (pip bpy, no render)
│   └── render.py                # Step 6 (optional): render frames via blender --background
├── viz/
│   ├── __init__.py
│   ├── primitives.py            # shared Blender geometry builders
│   └── layers.py                # per-step viz functions
└── tests/
    ├── test_voxel_grid.py
    ├── test_walkable.py
    ├── test_path_plan.py
    └── test_visualize.py
```

### Functions migrated from `render_walkthrough.py`

| Current function | New home |
|-----------------|----------|
| `_scene_bounds`, `_compute_scene_density_bounds`, `_get_unit_scale`, `_find_local_center`, `_build_local_voxel_grid`, `_build_voxel_grid`, `_build_voxel_grid_from_snake`, `_cast_all_hits_bidir`, `_collect_hits_bidir`, `_load_snake_data` | `pipeline/voxel_grid.py` |
| `_flood_fill_free_from_camera`, `_check_walkable_v2` | `pipeline/walkable.py` |
| `_bfs_largest_component`, `_farthest_point_sample`, `_greedy_tsp_tour`, `_bfs_path`, `_build_smooth_path`, `_snap_path_to_floor`, `_fine_adjust_path`, `_sample_path`, `_travel_direction_target` | `pipeline/path_plan.py` |
| `_build_equirect_grid`, `_normal_entropy`, `_compute_waypoint_orientations`, `_map_tour_to_path`, `_get_base_direction`, `_find_gaze_target` | `pipeline/camera_orient.py` |
| `_has_line_of_sight`, `_compute_look_at_quaternion`, `_setup_and_animate_camera`, `_ensure_lights`, `_enable_cycles_gpu` | `pipeline/camera_animate.py` |
| `_make_voxel_spheres`, `_make_voxel_wireframes`, `_make_sphere`, `_make_line`, `_make_arrow`, `_make_hit_markers`, `_flat_material`, `_edge_tube_nodegroup`, `_apply_edge_tube`, `_ico_template`, `_debug_collection`, `_spheres_col`, `_wireframes_col` | `viz/primitives.py` |
| `_add_debug_viz` (split into per-step functions) | `viz/layers.py` |

---

## Data Contracts (Intermediate Files)

All files saved to `<output_dir>/`.

### `voxel_grid.npz`
```
solid      (N, 3) int32   — grid indices of solid voxels
candidates (K, 3) int32   — flood-fill reachable voxels (free, connected to camera)
nx, ny, nz int            — grid dimensions
res        float64        — voxel size in Blender units
bounds     (6,) float64   — (min_x, min_y, max_x, max_y, min_z, max_z)
unit_scale float64        — metres per Blender unit
```
Optional: `hits (H, 3) float64` — ray cast hit positions (when `debug_viz` is on)

### `walkable.npz`
```
walkable   (M, 3) int32   — walkable grid indices
```

### `path.npz`
```
waypoints    (W, 3) int32    — waypoint grid indices
path_points  (P, 3) float64  — world-space path positions
tour         (T, 3) int32    — ordered waypoint indices
camera_height float64        — in Blender units
bounds       (6,) float64    — reference bounds (same as voxel_grid)
```

### `wp_schedule.json`
```json
[{"t": 0.0, "quat": [w, x, y, z]}, ...]
```

---

## Module APIs

### `pipeline/voxel_grid.py`

Three build modes, selected by config keys:
- **Snake** (`config["snake_npz"]` set): uses pre-computed VoxelGrid centers from snake contour
- **Local AABB** (`config["local_area_ratio"]` set): bidirectional ray_cast in a region around the camera
- **Global AABB** (neither): tri-axial sweep over full scene bounds

```python
@dataclass
class VoxelGridData:
    solid: np.ndarray        # (N, 3) int32
    candidates: np.ndarray   # (K, 3) int32 — flood-fill reachable from camera
    nx: int; ny: int; nz: int
    res: float
    bounds: tuple            # (min_x, min_y, max_x, max_y, min_z, max_z)
    unit_scale: float
    mode: str                # "snake" | "local" | "global"
    hits: np.ndarray | None  # (H, 3) float64 — ray hit positions (debug only)

def build(blend_path: str, config: dict) -> VoxelGridData
def save(data: VoxelGridData, path: str) -> None
def load(path: str) -> VoxelGridData
```

CLI: `python -m genesis_tools.walkthrough_renderer.pipeline.voxel_grid --blend scene.blend --config cfg.json --output out/voxel_grid.npz`

### `pipeline/walkable.py`
```python
@dataclass
class WalkableData:
    walkable: np.ndarray     # (M, 3) int32

def build(vg: VoxelGridData, config: dict) -> WalkableData
def save(data: WalkableData, path: str) -> None
def load(path: str) -> WalkableData
```

### `pipeline/path_plan.py` (pure Python — no bpy)
```python
@dataclass
class PathData:
    waypoints: np.ndarray    # (W, 3) int32
    path_points: np.ndarray  # (P, 3) float64
    tour: np.ndarray         # (T,) int32 — indices into waypoints
    camera_height: float
    bounds: tuple

def build(vg: VoxelGridData, wk: WalkableData, config: dict) -> PathData
def save(data: PathData, path: str) -> None
def load(path: str) -> PathData
```

### `pipeline/camera_orient.py`
```python
@dataclass
class OrientData:
    wp_schedule: list        # [{"t": float, "quat": [w,x,y,z]}, ...]

def build(blend_path: str, path: PathData, config: dict) -> OrientData
def save(data: OrientData, path: str) -> None
def load(path: str) -> OrientData
```

### `pipeline/camera_animate.py`
Writes camera keyframes into a copy of the input `.blend` and saves it. Does **not** render.

```python
def build(blend_path: str, path: PathData, orient: OrientData,
          config: dict, output_blend: str) -> str
```
Returns path to the saved `.blend` containing camera keyframes.

### `pipeline/render.py`
Invokes `blender --background` via `BlenderRunner` to render the animated `.blend` to frames.

```python
def build(blend_path: str, config: dict, output_dir: str) -> list[str]
```
Returns list of rendered frame paths. Uses `blender --background` (needs real Blender, not pip bpy).

---

## Walkthrough CLI / API

```python
# walkthrough.py
STEPS = ["voxel_grid", "walkable", "path", "camera_orient", "camera_animate", "render"]

def run(blend_path: str, config: dict, output_dir: str, render: bool = False) -> dict
```

```bash
python -m genesis_tools.walkthrough_renderer.walkthrough \
    --blend scene.blend \
    --config config.json \
    --output-dir out/ \
    [--render]
```

Steps run in order: `voxel_grid → walkable → path → camera_orient → camera_animate → (render)`.

**Implicit resume**: the orchestrator checks for each step's output file in `--output-dir`. If the file already exists, that step is skipped and its data is loaded from disk. To re-run from a step, delete that file and all subsequent output files:

```bash
# Re-run from path onwards:
rm out/path.npz out/wp_schedule.json out/scene_walkthrough.blend
python -m genesis_tools.walkthrough_renderer.walkthrough --blend scene.blend ...
```

---

## Visualization CLI / API

```python
# visualize.py
def visualize(
    blend_path: str,
    output_blend: str,
    *,
    voxel_grid: str | None = None,   # path to voxel_grid.npz
    walkable: str | None = None,     # path to walkable.npz
    path: str | None = None,         # path to path.npz
    camera_blend: str | None = None, # path to animated .blend (for camera axes)
) -> None
```

```bash
python -m genesis_tools.walkthrough_renderer.visualize \
    --blend scene.blend \
    --output debug.blend \
    [--voxel-grid out/voxel_grid.npz] \
    [--walkable   out/walkable.npz] \
    [--path       out/path.npz] \
    [--camera     out/scene_walkthrough.blend]
```

### Visualization Layers

Each layer is independent and only added if its data file is provided:

| Flag | Layer | Colors |
|------|-------|--------|
| `--voxel-grid` | Solid voxels | Red (solid), Yellow (free/non-candidate) |
| `--walkable` | Reachable voxels | Blue (candidate, not walkable), Cyan (walkable) |
| `--path` | Path + waypoints | Green (waypoints), Pink (path line) |
| `--camera` | Camera axes | RGB arrows at each second |

Layers are additive — pass all four flags to get the full debug view.

---

## viz/layers.py

```python
def add_voxel_grid_layer(vg: VoxelGridData, config: dict) -> None
    # red = solid, yellow = free (not candidate)

def add_walkable_layer(vg: VoxelGridData, wk: WalkableData, config: dict) -> None
    # blue = candidate not walkable, cyan = walkable

def add_path_layer(path: PathData, config: dict) -> None
    # green waypoint spheres, pink path line

def add_camera_layer(camera_blend: str, fps: int, res: float) -> None
    # RGB arrows at each 1-second frame
```

All functions operate on the currently-open bpy scene. `visualize()` calls `open_mainfile`, then calls whichever layer functions are needed, then `save_as_mainfile`.

---

## Migration Strategy

`render_walkthrough.py` is preserved unchanged during migration. The new modules are built alongside it. Once all modules pass tests:

1. `render_walkthrough.py` `main()` is replaced with a thin call to `walkthrough.run()`
2. `_add_debug_viz()` is replaced with calls to `visualize.visualize()`
3. Old helper functions are removed from `render_walkthrough.py`

This ensures no regression during the transition.

---

## Testing

- `test_voxel_grid.py` — mock `bpy.context.scene.ray_cast`, verify solid cell output
- `test_walkable.py` — pure Python flood fill, no bpy mock needed
- `test_path_plan.py` — pure Python, test with synthetic walkable grid
- `test_visualize.py` — mock `bpy.ops.wm.open_mainfile` + `save_as_mainfile`, verify layer functions called with correct args
