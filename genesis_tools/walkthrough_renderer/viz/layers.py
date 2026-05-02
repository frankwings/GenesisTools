"""Per-step debug visualization layers.

All functions operate on the currently-open bpy scene.
Layers are additive -- pass any combination of data to visualize.

Color scheme:
  Red    -- solid voxels
  Yellow -- free voxels (not candidate)
  Blue   -- candidate voxels (free + reachable, not walkable)
  Cyan   -- walkable voxels
  Green  -- waypoints
  Pink   -- path line
  RGB    -- camera axes (X=red, Y=green, Z=blue)
"""
from __future__ import annotations

from genesis_tools.walkthrough_renderer.viz.primitives import (
    add_voxel_type,
    make_line,
    make_arrow,
    make_sphere,
    _spheres_col,
    _debug_collection,
)


def add_voxel_grid_layer(vg, config: dict) -> None:
    """Add voxel grid layer: red=solid, yellow=free (not candidate)."""
    res = vg.res
    bounds = vg.bounds

    solid_set = {tuple(r) for r in vg.solid}
    cand_set  = {tuple(r) for r in vg.candidates}

    # Red -- solid
    add_voxel_type("solid", list(solid_set), bounds, res, (1.0, 0.1, 0.1))

    # Yellow -- free and not candidate (outside flood-fill)
    yellow = []
    for ix in range(vg.nx):
        for iy in range(vg.ny):
            for iz in range(vg.nz):
                cell = (ix, iy, iz)
                if cell not in solid_set and cell not in cand_set:
                    yellow.append(cell)
    add_voxel_type("free", yellow, bounds, res, (1.0, 0.85, 0.0))

    if vg.hits is not None:
        from genesis_tools.walkthrough_renderer.viz.primitives import make_hit_markers
        s = res * 0.08
        make_hit_markers("dbg_hits", [(h[0], h[1], h[2]) for h in vg.hits],
                         s=s, color=(1.0, 1.0, 1.0))


def add_walkable_layer(vg, wk, config: dict) -> None:
    """Add walkable layer: blue=candidate-not-walkable, cyan=walkable."""
    res = vg.res
    bounds = vg.bounds

    cand_set     = {tuple(r) for r in vg.candidates}
    walkable_set = {tuple(r) for r in wk.walkable}

    # Blue -- candidate but not walkable
    blue = [c for c in cand_set if c not in walkable_set]
    add_voxel_type("candidate", blue, bounds, res, (0.2, 0.4, 1.0))

    # Cyan -- walkable
    add_voxel_type("walkable", list(walkable_set), bounds, res, (0.0, 0.9, 0.9))


def add_path_layer(path_data, config: dict) -> None:
    """Add path layer: green=waypoints, pink=path line."""
    from mathutils import Vector

    bounds = path_data.bounds
    unit_scale = config.get("_unit_scale", 1.0)
    # grid_resolution is in metres; convert to BU for all geometry sizing
    res = config.get("grid_resolution", 0.5) / unit_scale
    min_x, min_y, min_z = bounds[0], bounds[1], bounds[4]
    wp_r = res * 0.25
    cam_h = config.get("camera_height", 1.7)
    cam_h_bu = cam_h / unit_scale

    # Green -- waypoints
    for i, wp in enumerate(path_data.waypoints):
        cx = min_x + (wp[0]+0.5)*res
        cy = min_y + (wp[1]+0.5)*res
        cz = min_z + (wp[2]+0.5)*res
        obj = make_sphere(f"dbg_waypoint_{i:02d}", Vector((cx, cy, cz)),
                          wp_r, (0.1, 1.0, 0.2))
        _debug_collection().objects.unlink(obj)
        _spheres_col().objects.link(obj)

    # Pink -- path line at camera height (thickness 0.3*res so it's visible in overview renders)
    if len(path_data.path_points) >= 2:
        pts = [Vector((p[0], p[1], p[2] + cam_h_bu)) for p in path_data.path_points]
        make_line("dbg_path", pts, (1.0, 0.3, 0.6), thickness=res * 0.3)


def read_camera_poses(camera_blend: str, fps: int) -> list:
    """Read (pos, right, up, forward) tuples from an animated .blend without
    modifying the current bpy scene.  Call this BEFORE opening the main blend.

    Returns a list of (pos, right, up, forward) each as plain tuples so no
    mathutils objects survive across scene loads.
    """
    import bpy
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=camera_blend)
    cam_obj = bpy.context.scene.camera
    if cam_obj is None:
        return []

    total_frames = bpy.context.scene.frame_end
    step = max(1, fps)
    poses = []
    for fi in range(0, total_frames, step):
        bpy.context.scene.frame_set(fi + 1)
        pos = tuple(cam_obj.location)
        m   = cam_obj.matrix_world.to_3x3()
        right   = tuple(Vector(m.col[0]).normalized())
        up      = tuple(Vector(m.col[1]).normalized())
        forward = tuple((-Vector(m.col[2])).normalized())
        poses.append((pos, right, up, forward))
    return poses


def add_camera_layer(camera_blend: str, fps: int, res: float) -> None:
    """Add camera axes layer: RGB arrows at each 1-second frame.

    NOTE: this must be called AFTER the main blend is open (i.e. after all
    other layers are added).  It pre-reads poses via read_camera_poses when
    the caller passes camera_blend=None and poses directly, but external
    callers should use visualize() which handles the ordering.
    """
    from mathutils import Vector

    # Poses should have been pre-read by visualize() before opening main blend.
    # This function is kept for API compat; actual drawing is done by
    # _add_camera_arrows_from_poses().
    raise RuntimeError(
        "add_camera_layer() must not be called directly; "
        "use visualize() which pre-reads poses before opening the main blend."
    )


def add_camera_arrows(poses: list, res_bu: float) -> None:
    """Draw RGB camera-axis arrows from pre-read poses into the current scene.

    Args:
        poses:  list of (pos, right, up, forward) plain-tuple camera poses
        res_bu: voxel grid resolution in Blender units (not metres)
    """
    from mathutils import Vector

    axis_len = res_bu * 2.0
    shaft_r  = res_bu * 0.05
    head_r   = res_bu * 0.15

    for i, (pos, right, up, forward) in enumerate(poses):
        p = Vector(pos)
        make_arrow(f"dbg_cam_x_{i:04d}", p, Vector(right),   axis_len, (1,0,0), shaft_r, head_r)
        make_arrow(f"dbg_cam_y_{i:04d}", p, Vector(up),      axis_len, (0,1,0), shaft_r, head_r)
        make_arrow(f"dbg_cam_z_{i:04d}", p, Vector(forward), axis_len, (0,0.4,1), shaft_r, head_r)
