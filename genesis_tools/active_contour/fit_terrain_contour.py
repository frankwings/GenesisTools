"""Fit a TerrainSnake to a Blender outdoor scene and save terrain_snake.npz.

Must be run under bpy Python (uses scene.ray_cast).

Usage (standalone bpy script)
-----
    blender --background scene.blend --python fit_terrain_contour.py -- \\
        --output-dir /path/to/output [--grid-resolution 5.0] ...

Or call fit_terrain_contour() from another bpy Python script:

    from genesis_tools.active_contour.fit_terrain_contour import fit_terrain_contour
    path = fit_terrain_contour(blend_path, output_dir, grid_resolution=5.0)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import importlib.util

import numpy as np

# Load TerrainSnake directly from its file to avoid importing the package
# __init__.py, which pulls in snake_3d (requires scipy — not available in
# Blender's bundled Python).
_spec = importlib.util.spec_from_file_location(
    "terrain_snake", Path(__file__).parent / "terrain_snake.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TerrainSnake = _mod.TerrainSnake


def fit_terrain_contour(
    blend_path: str,
    output_dir: str,
    grid_resolution: float = 5.0,
    max_grid_cells_xy: int = 200,
    env_sphere_percentile: float = 5.0,
    ray_samples: int = 1,
    alpha: float = 0.5,
    gravity: float = 0.1,
    dt: float = 1.0,
    max_iterations: int = 200,
    convergence_threshold: float = 1e-3,
) -> str:
    """Fit terrain snake to blend_path, save terrain_snake.npz, return output path."""
    import bpy
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=blend_path)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    unit_scale = bpy.context.scene.unit_settings.scale_length or 1.0

    # --- Scene bounds ---
    xs, ys, zs = [], [], []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    if not xs:
        raise RuntimeError("No mesh objects in scene.")
    min_x, min_y = min(xs), min(ys)
    max_x, max_y = max(xs), max(ys)
    min_z, max_z = min(zs), max(zs)

    # --- Grid resolution ---
    res_bu = grid_resolution / unit_scale
    span_x, span_y = max_x - min_x, max_y - min_y
    res_bu = max(res_bu, span_x / max_grid_cells_xy, span_y / max_grid_cells_xy)
    nx = max(1, int(math.ceil(span_x / res_bu)))
    ny = max(1, int(math.ceil(span_y / res_bu)))
    print(f"[TerrainSnake] Grid {nx}×{ny}, res={res_bu:.2f} BU — casting rays …")

    # --- Step 1: downward ray-cast per column ---
    ray_span_z = (max_z - min_z) + 4.0
    step_past = 0.05
    all_hits_flat: list[float] = []
    column_hits: dict[tuple, list[float]] = {}

    for ix in range(nx):
        for iy in range(ny):
            hits_z: list[float] = []
            for sx in range(ray_samples):
                for sy in range(ray_samples):
                    x = min_x + (ix + (sx + 0.5) / ray_samples) * res_bu
                    y = min_y + (iy + (sy + 0.5) / ray_samples) * res_bu
                    cur = Vector((x, y, max_z + 2.0))
                    direction = Vector((0.0, 0.0, -1.0))
                    rem = ray_span_z
                    while rem > step_past:
                        hit, loc, _n, *_ = scene.ray_cast(
                            depsgraph, cur, direction, distance=rem)
                        if not hit:
                            break
                        hits_z.append(loc.z)
                        all_hits_flat.append(loc.z)
                        rem -= (loc - cur).length + step_past
                        cur = loc + direction * step_past
            column_hits[(ix, iy)] = hits_z

    # --- Step 2: global percentile filter to remove env sphere hits ---
    z_threshold = (np.percentile(all_hits_flat, env_sphere_percentile)
                   if all_hits_flat else min_z)
    print(f"[TerrainSnake] env-sphere threshold (p{env_sphere_percentile})"
          f" = {z_threshold:.2f}")

    terrain_z_floor = np.full((nx, ny), np.nan, dtype=np.float64)
    for ix in range(nx):
        for iy in range(ny):
            valid = [z for z in column_hits[(ix, iy)] if z > z_threshold]
            if valid:
                terrain_z_floor[ix, iy] = min(valid)

    n_valid = int(np.sum(~np.isnan(terrain_z_floor)))
    print(f"[TerrainSnake] {n_valid}/{nx*ny} columns have valid terrain hits")

    # --- Step 3: fit TerrainSnake ---
    bounds = (min_x, min_y, max_x, max_y, min_z, max_z)
    snake = TerrainSnake(
        terrain_z_floor=terrain_z_floor,
        bounds=bounds,
        res=res_bu,
        alpha=alpha,
        gravity=gravity,
        dt=dt,
        max_iterations=max_iterations,
        convergence_threshold=convergence_threshold,
    )
    snake.fit()
    print(f"[TerrainSnake] converged in {snake.iterations_run} iterations")

    # --- Step 4: save ---
    heightmap = snake.to_heightmap()
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = str(output_dir_path / "terrain_snake.npz")
    np.savez_compressed(
        out_path,
        heightmap=heightmap.astype(np.float32),
        bounds=np.array(bounds, dtype=np.float64),
        res=np.float64(res_bu),
        unit_scale=np.float64(unit_scale),
    )
    print(f"[TerrainSnake] Saved → {out_path}")
    return out_path


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--grid-resolution", type=float, default=5.0)
    p.add_argument("--max-grid-cells-xy", type=int, default=200)
    p.add_argument("--env-sphere-percentile", type=float, default=5.0)
    p.add_argument("--ray-samples", type=int, default=1)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--gravity", type=float, default=0.1)
    p.add_argument("--dt", type=float, default=1.0)
    p.add_argument("--max-iterations", type=int, default=200)
    p.add_argument("--convergence-threshold", type=float, default=1e-3)
    # Blender passes script args after "--" in sys.argv; strip everything before it.
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    fit_terrain_contour(
        blend_path=args.blend,
        output_dir=args.output_dir,
        grid_resolution=args.grid_resolution,
        max_grid_cells_xy=args.max_grid_cells_xy,
        env_sphere_percentile=args.env_sphere_percentile,
        ray_samples=args.ray_samples,
        alpha=args.alpha,
        gravity=args.gravity,
        dt=args.dt,
        max_iterations=args.max_iterations,
        convergence_threshold=args.convergence_threshold,
    )
