"""Unit tests for the pure-NumPy helpers in fit_terrain_contour.

The full `fit_terrain_contour()` requires bpy (scene.ray_cast), but the
two helpers it relies on — `_hits_to_floor` and `_tight_bbox_of_valid` —
are pure NumPy and drive the two-pass refinement logic, so they get
their own tests.
"""
import numpy as np

from genesis_tools.active_contour.fit_terrain_contour import (
    _hits_to_floor,
    _tight_bbox_of_valid,
)


# ────────────────────────────────────────────────────────────────────────
# _hits_to_floor — picks the topmost valid hit per column, dropping the
# bottom percentile that catches env-sphere inner-surface hits.
# ────────────────────────────────────────────────────────────────────────
class TestHitsToFloor:
    def test_topmost_valid_hit_per_column(self):
        # Column (0, 0) has two surface hits at +5 and +10 — topmost wins.
        column_hits = {(0, 0): [5.0, 10.0],
                       (0, 1): [3.0],
                       (1, 0): [],
                       (1, 1): [-50.0]}
        all_hits = [5.0, 10.0, 3.0, -50.0]
        floor, z_lo = _hits_to_floor(column_hits, all_hits, 2, 2,
                                     env_sphere_percentile=5.0, min_z=-500.0)
        assert floor[0, 0] == 10.0
        assert floor[0, 1] == 3.0
        assert np.isnan(floor[1, 0])
        # (1, 1) only has -50 → above the p5 threshold (which is -47.85),
        # but only barely; verify exact behaviour below.
        # With 4 hits sorted ascending = [-50, 3, 5, 10], p5 = -47.85.
        # -50 < p5 → dropped → NaN.
        assert np.isnan(floor[1, 1])

    def test_drops_below_env_sphere_percentile(self):
        # All hits below p5 → the column is NaN.
        column_hits = {(0, 0): [-200.0]}
        all_hits = [-200.0, -100.0, -50.0, 0.0, 100.0, 200.0]   # p5 = -177.5
        floor, z_lo = _hits_to_floor(column_hits, all_hits, 1, 1,
                                     env_sphere_percentile=5.0, min_z=-500.0)
        assert -190 < z_lo < -170
        assert np.isnan(floor[0, 0])

    def test_keeps_hit_above_env_sphere(self):
        column_hits = {(0, 0): [-50.0]}     # well above p5 = -177.5
        all_hits = [-200.0, -100.0, -50.0, 0.0, 100.0, 200.0]
        floor, _ = _hits_to_floor(column_hits, all_hits, 1, 1,
                                  env_sphere_percentile=5.0, min_z=-500.0)
        assert floor[0, 0] == -50.0

    def test_empty_hits_falls_back_to_min_z(self):
        # No hits anywhere → z_lo = min_z, all columns NaN.
        column_hits = {(0, 0): [], (0, 1): []}
        floor, z_lo = _hits_to_floor(column_hits, [], 1, 2,
                                     env_sphere_percentile=5.0, min_z=-500.0)
        assert z_lo == -500.0
        assert np.all(np.isnan(floor))

    def test_strict_greater_than_threshold(self):
        # _hits_to_floor uses `z > z_lo` (strict): a hit exactly at the
        # threshold is dropped. Verify this contract.
        column_hits = {(0, 0): [-100.0]}
        all_hits = [-100.0]                  # p5 of one element = -100
        floor, z_lo = _hits_to_floor(column_hits, all_hits, 1, 1,
                                     env_sphere_percentile=5.0, min_z=-500.0)
        assert z_lo == -100.0
        assert np.isnan(floor[0, 0])

    def test_returned_shape_matches_grid(self):
        column_hits = {(ix, iy): [1.0] for ix in range(7) for iy in range(11)}
        floor, _ = _hits_to_floor(column_hits, [1.0] * 77, 7, 11,
                                  env_sphere_percentile=5.0, min_z=-500.0)
        assert floor.shape == (7, 11)
        assert floor.dtype == np.float64


# ────────────────────────────────────────────────────────────────────────
# _tight_bbox_of_valid — world-coord tight bbox of valid (non-NaN) cells
# in a (nx, ny) floor grid, plus a small NaN border for Laplacian context.
# ────────────────────────────────────────────────────────────────────────
class TestTightBboxOfValid:
    def test_centre_block_no_padding(self):
        floor = np.full((10, 10), np.nan)
        floor[3:6, 4:7] = 1.0   # 3×3 block at (3..5, 4..6)
        bbox = _tight_bbox_of_valid(floor, min_x=-100.0, min_y=-100.0,
                                    res_bu=10.0, pad_cells=0)
        # ix range 3..5 → world X [3*10, (5+1)*10) = [-70, -40)
        # iy range 4..6 → world Y [4*10, (6+1)*10) = [-60, -30)
        assert bbox == (-70.0, -60.0, -40.0, -30.0)

    def test_padding_grows_bbox(self):
        floor = np.full((10, 10), np.nan)
        floor[3:6, 4:7] = 1.0
        bbox = _tight_bbox_of_valid(floor, min_x=-100.0, min_y=-100.0,
                                    res_bu=10.0, pad_cells=2)
        # ix range 1..7, iy range 2..8
        assert bbox == (-90.0, -80.0, -20.0, -10.0)

    def test_padding_clipped_at_grid_edges(self):
        # Valid cells touch the bottom/left edges; padding must not
        # produce negative indices.
        floor = np.full((10, 10), np.nan)
        floor[0:2, 0:2] = 1.0
        bbox = _tight_bbox_of_valid(floor, min_x=-100.0, min_y=-100.0,
                                    res_bu=10.0, pad_cells=5)
        # ix should be clipped at 0, iy at 0; upper bounded at min(9, 1+5)=6
        # bbox = (min_x + 0*res, min_y + 0*res, min_x + (6+1)*res, min_y + (6+1)*res)
        assert bbox == (-100.0, -100.0, -30.0, -30.0)

    def test_no_valid_cells_returns_none(self):
        floor = np.full((5, 5), np.nan)
        assert _tight_bbox_of_valid(floor, 0.0, 0.0, 1.0, pad_cells=2) is None

    def test_single_valid_cell(self):
        floor = np.full((10, 10), np.nan)
        floor[4, 5] = 7.0
        bbox = _tight_bbox_of_valid(floor, min_x=0.0, min_y=0.0,
                                    res_bu=10.0, pad_cells=0)
        assert bbox == (40.0, 50.0, 50.0, 60.0)

    def test_default_pad_is_two(self):
        # The default pad in fit_terrain_contour is 2 cells. Verify.
        floor = np.full((10, 10), np.nan)
        floor[5, 5] = 1.0
        # Default pad = 2 → ix range 3..7, iy range 3..7
        bbox = _tight_bbox_of_valid(floor, min_x=0.0, min_y=0.0, res_bu=10.0)
        assert bbox == (30.0, 30.0, 80.0, 80.0)

    def test_full_grid_valid(self):
        floor = np.zeros((4, 4), dtype=np.float64)
        bbox = _tight_bbox_of_valid(floor, min_x=-2.0, min_y=-2.0,
                                    res_bu=1.0, pad_cells=0)
        assert bbox == (-2.0, -2.0, 2.0, 2.0)

    def test_disjoint_valid_blobs_are_bounded(self):
        # Two separate blobs — bbox is the bounding box of both.
        floor = np.full((20, 20), np.nan)
        floor[2, 3] = 1.0
        floor[15, 18] = 1.0
        bbox = _tight_bbox_of_valid(floor, min_x=0.0, min_y=0.0,
                                    res_bu=1.0, pad_cells=0)
        # ix 2..15 → X [2, 16); iy 3..18 → Y [3, 19)
        assert bbox == (2.0, 3.0, 16.0, 19.0)
