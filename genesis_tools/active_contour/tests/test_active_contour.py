"""Unit tests for genesis_tools.active_contour.snake_3d.

No Blender dependency — all geometry is constructed in pure NumPy.

Test coverage
-------------
sample_mesh_surface
  - basic sampling produces more points than just vertices
  - samples lie on the triangle faces (barycentric check)
  - large flat face with sparse vertices gets dense coverage

subdivide_mesh
  - each level quadruples triangle count
  - new vertices lie on original edges

Snake3D
  - initialises with a valid convex-hull mesh
  - fit() converges (max displacement drops)
  - contains() correctly classifies interior / exterior for a cube
  - KEY: high alpha bypasses small protrusion (spike tip outside contour)
  - KEY: low alpha wraps small protrusion (spike tip inside contour)
"""

import numpy as np
import pytest

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
    subdivide_mesh,
)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _unit_cube_mesh():
    """Axis-aligned unit cube [0,1]³ as (vertices, faces)."""
    v = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=float)
    f = np.array([
        [0, 2, 1], [0, 3, 2],   # bottom  (z=0)
        [4, 5, 6], [4, 6, 7],   # top     (z=1)
        [0, 1, 5], [0, 5, 4],   # front   (y=0)
        [2, 3, 7], [2, 7, 6],   # back    (y=1)
        [0, 4, 7], [0, 7, 3],   # left    (x=0)
        [1, 2, 6], [1, 6, 5],   # right   (x=1)
    ], dtype=int)
    return v, f


def _cube_with_spike_mesh(spike_height: float = 0.2, spike_base: float = 0.15):
    """Unit cube with a small square pyramid on the centre of the top face.

    The pyramid base sits at z=1, centred at (0.5, 0.5).
    Spike tip is at (0.5, 0.5, 1 + spike_height).

    The pyramid is intentionally small relative to the cube so that a
    high-alpha snake will bypass it (insufficient attraction to overcome
    the curvature penalty).
    """
    cv, cf = _unit_cube_mesh()

    cx, cy = 0.5, 0.5
    h = spike_height
    b = spike_base
    tip_idx = len(cv)
    tip = np.array([[cx, cy, 1.0 + h]])

    # Four base corners of the pyramid, sitting on the cube top face
    base_indices = len(cv) + 1 + np.arange(4)
    base = np.array([
        [cx - b, cy - b, 1.0],
        [cx + b, cy - b, 1.0],
        [cx + b, cy + b, 1.0],
        [cx - b, cy + b, 1.0],
    ])
    extra_verts = np.vstack([tip, base])

    # Four triangular faces of the pyramid
    t = tip_idx
    b0, b1, b2, b3 = int(base_indices[0]), int(base_indices[1]), int(base_indices[2]), int(base_indices[3])
    spike_faces = np.array([
        [t, b0, b1],
        [t, b1, b2],
        [t, b2, b3],
        [t, b3, b0],
    ], dtype=int)

    all_verts = np.vstack([cv, extra_verts])
    all_faces = np.vstack([cf, spike_faces])
    return all_verts, all_faces


# ---------------------------------------------------------------------------
# sample_mesh_surface
# ---------------------------------------------------------------------------

class TestSampleMeshSurface:

    def test_produces_more_than_vertex_count(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.2)
        assert len(pts) > len(v), "should produce many more points than vertices"

    def test_samples_within_cube_bounds(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.2)
        assert np.all(pts >= -1e-9)
        assert np.all(pts <= 1.0 + 1e-9)

    def test_large_face_gets_dense_coverage(self):
        """A single large quad (4 verts, 2 tris) should produce many samples."""
        v = np.array([[0,0,0],[10,0,0],[10,10,0],[0,10,0]], dtype=float)
        f = np.array([[0,1,2],[0,2,3]], dtype=int)
        pts = sample_mesh_surface([(v, f)], sampling_resolution=1.0)
        # 100 m² area / 1 m² per sample ≈ 100 points minimum
        assert len(pts) >= 80

    def test_empty_mesh_raises(self):
        with pytest.raises(ValueError):
            sample_mesh_surface([], sampling_resolution=0.5)

    def test_reproducibility_with_seed(self):
        v, f = _unit_cube_mesh()
        pts1 = sample_mesh_surface([(v, f)], sampling_resolution=0.3, seed=7)
        pts2 = sample_mesh_surface([(v, f)], sampling_resolution=0.3, seed=7)
        np.testing.assert_array_equal(pts1, pts2)


# ---------------------------------------------------------------------------
# subdivide_mesh
# ---------------------------------------------------------------------------

class TestSubdivideMesh:

    def test_triangle_count_quadruples_each_level(self):
        v, f = _unit_cube_mesh()
        _, f1 = subdivide_mesh(v, f, levels=1)
        _, f2 = subdivide_mesh(v, f, levels=2)
        assert len(f1) == len(f) * 4
        assert len(f2) == len(f) * 16

    def test_new_vertices_between_originals(self):
        v = np.array([[0, 0, 0], [2, 0, 0], [1, 2, 0]], dtype=float)
        f = np.array([[0, 1, 2]], dtype=int)
        v2, _ = subdivide_mesh(v, f, levels=1)
        # Midpoint of edge (0,1) should be (1,0,0)
        midpoints = v2[3:]
        assert any(np.allclose(m, [1, 0, 0]) for m in midpoints)


# ---------------------------------------------------------------------------
# Snake3D — initialisation
# ---------------------------------------------------------------------------

class TestSnake3DInit:

    def test_has_faces_after_init(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.3)
        snake = Snake3D(pts, subdivision_levels=1)
        assert len(snake.faces) > 0
        assert len(snake.vertices) > 0

    def test_initial_snapshot_stored(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.3)
        snake = Snake3D(pts, subdivision_levels=1)
        assert len(snake.snapshots) == 1

    def test_vertices_cover_point_cloud(self):
        """Initial convex hull bounding box must contain all sampled points."""
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.5)
        snake = Snake3D(pts, subdivision_levels=0)
        # The snake vertices span at least the extent of the sampled points
        # (convex hull ⊇ point cloud, so hull AABB ⊇ point cloud AABB)
        hull_lo = snake.vertices.min(axis=0)
        hull_hi = snake.vertices.max(axis=0)
        pts_lo  = pts.min(axis=0)
        pts_hi  = pts.max(axis=0)
        tol = 1e-6
        assert np.all(hull_lo <= pts_lo + tol), "hull must extend below point cloud"
        assert np.all(hull_hi >= pts_hi - tol), "hull must extend above point cloud"


# ---------------------------------------------------------------------------
# Snake3D — convergence
# ---------------------------------------------------------------------------

class TestSnake3DConvergence:

    def test_displacement_decreases(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.3)
        snake = Snake3D(pts, alpha=0.5, beta=0.3, dt=0.05,
                        max_iterations=50, subdivision_levels=1)
        snake.fit()
        disps = snake.max_displacements
        # Displacement should trend downward overall
        assert disps[-1] < disps[0]

    def test_snapshots_recorded(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.3)
        snake = Snake3D(pts, subdivision_levels=1, max_iterations=50)
        snake.fit(snapshot_every=10)
        assert len(snake.snapshots) >= 2


# ---------------------------------------------------------------------------
# Snake3D — inside/outside  (cube)
# ---------------------------------------------------------------------------

class TestSnake3DContainsCube:

    @pytest.fixture(scope="class")
    def fitted_snake(self):
        v, f = _unit_cube_mesh()
        pts = sample_mesh_surface([(v, f)], sampling_resolution=0.15)
        return Snake3D(pts, alpha=0.5, beta=0.4, dt=0.05,
                       max_iterations=200, subdivision_levels=2).fit()

    def test_centre_is_inside(self, fitted_snake):
        assert fitted_snake.contains([0.5, 0.5, 0.5])

    def test_far_point_is_outside(self, fitted_snake):
        assert not fitted_snake.contains([5.0, 5.0, 5.0])

    def test_negative_point_is_outside(self, fitted_snake):
        assert not fitted_snake.contains([-1.0, 0.5, 0.5])

    def test_batch_matches_single(self, fitted_snake):
        pts = np.array([[0.5, 0.5, 0.5], [5.0, 5.0, 5.0]])
        batch = fitted_snake.contains_batch(pts)
        single = np.array([fitted_snake.contains(p) for p in pts])
        np.testing.assert_array_equal(batch, single)


# ---------------------------------------------------------------------------
# KEY TEST — protrusion bypass
# ---------------------------------------------------------------------------

class TestProtrusionBypass:
    """
    The core guarantee of the Snake:
    High alpha (strong smoothness) → small spike EXCLUDED from contour.
    Low  alpha (weak  smoothness) → small spike INCLUDED in contour.

    Geometry: unit cube [0,1]³ with a 0.3 m pyramid (base 0.20) on the top face.
    Spike tip is at (0.5, 0.5, 1.3).
    TEST_POINT is at z=1.10 — well within the sampled region of the spike faces,
    so the attraction signal is reliable regardless of exact sample positions.
    """

    SPIKE_H = 0.2
    SPIKE_B = 0.12
    # z=1.15: well within sampled spike region (max_z≈1.18 at res=0.05)
    TEST_POINT = np.array([0.5, 0.5, 1.15])
    SAFE_INTERIOR = np.array([0.5, 0.5, 0.5])

    @pytest.fixture(scope="class")
    def mesh_pts(self):
        v, f = _cube_with_spike_mesh(spike_height=self.SPIKE_H, spike_base=self.SPIKE_B)
        return sample_mesh_surface([(v, f)], sampling_resolution=0.05)

    @pytest.fixture(scope="class")
    def snake_high_alpha(self, mesh_pts):
        """High smoothness — should bypass the spike."""
        return Snake3D(
            mesh_pts, alpha=0.85, beta=0.15, dt=0.04,
            max_iterations=300, subdivision_levels=2,
        ).fit()

    @pytest.fixture(scope="class")
    def snake_low_alpha(self, mesh_pts):
        """Low smoothness — should wrap the spike."""
        return Snake3D(
            mesh_pts, alpha=0.10, beta=0.80, dt=0.02,
            max_iterations=300, subdivision_levels=2,
        ).fit()

    def test_cube_centre_always_inside_high_alpha(self, snake_high_alpha):
        assert snake_high_alpha.contains(self.SAFE_INTERIOR), \
            "cube interior must always be inside the contour"

    def test_cube_centre_always_inside_low_alpha(self, snake_low_alpha):
        assert snake_low_alpha.contains(self.SAFE_INTERIOR), \
            "cube interior must always be inside the contour"

    def test_high_alpha_bypasses_spike(self, snake_high_alpha):
        """With strong smoothness the spike tip must be OUTSIDE the contour."""
        assert not snake_high_alpha.contains(self.TEST_POINT), (
            "High-alpha snake should smooth over the small spike — "
            "spike tip must be excluded from the contour"
        )

    def test_low_alpha_wraps_spike(self, snake_low_alpha):
        """With weak smoothness the spike tip must be INSIDE the contour."""
        assert snake_low_alpha.contains(self.TEST_POINT), (
            "Low-alpha snake should wrap the spike — "
            "spike tip must be included in the contour"
        )
