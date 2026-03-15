"""Unit tests for walkthrough_renderer pure-Python logic.

``bpy`` and ``mathutils`` are mocked at import time so no Blender
installation is required to run these tests.

Tested functions
----------------
_flood_fill_free_from_camera   — BFS through free voxels from camera voxel
_check_walkable_v2             — downward ray-cast walkable check (no cam_h limit)
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Lightweight Vector stub that satisfies `.x / .y / .z` access and unpacking
# ---------------------------------------------------------------------------

class _Vector:
    def __init__(self, xyz):
        self.x, self.y, self.z = float(xyz[0]), float(xyz[1]), float(xyz[2])

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __repr__(self):
        return f"Vector({self.x}, {self.y}, {self.z})"


# ---------------------------------------------------------------------------
# Inject mocks into sys.modules BEFORE the module is imported.
# Both bpy and mathutils are required by render_walkthrough at module level.
# ---------------------------------------------------------------------------

_bpy_mock = MagicMock(name="bpy")

_mathutils_mock = ModuleType("mathutils")
_mathutils_mock.Vector = _Vector  # type: ignore[attr-defined]

sys.modules.setdefault("bpy", _bpy_mock)
sys.modules.setdefault("mathutils", _mathutils_mock)

from genesis_tools.walkthrough_renderer.render_walkthrough import (  # noqa: E402
    _flood_fill_free_from_camera,
    _check_walkable_v2,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_config():
    return {
        "camera_height": 1.7,
        "_unit_scale": 1.0,
        "grid_resolution": 1.0,
        "_effective_grid_resolution": 1.0,
    }


def _make_bounds():
    """min_x=0, min_y=0, max_x=5, max_y=5, min_z=0, max_z=5."""
    return (0.0, 0.0, 5.0, 5.0, 0.0, 5.0)


def _setup_ray_cast(return_value):
    """Set bpy.context.scene.ray_cast to always return `return_value`."""
    _bpy_mock.context.scene.ray_cast.return_value = return_value
    _bpy_mock.context.evaluated_depsgraph_get.return_value = MagicMock()


def _setup_ray_cast_sequence(return_values):
    """Set bpy.context.scene.ray_cast to return items from the list in order."""
    it = iter(return_values)
    _bpy_mock.context.scene.ray_cast.side_effect = lambda dg, o, d: next(it)


# ===========================================================================
# _flood_fill_free_from_camera
# ===========================================================================

class TestFloodFillFreeFromCamera:

    def test_single_free_voxel(self):
        """1×1×1 grid, camera voxel is free → only that voxel returned."""
        result = _flood_fill_free_from_camera(set(), (0, 0, 0), 1, 1, 1)
        assert result == {(0, 0, 0)}

    def test_fully_open_grid_fills_all(self):
        """Fully free 2×2×2 grid — all 8 voxels reachable from any corner."""
        result = _flood_fill_free_from_camera(set(), (0, 0, 0), 2, 2, 2)
        assert len(result) == 8

    def test_solid_wall_blocks_flood_fill(self):
        """Solid column at x=1 isolates left voxel from the right side."""
        # Layout:  [cam] [wall] [other]   (3×1×1)
        solid = {(1, 0, 0)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 3, 1, 1)
        assert (0, 0, 0) in result          # camera voxel reachable
        assert (1, 0, 0) not in result      # solid — excluded from result
        assert (2, 0, 0) not in result      # blocked by wall

    def test_camera_surrounded_by_walls_gives_island(self):
        """Camera is isolated in the middle; only its voxel is reachable."""
        solid = {(1, 0, 0), (3, 0, 0)}     # walls on both sides
        result = _flood_fill_free_from_camera(solid, (2, 0, 0), 5, 1, 1)
        assert result == {(2, 0, 0)}

    def test_camera_in_solid_snaps_to_nearest_free(self):
        """Camera voxel is solid → BFS snaps to nearest free voxel and fills from there."""
        # 3×1×1: voxel 0 is solid; free space is {1, 2}
        solid = {(0, 0, 0)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 3, 1, 1)
        assert (0, 0, 0) not in result
        assert {(1, 0, 0), (2, 0, 0)}.issubset(result)

    def test_all_solid_returns_empty(self):
        """All voxels solid → empty result (no free voxel to snap to)."""
        solid = {(ix, iy, iz)
                 for ix in range(2) for iy in range(2) for iz in range(2)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 0), 2, 2, 2)
        assert result == set()

    def test_bfs_stays_within_bounds(self):
        """No returned index exceeds grid dimensions."""
        result = _flood_fill_free_from_camera(set(), (1, 1, 1), 3, 3, 3)
        for (ix, iy, iz) in result:
            assert 0 <= ix < 3
            assert 0 <= iy < 3
            assert 0 <= iz < 3

    def test_partial_room_floor_ceiling_solid(self):
        """Free voxels sandwiched between solid floor and solid ceiling are reachable."""
        # 1×1×5: iz=0 solid (floor), iz=4 solid (ceiling), iz=1,2,3 free
        solid = {(0, 0, 0), (0, 0, 4)}
        result = _flood_fill_free_from_camera(solid, (0, 0, 2), 1, 1, 5)
        assert {(0, 0, 1), (0, 0, 2), (0, 0, 3)}.issubset(result)
        assert (0, 0, 0) not in result
        assert (0, 0, 4) not in result


# ===========================================================================
# _check_walkable_v2  — cam_h height restriction REMOVED
# ===========================================================================

class TestCheckWalkableV2:

    def test_upward_floor_hit_is_walkable(self):
        """Voxel above an upward-facing floor → walkable."""
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((0.0, 0.0, 1.0))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) in result

    def test_low_voxel_now_walkable_after_removing_cam_h_check(self):
        """Voxel very close to floor (height < cam_h=1.7) is walkable.

        Before the fix, the condition ``(vz - loc.z) >= cam_h`` blocked these.
        iz=0 → vz = 0 + 0.5*1 = 0.5 m; floor at z=0 → height = 0.5 < 1.7.
        This must now pass.
        """
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((0.0, 0.0, 1.0))))
        result = _check_walkable_v2({(0, 0, 0)}, _make_bounds(), _make_config())
        assert (0, 0, 0) in result, (
            "Low voxel should be walkable now that cam_h restriction is removed"
        )

    def test_no_floor_hit_not_walkable(self):
        """ray_cast misses (hit=False) → not walkable."""
        _setup_ray_cast((False, _Vector((0.0, 0.0, 0.0)), _Vector((0.0, 0.0, 1.0))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) not in result

    def test_wall_normal_not_walkable(self):
        """Ray hits a vertical surface (normal.z ≈ 0) → not walkable."""
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((1.0, 0.0, 0.0))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) not in result

    def test_ceiling_normal_not_walkable(self):
        """Ray hits a downward-facing surface (normal.z = -1) → not walkable."""
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((0.0, 0.0, -1.0))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) not in result

    def test_diagonal_normal_above_threshold_is_walkable(self):
        """Surface tilted at ~30° (normal.z ≈ 0.87 > 0.5) counts as walkable floor."""
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((0.0, 0.5, 0.866))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) in result

    def test_diagonal_normal_below_threshold_not_walkable(self):
        """Steep slope (normal.z = 0.3 < 0.5) not accepted as walkable."""
        _setup_ray_cast((True, _Vector((0.5, 0.5, 0.0)), _Vector((0.0, 0.954, 0.3))))
        result = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert (0, 0, 2) not in result

    def test_empty_candidates_returns_empty(self):
        """No candidate voxels → empty walkable set, ray_cast never called."""
        _bpy_mock.context.scene.ray_cast.reset_mock()
        result = _check_walkable_v2(set(), _make_bounds(), _make_config())
        assert result == set()
        _bpy_mock.context.scene.ray_cast.assert_not_called()

    def test_all_candidates_walkable(self):
        """Two candidates both above upward floor → both walkable."""
        floor = _Vector((0.0, 0.0, 0.0))
        up    = _Vector((0.0, 0.0, 1.0))
        _setup_ray_cast((True, floor, up))      # same return for every call
        result = _check_walkable_v2({(0, 0, 1), (1, 0, 1)}, _make_bounds(), _make_config())
        assert result == {(0, 0, 1), (1, 0, 1)}

    def test_only_upward_normals_counted(self):
        """Mix of floor and wall hits: only floor hits produce walkable voxels."""
        floor  = _Vector((0.0, 0.0, 0.0))
        up     = _Vector((0.0, 0.0, 1.0))
        horiz  = _Vector((1.0, 0.0, 0.0))
        # We have exactly two candidates; one gets an upward hit, one a wall hit.
        # Since the set order is unpredictable we set both responses the same
        # and verify the count manually via a controlled single-voxel approach.
        _setup_ray_cast((True, floor, up))
        r1 = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        _setup_ray_cast((True, floor, horiz))
        r2 = _check_walkable_v2({(0, 0, 2)}, _make_bounds(), _make_config())
        assert len(r1) == 1 and len(r2) == 0


# ===========================================================================
# mark_parity removal — structural test
# ===========================================================================

class TestNoParilyFillInXYRays:
    """Verify mark_parity is not called for X-axis or Y-axis ray sweeps.

    We check the source code itself: after the removal the strings
    ``mark_parity`` must not appear in the X-ray or Y-ray loop bodies
    within _build_local_voxel_grid.
    """

    def test_mark_parity_not_invoked_in_xy_rays(self):
        import inspect
        import genesis_tools.walkthrough_renderer.render_walkthrough as rw
        src = inspect.getsource(rw._build_local_voxel_grid)

        # The helper definition itself may still be present (it's nested),
        # but it must NOT be called after the comment "X-axis rays" or
        # "Y-axis rays" sections.
        x_section_start = src.find("# X-axis rays")
        y_section_start = src.find("# Y-axis rays")
        assert x_section_start != -1, "Expected '# X-axis rays' comment not found"
        assert y_section_start != -1, "Expected '# Y-axis rays' comment not found"

        # Check that mark_parity() call is absent from both sections
        x_section = src[x_section_start:y_section_start]
        y_section  = src[y_section_start:]

        assert "mark_parity(" not in x_section, \
            "mark_parity() call found in X-axis ray section — parity fill not removed"
        assert "mark_parity(" not in y_section, \
            "mark_parity() call found in Y-axis ray section — parity fill not removed"
