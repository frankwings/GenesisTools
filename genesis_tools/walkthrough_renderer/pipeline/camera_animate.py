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
    cam_h = config.get("camera_height", 1.7) / unit_scale
    fps = config.get("fps", 12)

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

    total_frames = max(1, int(config["duration_seconds"] * fps))

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

    cam_data = bpy.data.cameras.new("WalkthroughCamera")
    cam_data.lens = 35
    cam_data.clip_start = 0.001 / unit_scale
    cam_data.clip_end = 100.0 / unit_scale
    cam_obj = bpy.data.objects.new("WalkthroughCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    cam_obj.rotation_mode = "QUATERNION"
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = total_frames

    prev_quat = None
    rotation_tau = config.get("rotation_smooth_seconds", 3.5)
    slerp_alpha = 1.0 - math.exp(-1.0 / max(1, fps * rotation_tau))

    for fi in range(total_frames):
        t = fi / max(1, total_frames - 1)
        path_pt = _sample_path(t)
        cam_pos = path_pt + Vector((0, 0, cam_h))

        if wp_gaze_mode == "waypoint" and wp_schedule:
            # Slerp between pre-computed waypoint quaternions (future-WP average gaze)
            target_quat = _get_base_quat(t)
        else:
            # Look-ahead along travel direction: sample a fixed spatial distance ahead
            lookahead_t = min(1.0, t + config.get("lookahead_fraction", 0.05))
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
