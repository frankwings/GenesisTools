"""BFS free-space scanner — bidirectional ray-cast from camera origin.

Purpose
-------
Find the **floor** (terrain surface) and **ceiling** (cloud/atmosphere surface)
of navigable space, starting from the original scene camera and expanding
outward via BFS.

Algorithm
---------
1. Seed: the grid cell containing the camera position.
2. At each cell, cast two rays from the camera eye height:
     - Downward → floor_z  (first solid hit below camera)
     - Upward   → ceil_z   (first solid hit above camera)
3. The cell's free column = [floor_z + cam_height, ceil_z].
4. BFS continues to a neighbour only when its free column overlaps the current
   cell's free column by ≥ min_overlap_bu.  This naturally isolates connected
   navigable regions (cliffs, interiors, etc. are excluded).
5. Unreachable cells remain NaN.

This approach is immune to the "ray starts above clouds" bug — rays originate
at camera height, so they correctly find terrain below and clouds above.

Output (terrain_scan.npz)
---------
  floor_z   : (nx, ny) float32  — terrain surface Z, NaN = unreachable
  ceil_z    : (nx, ny) float32  — cloud/ceiling Z,   NaN = unreachable
  free_h    : (nx, ny) float32  — ceil_z - floor_z headroom
  bounds    : (min_x, min_y, max_x, max_y)  float64
  res       : float64  — grid cell size in BU
  cam_xyz   : (3,) float64
  cam_height: float64  — eye height above floor (BU)

Runs inside Blender (requires bpy).  Call via:
    blender --background scene.blend --python expand_terrain_scan.py -- [options]
or import and call run_scan() directly from another Blender script.
"""
from __future__ import annotations
import sys
import math
import argparse
import numpy as np
from pathlib import Path
from collections import deque

# ---------------------------------------------------------------------------
# Core scanner (bpy-dependent)
# ---------------------------------------------------------------------------

def run_scan(
    output_path: str,
    cam_xyz: "tuple[float,float,float] | None" = None,
    res: float = 6.0,
    max_cells: int = 50_000,
    min_overlap_bu: float = 1.0,
    cam_height: float = 1.7,
    ray_distance: float = 800.0,
    verbose: bool = True,
) -> str:
    """Run BFS free-space scan and save terrain_scan.npz.

    Parameters
    ----------
    output_path : str
        Path to save terrain_scan.npz.
    cam_xyz : (x,y,z) world coords of the scene camera.
        Auto-detected from bpy.context.scene.camera if None.
    res : float
        Grid cell size in Blender units (BU).
    max_cells : int
        BFS hard cap (safety valve for huge scenes).
    min_overlap_bu : float
        Minimum free-column vertical overlap to consider two adjacent cells
        connected.  Larger values = more conservative connectivity.
    cam_height : float
        Eye height above terrain floor (BU).  Used to compute ray origin
        offset above floor when interpolating into unvisited cells.
    ray_distance : float
        Maximum ray-cast distance for both up and down directions.
    """
    import bpy
    from mathutils import Vector

    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()

    # --- Locate camera ---
    if cam_xyz is None:
        cam_obj = scene.camera or next(
            (o for o in scene.objects if o.type == "CAMERA"), None)
        if cam_obj is None:
            raise RuntimeError("[ExpandScan] No camera found in scene.")
        loc = cam_obj.matrix_world @ Vector((0, 0, 0))
        cam_xyz = (float(loc.x), float(loc.y), float(loc.z))
    cam_x, cam_y, cam_z = cam_xyz
    if verbose:
        print(f"[ExpandScan] Camera @ ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})")

    # --- Scene XY bounds from all mesh objects ---
    xs, ys = [], []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        for c in obj.bound_box:
            w = obj.matrix_world @ Vector(c)
            xs.append(w.x); ys.append(w.y)
    if not xs:
        raise RuntimeError("[ExpandScan] No mesh objects.")
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    nx = max(1, int(math.ceil((max_x - min_x) / res)))
    ny = max(1, int(math.ceil((max_y - min_y) / res)))
    if verbose:
        print(f"[ExpandScan] Grid {nx}×{ny}, res={res:.1f} BU  "
              f"XY=[{min_x:.0f},{max_x:.0f}]×[{min_y:.0f},{max_y:.0f}]")

    # --- Helpers ---
    def cell_to_world(ix: int, iy: int) -> tuple[float, float]:
        return min_x + (ix + 0.5) * res, min_y + (iy + 0.5) * res

    def cam_cell() -> tuple[int, int]:
        ix = int(np.clip((cam_x - min_x) / res, 0, nx - 1))
        iy = int(np.clip((cam_y - min_y) / res, 0, ny - 1))
        return ix, iy

    def cast_vertical(wx: float, wy: float, wz: float
                      ) -> "tuple[float|None, float|None]":
        """Return (floor_z, ceil_z) from bidirectional ray at (wx,wy,wz)."""
        origin = Vector((wx, wy, wz))
        # Down
        hit_d, loc_d, *_ = scene.ray_cast(dg, origin, Vector((0, 0, -1)),
                                           distance=ray_distance)
        floor_z = float(loc_d.z) if hit_d else None
        # Up
        hit_u, loc_u, *_ = scene.ray_cast(dg, origin, Vector((0, 0, 1)),
                                           distance=ray_distance)
        ceil_z = float(loc_u.z) if hit_u else None
        return floor_z, ceil_z

    # --- BFS ---
    floor_map = np.full((nx, ny), np.nan, dtype=np.float64)
    ceil_map  = np.full((nx, ny), np.nan, dtype=np.float64)
    visited   = np.zeros((nx, ny), dtype=bool)

    ix0, iy0 = cam_cell()
    # Seed: use actual camera Z as ray origin
    f0, c0 = cast_vertical(*cell_to_world(ix0, iy0), cam_z)
    if f0 is None:
        f0 = cam_z - cam_height   # fallback: assume flat floor
    if c0 is None:
        c0 = cam_z + ray_distance  # no ceiling detected

    floor_map[ix0, iy0] = f0
    ceil_map[ix0, iy0]  = c0
    visited[ix0, iy0]   = True

    queue = deque([(ix0, iy0)])
    n_visited = 1
    DIRS = [(1,0),(-1,0),(0,1),(0,-1)]

    while queue and n_visited < max_cells:
        ix, iy = queue.popleft()
        f_cur = floor_map[ix, iy]
        c_cur = ceil_map[ix, iy]
        # Ray origin for this cell: floor + cam_height (eye level above terrain)
        ray_z = f_cur + cam_height

        for dx, dy in DIRS:
            nx2, ny2 = ix + dx, iy + dy
            if nx2 < 0 or nx2 >= nx or ny2 < 0 or ny2 >= ny:
                continue
            if visited[nx2, ny2]:
                continue
            visited[nx2, ny2] = True

            wx, wy = cell_to_world(nx2, ny2)
            f_nbr, c_nbr = cast_vertical(wx, wy, ray_z)

            if f_nbr is None:
                # No terrain hit — interpolate from current cell (vegetation gap)
                f_nbr = f_cur
            if c_nbr is None:
                c_nbr = c_cur  # inherit ceiling from neighbour

            # Connectivity check: free columns must overlap vertically
            free_lo = max(f_cur + cam_height, f_nbr + cam_height)
            free_hi = min(c_cur, c_nbr)
            if free_hi - free_lo < min_overlap_bu:
                # Columns don't overlap (cliff / ceiling drops below walkable) —
                # mark as visited but don't store or enqueue.
                continue

            floor_map[nx2, ny2] = f_nbr
            ceil_map[nx2, ny2]  = c_nbr
            queue.append((nx2, ny2))
            n_visited += 1

    if verbose:
        reachable = int((~np.isnan(floor_map)).sum()) if floor_map.size else 0
        print(f"[ExpandScan] BFS complete: {n_visited} cells visited, "
              f"{reachable} reachable  "
              f"floor Z=[{np.nanmin(floor_map):.2f},{np.nanmax(floor_map):.2f}]  "
              f"ceil Z=[{np.nanmin(ceil_map):.2f},{np.nanmax(ceil_map):.2f}]")

    free_h = ceil_map - floor_map

    # --- Save ---
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        str(out),
        floor_z=floor_map.astype(np.float32),
        ceil_z=ceil_map.astype(np.float32),
        free_h=free_h.astype(np.float32),
        bounds=np.array([min_x, min_y, max_x, max_y], dtype=np.float64),
        res=np.float64(res),
        cam_xyz=np.array(cam_xyz, dtype=np.float64),
        cam_height=np.float64(cam_height),
    )
    print(f"[ExpandScan] Saved → {out}")
    return str(out)


# ---------------------------------------------------------------------------
# CLI entry point (blender --python expand_terrain_scan.py -- ...)
# ---------------------------------------------------------------------------

def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser(description="BFS terrain + ceiling scanner")
    p.add_argument("--output", required=True, help="Path to terrain_scan.npz")
    p.add_argument("--res",    type=float, default=6.0,  help="Grid resolution BU")
    p.add_argument("--cam_height", type=float, default=1.7, help="Eye height above floor")
    p.add_argument("--min_overlap", type=float, default=1.0, help="Min free-column overlap BU")
    p.add_argument("--max_cells", type=int, default=50_000)
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run_scan(
        output_path=args.output,
        res=args.res,
        cam_height=args.cam_height,
        min_overlap_bu=args.min_overlap,
        max_cells=args.max_cells,
    )
