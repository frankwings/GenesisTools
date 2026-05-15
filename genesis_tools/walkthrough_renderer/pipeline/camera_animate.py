"""Step 5: write camera keyframes into a copy of the .blend.

Input:  blend_path + PathData + OrientData
Output: animated .blend file (no render)

Requires bpy Python.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path


def build(blend_path: str, path_data, orient: "OrientData",
          config: dict, output_blend: str) -> str:
    """Animate camera in a copy of blend_path and save to output_blend.

    Returns output_blend path.
    """
    import bpy
    from mathutils import Vector, Quaternion

    bpy.ops.wm.open_mainfile(filepath=blend_path)

    unit_scale = float(bpy.context.scene.unit_settings.scale_length or 1.0)
    # In aerial mode path points are 3D flying positions — the camera IS at the
    # path point. camera_height is a walking metaphor (eye above floor) and must
    # not be added in aerial mode or it pushes the camera above the ceiling.
    if config.get("aerial"):
        cam_h = 0.0
    else:
        cam_h = config.get("camera_height", 1.7) / unit_scale
    fps = config.get("fps", 12)

    # Optional: per-frame ground Z from the cloth heightmap (terrain_snake.npz).
    # The path is built from voxel centres which are quantised to res (e.g. 20 m).
    # If we have the cloth heightmap, look up the actual ground Z at each path
    # point's (x, y) via bilinear interpolation — the camera then walks at exactly
    # cloth_z + camera_height, eliminating voxel-quantisation clipping into hills.
    cloth_z_lookup = None
    raycast_ground_z = None
    _camera_xyz = None   # original scene camera position from terrain_npz [x, y, z] in BU
    terrain_npz = config.get("terrain_npz")
    if terrain_npz and not config.get("aerial"):
        import numpy as _np
        from pathlib import Path as _Path
        if _Path(terrain_npz).exists():
            _td = _np.load(terrain_npz)
            _hm = _np.asarray(_td["heightmap"], dtype=_np.float64)
            _bounds = _td["bounds"]
            _res = float(_td["res"])
            _min_x, _min_y = float(_bounds[0]), float(_bounds[1])
            _nx, _ny = _hm.shape
            _floor_mask = ~_np.isnan(_np.asarray(_td["terrain_z_floor"], dtype=_np.float64))

            def cloth_z_lookup(world_x: float, world_y: float) -> "float | None":
                fx = (world_x - _min_x) / _res - 0.5  # to cell-centre coords
                fy = (world_y - _min_y) / _res - 0.5
                ix = max(0, min(_nx - 2, int(fx)))
                iy = max(0, min(_ny - 2, int(fy)))
                tx = max(0.0, min(1.0, fx - ix))
                ty = max(0.0, min(1.0, fy - iy))
                # Skip lookup if any of the 4 neighbours is NaN-domain (off-island)
                if not (_floor_mask[ix, iy] and _floor_mask[ix+1, iy]
                        and _floor_mask[ix, iy+1] and _floor_mask[ix+1, iy+1]):
                    return None
                z00 = _hm[ix, iy]
                z10 = _hm[ix+1, iy]
                z01 = _hm[ix, iy+1]
                z11 = _hm[ix+1, iy+1]
                return float((1-tx)*(1-ty)*z00 + tx*(1-ty)*z10
                             + (1-tx)*ty*z01 + tx*ty*z11)
            print(f"[CameraAnimate] Using cloth heightmap from {terrain_npz} "
                  f"for per-frame ground Z (eliminates voxel-Z quantisation)")

            if "camera_xyz" in _td.files:
                _camera_xyz = _np.asarray(_td["camera_xyz"], dtype=_np.float64)
                print(f"[CameraAnimate] Original camera position: "
                      f"({float(_camera_xyz[0]):.1f}, {float(_camera_xyz[1]):.1f}, "
                      f"{float(_camera_xyz[2]):.1f}) BU — frame 1 will use this exactly")

    # Ray-cast ground Z: fires a downward ray through the actual terrain mesh at
    # each frame's XY.  Scatter instances are render-time only — ray_cast hits
    # only real mesh geometry — so we get exact terrain Z without tree noise.
    # Fallback to cloth_z_lookup when ray misses (open edges, outside domain).
    # _rc_dg[0] is filled in just before the frame loop once the scene is ready.
    _rc_dg = [None]
    if not config.get("aerial"):
        _rc_max_z = float(path_data.bounds[5]) if (
            hasattr(path_data, "bounds") and path_data.bounds is not None
        ) else 1000.0
        _rc_origin_z = _rc_max_z + 10.0
        _rc_dir = Vector((0.0, 0.0, -1.0))

        def raycast_ground_z(world_x: float, world_y: float) -> "float | None":
            dg = _rc_dg[0]
            if dg is None:
                return None
            origin = Vector((world_x, world_y, _rc_origin_z))
            hit, loc, _n, _i, _o, _m = bpy.context.scene.ray_cast(dg, origin, _rc_dir)
            return float(loc.z) if hit else None

        print("[CameraAnimate] Ray-cast ground Z enabled (exact terrain surface, "
              "heightmap fallback)")

    path_vecs = [Vector(tuple(p)) for p in path_data.path_points]
    if not path_vecs:
        raise RuntimeError("PathData has no path_points — cannot animate camera.")

    # Precompute cumulative arc lengths for uniform-speed sampling
    arc_lengths = [0.0]
    for i in range(len(path_vecs) - 1):
        arc_lengths.append(arc_lengths[-1] + (path_vecs[i+1] - path_vecs[i]).length)
    total_arc = max(1e-10, arc_lengths[-1])

    # Auto-calculate duration
    if not config.get("duration_seconds"):
        path_length = sum(
            (path_vecs[i+1] - path_vecs[i]).length
            for i in range(len(path_vecs) - 1)
        )
        walk_speed = config.get("walk_speed_mps", 1.2)
        path_length_m = path_length * unit_scale  # BU → metres
        raw_dur = max(5.0, path_length_m / walk_speed)
        max_dur = config.get("max_duration_seconds")
        config["duration_seconds"] = min(raw_dur, max_dur) if max_dur else raw_dur

    path_frames = max(1, int(config["duration_seconds"] * fps))
    # camera_origin_hold_frames: extra stationary frames at the start where the
    # camera holds at the original scene camera position before the path begins.
    # Makes the opening shot clearly visible; 0 = no hold (default).
    _origin_hold = int(config.get("camera_origin_hold_frames", 0))
    total_frames = path_frames + _origin_hold

    # Build wp_schedule list of (t, Quaternion) from OrientData
    wp_schedule = []
    for entry in orient.wp_schedule:
        t = float(entry["t"])
        q = entry["quat"]
        wp_schedule.append((t, Quaternion((q[0], q[1], q[2], q[3]))))

    # Arc-length fraction of the second waypoint — used as the blend endpoint
    # for the wp0→normal transition (frame 1 = exact origin, by wp1 = terrain+cam_h).
    _wp0_t1 = wp_schedule[1][0] if len(wp_schedule) >= 2 else 1.0

    wp_gaze_mode = config.get("waypoint_gaze_mode", "free")

    def _get_base_quat(t):
        if not wp_schedule:
            return None
        if t <= wp_schedule[0][0]:
            return wp_schedule[0][1]
        if t >= wp_schedule[-1][0]:
            return wp_schedule[-1][1]
        for k in range(len(wp_schedule) - 1):
            if wp_schedule[k][0] <= t <= wp_schedule[k+1][0]:
                span = wp_schedule[k+1][0] - wp_schedule[k][0]
                frac = (t - wp_schedule[k][0]) / max(1e-6, span)
                return wp_schedule[k][1].slerp(wp_schedule[k+1][1], frac)
        return wp_schedule[-1][1]

    def _sample_path(t_val):
        """Sample path at arc-length fraction t_val ∈ [0, 1] — uniform speed."""
        if not path_vecs:
            return Vector((0, 0, 0))
        target = t_val * total_arc
        lo, hi = 0, len(arc_lengths) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if arc_lengths[mid] <= target:
                lo = mid
            else:
                hi = mid
        seg = arc_lengths[hi] - arc_lengths[lo]
        frac = (target - arc_lengths[lo]) / max(1e-10, seg)
        return path_vecs[lo].lerp(path_vecs[min(hi, len(path_vecs) - 1)], frac)

    def _look_at_quat(frm, to):
        direction = (to - frm).normalized()
        if direction.length < 1e-6:
            direction = Vector((0, 1, 0))
        return direction.to_track_quat("-Z", "Y")

    # Remove existing WalkthroughCamera
    for obj in list(bpy.data.objects):
        if obj.name == "WalkthroughCamera":
            bpy.data.objects.remove(obj, do_unlink=True)

    # If we have the original camera position, find the matching scene camera and
    # copy its exact optical settings so frame 1 renders identically to Camera006.
    _src_lens = config.get("camera_lens", 35.0)
    _src_sensor = config.get("camera_sensor_width", 36.0)
    _src_clip_end = config.get("camera_clip_end", 10000.0) / unit_scale
    if _camera_xyz is not None:
        _tol = 5.0  # BU — position match tolerance
        for _obj in bpy.context.scene.objects:
            if _obj.type != "CAMERA":
                continue
            _p = _obj.matrix_world.translation
            if (abs(_p.x - float(_camera_xyz[0])) < _tol and
                    abs(_p.y - float(_camera_xyz[1])) < _tol and
                    abs(_p.z - float(_camera_xyz[2])) < _tol):
                _src_lens = _obj.data.lens
                _src_sensor = _obj.data.sensor_width
                _src_clip_end = _obj.data.clip_end
                print(f"[CameraAnimate] Matched scene camera '{_obj.name}': "
                      f"lens={_src_lens}mm sensor={_src_sensor}mm "
                      f"clip_end={_src_clip_end:.0f} BU")
                break

    cam_data = bpy.data.cameras.new("WalkthroughCamera")
    cam_data.lens = _src_lens
    cam_data.sensor_width = _src_sensor
    cam_data.clip_start = 0.001 / unit_scale
    cam_data.clip_end = _src_clip_end
    cam_obj = bpy.data.objects.new("WalkthroughCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    cam_obj.rotation_mode = "QUATERNION"
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = total_frames

    prev_quat = None
    rotation_tau = config.get("rotation_smooth_seconds", 3.5)
    slerp_alpha = 1.0 - math.exp(-1.0 / max(1, fps * rotation_tau))

    # Freeze the evaluated depsgraph now — all objects are linked, camera created.
    if raycast_ground_z is not None:
        _rc_dg[0] = bpy.context.evaluated_depsgraph_get()

    _origin_quat = (wp_schedule[0][1] if wp_schedule
                    else Quaternion((1.0, 0.0, 0.0, 0.0)))

    for fi in range(total_frames):
        # --- Hold phase: camera stationary at original scene-camera position ---
        if fi < _origin_hold and _camera_xyz is not None:
            cam_pos = Vector((float(_camera_xyz[0]),
                              float(_camera_xyz[1]),
                              float(_camera_xyz[2])))
            target_quat = _origin_quat
            if prev_quat is not None:
                if prev_quat.dot(target_quat) < 0:
                    target_quat.negate()
                target_quat = prev_quat.slerp(target_quat, slerp_alpha)
            prev_quat = target_quat
            cam_obj.location = cam_pos
            cam_obj.rotation_quaternion = target_quat
            cam_obj.keyframe_insert(data_path="location", frame=fi + 1)
            cam_obj.keyframe_insert(data_path="rotation_quaternion", frame=fi + 1)
            continue

        # --- Path phase: traverse the walkable path ---
        t_path = (fi - _origin_hold) / max(1, path_frames - 1)
        path_pt = _sample_path(t_path)
        # Get exact terrain Z.
        # In terrain mode (terrain_npz present) the TerrainSnake cloth is the
        # canonical ground surface — it ignores vegetation and water-surface
        # mesh objects that ray_cast would hit first.  Use heightmap first so
        # the camera walks along smooth terrain rather than tree canopies.
        # In non-terrain mode (interior / city) ray_cast is the primary source
        # (finds exact floor Z) with heightmap as fallback.
        ground_z = None
        if cloth_z_lookup is not None and terrain_npz:
            ground_z = cloth_z_lookup(path_pt.x, path_pt.y)
        if ground_z is None and raycast_ground_z is not None:
            ground_z = raycast_ground_z(path_pt.x, path_pt.y)
        if ground_z is not None:
            path_pt = Vector((path_pt.x, path_pt.y, ground_z))
        cam_pos = path_pt + Vector((0, 0, cam_h))

        # Smoothly blend from the exact original camera position (first path frame)
        # to the normal terrain+cam_h position (at wp1, t=_wp0_t1).
        if _camera_xyz is not None and _wp0_t1 > 1e-6 and t_path <= _wp0_t1:
            alpha = t_path / _wp0_t1
            cam_pos = Vector((
                float(_camera_xyz[0]) * (1.0 - alpha) + cam_pos.x * alpha,
                float(_camera_xyz[1]) * (1.0 - alpha) + cam_pos.y * alpha,
                float(_camera_xyz[2]) * (1.0 - alpha) + cam_pos.z * alpha,
            ))

        if wp_gaze_mode == "waypoint" and wp_schedule:
            # Slerp between pre-computed waypoint quaternions (future-WP average gaze)
            target_quat = _get_base_quat(t_path)
        else:
            # Look-ahead along travel direction: sample a fixed spatial distance ahead
            lookahead_t = min(1.0, t_path + config.get("lookahead_fraction", 0.05))
            floor_ahead = _sample_path(lookahead_t)
            look_target = cam_pos + (floor_ahead - path_pt)
            target_quat = _look_at_quat(cam_pos, look_target)

        if prev_quat is not None:
            if prev_quat.dot(target_quat) < 0:
                target_quat.negate()
            target_quat = prev_quat.slerp(target_quat, slerp_alpha)
        prev_quat = target_quat

        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = target_quat
        cam_obj.keyframe_insert(data_path="location", frame=fi + 1)
        cam_obj.keyframe_insert(data_path="rotation_quaternion", frame=fi + 1)

    if cam_obj.animation_data and cam_obj.animation_data.action:
        for fc in cam_obj.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"

    Path(output_blend).parent.mkdir(parents=True, exist_ok=True)
    bpy.data.use_autopack = False
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    print(f"[CameraAnimate] Saved -> {output_blend}  ({total_frames} frames)")
    return output_blend


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 5: camera animate")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--path", required=True, help="Path to path.npz")
    parser.add_argument("--orient", required=True, help="Path to wp_schedule.json")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-blend", required=True)
    args = parser.parse_args()
    from genesis_tools.walkthrough_renderer.pipeline.path_plan import load as pd_load
    from genesis_tools.walkthrough_renderer.pipeline.camera_orient import load as orient_load
    with open(args.config) as f:
        config = json.load(f)
    path_data = pd_load(args.path)
    orient = orient_load(args.orient)
    build(args.blend, path_data, orient, config, args.output_blend)


if __name__ == "__main__":
    _cli()
