"""3D Active Contour (Snake) for finding the minimal smooth bounding surface
of a 3D scene mesh.

The snake contracts from an initial convex hull toward a point cloud sampled
from the actual mesh faces (not just vertices). Internal Laplacian energy keeps
the surface smooth, which causes small protrusions — window frames, bolts, trim
— to be bypassed. External energy (nearest-point attraction) pulls the surface
toward dominant geometry (walls, floors, large terrain patches).

Primary use: determining the valid voxel region for walkthrough rendering, so
the camera path cannot drift into empty space beyond scene boundaries.

Pipeline
--------
    mesh_list = [(verts_array, faces_array), ...]
    pts    = sample_mesh_surface(mesh_list, sampling_resolution=0.5)
    snake  = Snake3D(pts, alpha=0.6, beta=0.3).fit()
    indoor = snake.contains(camera_position)      # True → indoor, False → outdoor
    mask   = snake.contains_batch(voxel_centres)  # restrict voxel grid
"""

from __future__ import annotations

from collections import defaultdict
from typing import List, Tuple

import numpy as np
from scipy.spatial import ConvexHull, KDTree


# ---------------------------------------------------------------------------
# Mesh surface sampling
# ---------------------------------------------------------------------------

def sample_mesh_surface(
    mesh_list: List[Tuple[np.ndarray, np.ndarray]],
    sampling_resolution: float = 0.5,
    seed: int = 42,
) -> np.ndarray:
    """Sample points uniformly from triangle mesh faces (area-weighted).

    Vertices alone are insufficient: a 100 m² floor quad has only 4 corner
    vertices, but the snake needs dense coverage of the entire surface to
    recognise it as a solid boundary.  This function samples one point per
    sampling_resolution² of face area using random barycentric coordinates.

    Args:
        mesh_list: list of (vertices, faces) tuples.
                   vertices – (N, 3) float array, world-space positions.
                   faces    – (M, 3) int array, triangle vertex indices.
        sampling_resolution: target sample spacing in world units.
        seed: random seed for reproducibility.

    Returns:
        (K, 3) float array of sampled surface points.
    """
    rng = np.random.default_rng(seed)
    chunks: List[np.ndarray] = []
    res2 = sampling_resolution ** 2

    for verts, faces in mesh_list:
        verts = np.asarray(verts, dtype=np.float64)
        faces = np.asarray(faces, dtype=np.int64)
        v0 = verts[faces[:, 0]]          # (F, 3)
        v1 = verts[faces[:, 1]]
        v2 = verts[faces[:, 2]]
        e1, e2 = v1 - v0, v2 - v0
        # area = 0.5 * |e1 × e2|
        cross = np.cross(e1, e2)         # (F, 3)
        areas = np.linalg.norm(cross, axis=1) * 0.5   # (F,)
        counts = (areas / res2).astype(np.int64)       # (F,) — 0 means skip
        mask = counts > 0
        if not mask.any():
            continue
        # Repeat each face index by its sample count
        face_idx = np.repeat(np.where(mask)[0], counts[mask])  # (K,)
        K = len(face_idx)
        r1 = rng.random(K)
        r2 = rng.random(K)
        # Fold samples outside the triangle back inside
        fold = r1 + r2 > 1.0
        r1[fold] = 1.0 - r1[fold]
        r2[fold] = 1.0 - r2[fold]
        w0 = (1.0 - r1 - r2)[:, None]
        pts_chunk = (w0 * v0[face_idx]
                     + r1[:, None] * v1[face_idx]
                     + r2[:, None] * v2[face_idx])
        chunks.append(pts_chunk)

    if not chunks:
        raise ValueError("No points sampled — mesh_list is empty or degenerate.")
    return np.concatenate(chunks, axis=0).astype(np.float64)


# ---------------------------------------------------------------------------
# Mesh subdivision
# ---------------------------------------------------------------------------

def subdivide_mesh(
    vertices: np.ndarray,
    faces: np.ndarray,
    levels: int = 2,
) -> Tuple[np.ndarray, np.ndarray]:
    """Midpoint subdivision: each triangle → 4 triangles, sharing edge midpoints.

    Increases snake vertex count so the surface has enough degrees of freedom
    to wrap complex geometry after contracting from the convex hull.

    Each level quadruples the triangle count.  levels=2 is usually sufficient.
    """
    verts: List[np.ndarray] = list(np.asarray(vertices, dtype=np.float64))
    tris: List[List[int]] = [list(map(int, f)) for f in faces]

    for _ in range(levels):
        edge_mid: dict[Tuple[int, int], int] = {}
        new_tris: List[List[int]] = []

        def _mid(i: int, j: int) -> int:
            key = (min(i, j), max(i, j))
            if key not in edge_mid:
                edge_mid[key] = len(verts)
                verts.append((verts[i] + verts[j]) * 0.5)
            return edge_mid[key]

        for a, b, c in tris:
            ab, bc, ca = _mid(a, b), _mid(b, c), _mid(c, a)
            new_tris += [[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]

        tris = new_tris

    return np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int64)


# ---------------------------------------------------------------------------
# Ray-triangle intersection  (Möller–Trumbore, vectorised over all faces)
# ---------------------------------------------------------------------------

def _ray_hits_count(
    origin: np.ndarray,
    direction: np.ndarray,
    verts: np.ndarray,
    faces: np.ndarray,
    eps: float = 1e-9,
) -> int:
    """Count how many triangles a ray hits (parity test).

    Vectorised over all faces simultaneously — ~100× faster than a Python loop.
    """
    v0 = verts[faces[:, 0]]        # (F, 3)
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    e1 = v1 - v0                   # (F, 3)
    e2 = v2 - v0
    h = np.cross(direction, e2)    # (F, 3)  — direction broadcast
    a = np.einsum("ij,ij->i", e1, h)  # (F,)
    valid = np.abs(a) > eps
    inv_a = np.where(valid, 1.0 / np.where(valid, a, 1.0), 0.0)
    s = origin - v0                # (F, 3)
    u = inv_a * np.einsum("ij,ij->i", s, h)
    u_ok = (u >= 0.0) & (u <= 1.0)
    q = np.cross(s, e1)            # (F, 3)
    v = inv_a * np.einsum("j,ij->i", direction, q)
    v_ok = (v >= 0.0) & (u + v <= 1.0)
    t = inv_a * np.einsum("ij,ij->i", e2, q)
    hit = valid & u_ok & v_ok & (t > eps)
    return int(np.sum(hit))


# ---------------------------------------------------------------------------
# Snake3D
# ---------------------------------------------------------------------------

class Snake3D:
    """3D Active Contour that fits a smooth minimal surface to a point cloud.

    Energy decomposition
    --------------------
    E_total = α · E_internal  +  β · E_external

    E_internal  Laplacian smoothness — resists bending / high curvature.
                High α → snake stays smooth and bypasses small protrusions
                (window frames, bolts) because wrapping them would cost more
                internal energy than the small external attraction they offer.

    E_external  Nearest-point attraction — pulls surface toward sampled geometry.
                High β → tighter fit to every surface detail.

    Initialisation
    --------------
    The snake starts as the convex hull of the sampled point cloud, then
    subdivides that hull mesh (default 2 levels) to obtain enough vertices for
    fine deformation, then iterates.

    Parameters
    ----------
    sampled_points: (K, 3) float array from sample_mesh_surface().
    alpha:  smoothness weight  (higher → more protrusions bypassed).
    beta:   attraction weight  (higher → tighter fit).
    dt:     integration step   (smaller → more stable, slower).
    max_iterations:            safety cap on iteration count.
    convergence_threshold:     stop when max vertex displacement < this.
    subdivision_levels:        convex-hull subdivision before iteration.
    """

    def __init__(
        self,
        sampled_points: np.ndarray,
        alpha: float = 0.6,
        beta: float = 0.3,
        dt: float = 0.15,
        max_iterations: int = 300,
        convergence_threshold: float = 1e-4,
        subdivision_levels: int = 2,
    ) -> None:
        self.sampled_points = np.asarray(sampled_points, dtype=np.float64)
        self.alpha = alpha
        self.beta = beta
        self.dt = dt
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold

        self._kd = KDTree(self.sampled_points)

        hull = ConvexHull(self.sampled_points)
        init_verts = self.sampled_points[hull.vertices].copy()
        vmap = {old: new for new, old in enumerate(hull.vertices)}
        init_faces = np.array(
            [[vmap[int(i)] for i in s] for s in hull.simplices], dtype=np.int64
        )
        self.vertices, self.faces = subdivide_mesh(
            init_verts, init_faces, levels=subdivision_levels
        )
        self._nbrs: List[List[int]] = self._build_neighbors()

        # Snapshots stored during fit() for visualization
        self.snapshots: List[np.ndarray] = [self.vertices.copy()]
        self.max_displacements: List[float] = []
        self.iterations_run: int = 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_neighbors(self) -> List[List[int]]:
        adj: dict[int, set] = defaultdict(set)
        for f in self.faces:
            a, b, c = int(f[0]), int(f[1]), int(f[2])
            adj[a].update({b, c})
            adj[b].update({a, c})
            adj[c].update({a, b})
        return [sorted(adj[i]) for i in range(len(self.vertices))]

    def _laplacian_force(self) -> np.ndarray:
        """Pull each vertex toward the mean position of its mesh neighbours."""
        F = np.zeros_like(self.vertices)
        for i, nbrs in enumerate(self._nbrs):
            if nbrs:
                F[i] = self.vertices[nbrs].mean(axis=0) - self.vertices[i]
        return F

    def _external_force(self) -> np.ndarray:
        """Pull each vertex toward its nearest sampled surface point."""
        _, idxs = self._kd.query(self.vertices)
        return self.sampled_points[idxs] - self.vertices

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self) -> float:
        """Perform one Snake iteration.  Returns max vertex displacement."""
        disp = self.dt * (
            self.alpha * self._laplacian_force()
            + self.beta * self._external_force()
        )
        self.vertices += disp
        self.iterations_run += 1
        max_d = float(np.max(np.linalg.norm(disp, axis=1)))
        self.max_displacements.append(max_d)
        return max_d

    def fit(self, snapshot_every: int = 25, plateau_window: int = 20,
            plateau_rtol: float = 0.02) -> "Snake3D":
        """Run the snake until convergence or plateau.  Returns self for chaining.

        Stops when either:
        - max vertex displacement drops below convergence_threshold, OR
        - displacement hasn't changed more than plateau_rtol over the last
          plateau_window iterations (equilibrium reached).

        Args:
            snapshot_every: store a vertex snapshot every N iterations.
            plateau_window:  window size for plateau detection (default 20).
            plateau_rtol:    relative change threshold for plateau (default 2%).
        """
        for i in range(self.max_iterations):
            max_d = self.step()
            if (i + 1) % snapshot_every == 0:
                self.snapshots.append(self.vertices.copy())
            if max_d < self.convergence_threshold:
                break
            if len(self.max_displacements) >= plateau_window * 2:
                w = self.max_displacements
                older = sum(w[-plateau_window * 2:-plateau_window]) / plateau_window
                recent = sum(w[-plateau_window:]) / plateau_window
                if abs(older - recent) / (older + 1e-12) < plateau_rtol:
                    break
        self.snapshots.append(self.vertices.copy())
        return self

    def contains(self, point: np.ndarray) -> bool:
        """True if point lies inside the snake surface.

        Ray-parity test: cast three rays and take majority vote.
        Uses vectorised Möller–Trumbore over all faces — fast even for dense meshes.
        """
        p = np.asarray(point, dtype=np.float64)
        votes = 0
        for d in [
            np.array([0.0, 0.0, 1.0]),
            np.array([0.0, 1.0, 0.1]),
            np.array([1.0, 0.0, 0.1]),
        ]:
            votes += _ray_hits_count(p, d, self.vertices, self.faces) % 2
        return votes >= 2

    def contains_batch(self, points: np.ndarray) -> np.ndarray:
        """Vectorised inside test.  Returns bool array of shape (N,)."""
        return np.array([self.contains(p) for p in points], dtype=bool)
