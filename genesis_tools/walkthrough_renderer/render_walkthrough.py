"""Blender headless script: generate a patrol walkthrough animation.

Called by render_scene_walkthrough() in __init__.py via::

    blender --background scene.blend --python render_walkthrough.py -- \\
        --config /tmp/cfg.json \\
        --output-blend /out/scene_walkthrough.blend \\
        --output-dir /out/

Prints a single ``WALKTHROUGH_RESULT:{...}`` JSON line to stdout on completion.

Algorithm
---------
1. Parse CLI args
2. Build floor height map  (raycast downward, accept normal.z > 0.7 only)
3. Build occupancy grid    (capsule: 3-height horizontal sweeps + overhead)
4. Plan coverage path      (BFS component → farthest-point sampling →
                            greedy tour → Catmull-Rom spline →
                            post-smooth snap to free cells)
5. Find interesting objects (volume/distance² scoring, pre-filter by name/size)
6. Setup QUATERNION camera
7. Animate camera          (per-frame line-of-sight check, SLERP smoothing,
                            LINEAR interp on rotation_quaternion,
                            BEZIER interp on location)
8. Save .blend + optional render
9. Print WALKTHROUGH_RESULT
"""

import json
import math
import sys
from collections import deque
from pathlib import Path

import bpy
from mathutils import Vector

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def _parse_args():
    argv = sys.argv
    after_dash_dash = argv[argv.index("--") + 1:] if "--" in argv else []

    config_path = None
    output_blend = None
    output_dir = None

    render_engine_override = None
    i = 0
    while i < len(after_dash_dash):
        tok = after_dash_dash[i]
        if tok == "--config":
            config_path = after_dash_dash[i + 1]; i += 2
        elif tok == "--output-blend":
            output_blend = Path(after_dash_dash[i + 1]); i += 2
        elif tok == "--output-dir":
            output_dir = Path(after_dash_dash[i + 1]); i += 2
        elif tok == "--render-engine":
            render_engine_override = after_dash_dash[i + 1].upper(); i += 2
        else:
            i += 1

    if not (config_path and output_blend and output_dir):
        raise ValueError("Missing required args: --config, --output-blend, --output-dir")

    with open(config_path, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    # CLI --render-engine overrides config value.
    if render_engine_override:
        config["render_engine"] = render_engine_override

    return config, output_blend, output_dir


# ---------------------------------------------------------------------------
# Scene bounds
# ---------------------------------------------------------------------------

def _scene_bounds():
    """Return (min_x, min_y, max_x, max_y, min_z, max_z) of all mesh objects."""
    xs, ys, zs = [], [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            xs.append(world.x)
            ys.append(world.y)
            zs.append(world.z)
    if not xs:
        raise RuntimeError("No mesh objects in scene — cannot build floor map.")
    return min(xs), min(ys), max(xs), max(ys), min(zs), max(zs)


# ---------------------------------------------------------------------------
# Step 2: Floor height map
# ---------------------------------------------------------------------------

def _build_floor_map(config, scene_bounds):
    """Raycast downward from 60 % scene height; only accept normal.z > 0.7."""
    min_x, min_y, max_x, max_y, min_z, max_z = scene_bounds
    res = config["grid_resolution"]
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # Cast from 60 % of scene height to avoid hitting roofs in enclosed scenes.
    cast_z = min_z + (max_z - min_z) * 0.6

    nx = max(1, int(math.ceil((max_x - min_x) / res)))
    ny = max(1, int(math.ceil((max_y - min_y) / res)))

    floor_map = {}
    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iy in range(ny):
            y = min_y + (iy + 0.5) * res
            origin = Vector((x, y, cast_z))
            hit, loc, normal, *_ = scene.ray_cast(depsgraph, origin, Vector((0, 0, -1)))
            if hit and normal.z > 0.7:
                floor_map[(ix, iy)] = loc.z

    return floor_map, nx, ny


# ---------------------------------------------------------------------------
# Step 3: Occupancy grid
# ---------------------------------------------------------------------------

def _build_occupancy_grid(floor_map, config, scene_bounds):
    """Mark cells blocked by a capsule (3-height horizontal + overhead sweep)."""
    min_x, min_y, *_ = scene_bounds
    res = config["grid_resolution"]
    r = config["obstacle_radius"]
    cam_h = config["camera_height"]

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # 8 horizontal directions.
    h_dirs = [
        Vector((math.cos(math.radians(a)), math.sin(math.radians(a)), 0))
        for a in range(0, 360, 45)
    ]
    # 3-height capsule simulation.
    check_heights = [0.3, cam_h * 0.55, cam_h]

    free_cells = set()

    for (ix, iy), z_floor in floor_map.items():
        x = min_x + (ix + 0.5) * res
        y = min_y + (iy + 0.5) * res
        blocked = False

        for height_offset in check_heights:
            pos = Vector((x, y, z_floor + height_offset))
            for direction in h_dirs:
                hit, *_ = scene.ray_cast(depsgraph, pos, direction, distance=r)
                if hit:
                    blocked = True
                    break
            if blocked:
                break

        # Overhead clearance at full camera height.
        if not blocked:
            cam_pos = Vector((x, y, z_floor + cam_h))
            hit, *_ = scene.ray_cast(depsgraph, cam_pos, Vector((0, 0, 1)), distance=0.3)
            if hit:
                blocked = True

        if not blocked:
            free_cells.add((ix, iy))

    return free_cells


# ---------------------------------------------------------------------------
# Step 4: Coverage path planning
# ---------------------------------------------------------------------------

def _bfs_largest_component(free_cells):
    """Return the largest 4-connected component of free_cells."""
    remaining = set(free_cells)
    best = set()
    while remaining:
        start = next(iter(remaining))
        component = set()
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if cell in component or cell not in remaining:
                continue
            component.add(cell)
            cx, cy = cell
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                nb = (cx+dx, cy+dy)
                if nb in remaining and nb not in component:
                    queue.append(nb)
        remaining -= component
        if len(component) > len(best):
            best = component
    return best


def _farthest_point_sample(cells, n, rng_seed):
    """Return n cells from cells using farthest-point sampling."""
    import random
    rng = random.Random(rng_seed)
    cells_list = list(cells)
    if len(cells_list) <= n:
        return cells_list
    selected = [rng.choice(cells_list)]
    dist = {c: 0.0 for c in cells_list}
    for _ in range(n - 1):
        for c in cells_list:
            d = min((c[0]-s[0])**2 + (c[1]-s[1])**2 for s in selected)
            dist[c] = d
        farthest = max(cells_list, key=lambda c: dist[c])
        selected.append(farthest)
    return selected


def _greedy_tsp_tour(waypoints):
    """Nearest-neighbour greedy tour; closes the loop."""
    if not waypoints:
        return []
    remaining = list(waypoints)
    tour = [remaining.pop(0)]
    while remaining:
        last = tour[-1]
        nearest = min(remaining, key=lambda c: (c[0]-last[0])**2 + (c[1]-last[1])**2)
        remaining.remove(nearest)
        tour.append(nearest)
    tour.append(tour[0])  # Close loop.
    return tour


def _catmull_rom(p0, p1, p2, p3, t):
    """Catmull-Rom spline interpolation (returns (x, y) tuple)."""
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * (
        (2*p1[0]) +
        (-p0[0] + p2[0]) * t +
        (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2 +
        (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3
    )
    y = 0.5 * (
        (2*p1[1]) +
        (-p0[1] + p2[1]) * t +
        (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2 +
        (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3
    )
    return x, y


def _build_smooth_path(tour, floor_map, free_cells, config, scene_bounds):
    """Catmull-Rom spline over tour waypoints + post-smooth snap to free cells."""
    min_x, min_y, *_ = scene_bounds
    res = config["grid_resolution"]
    samples_per_seg = 20
    n = len(tour)
    path_points = []

    for i in range(n - 1):  # tour[-1] == tour[0], so skip last duplicate
        p0 = tour[(i - 1) % (n - 1)]
        p1 = tour[i]
        p2 = tour[(i + 1) % (n - 1)]
        p3 = tour[(i + 2) % (n - 1)]
        for s in range(samples_per_seg):
            t = s / samples_per_seg
            sx, sy = _catmull_rom(p0, p1, p2, p3, t)
            path_points.append([sx, sy])

    # Post-smooth validation: snap points that land outside free cells.
    free_list = list(free_cells)
    snapped = []
    for pt in path_points:
        ix = int((pt[0] - min_x) / res)
        iy = int((pt[1] - min_y) / res)
        if (ix, iy) not in free_cells:
            nearest = min(free_list, key=lambda c: (c[0]-ix)**2 + (c[1]-iy)**2)
            pt[0] = min_x + (nearest[0] + 0.5) * res
            pt[1] = min_y + (nearest[1] + 0.5) * res
            ix, iy = nearest
        # Interpolate floor Z for this cell.
        z = floor_map.get((ix, iy), floor_map.get((max(0,ix), max(0,iy)), 0.0))
        snapped.append(Vector((pt[0], pt[1], z)))

    return snapped


def _sample_path(path_points, t):
    """Sample a point along path_points at normalised t in [0,1]."""
    if not path_points:
        return Vector((0, 0, 0))
    idx = t * (len(path_points) - 1)
    i = int(idx)
    frac = idx - i
    if i >= len(path_points) - 1:
        return path_points[-1]
    return path_points[i].lerp(path_points[i + 1], frac)


def _travel_direction_target(cam_pos, path_points, t, ahead=0.05):
    """Return a point slightly ahead along the path for forward-look fallback."""
    t_ahead = min(1.0, t + ahead)
    return _sample_path(path_points, t_ahead)


# ---------------------------------------------------------------------------
# Step 5: Interesting objects
# ---------------------------------------------------------------------------

EXCLUDE_KEYWORDS = {
    "floor", "ground", "terrain", "sky", "plane", "landscape",
    "ceiling", "wall", "room", "baseboard", "trim",
}

def _find_interesting_objects():
    """Return list of {name, center, clamped_volume} for scoreable objects."""
    result = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        name_lower = obj.name.lower()
        if any(kw in name_lower for kw in EXCLUDE_KEYWORDS):
            continue
        dim = obj.dimensions
        if any(d > 30.0 for d in (dim.x, dim.y, dim.z)):
            continue  # Terrain/building shell
        volume = dim.x * dim.y * dim.z
        if volume < 0.001:
            continue
        clamped = min(volume, 50.0)
        center = obj.matrix_world.translation.copy()
        result.append({"name": obj.name, "center": center, "clamped_volume": clamped})
    return result


# ---------------------------------------------------------------------------
# Step 5b: Line-of-sight
# ---------------------------------------------------------------------------

def _has_line_of_sight(cam_pos, target_center, depsgraph):
    """Return True if no geometry blocks the ray from cam_pos to target_center."""
    scene = bpy.context.scene
    direction = (target_center - cam_pos).normalized()
    distance = (target_center - cam_pos).length
    if distance < 0.1:
        return True
    hit, *_ = scene.ray_cast(depsgraph, cam_pos, direction, distance=distance - 0.1)
    return not hit


# ---------------------------------------------------------------------------
# Step 6 + 7: Camera setup & animation
# ---------------------------------------------------------------------------

def _compute_look_at_quaternion(from_pos, to_pos):
    """Return a quaternion pointing the camera (-Z local) toward to_pos."""
    direction = (to_pos - from_pos).normalized()
    if direction.length < 1e-6:
        direction = Vector((0, 1, 0))
    return direction.to_track_quat("-Z", "Y")


def _setup_and_animate_camera(path_points, interesting_objects, config, depsgraph):
    cam_h = config["camera_height"]
    fps = config["fps"]
    total_frames = max(1, int(config["duration_seconds"] * fps))
    look_range = config["look_range"]
    look_smooth_frames = fps  # blend over ~1 second

    # Remove any existing WalkthroughCamera.
    for obj in list(bpy.data.objects):
        if obj.name == "WalkthroughCamera":
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new("WalkthroughCamera")
    cam_data.lens = 35
    cam_obj = bpy.data.objects.new("WalkthroughCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    cam_obj.rotation_mode = "QUATERNION"  # CRITICAL — avoids gimbal lock

    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = total_frames

    keyframe_stride = max(1, fps // 6)  # ~4 keyframes/second
    prev_quat = None

    for frame_idx in range(0, total_frames, keyframe_stride):
        t = frame_idx / max(1, total_frames - 1)
        path_pt = _sample_path(path_points, t)
        cam_pos = path_pt + Vector((0, 0, cam_h))

        # Find best VISIBLE object to look at.
        best_target = None
        best_score = 0.0
        for obj_info in interesting_objects:
            dist = (obj_info["center"] - cam_pos).length
            if 0.5 < dist < look_range:
                if _has_line_of_sight(cam_pos, obj_info["center"], depsgraph):
                    score = obj_info["clamped_volume"] / (dist ** 2)
                    if score > best_score:
                        best_score = score
                        best_target = obj_info["center"]

        look_target = best_target if best_target else _travel_direction_target(
            cam_pos, path_points, t
        )

        target_quat = _compute_look_at_quaternion(cam_pos, look_target)

        # SLERP toward new quaternion for smooth transitions.
        if prev_quat is not None:
            blend = min(1.0, keyframe_stride / look_smooth_frames)
            target_quat = prev_quat.slerp(target_quat, blend)
        prev_quat = target_quat

        frame_number = frame_idx + 1
        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = target_quat
        cam_obj.keyframe_insert(data_path="location", frame=frame_number)
        cam_obj.keyframe_insert(data_path="rotation_quaternion", frame=frame_number)

    # Set interpolation: LINEAR for rotation (quaternion hypersphere geodesic),
    # BEZIER for location (smooth positional gliding).
    if cam_obj.animation_data and cam_obj.animation_data.action:
        for fcurve in cam_obj.animation_data.action.fcurves:
            interp = "LINEAR" if fcurve.data_path == "rotation_quaternion" else "BEZIER"
            for kp in fcurve.keyframe_points:
                kp.interpolation = interp

    return cam_obj, total_frames


# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------

def _enable_cycles_gpu(scene):
    """Activate GPU rendering for Cycles (OptiX → CUDA → HIP → CPU fallback).

    Must be called after scene.render.engine = "CYCLES" is set.
    Calls save_userpref() so headless Blender retains the device selection.
    """
    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences

    activated = False
    for device_type in ("OPTIX", "CUDA", "HIP", "METAL"):
        try:
            prefs.compute_device_type = device_type
            prefs.get_devices()
            gpu_devices = [d for d in prefs.devices if d.type != "CPU"]
            if gpu_devices:
                for d in prefs.devices:
                    d.use = True  # enable CPU too so GPU+CPU render together
                # Persist preferences so headless Blender commits the change.
                bpy.ops.wm.save_userpref()
                print(
                    f"[Walkthrough] GPU ({device_type}): "
                    + ", ".join(d.name for d in prefs.devices if d.use)
                )
                activated = True
                break
        except Exception as exc:
            print(f"[Walkthrough] {device_type} unavailable: {exc}")

    if not activated:
        scene.cycles.device = "CPU"
        print("[Walkthrough] No GPU found, falling back to CPU.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        config, output_blend, output_dir = _parse_args()
    except Exception as exc:
        print("WALKTHROUGH_RESULT:" + json.dumps({"status": "error", "message": str(exc)}))
        return

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # ---- Step 2: Floor map ----
        scene_bounds = _scene_bounds()
        floor_map, nx, ny = _build_floor_map(config, scene_bounds)
        if not floor_map:
            raise RuntimeError(
                "No floor cells detected. Check scene has mesh geometry with upward-facing surfaces."
            )

        # ---- Step 3: Occupancy grid ----
        free_cells = _build_occupancy_grid(floor_map, config, scene_bounds)
        if not free_cells:
            raise RuntimeError(
                "No free (traversable) cells found. Try reducing obstacle_radius or camera_height."
            )

        # ---- Step 4: Coverage path ----
        component = _bfs_largest_component(free_cells)
        n_wp = min(config["num_waypoints"], len(component))
        waypoints = _farthest_point_sample(component, n_wp, config["seed"])
        tour = _greedy_tsp_tour(waypoints)
        path_points = _build_smooth_path(tour, floor_map, free_cells, config, scene_bounds)

        if not path_points:
            raise RuntimeError("Path planning produced no points.")

        # ---- Step 5: Interesting objects ----
        interesting_objects = _find_interesting_objects()

        # ---- Steps 6 & 7: Camera animation ----
        depsgraph = bpy.context.evaluated_depsgraph_get()
        cam_obj, total_frames = _setup_and_animate_camera(
            path_points, interesting_objects, config, depsgraph
        )

        # ---- Step 8: Save ----
        output_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

        frames_dir = None
        if config.get("render"):
            frames_dir = output_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            scene = bpy.context.scene
            engine = config.get("render_engine", "CYCLES").upper()

            if engine == "WORKBENCH":
                scene.render.engine = "BLENDER_WORKBENCH"
            elif engine == "EEVEE":
                scene.render.engine = "BLENDER_EEVEE_NEXT"
            else:
                # CYCLES with GPU acceleration (OptiX → CUDA → HIP → CPU fallback).
                scene.render.engine = "CYCLES"
                scene.cycles.samples = 32  # low sample count for walkthrough preview
                _enable_cycles_gpu(scene)

            scene.render.resolution_x = 1280
            scene.render.resolution_y = 720
            scene.render.filepath = str(frames_dir / "frame_")
            scene.render.image_settings.file_format = "PNG"
            bpy.ops.render.render(animation=True)

        # ---- Step 9: Report ----
        print("WALKTHROUGH_RESULT:" + json.dumps({
            "status": "success",
            "blend_output": str(output_blend),
            "frames_dir": str(frames_dir) if frames_dir else None,
            "path_points_count": len(path_points),
            "free_cells_count": len(free_cells),
            "interesting_objects_count": len(interesting_objects),
        }))

    except Exception as exc:
        import traceback
        print("WALKTHROUGH_RESULT:" + json.dumps({
            "status": "error",
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }))


main()
