"""Step 2: flood-fill reachable voxels → walkable cells.

Input:  VoxelGridData (from step 1)
Output: WalkableData  (walkable.npz)

All logic is pure Python — no bpy dependency.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class WalkableData:
    walkable: np.ndarray  # (M, 3) int32


# ---------------------------------------------------------------------------
# Core logic (migrated verbatim from render_walkthrough.py)
# ---------------------------------------------------------------------------

def _flood_fill_free_from_camera(solid: set, camera_ijk: tuple,
                                  nx: int, ny: int, nz: int) -> set:
    """BFS flood fill through free (non-solid) voxels starting from camera_ijk."""
    cx, cy, cz = camera_ijk
    if (cx, cy, cz) in solid:
        best, best_d = None, float("inf")
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    if (ix, iy, iz) not in solid:
                        d = (ix - cx) ** 2 + (iy - cy) ** 2 + (iz - cz) ** 2
                        if d < best_d:
                            best_d, best = d, (ix, iy, iz)
        if best is None:
            return set()
        cx, cy, cz = best
        print(f"[Walkable] Camera voxel was solid; snapped to {(cx, cy, cz)}")

    visited = {(cx, cy, cz)}
    queue = deque([(cx, cy, cz)])
    while queue:
        ix, iy, iz = queue.popleft()
        for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 1, 0),
                           (0, -1, 0), (0, 0, 1), (0, 0, -1)]:
            ni, nj, nk = ix + dx, iy + dy, iz + dz
            if 0 <= ni < nx and 0 <= nj < ny and 0 <= nk < nz:
                cell = (ni, nj, nk)
                if cell not in visited and cell not in solid:
                    visited.add(cell)
                    queue.append(cell)
    print(f"[Walkable] Flood fill: {len(visited)} candidate voxels")
    return visited


def _check_voxel_free_by_edges(raw: set, vg) -> set:
    """Snake mode step 2a: filter raw voxels by edge-mesh intersection (bpy).

    Fires rays along each of the 12 edges of the voxel against scene geometry.
    A voxel with no edge hits is entirely free (no geometry passes through it).
    Requires bpy — call only after a .blend file is open.
    """
    import bpy
    from mathutils import Vector

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    min_x, min_y, _, _, min_z, _ = vg.bounds
    res = vg.res
    DX = Vector((1.0, 0.0, 0.0))
    DY = Vector((0.0, 1.0, 0.0))
    DZ = Vector((0.0, 0.0, 1.0))

    free = set()
    for (ix, iy, iz) in raw:
        x0 = min_x + ix * res;  x1 = x0 + res
        y0 = min_y + iy * res;  y1 = y0 + res
        z0 = min_z + iz * res;  z1 = z0 + res

        hit = False
        # 4 edges along X
        for (y, z) in ((y0, z0), (y1, z0), (y0, z1), (y1, z1)):
            h, *_ = scene.ray_cast(depsgraph, Vector((x0, y, z)), DX, distance=res)
            if h: hit = True; break
        # 4 edges along Y
        if not hit:
            for (x, z) in ((x0, z0), (x1, z0), (x0, z1), (x1, z1)):
                h, *_ = scene.ray_cast(depsgraph, Vector((x, y0, z)), DY, distance=res)
                if h: hit = True; break
        # 4 edges along Z
        if not hit:
            for (x, y) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                h, *_ = scene.ray_cast(depsgraph, Vector((x, y, z0)), DZ, distance=res)
                if h: hit = True; break

        if not hit:
            free.add((ix, iy, iz))

    print(f"[Walkable] Edge check: {len(free)} free voxels (from {len(raw)} raw)")
    return free


def _flood_fill_through(free: set, camera_ijk: tuple,
                         nx: int, ny: int, nz: int) -> set:
    """BFS from camera_ijk through the free set only."""
    cx, cy, cz = camera_ijk
    if (cx, cy, cz) not in free:
        if not free:
            return set()
        best = min(free, key=lambda c: (c[0]-cx)**2 + (c[1]-cy)**2 + (c[2]-cz)**2)
        cx, cy, cz = best
        print(f"[Walkable] Camera not in free set; snapped to {(cx, cy, cz)}")
    visited = {(cx, cy, cz)}
    q = deque([(cx, cy, cz)])
    while q:
        ix, iy, iz = q.popleft()
        for dx, dy, dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            nb = (ix+dx, iy+dy, iz+dz)
            if nb in free and nb not in visited:
                visited.add(nb); q.append(nb)
    print(f"[Walkable] BFS: {len(visited)} walkable voxels connected to camera")
    return visited


def _check_walkable_v2(candidates: set, solid: set, bounds: tuple, config: dict) -> set:
    """Return only floor-surface walkable voxels: those with solid directly below.

    A walkable voxel must have either iz==0 (scene bottom) or a solid voxel at
    (ix, iy, iz-1) — meaning the camera can stand on solid geometry there.
    Without this filter the set includes mid-air and ceiling-level voxels, which
    causes the path to route through floors when path_plan picks the minimum iz.
    """
    floor_level = set()
    for (ix, iy, iz) in candidates:
        if iz == 0 or (ix, iy, iz - 1) in solid:
            floor_level.add((ix, iy, iz))
    if floor_level:
        print(f"[Walkable] Floor filter: {len(floor_level)} floor-level voxels "
              f"(from {len(candidates)} free candidates)")
        return floor_level
    print(f"[Walkable] Floor filter found 0 — falling back to all {len(candidates)} candidates")
    return set(candidates)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(vg, config: dict, camera_ijk: tuple | None = None) -> WalkableData:
    """Build WalkableData from a VoxelGridData.

    Args:
        vg:          VoxelGridData from pipeline/voxel_grid.py
        config:      pipeline config dict (same as voxel_grid step)
        camera_ijk:  (i, j, k) grid index of camera start; derived from vg
                     candidates centroid when None
    """
    if vg.mode == "snake":
        # Snake mode: vg.candidates = raw (inside-AC) voxels from step 1.
        # Step 2a: edge-mesh intersection → free voxels.
        # Step 2b: BFS from camera through free → walkable.
        raw_set = {tuple(r) for r in vg.candidates}
        if camera_ijk is None:
            if raw_set:
                c = vg.candidates.mean(axis=0)
                camera_ijk = (int(round(c[0])), int(round(c[1])), int(round(c[2])))
            else:
                camera_ijk = (vg.nx // 2, vg.ny // 2, vg.nz // 2)
        try:
            import bpy
            free_set = _check_voxel_free_by_edges(raw_set, vg)
            if not free_set:
                print("[Walkable] Edge check returned 0 free voxels — using all raw")
                free_set = raw_set
        except ImportError:
            # Pure-Python fallback for test environments (no bpy)
            free_set = raw_set
        walkable_set = _flood_fill_through(free_set, camera_ijk, vg.nx, vg.ny, vg.nz)
    else:
        # Local / global mode: vg.solid = scene geometry, vg.candidates = flood-filled.
        solid_set = {tuple(r) for r in vg.solid}
        if camera_ijk is None:
            if len(vg.candidates) > 0:
                c = vg.candidates.mean(axis=0)
                camera_ijk = (int(round(c[0])), int(round(c[1])), int(round(c[2])))
            else:
                camera_ijk = (vg.nx // 2, vg.ny // 2, vg.nz // 2)
        free = _flood_fill_free_from_camera(solid_set, camera_ijk, vg.nx, vg.ny, vg.nz)
        walkable_set = _check_walkable_v2(free, solid_set, vg.bounds, config)

    if walkable_set:
        walkable_arr = np.array(sorted(walkable_set), dtype=np.int32)
    else:
        walkable_arr = np.empty((0, 3), dtype=np.int32)

    return WalkableData(walkable=walkable_arr)


def save(data: WalkableData, path: str) -> None:
    np.savez_compressed(path, walkable=data.walkable)
    print(f"[Walkable] Saved → {path}")


def load(path: str) -> WalkableData:
    npz = np.load(path)
    return WalkableData(walkable=npz["walkable"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 2: walkable voxels")
    parser.add_argument("--voxel-grid", required=True, help="Path to voxel_grid.npz")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--output", required=True, help="Path to output walkable.npz")
    args = parser.parse_args()

    from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import load as vg_load
    vg = vg_load(args.voxel_grid)

    with open(args.config) as f:
        config = json.load(f)

    data = build(vg, config)
    save(data, args.output)


if __name__ == "__main__":
    _cli()
