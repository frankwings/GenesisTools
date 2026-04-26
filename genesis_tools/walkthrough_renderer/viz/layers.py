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
    res_hint = 0.5  # display size fallback if no bounds info

    bounds = path_data.bounds
    res = config.get("grid_resolution", res_hint)
    min_x, min_y, min_z = bounds[0], bounds[1], bounds[4]
    wp_r = res * 0.25
    cam_h = config.get("camera_height", 1.7)
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h_bu = cam_h / unit_scale

    # Green -- waypoints
    for i, wp in enumerate(path_data.waypoints):
        cx = min_x + (wp[0]+0.5)*res
        cy = min_y + (wp[1]+0.5)*res
        cz = min_z + wp[2]*res
        obj = make_sphere(f"dbg_waypoint_{i:02d}", Vector((cx, cy, cz)),
                          wp_r, (0.1, 1.0, 0.2))
        _debug_collection().objects.unlink(obj)
        _spheres_col().objects.link(obj)

    # Pink -- path line at camera height
    if len(path_data.path_points) >= 2:
        pts = [Vector((p[0], p[1], p[2] + cam_h_bu)) for p in path_data.path_points]
        make_line("dbg_path", pts, (1.0, 0.3, 0.6), thickness=res * 0.05)


def add_camera_layer(camera_blend: str, fps: int, res: float) -> None:
    """Add camera axes layer: RGB arrows at each 1-second frame."""
    import bpy
    from mathutils import Vector

    bpy.ops.wm.open_mainfile(filepath=camera_blend)
    cam_obj = bpy.context.scene.camera
    if cam_obj is None:
        print("[CameraLayer] No camera found in blend file, skipping.")
        return

    total_frames = bpy.context.scene.frame_end
    axis_len = res * 0.6
    shaft_r  = res * 0.015
    head_r   = res * 0.05
    step = max(1, fps)

    for fi in range(0, total_frames, step):
        bpy.context.scene.frame_set(fi + 1)
        pos  = Vector(cam_obj.location)
        mat4 = cam_obj.matrix_world.to_3x3()
        right   = Vector(mat4.col[0]).normalized()
        up      = Vector(mat4.col[1]).normalized()
        forward = -Vector(mat4.col[2]).normalized()
        make_arrow(f"dbg_cam_x_{fi:04d}", pos, right,   axis_len, (1,0,0), shaft_r, head_r)
        make_arrow(f"dbg_cam_y_{fi:04d}", pos, up,      axis_len, (0,1,0), shaft_r, head_r)
        make_arrow(f"dbg_cam_z_{fi:04d}", pos, forward, axis_len, (0,0.4,1), shaft_r, head_r)
