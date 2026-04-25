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

import random
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
    rng = random.Random(seed)
    pts: List[np.ndarray] = []

    for verts, faces in mesh_list:
        verts = np.asarray(verts, dtype=np.float64)
        faces = np.asarray(faces, dtype=np.int64)
        for tri in faces:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            area = float(np.linalg.norm(np.cross(v1 - v0, v2 - v0))) * 0.5
            n = max(1, int(area / (sampling_resolution ** 2)))
            for _ in range(n):
                r1 = rng.random()
                r2 = rng.random()
                if r1 + r2 > 1.0:
                    r1, r2 = 1.0 - r1, 1.0 - r2
                pts.append((1.0 - r1 - r2) * v0 + r1 * v1 + r2 * v2)

    if not pts:
        raise ValueError("No points sampled — mesh_list is empty or degenerate.")
    return np.array(pts, dtype=np.float64)


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
# Ray-triangle intersection  (Möller–Trumbore)
# ---------------------------------------------------------------------------

def _ray_tri_hit(
    origin: np.ndarray,
    direction: np.ndarray,
    v0: np.ndarray,
    v1: np.ndarray,
    v2: np.ndarray,
    eps: float = 1e-9,
) -> bool:
    """Return True if ray (origin + t·direction, t > eps) intersects triangle."""
    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(direction, e2)
    a = float(e1 @ h)
    if abs(a) < eps:
        return False
    f = 1.0 / a
    s = origin - v0
    u = f * float(s @ h)
    if u < 0.0 or u > 1.0:
        return False
    q = np.cross(s, e1)
    v = f * float(direction @ q)
    if v < 0.0 or u + v > 1.0:
        return False
    return f * float(e2 @ q) > eps


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
        dt: float = 0.05,
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

    def fit(self, snapshot_every: int = 25) -> "Snake3D":
        """Run the snake until convergence.  Returns self for chaining.

        Args:
            snapshot_every: store a vertex snapshot every N iterations for
                            the visualization script.
        """
        for i in range(self.max_iterations):
            max_d = self.step()
            if (i + 1) % snapshot_every == 0:
                self.snapshots.append(self.vertices.copy())
            if max_d < self.convergence_threshold:
                break
        self.snapshots.append(self.vertices.copy())
        return self

    def contains(self, point: np.ndarray) -> bool:
        """True if point lies inside the snake surface.

        Uses the ray-parity test: cast a ray in +Z and count triangle
        intersections.  Odd count → inside.  Even (including 0) → outside.

        For robustness against degenerate alignment, three ray directions are
        tested and the majority vote is returned.
        """
        p = np.asarray(point, dtype=np.float64)
        results = []
        for d in [
            np.array([0.0, 0.0, 1.0]),
            np.array([0.0, 1.0, 0.1]),
            np.array([1.0, 0.0, 0.1]),
        ]:
            cnt = sum(
                1 for f in self.faces
                if _ray_tri_hit(
                    p, d,
                    self.vertices[int(f[0])],
                    self.vertices[int(f[1])],
                    self.vertices[int(f[2])],
                )
            )
            results.append(cnt % 2)
        return sum(results) >= 2  # majority vote

    def contains_batch(self, points: np.ndarray) -> np.ndarray:
        """Vectorised inside test.  Returns bool array of shape (N,)."""
        return np.array([self.contains(p) for p in points], dtype=bool)
