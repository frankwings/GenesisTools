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


def _check_walkable_v2(candidates: set, bounds: tuple, config: dict) -> set:
    """Floor-based walkable filter — all BFS-reachable candidates are walkable."""
    print(f"[Walkable] Floor check skipped — all {len(candidates)} candidates walkable")
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
    solid_set = {tuple(r) for r in vg.solid}

    if camera_ijk is None:
        if len(vg.candidates) > 0:
            c = vg.candidates.mean(axis=0)
            camera_ijk = (int(round(c[0])), int(round(c[1])), int(round(c[2])))
        else:
            camera_ijk = (vg.nx // 2, vg.ny // 2, vg.nz // 2)

    free = _flood_fill_free_from_camera(solid_set, camera_ijk, vg.nx, vg.ny, vg.nz)
    walkable_set = _check_walkable_v2(free, vg.bounds, config)

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
