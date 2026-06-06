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

    # Fix Infinigen scatter: redirect GeoNode Object Info nodes from coarse
    # inview-proxy terrain meshes (50–760 verts, near original scene camera)
    # to OpaqueTerrain_fine (full terrain, ~355K verts).  Without this patch,
    # "Distribute Points on Faces" scatters vegetation only in a tiny zone
    # around the original camera position — walkthrough cameras that stray
    # away from that zone see zero vegetation.
    _fine = bpy.data.objects.get("OpaqueTerrain_fine")
    if _fine and not config.get("aerial"):
        _PROXY_NAMES = {
            "OpaqueTerrain.inview_inview",
            "OpaqueTerrain.inview_near",
            "OpaqueTerrain.inview_center",
        }
        _n_patched = 0
        for _sobj in bpy.data.objects:
            if not _sobj.name.startswith("scatter:"):
                continue
            for _mod in _sobj.modifiers:
                if _mod.type != "NODES" or not _mod.node_group:
                    continue
                for _node in _mod.node_group.nodes:
                    if _node.type != "OBJECT_INFO":
                        continue
                    _inp = _node.inputs.get("Object")
                    if _inp and _inp.default_value and _inp.default_value.name in _PROXY_NAMES:
                        _old = _inp.default_value.name
                        _inp.default_value = _fine
                        _n_patched += 1
                        print(f"[CameraAnimate] Scatter patch: '{_sobj.name}' "
                              f"'{_old}' → 'OpaqueTerrain_fine'")
        if _n_patched:
            print(f"[CameraAnimate] Scatter terrain patch: {_n_patched} Object Info "
                  f"node(s) redirected to OpaqueTerrain_fine "
                  f"({len(_fine.data.vertices)} verts) — vegetation will render "
                  f"across entire walkthrough path")
        else:
            print("[CameraAnimate] Scatter terrain patch: no inview proxies found "
                  "(scene may not be Infinigen, or patch already applied)")

        # Freeze scene-time in scatter GeoNodes: disconnect INPUT_SCENE_TIME outputs
        # so scatter positions are static (t=0 default) across all frames.
        # Without this, Blender rebuilds the scatter BVH every frame because the
        # time-dependent geometry prevents use_persistent_data from reusing the BVH,
        # making renders ~4-8x slower.
        _time_frozen = 0
        for _sobj in bpy.data.objects:
            if not _sobj.name.startswith("scatter:"):
                continue
            for _mod in _sobj.modifiers:
                if _mod.type != "NODES" or not _mod.node_group:
                    continue
                _ng = _mod.node_group
                for _node in list(_ng.nodes):
                    if _node.type != "INPUT_SCENE_TIME":
                        continue
                    # Remove all links from this node (downstream sockets use defaults)
                    _links_to_remove = [_lnk for _lnk in _ng.links if _lnk.from_node == _node]
                    for _lnk in _links_to_remove:
                        _ng.links.remove(_lnk)
                    _time_frozen += 1
        if _time_frozen:
            print(f"[CameraAnimate] Froze {_time_frozen} INPUT_SCENE_TIME node(s): "
                  f"disconnected outputs → static scatter BVH reusable across frames")

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

    # ── smooth_adaptive: offline bidirectional Gaussian yaw/pitch smoothing ──────
    # Precompute quaternions for all path frames before writing any keyframes.
    # This allows zero-phase (symmetric) filtering — impossible in real-time.
    #
    # Yaw  : path tangent direction → unwrap → Gaussian bidirectional → rewrap
    # Pitch: heightmap lookup 15 m ahead → atan2 → clamp ±deg → Gaussian bidir
    _precomp_quats = None   # list[Quaternion] indexed by path frame index
    if wp_gaze_mode == "smooth_adaptive" and not config.get("aerial"):
        import numpy as _np
        _lah_m       = float(config.get("smooth_pitch_lookahead_m",   15.0))
        _lah_bu      = _lah_m / unit_scale
        _pitch_min   = math.radians(float(config.get("smooth_pitch_min_deg", -15.0)))
        _pitch_max   = math.radians(float(config.get("smooth_pitch_max_deg",   8.0)))
        _yaw_sig     = float(config.get("smooth_yaw_sigma_s",   1.5)) * fps
        _pitch_sig   = float(config.get("smooth_pitch_sigma_s", 0.8)) * fps

        _raw_yaw   = _np.zeros(path_frames)
        _raw_pitch = _np.zeros(path_frames)
        _raw_pos   = []   # Vector: camera world position per frame

        for _fi in range(path_frames):
            _t = _fi / max(1, path_frames - 1)
            _pt = _sample_path(_t)

            # Ground Z (heightmap preferred over ray_cast for terrain)
            _gz = None
            if cloth_z_lookup is not None and terrain_npz:
                _gz = cloth_z_lookup(_pt.x, _pt.y)
            if _gz is None and raycast_ground_z is not None:
                _gz = raycast_ground_z(_pt.x, _pt.y)
            if _gz is not None:
                _pt = Vector((_pt.x, _pt.y, _gz))
            _eye = _pt + Vector((0, 0, cam_h))
            _raw_pos.append(_eye)

            # Yaw: from path tangent (look ahead along arc-length)
            _t_ah = min(1.0, _t + config.get("lookahead_fraction", 0.05))
            _ah   = _sample_path(_t_ah)
            _raw_yaw[_fi] = math.atan2(_ah.y - _pt.y, _ah.x - _pt.x)

            # Pitch: terrain height at _lah_bu ahead in current yaw direction
            _yw   = _raw_yaw[_fi]
            _ax   = _eye.x + math.cos(_yw) * _lah_bu
            _ay   = _eye.y + math.sin(_yw) * _lah_bu
            _atz  = None
            if cloth_z_lookup is not None and terrain_npz:
                _atz = cloth_z_lookup(_ax, _ay)
            if _atz is None:
                _atz = _pt.z               # fallback: assume flat
            _raw_pitch[_fi] = math.atan2((_atz + cam_h) - _eye.z, _lah_bu)

        # Gaussian smoothing: symmetric FIR kernel + edge padding = zero phase
        def _gauss_smooth(arr, sig):
            """1-D Gaussian convolution, nearest-edge padding, zero phase."""
            if sig < 0.5:
                return arr.copy()
            radius = max(1, int(math.ceil(4.0 * sig)))
            x = _np.arange(-radius, radius + 1, dtype=_np.float64)
            k = _np.exp(-0.5 * (x / sig) ** 2)
            k /= k.sum()
            padded = _np.concatenate([[arr[0]] * radius, arr, [arr[-1]] * radius])
            return _np.convolve(padded, k, mode="valid")[:len(arr)]

        _yaw_uw   = _np.unwrap(_raw_yaw)
        _yaw_sm   = _gauss_smooth(_yaw_uw,    _yaw_sig)
        _pitch_sm = _gauss_smooth(_raw_pitch, _pitch_sig)
        print(f"[CameraAnimate] smooth_adaptive: Gaussian smooth "
              f"(yaw σ={_yaw_sig:.1f}fr, pitch σ={_pitch_sig:.1f}fr)")

        # Convert to Blender quaternions
        # Blender camera: -Z is forward, Y is up.
        # We construct look direction from yaw+pitch, then to_track_quat.
        _precomp_quats = []
        for _fi in range(path_frames):
            _yw  = float(_yaw_sm[_fi])
            _pit = float(_pitch_sm[_fi])
            _dz  = math.sin(_pit)
            _dxy = math.cos(_pit)
            _fwd = Vector((_dxy * math.cos(_yw), _dxy * math.sin(_yw), _dz)).normalized()
            _precomp_quats.append(_fwd.to_track_quat("-Z", "Y"))
        print(f"[CameraAnimate] smooth_adaptive: precomputed {path_frames} quaternions")

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

        if wp_gaze_mode == "smooth_adaptive" and _precomp_quats is not None:
            # Bidirectional-smoothed yaw+pitch from precomputed list
            _pf_idx = fi - _origin_hold
            target_quat = _precomp_quats[max(0, min(len(_precomp_quats) - 1, _pf_idx))]
        elif wp_gaze_mode == "waypoint" and wp_schedule:
            # Slerp between pre-computed waypoint quaternions (future-WP average gaze)
            target_quat = _get_base_quat(t_path)
        elif wp_gaze_mode == "eye_level":
            # Option C: look at a point ahead on the path but at current eye height.
            # look_target.z == cam_pos.z → gaze is always horizontal regardless of
            # terrain slope, so camera never pitches toward the ground on descent.
            lookahead_t = min(1.0, t_path + config.get("lookahead_fraction", 0.05))
            floor_ahead = _sample_path(lookahead_t)
            look_target = Vector((floor_ahead.x, floor_ahead.y, cam_pos.z))
            target_quat = _look_at_quat(cam_pos, look_target)
        else:
            # Look-ahead along travel direction: sample a fixed spatial distance ahead.
            # Includes terrain Z delta so camera tilts up/down with slope.
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

    # Disable particle physics (Newton + gravity) — scatter vegetation must be
    # static. With physics enabled, gravity pulls particles downward each frame,
    # making trees visibly sink during the walkthrough.
    for _ps in bpy.data.particles:
        if _ps.physics_type != 'NO':
            _ps.physics_type = 'NO'
            _ps.effector_weights.gravity = 0.0
            print(f"[CameraAnimate] Particle '{_ps.name}': physics disabled (was NEWTON+gravity)")

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
