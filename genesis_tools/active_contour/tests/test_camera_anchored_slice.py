"""Unit tests for camera_anchored_slice helpers — pure NumPy, no bpy."""
import numpy as np

from genesis_tools.active_contour.camera_anchored_slice import (
    camera_anchored_iy,
    camera_anchored_ix,
)


# Standard 180×180 grid over ±1800 m world (matches arctic v57 pass-1 layout).
MIN_X = MIN_Y = -1800.0
RES   = 20.0
NX    = NY = 180


class TestCameraAnchoredIy:
    def test_camera_at_origin_picks_centre(self):
        # Camera at world (0, 0). Centre row of 180-cell axis from −1800 m
        # is iy = 90 (cell centre = −1800 + 90.5 * 20 = 10 m, closest to 0).
        camera = np.array([0.0, 0.0, 5.0])
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 90

    def test_camera_at_grid_min_clamps_low(self):
        camera = np.array([0.0, MIN_Y, 5.0])  # Y at world min
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 0

    def test_camera_at_grid_max_clamps_high(self):
        camera = np.array([0.0, MIN_Y + RES * NY, 5.0])  # Y at world max
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == NY - 1

    def test_camera_below_grid_min_still_clamps(self):
        camera = np.array([0.0, MIN_Y - 500.0, 5.0])
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 0

    def test_camera_above_grid_max_still_clamps(self):
        camera = np.array([0.0, MIN_Y + RES * NY + 500.0, 5.0])
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == NY - 1

    def test_round_to_nearest_cell(self):
        # Camera 0.04 m above origin (the actual arctic v57 camera Y).
        # World Y = 0.04 → (0.04 - (-1800))/20 - 0.5 = 89.502 → round to 90.
        camera = np.array([-68.55, 0.04, 2.72])
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 90

    def test_round_picks_nearest_cell_centre(self):
        # Cell iy spans world Y in [min_y + iy*res, min_y + (iy+1)*res),
        # centre at min_y + (iy + 0.5) * res.  iy=5 centre = -1690 m,
        # iy=6 centre = -1670 m. The function picks the cell whose centre
        # is closest to camera Y.
        camera = np.array([0.0, -1689.0, 0.0])  # 1 m past centre of cell 5
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 5
        camera = np.array([0.0, -1671.0, 0.0])  # 1 m past centre of cell 6
        assert camera_anchored_iy(camera, MIN_Y, RES, NY) == 6

    def test_camera_xyz_none_falls_back_to_centre(self):
        assert camera_anchored_iy(None, MIN_Y, RES, NY) == NY // 2

    def test_works_with_python_list(self):
        # Some callers may pass a tuple/list rather than np.ndarray.
        assert camera_anchored_iy([0.0, 0.0, 5.0], MIN_Y, RES, NY) == 90
        assert camera_anchored_iy((0.0, 0.0, 5.0), MIN_Y, RES, NY) == 90


class TestCameraAnchoredIx:
    def test_camera_at_origin_picks_centre(self):
        camera = np.array([0.0, 0.0, 5.0])
        assert camera_anchored_ix(camera, MIN_X, RES, NX) == 90

    def test_uses_x_component(self):
        # Helper must read camera[0] (X), not camera[1] (Y).
        camera = np.array([MIN_X, 0.0, 0.0])     # X at world min, Y at 0
        assert camera_anchored_ix(camera, MIN_X, RES, NX) == 0
        camera = np.array([MIN_X + RES * NX, 0.0, 0.0])
        assert camera_anchored_ix(camera, MIN_X, RES, NX) == NX - 1

    def test_camera_xyz_none_falls_back_to_centre(self):
        assert camera_anchored_ix(None, MIN_X, RES, NX) == NX // 2

    def test_clipping_below_min(self):
        camera = np.array([MIN_X - 10000.0, 0.0, 0.0])
        assert camera_anchored_ix(camera, MIN_X, RES, NX) == 0

    def test_clipping_above_max(self):
        camera = np.array([MIN_X + RES * NX + 10000.0, 0.0, 0.0])
        assert camera_anchored_ix(camera, MIN_X, RES, NX) == NX - 1


class TestSliceCoverage:
    """The chosen slice should land on a cell that contains a real
    column of the grid, not off-by-one out of bounds."""

    def test_iy_is_valid_grid_index(self):
        rng = np.random.default_rng(seed=42)
        for _ in range(50):
            cy = rng.uniform(MIN_Y - 200, MIN_Y + RES * NY + 200)
            iy = camera_anchored_iy(np.array([0.0, cy, 0.0]), MIN_Y, RES, NY)
            assert 0 <= iy < NY

    def test_ix_is_valid_grid_index(self):
        rng = np.random.default_rng(seed=42)
        for _ in range(50):
            cx = rng.uniform(MIN_X - 200, MIN_X + RES * NX + 200)
            ix = camera_anchored_ix(np.array([cx, 0.0, 0.0]), MIN_X, RES, NX)
            assert 0 <= ix < NX

    def test_finer_resolution_is_more_accurate(self):
        # With res=1.0 the cell centre at the camera Y matches camera Y to
        # within 0.5 m — so anchored cell centre should be very close.
        cam_y = 7.3
        camera = np.array([0.0, cam_y, 0.0])
        iy = camera_anchored_iy(camera, MIN_Y, 1.0, 4000)
        cell_centre_y = MIN_Y + (iy + 0.5) * 1.0
        assert abs(cell_centre_y - cam_y) <= 0.5
