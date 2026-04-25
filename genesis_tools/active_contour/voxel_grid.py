"""Voxel grid constrained inside a fitted Snake3D surface.

Usage
-----
    from genesis_tools.active_contour.snake_3d import Snake3D, sample_mesh_surface
    from genesis_tools.active_contour.voxel_grid import VoxelGrid

    snake = Snake3D(pts).fit()
    grid  = VoxelGrid(snake, target_voxels=15_000)

    print(grid.voxel_size)   # derived size
    print(grid.count)        # actual voxels inside contour
    grid.save("voxels.npz")

CLI
---
    python genesis_tools/active_contour/voxel_grid.py \
        --snake-npz results/.../snake_mesh.npz \
        --target 15000 \
        --output voxels.npz
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Batched ray-triangle inside test  (N origins × F faces)
# ---------------------------------------------------------------------------

def _batch_ray_hits(
    origins: np.ndarray,
    direction: np.ndarray,
    verts: np.ndarray,
    faces: np.ndarray,
    eps: float = 1e-9,
) -> np.ndarray:
    """Möller-Trumbore for N origins vs all F faces.  Returns (N,) hit counts."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    e1 = v1 - v0
    e2 = v2 - v0

    h = np.cross(direction, e2)                           # (F, 3)
    a = np.einsum("fj,fj->f", e1, h)                     # (F,)
    valid = np.abs(a) > eps
    inv_a = np.where(valid, 1.0 / np.where(valid, a, 1.0), 0.0)

    s = origins[:, None, :] - v0[None, :, :]             # (N, F, 3)
    u = inv_a[None, :] * np.einsum("nfj,fj->nf", s, h)  # (N, F)
    u_ok = (u >= 0.0) & (u <= 1.0)

    q = np.cross(s, e1[None, :, :])                      # (N, F, 3)
    v = inv_a[None, :] * np.einsum("j,nfj->nf", direction, q)
    v_ok = (v >= 0.0) & (u + v <= 1.0)

    t = inv_a[None, :] * np.einsum("fj,nfj->nf", e2, q)
    hit = valid[None, :] & u_ok & v_ok & (t > eps)
    return hit.sum(axis=1)


def _batch_contains(
    points: np.ndarray,
    verts: np.ndarray,
    faces: np.ndarray,
    chunk_size: int = 2048,
) -> np.ndarray:
    """Return bool (N,) — True if each point is inside the closed mesh."""
    RAYS = [
        np.array([0.0, 0.0, 1.0]),
        np.array([0.0, 1.0, 0.1]),
        np.array([1.0, 0.0, 0.1]),
    ]
    N = len(points)
    votes = np.zeros(N, dtype=np.int32)
    for d in RAYS:
        d = d / np.linalg.norm(d)
        for start in range(0, N, chunk_size):
            chunk = points[start:start + chunk_size]
            hits = _batch_ray_hits(chunk, d, verts, faces)
            votes[start:start + chunk_size] += (hits % 2).astype(np.int32)
    return votes >= 2


# ---------------------------------------------------------------------------
# Fill-ratio estimation via coarse grid
# ---------------------------------------------------------------------------

def _estimate_fill_ratio(
    verts: np.ndarray,
    faces: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    coarse_n: int = 20,
) -> float:
    """Sample a coarse_n³ grid over the AABB and return fraction inside snake.

    Much faster than the full grid test and gives an accurate volume estimate
    without depending on face-winding consistency (divergence theorem breaks
    when ConvexHull simplices are not consistently outward-oriented).
    """
    xs = np.linspace(lo[0], hi[0], coarse_n + 2)[1:-1]
    ys = np.linspace(lo[1], hi[1], coarse_n + 2)[1:-1]
    zs = np.linspace(lo[2], hi[2], coarse_n + 2)[1:-1]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    inside = _batch_contains(pts, verts, faces, chunk_size=2048)
    return float(inside.sum()) / len(pts)


# ---------------------------------------------------------------------------
# VoxelGrid
# ---------------------------------------------------------------------------

class VoxelGrid:
    """Regular 3D voxel grid where every voxel centre lies inside a Snake3D.

    Parameters
    ----------
    snake:
        A fitted Snake3D (or any object with .vertices (V,3) and .faces (F,3)).
    target_voxels:
        Desired number of voxels inside the contour.  voxel_size is derived by:
          1. Estimating snake volume via a coarse-grid fill-ratio test
          2. voxel_size = (snake_volume / target_voxels)^(1/3)
        Actual count will be close to target (±10% typical).
    chunk_size:
        Points per batch for the inside test.  Reduce if memory is tight.
    coarse_n:
        Resolution of the pre-pass fill-ratio grid (default 20 → 8000 points).

    Attributes
    ----------
    voxel_size : float      — edge length of each cubic voxel
    centers    : (K, 3)     — world-space centres of inside voxels
    count      : int        — K
    fill_ratio : float      — fraction of AABB occupied by the snake
    snake_volume : float    — estimated snake volume (AABB × fill_ratio)
    grid_shape : (nx,ny,nz) — full AABB grid dimensions
    """

    def __init__(
        self,
        snake,
        target_voxels: int = 15_000,
        chunk_size: int = 2048,
        coarse_n: int = 20,
    ) -> None:
        t0 = time.perf_counter()

        verts = np.asarray(snake.vertices, dtype=np.float64)
        faces = np.asarray(snake.faces,    dtype=np.int64)

        lo = verts.min(axis=0)
        hi = verts.max(axis=0)
        aabb_vol = float(np.prod(hi - lo))

        # --- 1. Coarse fill-ratio pass ---
        print(f"  [voxel] estimating fill ratio ({coarse_n}³ coarse grid) …")
        self.fill_ratio = _estimate_fill_ratio(verts, faces, lo, hi, coarse_n)
        self.snake_volume = aabb_vol * self.fill_ratio
        print(f"  [voxel] fill_ratio={self.fill_ratio:.3f}  "
              f"snake_volume={self.snake_volume:.2f}  aabb_volume={aabb_vol:.2f}")

        # --- 2. Derive voxel size from estimated volume ---
        self.voxel_size = (self.snake_volume / target_voxels) ** (1.0 / 3.0)
        half = self.voxel_size / 2.0

        xs = np.arange(lo[0] + half, hi[0], self.voxel_size)
        ys = np.arange(lo[1] + half, hi[1], self.voxel_size)
        zs = np.arange(lo[2] + half, hi[2], self.voxel_size)
        self.grid_shape = (len(xs), len(ys), len(zs))
        n_candidates = len(xs) * len(ys) * len(zs)

        print(f"  [voxel] grid {self.grid_shape}  candidates={n_candidates:,}  "
              f"voxel_size={self.voxel_size:.4f}")

        # --- 3. Full inside test ---
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        candidates = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
        mask = _batch_contains(candidates, verts, faces, chunk_size=chunk_size)
        self.centers = candidates[mask]

        elapsed = time.perf_counter() - t0
        print(f"  [voxel] inside={self.count:,}/{n_candidates:,}  "
              f"({self.count / target_voxels * 100:.1f}% of target)  {elapsed:.1f}s")

    @property
    def count(self) -> int:
        return len(self.centers)

    def save(self, path: str | Path) -> None:
        np.savez(
            str(path),
            centers=self.centers,
            voxel_size=np.array(self.voxel_size),
            grid_shape=np.array(self.grid_shape),
            snake_volume=np.array(self.snake_volume),
            fill_ratio=np.array(self.fill_ratio),
        )
        print(f"  [voxel] saved {self.count:,} voxels → {path}")

    @classmethod
    def load(cls, path: str | Path) -> "VoxelGrid":
        obj = cls.__new__(cls)
        data = np.load(str(path))
        obj.centers      = data["centers"]
        obj.voxel_size   = float(data["voxel_size"])
        obj.grid_shape   = tuple(data["grid_shape"].tolist())
        obj.snake_volume = float(data["snake_volume"])
        obj.fill_ratio   = float(data["fill_ratio"])
        return obj


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--snake-npz", required=True)
    p.add_argument("--target",    type=int, default=15_000)
    p.add_argument("--output",    required=True)
    p.add_argument("--chunk-size", type=int, default=2048)
    p.add_argument("--coarse-n",   type=int, default=20)
    args = p.parse_args()

    data = np.load(args.snake_npz)

    class _Snake:
        vertices = data["vertices"]
        faces    = data["faces"]

    grid = VoxelGrid(_Snake(), target_voxels=args.target,
                     chunk_size=args.chunk_size, coarse_n=args.coarse_n)
    grid.save(args.output)


if __name__ == "__main__":
    main()
