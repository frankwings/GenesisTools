"""Fit a TerrainSnake to a Blender outdoor scene and save terrain_snake.npz.

Must be run under bpy Python (uses scene.ray_cast).

Two-pass ray cast
-----------------
Pass 1 covers the full scene AABB at the user-supplied ``grid_resolution``.
On large scenes this typically wastes most of the budget on empty ocean / sky
columns where the downward ray hits nothing.  Pass 2 re-runs the same
``nx × ny`` grid over the tight XY bbox of the valid hits (plus a small NaN
border kept for Laplacian bridging at the edges).  Cell size is recomputed
from the tight bbox, so the effective XY resolution can be much finer than
pass 1 at the same compute cost.

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

# Load TerrainSnake + VolumeClassifier directly from their files to avoid
# importing the package __init__.py, which pulls in snake_3d (requires scipy
# — not available in Blender's bundled Python).
def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

TerrainSnake           = _load_module("terrain_snake").TerrainSnake
ExpandSnake            = _load_module("terrain_snake").ExpandSnake
SceneObjectClassifier  = _load_module("scene_object_classifier").SceneObjectClassifier


def _cast_terrain_rays(scene, depsgraph, classifier,
                       min_x: float, min_y: float,
                       max_x: float, max_y: float,
                       max_z: float, ray_span_z: float,
                       nx: int, ny: int, res_x: float, res_y: float,
                       ray_samples: int):
    """Cast downward rays for every grid column.

    Returns (column_hits, all_hits_flat, n_skipped).
        column_hits: dict[(ix, iy)] -> list of Z values (skips classified-out hits)
        all_hits_flat: flat list of every kept hit Z (for percentile filter)
        n_skipped: count of ray hits dropped by the classifier
    """
    from mathutils import Vector
    step_past = 0.05

    all_hits_flat: list[float] = []
    column_hits: dict[tuple, list[float]] = {}
    n_skipped = 0

    for ix in range(nx):
        for iy in range(ny):
            hits_z: list[float] = []
            for sx in range(ray_samples):
                for sy in range(ray_samples):
                    x = min_x + (ix + (sx + 0.5) / ray_samples) * res_x
                    y = min_y + (iy + (sy + 0.5) / ray_samples) * res_y
                    cur = Vector((x, y, max_z + 2.0))
                    direction = Vector((0.0, 0.0, -1.0))
                    rem = ray_span_z
                    while rem > step_past:
                        hit, loc, _norm, _idx, hit_obj, _mat = scene.ray_cast(
                            depsgraph, cur, direction, distance=rem)
                        if not hit:
                            break
                        # Skip ray hits on atmospheric volumes (clouds high above
                        # the camera) — they aren't walking surfaces. Advance the
                        # ray past the hit so subsequent geometry below the cloud
                        # can still be recorded.
                        if classifier.should_skip(hit_obj):
                            n_skipped += 1
                        else:
                            hits_z.append(loc.z)
                            all_hits_flat.append(loc.z)
                        rem -= (loc - cur).length + step_past
                        cur = loc + direction * step_past
            column_hits[(ix, iy)] = hits_z
    return column_hits, all_hits_flat, n_skipped


def _hits_to_floor(column_hits: dict, all_hits_flat: list,
                   nx: int, ny: int,
                   env_sphere_percentile: float, min_z: float):
    """Build (nx, ny) terrain_z_floor from per-column hits.

    Topmost valid hit per column = first surface seen by the downward ray =
    terrain walking surface.  Hits below the env-sphere percentile are dropped
    to remove inner-surface hits on far-field geometry.
    """
    z_lo = (np.percentile(all_hits_flat, env_sphere_percentile)
            if all_hits_flat else min_z)
    floor = np.full((nx, ny), np.nan, dtype=np.float64)
    for ix in range(nx):
        for iy in range(ny):
            valid = [z for z in column_hits[(ix, iy)] if z > z_lo]
            if valid:
                floor[ix, iy] = max(valid)
    return floor, z_lo


def _tight_bbox_of_valid(floor: np.ndarray,
                         min_x: float, min_y: float, res_bu: float,
                         pad_cells: int = 2):
    """World-coord tight bbox of valid hits in `floor`, with `pad_cells` NaN border.

    Returns (tight_min_x, tight_min_y, tight_max_x, tight_max_y) or None if
    no valid hits exist.
    """
    valid = ~np.isnan(floor)
    if not valid.any():
        return None
    nx, ny = floor.shape
    ix_v, iy_v = np.where(valid)
    ix_lo = max(0, int(ix_v.min()) - pad_cells)
    ix_hi = min(nx - 1, int(ix_v.max()) + pad_cells)
    iy_lo = max(0, int(iy_v.min()) - pad_cells)
    iy_hi = min(ny - 1, int(iy_v.max()) + pad_cells)
    return (
        min_x + ix_lo * res_bu,
        min_y + iy_lo * res_bu,
        min_x + (ix_hi + 1) * res_bu,
        min_y + (iy_hi + 1) * res_bu,
    )


def fit_terrain_contour(
    blend_path: str,
    output_dir: str,
    grid_resolution: float = 5.0,
    max_grid_cells_xy: int = 200,
    env_sphere_percentile: float = 5.0,
    ray_samples: int = 1,
    # --- contract snake params ---
    alpha: float = 0.5,
    gravity: float = 0.1,
    dt: float = 1.0,
    max_iterations: int = 200,
    convergence_threshold: float = 1e-3,
    start_height: float = 1.7,
    # --- expand snake params (terrain mode only) ---
    snake_mode: str = "contract",        # "contract" | "expand"
    expand_floor_tolerance: float = 2.0, # BU: max deviation from seed floor Z
    expand_smoothing_iters: int = 50,    # Laplacian passes after expansion
    expand_alpha: float = 0.3,           # smoothing weight for expand snake
    # --- refine pass ---
    refine_pass: bool = True,
    refine_pad_cells: int = 2,
) -> str:
    """Fit terrain snake to blend_path, save terrain_snake.npz, return output path.

    snake_mode="expand"  (terrain mode only):
        Seeds from ray-cast floor hits, diffuses outward via Laplacian propagation.
        More robust than contract for scenes where the cloth init Z is far from the
        actual terrain (e.g. when the walkthrough camera is 90+ BU above the cloth
        start position).  Produces a heightmap whose Z values match the actual
        ray-cast hits rather than a physics simulation.
    """
    import bpy
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=blend_path)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    unit_scale = bpy.context.scene.unit_settings.scale_length or 1.0

    # --- Scene bounds (full AABB) ---
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
    print(f"[TerrainSnake] Pass 1 grid {nx}×{ny}, res={res_bu:.2f} BU "
          f"over full AABB ({span_x:.0f}×{span_y:.0f} BU)")

    # --- Camera lookup (anchor for cloth init Z + volume classification) ---
    cam_x = cam_y = cam_z = None
    cam_lookat_x = cam_lookat_y = None
    # Prefer the active (scene) camera; fall back to first camera in scene.objects.
    _cam_candidates = ([scene.camera] if scene.camera and scene.camera.type == "CAMERA"
                       else []) + [o for o in scene.objects if o.type == "CAMERA"]
    for obj in _cam_candidates:
        if obj.type == "CAMERA":
            loc = obj.matrix_world @ Vector((0.0, 0.0, 0.0))
            cam_x, cam_y, cam_z = float(loc.x), float(loc.y), float(loc.z)
            # Camera forward = -Z axis of local frame; project to XY and normalise.
            fwd = obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
            mag = (fwd.x ** 2 + fwd.y ** 2) ** 0.5
            if mag > 1e-6:
                cam_lookat_x, cam_lookat_y = float(fwd.x / mag), float(fwd.y / mag)
            print(f"[TerrainSnake] active camera '{obj.name}' "
                  f"@ ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})  "
                  f"lookat_xy=({cam_lookat_x:.3f}, {cam_lookat_y:.3f})")
            break
    if cam_z is None:
        cam_x = (min_x + max_x) / 2.0
        cam_y = (min_y + max_y) / 2.0
        cam_z = float(max_z)
        print(f"[TerrainSnake] no camera in scene, falling back to z_max = {cam_z:.2f}")

    # --- Scene object classifier: skip ray hits on atmospheric volumes etc. ---
    classifier = SceneObjectClassifier(camera_z=cam_z)
    classifier.report(scene)

    ray_span_z = (max_z - min_z) + 4.0

    # ------------------------------------------------------------------
    # Pass 1 — full AABB, square cells (res_bu × res_bu)
    # ------------------------------------------------------------------
    print("[TerrainSnake] Pass 1: casting rays over full AABB …")
    column_hits_1, all_hits_1, n_skipped_1 = _cast_terrain_rays(
        scene, depsgraph, classifier,
        min_x, min_y, max_x, max_y, max_z, ray_span_z,
        nx, ny, res_bu, res_bu, ray_samples,
    )
    if n_skipped_1:
        print(f"[TerrainSnake] Pass 1: skipped {n_skipped_1} ray hits "
              f"on atmospheric volumes")
    floor_1, z_lo_1 = _hits_to_floor(
        column_hits_1, all_hits_1, nx, ny, env_sphere_percentile, min_z)
    n_valid_1 = int(np.sum(~np.isnan(floor_1)))
    print(f"[TerrainSnake] Pass 1: env-sphere p{env_sphere_percentile}={z_lo_1:.2f}, "
          f"{n_valid_1}/{nx*ny} columns with valid hits "
          f"({100.0 * n_valid_1 / (nx*ny):.1f}%)")

    # ------------------------------------------------------------------
    # Pass 2 — tight bbox around valid hits (+ small NaN border for Laplacian)
    # Same nx × ny → finer effective XY resolution.
    # ------------------------------------------------------------------
    do_refine = bool(refine_pass) and n_valid_1 > 0
    tight = _tight_bbox_of_valid(floor_1, min_x, min_y, res_bu,
                                 pad_cells=refine_pad_cells) if do_refine else None
    # Skip the refine pass if pass 1 already covers nearly the whole scene —
    # there's nothing to gain.
    if tight is not None:
        tspan_x = tight[2] - tight[0]
        tspan_y = tight[3] - tight[1]
        if tspan_x >= 0.95 * span_x and tspan_y >= 0.95 * span_y:
            print("[TerrainSnake] Pass 2 skipped — pass 1 already covers ≥95% "
                  "of the scene in both X and Y")
            tight = None

    if tight is not None:
        tight_min_x, tight_min_y, tight_max_x, tight_max_y = tight
        tspan_x = tight_max_x - tight_min_x
        tspan_y = tight_max_y - tight_min_y
        # Keep cells square so the Laplacian neighbours are isotropic.
        res_bu_2 = max(tspan_x / nx, tspan_y / ny)
        nx_2 = max(1, int(math.ceil(tspan_x / res_bu_2)))
        ny_2 = max(1, int(math.ceil(tspan_y / res_bu_2)))
        # Re-extend the bbox to fit nx_2×ny_2 cells exactly (so cell centres
        # land cleanly inside the pass-2 grid).
        tight_max_x = tight_min_x + nx_2 * res_bu_2
        tight_max_y = tight_min_y + ny_2 * res_bu_2

        print(f"[TerrainSnake] Pass 2 grid {nx_2}×{ny_2}, res={res_bu_2:.2f} BU "
              f"over tight bbox ({tspan_x:.0f}×{tspan_y:.0f} BU, "
              f"{100.0*tspan_x/span_x:.1f}%×{100.0*tspan_y/span_y:.1f}% of scene) "
              f"— resolution ×{res_bu/res_bu_2:.2f}")
        column_hits_2, all_hits_2, n_skipped_2 = _cast_terrain_rays(
            scene, depsgraph, classifier,
            tight_min_x, tight_min_y, tight_max_x, tight_max_y, max_z, ray_span_z,
            nx_2, ny_2, res_bu_2, res_bu_2, ray_samples,
        )
        if n_skipped_2:
            print(f"[TerrainSnake] Pass 2: skipped {n_skipped_2} ray hits "
                  f"on atmospheric volumes")
        floor_2, z_lo_2 = _hits_to_floor(
            column_hits_2, all_hits_2, nx_2, ny_2, env_sphere_percentile, min_z)
        n_valid_2 = int(np.sum(~np.isnan(floor_2)))
        print(f"[TerrainSnake] Pass 2: env-sphere p{env_sphere_percentile}={z_lo_2:.2f}, "
              f"{n_valid_2}/{nx_2*ny_2} columns with valid hits "
              f"({100.0 * n_valid_2 / (nx_2*ny_2):.1f}%)")

        final_bounds = (tight_min_x, tight_min_y, tight_max_x, tight_max_y,
                        min_z, max_z)
        final_floor = floor_2
        final_res = res_bu_2
    else:
        final_bounds = (min_x, min_y, max_x, max_y, min_z, max_z)
        final_floor = floor_1
        final_res = res_bu

    # ------------------------------------------------------------------
    # Fit snake on the final (refined) floor.
    # mode="expand"  → ExpandSnake (terrain mode only, seeds from ray-cast hits)
    # mode="contract" → TerrainSnake (classic cloth, default)
    # ------------------------------------------------------------------
    _mode = snake_mode.lower().strip()
    if _mode == "expand":
        print(f"[TerrainSnake] Using ExpandSnake (outward diffusion from {int(np.sum(~np.isnan(final_floor)))} seeds)")
        # Single-seed expand: start from original scene camera XY
        _seed_xy = (cam_x, cam_y) if cam_x is not None else None
        snake = ExpandSnake(
            terrain_z_floor=final_floor,
            bounds=final_bounds,
            res=final_res,
            seed_xy=_seed_xy,
            alpha=expand_alpha,
            floor_tolerance=expand_floor_tolerance,
            max_iterations=max_iterations,
            smoothing_iterations=expand_smoothing_iters,
            convergence_threshold=convergence_threshold,
            seed_filter_percentile=env_sphere_percentile,
        )
    else:
        snake = TerrainSnake(
            terrain_z_floor=final_floor,
            cloth_init_z=cam_z,
            bounds=final_bounds,
            res=final_res,
            alpha=alpha,
            gravity=gravity,
            dt=dt,
            max_iterations=max_iterations,
            convergence_threshold=convergence_threshold,
            start_height=start_height,
        )
    snake.fit()
    print(f"[TerrainSnake/{_mode}] converged in {snake.iterations_run} iterations")

    # --- Save ---
    heightmap = snake.to_heightmap()
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = str(output_dir_path / "terrain_snake.npz")
    np.savez_compressed(
        out_path,
        heightmap=heightmap.astype(np.float32),
        terrain_z_floor=final_floor.astype(np.float32),
        max_displacements=np.array(snake.max_displacements, dtype=np.float32),
        bounds=np.array(final_bounds, dtype=np.float64),
        res=np.float64(final_res),
        unit_scale=np.float64(unit_scale),
        cloth_init_z=np.float64(cam_z),
        camera_xyz=np.array([cam_x, cam_y, cam_z], dtype=np.float64),
        camera_lookat=(np.array([cam_lookat_x, cam_lookat_y], dtype=np.float64)
                       if cam_lookat_x is not None
                       else np.array([0.0, 0.0], dtype=np.float64)),
        snake_mode=np.bytes_(_mode),
        # Pass-1 (full-AABB) coverage saved for visualisation / debugging
        pass1_floor=floor_1.astype(np.float32),
        pass1_bounds=np.array(
            (min_x, min_y, max_x, max_y, min_z, max_z), dtype=np.float64),
        pass1_res=np.float64(res_bu),
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
    p.add_argument("--start-height", type=float, default=1.7)
    p.add_argument("--no-refine-pass", action="store_true",
                   help="Skip the second-pass tight-bbox ray cast")
    p.add_argument("--refine-pad-cells", type=int, default=2,
                   help="NaN border cells kept around the valid-hit bbox")
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
        start_height=args.start_height,
        refine_pass=not args.no_refine_pass,
        refine_pad_cells=args.refine_pad_cells,
    )
