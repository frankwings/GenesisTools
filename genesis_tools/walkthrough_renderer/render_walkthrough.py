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
2. Build 3D voxel grid  (tri-axial sweep: Z + X + Y marks solid voxels)
3. Find walkable voxels  (floor surface voxel + camera-height clearance above)
4. Plan coverage path   (BFS component → farthest-point sampling →
                          greedy tour → BFS pathfinding between waypoints →
                          constrained Laplacian smoothing → 4× upsample)
5. Find interesting objects (volume scoring, pre-filter by name/size)
6. Setup QUATERNION camera
7. Animate camera          (gaze state machine: FORWARD / GLANCING,
                            per-frame line-of-sight, SLERP, LINEAR interp)
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
        raise RuntimeError("No mesh objects in scene — cannot build voxel grid.")
    return min(xs), min(ys), max(xs), max(ys), min(zs), max(zs)


# ---------------------------------------------------------------------------
# Step 2: 3D voxel grid (tri-axial sweep)
# ---------------------------------------------------------------------------

def _cast_all_hits(scene, depsgraph, origin, direction, max_dist):
    """Yield every surface hit location along a ray (steps past each surface)."""
    origin = Vector(origin)
    direction = Vector(direction).normalized()
    remaining = max_dist
    step_past = 0.05  # 5 cm step past each surface to find the next one
    while remaining > step_past:
        hit, loc, _normal, *_ = scene.ray_cast(depsgraph, origin, direction,
                                                distance=remaining)
        if not hit:
            break
        yield loc
        traveled = (loc - origin).length
        remaining -= traveled + step_past
        origin = loc + direction * step_past


def _build_voxel_grid(config, scene_bounds):
    """Tri-axial sweep voxelisation covering the full scene bounding box.

    Three orthogonal sweeps ensure all surface orientations are captured:
    - Z sweep  (top→down)  : floors, terrain, tabletops, ceilings
    - X sweep  (left→right): walls facing ±X
    - Y sweep  (front→back): walls facing ±Y

    Each sweep fires one ray per grid row and steps past every surface hit,
    so multi-layer structures (mezzanines, furniture stacks) are all captured.

    Complexity: O(nx*ny + ny*nz + nx*nz) rays, each with O(surfaces) hits.
    For a 20×20×10 indoor grid: ~800 rays, ~2 400 ray_cast calls.

    Returns
    -------
    solid : set of (ix, iy, iz)
    nx, ny, nz : grid dimensions
    """
    min_x, min_y, max_x, max_y, min_z, max_z = scene_bounds
    res = config["grid_resolution"]
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    nx = max(1, int(math.ceil((max_x - min_x) / res)))
    ny = max(1, int(math.ceil((max_y - min_y) / res)))
    nz = max(1, int(math.ceil((max_z - min_z) / res)))

    solid = set()

    def mark(loc):
        ix = min(nx - 1, max(0, int((loc.x - min_x) / res)))
        iy = min(ny - 1, max(0, int((loc.y - min_y) / res)))
        iz = min(nz - 1, max(0, int((loc.z - min_z) / res)))
        solid.add((ix, iy, iz))

    span_x = max_x - min_x + 2.0
    span_y = max_y - min_y + 2.0
    span_z = max_z - min_z + 2.0

    # Z sweep: captures horizontal surfaces (floors, terrain, tabletops).
    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iy in range(ny):
            y = min_y + (iy + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (x, y, max_z + 1.0), (0, 0, -1), span_z):
                mark(loc)

    # X sweep: captures walls facing ±X.
    for iy in range(ny):
        y = min_y + (iy + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (min_x - 1.0, y, z), (1, 0, 0), span_x):
                mark(loc)

    # Y sweep: captures walls facing ±Y.
    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (x, min_y - 1.0, z), (0, 1, 0), span_y):
                mark(loc)

    print(f"[Walkthrough] Voxel grid {nx}×{ny}×{nz} "
          f"({nx * ny * nz} total), {len(solid)} solid voxels")
    return solid, nx, ny, nz


# ---------------------------------------------------------------------------
# Step 3: Walkable voxels
# ---------------------------------------------------------------------------

def _find_walkable_voxels(solid, config, scene_bounds, nx, ny, nz):
    """Find voxels where the camera can stand.

    A voxel (ix, iy, iz) is **walkable** (camera feet position) when:
    - (ix, iy, iz-1) is solid  → there is a floor surface below
    - (ix, iy, iz) … (ix, iy, iz + cam_h_voxels - 1) are all NOT solid
      → enough headroom for the full camera height

    The returned iz represents the camera FEET. World-space floor Z =
    ``min_z + iz * res``  (top face of the solid voxel below).
    Camera eye Z = floor Z + camera_height.
    """
    res = config["grid_resolution"]
    cam_h = config["camera_height"]
    min_z = scene_bounds[4]
    cam_h_voxels = max(1, int(math.ceil(cam_h / res)))

    # Floor surface voxels: solid with an empty voxel directly above.
    floor_surfaces = {
        (ix, iy, iz) for (ix, iy, iz) in solid
        if (ix, iy, iz + 1) not in solid
    }

    walkable = set()
    for (ix, iy, iz_floor) in floor_surfaces:
        iz_feet = iz_floor + 1          # first empty voxel = camera feet
        clear = True
        for k in range(cam_h_voxels):
            if (ix, iy, iz_feet + k) in solid or iz_feet + k >= nz:
                clear = False
                break
        if clear:
            walkable.add((ix, iy, iz_feet))

    print(f"[Walkthrough] Walkable voxels: {len(walkable)}")
    return walkable


# ---------------------------------------------------------------------------
# Step 4: Coverage path planning
# ---------------------------------------------------------------------------

def _bfs_largest_component(walkable):
    """Return the largest connected component of walkable voxels.

    Two walkable voxels are neighbours if they differ by ±1 in X or Y
    (4-connected) and by at most ±1 in Z — allowing one-voxel steps up/down
    for terrain slopes and shallow stairs.
    """
    remaining = set(walkable)
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
            cx, cy, cz = cell
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                for dz in (-1, 0, 1):
                    nb = (cx + dx, cy + dy, cz + dz)
                    if nb in remaining and nb not in component:
                        queue.append(nb)
        remaining -= component
        if len(component) > len(best):
            best = component
    return best


def _farthest_point_sample(cells, n, rng_seed):
    """Return n cells using farthest-point sampling (XY distance, 3-tuple aware)."""
    import random
    rng = random.Random(rng_seed)
    cells_list = list(cells)
    if len(cells_list) <= n:
        return cells_list
    first = rng.choice(cells_list)
    selected = [first]
    # Distance of each cell to its nearest selected neighbour.
    dist = {c: (c[0] - first[0]) ** 2 + (c[1] - first[1]) ** 2
            for c in cells_list}
    for _ in range(n - 1):
        farthest = max(cells_list, key=lambda c: dist[c])
        selected.append(farthest)
        for c in cells_list:
            d = (c[0] - farthest[0]) ** 2 + (c[1] - farthest[1]) ** 2
            if d < dist[c]:
                dist[c] = d
    return selected


def _greedy_tsp_tour(waypoints):
    """Nearest-neighbour greedy tour (XY distance); closes the loop."""
    if not waypoints:
        return []
    remaining = list(waypoints)
    tour = [remaining.pop(0)]
    while remaining:
        last = tour[-1]
        nearest = min(remaining,
                      key=lambda c: (c[0] - last[0]) ** 2 + (c[1] - last[1]) ** 2)
        remaining.remove(nearest)
        tour.append(nearest)
    tour.append(tour[0])   # close loop
    return tour


def _bfs_path(start, goal, walkable):
    """BFS shortest path between two walkable voxels.

    Uses 4-connected XY with |Δiz| ≤ 1 — matches component connectivity.
    """
    if start == goal:
        return [start]
    parent = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        if cell == goal:
            path = []
            c = cell
            while c is not None:
                path.append(c)
                c = parent[c]
            path.reverse()
            return path
        cx, cy, cz = cell
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            for dz in (-1, 0, 1):
                nb = (cx + dx, cy + dy, cz + dz)
                if nb in walkable and nb not in parent:
                    parent[nb] = cell
                    queue.append(nb)
    return [start, goal]   # disconnected — fallback


def _build_smooth_path(tour, walkable, config, scene_bounds):
    """BFS corridor + constrained Laplacian smoothing + 4× upsample.

    1. BFS between consecutive waypoints — guaranteed wall-free path.
    2. Laplacian smoothing in XY only; Z is re-resolved from the walkable
       voxel at each XY so the camera follows terrain correctly.
    3. 4× linear upsampling for dense per-frame path sampling.
    """
    min_x = scene_bounds[0]
    min_y = scene_bounds[1]
    min_z = scene_bounds[4]
    res = config["grid_resolution"]

    # ---- 1. BFS corridor ------------------------------------------------
    cell_path = []
    n = len(tour)
    for i in range(n - 1):
        segment = _bfs_path(tour[i], tour[i + 1], walkable)
        if i == 0:
            cell_path.extend(segment)
        else:
            cell_path.extend(segment[1:])   # skip duplicate join point

    if not cell_path:
        return []

    # (ix, iy) → lowest walkable iz at that XY (for smooth terrain following).
    walkable_xy = {}
    for (ix, iy, iz) in walkable:
        if (ix, iy) not in walkable_xy or iz < walkable_xy[(ix, iy)]:
            walkable_xy[(ix, iy)] = iz

    def c2w(cell):
        ix, iy, iz = cell
        return [
            min_x + (ix + 0.5) * res,
            min_y + (iy + 0.5) * res,
            min_z + iz * res,             # floor top = bottom of walkable voxel
        ]

    points = [c2w(c) for c in cell_path]

    # ---- 2. Constrained Laplacian smoothing (5 passes, XY only) ---------
    for _ in range(5):
        new_pts = [points[0]]
        for i in range(1, len(points) - 1):
            sx = (points[i - 1][0] + points[i][0] + points[i + 1][0]) / 3.0
            sy = (points[i - 1][1] + points[i][1] + points[i + 1][1]) / 3.0
            ix = int((sx - min_x) / res)
            iy = int((sy - min_y) / res)
            if (ix, iy) in walkable_xy:
                sz = min_z + walkable_xy[(ix, iy)] * res
                new_pts.append([sx, sy, sz])
            else:
                new_pts.append(points[i])   # smoothed pos out of bounds — keep
        new_pts.append(points[-1])
        points = new_pts

    # ---- 3. 4× linear upsampling ----------------------------------------
    upsampled = []
    steps = 4
    for i in range(len(points) - 1):
        for j in range(steps):
            t = j / steps
            x = points[i][0] + t * (points[i + 1][0] - points[i][0])
            y = points[i][1] + t * (points[i + 1][1] - points[i][1])
            z = points[i][2] + t * (points[i + 1][2] - points[i][2])
            upsampled.append([x, y, z])
    upsampled.append(points[-1])

    return [Vector((p[0], p[1], p[2])) for p in upsampled]


def _sample_path(path_points, t):
    """Sample a point along path_points at normalised t in [0, 1]."""
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
            continue
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
    glance_range = min(config["look_range"], 5.0)
    glance_duration = fps * 3   # hold gaze 3 s

    for obj in list(bpy.data.objects):
        if obj.name == "WalkthroughCamera":
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new("WalkthroughCamera")
    cam_data.lens = 35
    cam_obj = bpy.data.objects.new("WalkthroughCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    cam_obj.rotation_mode = "QUATERNION"

    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = total_frames

    prev_quat = None
    gaze_target = None
    gaze_remaining = 0
    glance_cooldown = {}    # name → frames until eligible again

    # Rotation smoothing: first-order low-pass filter (frame-rate independent).
    # τ = rotation_smooth_seconds → camera reaches 63% of target in τ seconds.
    # α = 1 - exp(-1 / (fps * τ))
    # τ=2s at 12fps → α≈0.04  (slow, cinematic)
    # τ=2s at 24fps → α≈0.02  (same feel at higher frame rate)
    rotation_tau = config.get("rotation_smooth_seconds", 2.0)
    slerp_alpha = 1.0 - math.exp(-1.0 / max(1, fps * rotation_tau))

    for frame_idx in range(total_frames):
        t = frame_idx / max(1, total_frames - 1)
        path_pt = _sample_path(path_points, t)
        cam_pos = path_pt + Vector((0, 0, cam_h))

        # Tick cooldowns.
        for name in list(glance_cooldown):
            glance_cooldown[name] -= 1
            if glance_cooldown[name] <= 0:
                del glance_cooldown[name]

        if gaze_remaining > 0:
            gaze_remaining -= 1
            if gaze_remaining == 0:
                gaze_target = None

        # When looking forward, find a nearby object to glance at.
        if gaze_target is None:
            best_candidate = None
            best_dist = float("inf")
            for obj_info in interesting_objects:
                if obj_info["name"] in glance_cooldown:
                    continue
                dist = (obj_info["center"] - cam_pos).length
                if 0.5 < dist < glance_range and dist < best_dist:
                    if _has_line_of_sight(cam_pos, obj_info["center"], depsgraph):
                        best_candidate = obj_info
                        best_dist = dist
            if best_candidate:
                gaze_target = best_candidate["center"]
                gaze_remaining = glance_duration
                glance_cooldown[best_candidate["name"]] = glance_duration * 4

        if gaze_target is not None:
            look_target = gaze_target
        else:
            look_target = _travel_direction_target(cam_pos, path_points, t, ahead=0.15)

        target_quat = _compute_look_at_quaternion(cam_pos, look_target)
        if prev_quat is not None:
            target_quat = prev_quat.slerp(target_quat, slerp_alpha)
        prev_quat = target_quat

        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = target_quat
        cam_obj.keyframe_insert(data_path="location", frame=frame_idx + 1)
        cam_obj.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx + 1)

    if cam_obj.animation_data and cam_obj.animation_data.action:
        for fcurve in cam_obj.animation_data.action.fcurves:
            for kp in fcurve.keyframe_points:
                kp.interpolation = "LINEAR"

    return cam_obj, total_frames


# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------

def _enable_cycles_gpu(scene):
    """Activate GPU rendering for Cycles.

    WSL2 note: OptiX requires /dev/nvidia* which doesn't exist in WSL2 (GPU
    access goes through /dev/dxg / DirectX passthrough). Setting OptiX in WSL2
    enumerates devices successfully but causes a silent CPU fallback at render
    time. We detect WSL2 and skip OPTIX, using CUDA directly instead.
    """
    import os
    is_wsl2 = os.path.exists("/dev/dxg")

    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences

    if is_wsl2:
        device_order = ("CUDA", "HIP", "METAL")
        print("[Walkthrough] WSL2 detected — skipping OPTIX (silent CPU fallback)")
    else:
        device_order = ("OPTIX", "CUDA", "HIP", "METAL")

    activated = False
    for device_type in device_order:
        try:
            prefs.compute_device_type = device_type
            prefs.get_devices()
            gpu_devices = [d for d in prefs.devices if d.type != "CPU"]
            if gpu_devices:
                for d in prefs.devices:
                    d.use = (d.type != "CPU")   # GPU only — CPU+GPU hybrid is slower
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

        # ---- Step 2: 3D voxel grid ----
        scene_bounds = _scene_bounds()
        solid, nx, ny, nz = _build_voxel_grid(config, scene_bounds)

        # ---- Step 3: Walkable voxels ----
        walkable = _find_walkable_voxels(solid, config, scene_bounds, nx, ny, nz)
        if not walkable:
            raise RuntimeError(
                "No walkable voxels found. Check the scene has upward-facing floor "
                "surfaces and sufficient clearance for camera_height."
            )

        # ---- Step 4: Coverage path ----
        component = _bfs_largest_component(walkable)
        n_wp = min(config["num_waypoints"], len(component))
        waypoints = _farthest_point_sample(component, n_wp, config["seed"])
        tour = _greedy_tsp_tour(waypoints)
        path_points = _build_smooth_path(tour, walkable, config, scene_bounds)

        if not path_points:
            raise RuntimeError("Path planning produced no points.")

        # Auto-calculate duration from path length if not set by user.
        if not config.get("duration_seconds"):
            path_length = sum(
                (path_points[i + 1] - path_points[i]).length
                for i in range(len(path_points) - 1)
            )
            walk_speed = config.get("walk_speed_mps", 1.2)
            config["duration_seconds"] = max(5.0, path_length / walk_speed)
            print(
                f"[Walkthrough] Path length: {path_length:.1f}m "
                f"/ {walk_speed}m/s = {config['duration_seconds']:.1f}s"
            )

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
                scene.render.engine = "CYCLES"
                scene.cycles.samples = 32
                scene.cycles.use_adaptive_sampling = True
                scene.cycles.adaptive_threshold = 0.01
                scene.cycles.adaptive_min_samples = 4
                scene.view_layers[0].cycles.use_denoising = True
                _enable_cycles_gpu(scene)

            scene.render.resolution_x = 1280
            scene.render.resolution_y = 720
            scene.render.filepath = str(frames_dir / "frame_")
            scene.render.image_settings.file_format = "PNG"
            scene.render.use_persistent_data = True
            bpy.ops.render.render(animation=True)

        # ---- Step 9: Report ----
        print("WALKTHROUGH_RESULT:" + json.dumps({
            "status": "success",
            "blend_output": str(output_blend),
            "frames_dir": str(frames_dir) if frames_dir else None,
            "path_points_count": len(path_points),
            "walkable_voxels_count": len(walkable),
            "solid_voxels_count": len(solid),
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
