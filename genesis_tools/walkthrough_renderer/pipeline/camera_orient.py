"""Step 4: waypoint gaze orientations.

Input:  blend_path + PathData
Output: OrientData -> wp_schedule.json

Requires bpy Python for LOS ray_cast.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field


@dataclass
class OrientData:
    wp_schedule: list  # [{"t": float, "quat": [w, x, y, z]}, ...]


# ---------------------------------------------------------------------------
# bpy-dependent helpers
# ---------------------------------------------------------------------------

def _compute_waypoint_orientations(tour, cam_height, scene, depsgraph):
    """For each tour waypoint, find the horizontal direction toward visible waypoints."""
    from mathutils import Vector
    n = len(tour)
    if n < 2:
        return [Vector((1, 0, 0))] * n

    eyes = [Vector(w) + Vector((0, 0, cam_height)) for w in tour]
    vis = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = eyes[j] - eyes[i]
            dist = d.length
            if dist < 0.1:
                vis[i][j] = vis[j][i] = True
                continue
            hit, *_ = scene.ray_cast(depsgraph, eyes[i], d.normalized(),
                                     distance=dist - 0.1)
            if not hit:
                vis[i][j] = vis[j][i] = True

    orientations = []
    for i in range(n):
        visible_eyes = [eyes[j] for j in range(n) if j != i and vis[i][j]]
        if not visible_eyes:
            nxt = (i + 1) % n
            fwd = eyes[nxt] - eyes[i]; fwd.z = 0
            orientations.append(fwd.normalized() if fwd.length > 0.01
                                else Vector((1, 0, 0)))
            continue
        avg = Vector((0.0, 0.0, 0.0))
        for vp in visible_eyes:
            to_vp = vp - eyes[i]; to_vp.z = 0.0
            if to_vp.length > 0.01:
                avg += to_vp.normalized()
        orientations.append(avg.normalized() if avg.length > 0.01
                            else Vector((1, 0, 0)))
    return orientations


def _map_tour_to_path(tour, path_points):
    """Find the path_point index closest to each tour waypoint."""
    from mathutils import Vector
    indices = []
    for wp in tour:
        wp_v = Vector(wp)
        best_idx, best_d2 = 0, float("inf")
        for idx, pp in enumerate(path_points):
            d2 = (pp - wp_v).dot(pp - wp_v)
            if d2 < best_d2:
                best_d2, best_idx = d2, idx
        indices.append(best_idx)
    return indices


def _dir_to_quat(direction):
    """Convert a horizontal look direction to a Blender camera quaternion [w,x,y,z]."""
    from mathutils import Vector
    d = Vector((direction.x, direction.y, 0.0)).normalized()
    if d.length < 0.01:
        d = Vector((1.0, 0.0, 0.0))
    # Camera points along -Z in local space, track toward -Z with Y as up
    target = Vector((d.x, d.y, -0.3)).normalized()
    q = target.to_track_quat("-Z", "Y")
    return [q.w, q.x, q.y, q.z]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(blend_path: str, path_data, config: dict) -> OrientData:
    """Compute waypoint orientations via LOS-based visible-waypoint averaging.

    For each waypoint, casts rays to all other waypoints; averages horizontal
    directions toward the visible ones. camera_animate interpolates between
    these quaternions along the path with slerp smoothing.
    """
    import bpy
    from mathutils import Vector
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    unit_scale = float(bpy.context.scene.unit_settings.scale_length or 1.0)
    cam_h_bu = config.get("camera_height", 1.7) / unit_scale

    if len(path_data.waypoints) < 2:
        return OrientData(wp_schedule=[])

    dg = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    # Build tour world positions from waypoints + bounds
    bounds = path_data.bounds
    res = config.get("grid_resolution", 0.5) / unit_scale
    min_x, min_y, min_z = bounds[0], bounds[1], bounds[4]

    tour_world = [
        Vector((min_x+(wp[0]+0.5)*res, min_y+(wp[1]+0.5)*res, min_z+wp[2]*res))
        for wp in path_data.waypoints
    ]
    wp_oris = _compute_waypoint_orientations(tour_world, cam_h_bu, scene, dg)

    # Build path_points as Vector list
    path_vecs = [Vector(tuple(p)) for p in path_data.path_points]
    wp_path_idx = _map_tour_to_path(tour_world, path_vecs)
    n_pp = max(1, len(path_vecs) - 1)

    schedule_raw = sorted(
        [(wp_path_idx[k] / n_pp, wp_oris[k]) for k in range(len(tour_world))],
        key=lambda x: x[0],
    )

    wp_schedule = [{"t": float(t), "quat": _dir_to_quat(d)}
                   for t, d in schedule_raw]
    return OrientData(wp_schedule=wp_schedule)


def save(data: OrientData, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data.wp_schedule, f, indent=2)
    print(f"[CameraOrient] Saved -> {path}")


def load(path: str) -> OrientData:
    with open(path) as f:
        return OrientData(wp_schedule=json.load(f))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 4: camera orient")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--path", required=True, help="Path to path.npz")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True, help="Path to wp_schedule.json")
    args = parser.parse_args()
    from genesis_tools.walkthrough_renderer.pipeline.path_plan import load as pd_load
    with open(args.config) as f:
        config = json.load(f)
    path_data = pd_load(args.path)
    data = build(args.blend, path_data, config)
    save(data, args.output)


if __name__ == "__main__":
    _cli()
