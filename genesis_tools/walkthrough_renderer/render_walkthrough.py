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
2. Build voxel grid — two modes:
   a. LOCAL  (local_radius_xy set): build BVHTree only from nearby objects,
      voxelise a fixed-size region around the camera, flood-fill reachable cells.
   b. GLOBAL (legacy): tri-axial sweep over the full scene using scene.ray_cast.
3. Find walkable voxels  (floor surface + camera-height clearance above)
4. Plan coverage path   (BFS component / flood-fill → farthest-point sampling →
                          greedy tour → BFS pathfinding between waypoints →
                          constrained Laplacian smoothing → 4× upsample)
5. Find interesting objects (volume scoring, pre-filter by name/size)
6. Setup QUATERNION camera
7. Animate camera          (gaze state machine: FORWARD / GLANCING,
                            per-frame line-of-sight, SLERP, LINEAR interp)
8. Save .blend + optional render
9. Print WALKTHROUGH_RESULT (includes per-phase timing)
"""

import json
import math
import sys
import time
from collections import deque
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


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
# Scene bounds (used by global mode)
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
# Unit scale helper
# ---------------------------------------------------------------------------

def _get_unit_scale():
    """Return scene unit scale: metres per Blender unit.

    Blender stores coordinates in 'Blender units'. The scene unit_settings
    tell us what 1 Blender unit equals in metres.
      - Standard metric scene:  scale_length = 1.0  (1 BU = 1 m)
      - Centimetre scene:       scale_length = 0.01 (1 BU = 1 cm)
    All config distances (grid_resolution, local_radius_xy, etc.) are in
    real metres; divide by scale to convert to Blender units for ray_cast.
    """
    scale = bpy.context.scene.unit_settings.scale_length
    if scale <= 0:
        scale = 1.0
    return scale


# ---------------------------------------------------------------------------
# LOCAL MODE helpers
# ---------------------------------------------------------------------------

def _find_local_center(config):
    """Find a good XYZ centre for the local voxel region.

    Priority:
      1. Scene's active camera position.
      2. First camera object found in the scene.
      3. XY centre of all mesh objects at 60% height (fallback).
    """
    cam = bpy.context.scene.camera
    if cam is not None:
        return cam.location.copy()
    for obj in bpy.context.scene.objects:
        if obj.type == "CAMERA":
            return obj.location.copy()
    # Geometric fallback
    xs, ys, zs = [], [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    if xs:
        return Vector((
            (min(xs) + max(xs)) / 2,
            (min(ys) + max(ys)) / 2,
            min(zs) + (max(zs) - min(zs)) * 0.6,
        ))
    return Vector((0.0, 0.0, 1.7))


def _filter_nearby_objects(center, radius_xy_bu, height_above_bu, height_below_bu):
    """Return mesh objects whose world AABB overlaps the local region.

    All distance arguments are in Blender units (caller is responsible for
    converting from real-world distances).

    The local region is a box:
      X: [cx - radius_xy, cx + radius_xy]
      Y: [cy - radius_xy, cy + radius_xy]
      Z: [cz - height_below, cz + height_above]
    """
    radius_xy   = radius_xy_bu
    height_above = height_above_bu
    height_below = height_below_bu
    cx, cy, cz = center.x, center.y, center.z
    nearby = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        ox_min = min(c.x for c in corners)
        ox_max = max(c.x for c in corners)
        oy_min = min(c.y for c in corners)
        oy_max = max(c.y for c in corners)
        oz_min = min(c.z for c in corners)
        oz_max = max(c.z for c in corners)
        if (ox_max < cx - radius_xy or ox_min > cx + radius_xy or
                oy_max < cy - radius_xy or oy_min > cy + radius_xy or
                oz_max < cz - height_below or oz_min > cz + height_above):
            continue
        nearby.append(obj)
    return nearby


def _build_bvh_from_objects(objects, depsgraph):
    """Build a combined BVHTree from the evaluated meshes of given objects.

    Each object is evaluated via depsgraph (applies modifiers/geometry nodes),
    transformed to world space, and merged into a single BVHTree.
    """
    verts_all = []
    polys_all = []
    vert_offset = 0

    for obj in objects:
        try:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            if mesh is None or len(mesh.polygons) == 0:
                eval_obj.to_mesh_clear()
                continue
            mat = obj.matrix_world
            for v in mesh.vertices:
                verts_all.append(mat @ v.co)
            for poly in mesh.polygons:
                polys_all.append(tuple(vert_offset + i for i in poly.vertices))
            vert_offset += len(mesh.vertices)
            eval_obj.to_mesh_clear()
        except Exception as exc:
            print(f"[Walkthrough] Skipping {obj.name}: {exc}")

    if not verts_all:
        raise RuntimeError("No mesh data available for local BVHTree — no nearby objects?")

    return BVHTree.FromPolygons(verts_all, polys_all, all_triangles=False)


def _cast_all_hits_bvh(bvh, origin, direction, max_dist):
    """Yield every surface hit along a ray using a local BVHTree."""
    origin = Vector(origin)
    direction = Vector(direction).normalized()
    remaining = max_dist
    step_past = 0.05
    while remaining > step_past:
        loc, _normal, _index, _dist = bvh.ray_cast(origin, direction, remaining)
        if loc is None:
            break
        yield loc
        traveled = (loc - origin).length
        remaining -= traveled + step_past
        origin = loc + direction * step_past


def _build_local_voxel_grid(config, center, bvh):
    """Tri-axial voxelisation of a fixed local region using a local BVHTree.

    Unlike the global mode, the grid is anchored at `center` with a fixed
    physical size (local_radius_xy × local_radius_xy × local_height metres),
    so computation cost is O(1) regardless of scene size.

    All config distances are in real metres; they are converted to Blender
    units via _get_unit_scale() before use in ray_cast or coordinate maths.

    The floor level is auto-detected by casting a ray down from `center`.

    Returns
    -------
    solid      : set of (ix, iy, iz) voxel indices
    nx, ny, nz : grid dimensions
    res        : voxel size in Blender units
    local_bounds : (min_x, min_y, max_x, max_y, min_z, max_z) in Blender units
    """
    unit_scale = _get_unit_scale()   # metres per Blender unit (still needed for res, height)
    radius_xy = config["_local_radius_bu"]           # pre-computed ratio × scene size (BU)
    height    = config.get("local_height", 8.0)     / unit_scale
    res       = config["grid_resolution"]            / unit_scale

    min_x = center.x - radius_xy
    max_x = center.x + radius_xy
    min_y = center.y - radius_xy
    max_y = center.y + radius_xy

    # Auto-detect floor level from camera center.
    floor_loc, _, _, _ = bvh.ray_cast(
        Vector((center.x, center.y, center.z + height)),
        Vector((0.0, 0.0, -1.0)),
        height * 3.0,
    )
    if floor_loc is not None:
        min_z = floor_loc.z - 0.5
        max_z = floor_loc.z + height
    else:
        min_z = center.z - 1.0
        max_z = center.z + height

    local_bounds = (min_x, min_y, max_x, max_y, min_z, max_z)
    config["_effective_grid_resolution"] = res
    config["_local_bounds"] = local_bounds

    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z

    nx = max(1, int(math.ceil(span_x / res)))
    ny = max(1, int(math.ceil(span_y / res)))
    nz = max(1, int(math.ceil(span_z / res)))

    print(f"[Walkthrough] LOCAL grid {nx}×{ny}×{nz}  res={res}m  "
          f"centre=({center.x:.1f},{center.y:.1f},{center.z:.1f})  "
          f"z=[{min_z:.1f},{max_z:.1f}]")

    solid = set()

    def mark(loc_v):
        ix = min(nx - 1, max(0, int((loc_v.x - min_x) / res)))
        iy = min(ny - 1, max(0, int((loc_v.y - min_y) / res)))
        iz = min(nz - 1, max(0, int((loc_v.z - min_z) / res)))
        solid.add((ix, iy, iz))

    ray_span_z = span_z + 2.0
    ray_span_x = span_x + 2.0
    ray_span_y = span_y + 2.0

    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iy in range(ny):
            y = min_y + (iy + 0.5) * res
            for loc_v in _cast_all_hits_bvh(bvh, (x, y, max_z + 1.0), (0, 0, -1), ray_span_z):
                mark(loc_v)

    for iy in range(ny):
        y = min_y + (iy + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc_v in _cast_all_hits_bvh(bvh, (min_x - 1.0, y, z), (1, 0, 0), ray_span_x):
                mark(loc_v)

    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc_v in _cast_all_hits_bvh(bvh, (x, min_y - 1.0, z), (0, 1, 0), ray_span_y):
                mark(loc_v)

    print(f"[Walkthrough] Local voxel grid {nx}×{ny}×{nz} "
          f"({nx * ny * nz} total), {len(solid)} solid voxels")
    return solid, nx, ny, nz, res, local_bounds


def _flood_fill_walkable(solid, config, local_bounds, nx, ny, nz, center, bvh):
    """Find walkable voxels and flood-fill reachable cells from camera seed.

    Step 1 — Find walkable voxels: same as global mode (solid voxel with
    empty space above for camera_height clearance).

    Step 2 — Find seed via downward ray cast from camera.
    The camera voxel may be solid simply because the voxel is large enough to
    straddle both the camera position and the floor surface beneath it — the
    camera is not literally inside geometry. Casting a ray straight down from
    the camera finds the exact floor hit point, and the walkable voxel
    immediately above that hit is the correct standing position directly under
    the camera. Falls back to nearest walkable by 3D voxel distance if the ray
    misses (camera above an open void, etc.).

    Step 3 — Flood fill BFS outward from seed.

    Returns (reachable, seed) where seed is the voxel index to start the path.
    """
    min_x, min_y, _mx, _my, min_z, _mz = local_bounds
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h = config["camera_height"] / unit_scale   # convert metres → BU
    cam_h_voxels = max(1, int(math.ceil(cam_h / res)))

    # --- Step 1: walkable voxels ---
    floor_surfaces = {(ix, iy, iz) for (ix, iy, iz) in solid
                      if (ix, iy, iz + 1) not in solid}
    walkable = set()
    for (ix, iy, iz_floor) in floor_surfaces:
        iz_feet = iz_floor + 1
        if all((ix, iy, iz_feet + k) not in solid and iz_feet + k < nz
               for k in range(cam_h_voxels)):
            walkable.add((ix, iy, iz_feet))

    print(f"[Walkthrough] Walkable voxels: {len(walkable)}")
    if not walkable:
        return walkable, None

    # --- Step 2: find seed via downward ray from camera ---
    # Cast straight down from camera; the first floor hit gives the precise
    # floor position regardless of voxel size.
    seed = None
    floor_hit, _, _, _ = bvh.ray_cast(
        Vector((center.x, center.y, center.z)),
        Vector((0.0, 0.0, -1.0)),
        cam_h * 10.0,       # search up to 10× camera height below
    )
    if floor_hit is not None:
        fx = int((floor_hit.x - min_x) / res)
        fy = int((floor_hit.y - min_y) / res)
        fz = int((floor_hit.z - min_z) / res) + 1   # +1: stand on top of floor voxel
        candidate = (max(0, fx), max(0, fy), max(0, fz))
        if candidate in walkable:
            seed = candidate
            print(f"[Walkthrough] Seed from downward ray: floor z={floor_hit.z:.1f}  "
                  f"seed={seed}")
        else:
            print(f"[Walkthrough] Ray hit floor at z={floor_hit.z:.1f} but "
                  f"candidate {candidate} not walkable — falling back to 3D distance")

    if seed is None:
        # Fallback: nearest walkable by 3D voxel-index distance.
        seed_ix = int((center.x - min_x) / res)
        seed_iy = int((center.y - min_y) / res)
        seed_iz = int((center.z - min_z) / res)
        seed = min(walkable, key=lambda c: (c[0] - seed_ix) ** 2
                                         + (c[1] - seed_iy) ** 2
                                         + (c[2] - seed_iz) ** 2)
        print(f"[Walkthrough] Seed from 3D distance fallback: seed={seed}")

    # --- Step 3: flood fill from seed ---
    reachable = set()
    queue = deque([seed])
    while queue:
        cell = queue.popleft()
        if cell in reachable:
            continue
        reachable.add(cell)
        cx, cy, cz = cell
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            for dz in (-1, 0, 1):
                nb = (cx + dx, cy + dy, cz + dz)
                if nb in walkable and nb not in reachable:
                    queue.append(nb)

    print(f"[Walkthrough] Reachable from seed: {len(reachable)} / {len(walkable)} walkable voxels")
    return reachable, seed


# ---------------------------------------------------------------------------
# GLOBAL MODE helpers  (legacy — used when local_radius_xy is not set)
# ---------------------------------------------------------------------------

def _cast_all_hits(scene, depsgraph, origin, direction, max_dist):
    """Yield every surface hit along a ray via scene.ray_cast (global BVH)."""
    origin = Vector(origin)
    direction = Vector(direction).normalized()
    remaining = max_dist
    step_past = 0.05
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
    """Tri-axial sweep voxelisation over the full scene (global BVH mode).

    Grid dimensions are capped at max_grid_cells_xy / max_grid_cells_z so that
    ray count stays fixed regardless of scene size. Voxel size is scaled up
    when the scene is larger than grid_resolution * max_grid_cells.

    Complexity: O(nx*ny + ny*nz + nx*nz) rays, each with O(surfaces) hits.
    """
    min_x, min_y, max_x, max_y, min_z, max_z = scene_bounds
    max_xy     = config.get("max_grid_cells_xy", 80)
    max_z_cells = config.get("max_grid_cells_z", 40)
    min_res    = config["grid_resolution"]

    span_x = max_x - min_x
    span_y = max_y - min_y
    span_z = max_z - min_z
    res_xy = max(min_res, span_x / max_xy, span_y / max_xy)
    res_z  = max(min_res, span_z / max_z_cells)
    res    = max(res_xy, res_z)

    scene     = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    nx = max(1, int(math.ceil(span_x / res)))
    ny = max(1, int(math.ceil(span_y / res)))
    nz = max(1, int(math.ceil(span_z / res)))

    config["_effective_grid_resolution"] = res
    print(f"[Walkthrough] GLOBAL grid {nx}×{ny}×{nz}  "
          f"config_res={min_res}m → effective_res={res:.2f}m  "
          f"(caps: xy≤{max_xy}, z≤{max_z_cells})")

    solid = set()

    def mark(loc):
        ix = min(nx - 1, max(0, int((loc.x - min_x) / res)))
        iy = min(ny - 1, max(0, int((loc.y - min_y) / res)))
        iz = min(nz - 1, max(0, int((loc.z - min_z) / res)))
        solid.add((ix, iy, iz))

    ray_span_x = span_x + 2.0
    ray_span_y = span_y + 2.0
    ray_span_z = span_z + 2.0

    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iy in range(ny):
            y = min_y + (iy + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (x, y, max_z + 1.0), (0, 0, -1), ray_span_z):
                mark(loc)

    for iy in range(ny):
        y = min_y + (iy + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (min_x - 1.0, y, z), (1, 0, 0), ray_span_x):
                mark(loc)

    for ix in range(nx):
        x = min_x + (ix + 0.5) * res
        for iz in range(nz):
            z = min_z + (iz + 0.5) * res
            for loc in _cast_all_hits(scene, depsgraph,
                                      (x, min_y - 1.0, z), (0, 1, 0), ray_span_y):
                mark(loc)

    print(f"[Walkthrough] Voxel grid {nx}×{ny}×{nz} "
          f"({nx * ny * nz} total), {len(solid)} solid voxels")
    return solid, nx, ny, nz, res


# ---------------------------------------------------------------------------
# Step 3: Walkable voxels (global mode)
# ---------------------------------------------------------------------------

def _find_walkable_voxels(solid, config, scene_bounds, nx, ny, nz):
    """Find voxels where the camera can stand (global mode).

    A voxel (ix, iy, iz) is walkable when:
    - (ix, iy, iz-1) is solid  → floor surface below
    - (ix, iy, iz) … (ix, iy, iz + cam_h_voxels - 1) are NOT solid → headroom
    """
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h = config["camera_height"] / unit_scale   # convert metres → BU
    cam_h_voxels = max(1, int(math.ceil(cam_h / res)))

    floor_surfaces = {
        (ix, iy, iz) for (ix, iy, iz) in solid
        if (ix, iy, iz + 1) not in solid
    }

    walkable = set()
    for (ix, iy, iz_floor) in floor_surfaces:
        iz_feet = iz_floor + 1
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
    """Return the largest 4-connected XY component (±1 Z) of walkable voxels."""
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


def _farthest_point_sample(cells, n, rng_seed, fixed_first=None):
    """Return n cells using farthest-point sampling (XY distance).

    If fixed_first is provided it is used as the first waypoint instead of a
    random choice. This ensures the path always starts at the camera seed.
    """
    import random
    rng = random.Random(rng_seed)
    cells_list = list(cells)
    if len(cells_list) <= n:
        # Return fixed_first as first element if given, rest in original order.
        if fixed_first is not None and fixed_first in cells:
            rest = [c for c in cells_list if c != fixed_first]
            return [fixed_first] + rest
        return cells_list
    first = fixed_first if (fixed_first is not None and fixed_first in cells) \
            else rng.choice(cells_list)
    selected = [first]
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
    tour.append(tour[0])
    return tour


def _bfs_path(start, goal, walkable):
    """BFS shortest path between two walkable voxels (4-connected XY, ±1 Z)."""
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
    return [start, goal]


def _build_smooth_path(tour, walkable, config, bounds):
    """BFS corridor + constrained Laplacian smoothing + 4× upsample.

    1. BFS between consecutive waypoints — guaranteed wall-free path.
    2. Laplacian smoothing in XY only; Z is re-resolved from the walkable
       voxel at each XY so the camera follows terrain correctly.
    3. 4× linear upsampling for dense per-frame path sampling.

    `bounds` must be (min_x, min_y, max_x, max_y, min_z, max_z).
    """
    min_x = bounds[0]
    min_y = bounds[1]
    min_z = bounds[4]
    res = config.get("_effective_grid_resolution", config["grid_resolution"])

    cell_path = []
    n = len(tour)
    for i in range(n - 1):
        segment = _bfs_path(tour[i], tour[i + 1], walkable)
        if i == 0:
            cell_path.extend(segment)
        else:
            cell_path.extend(segment[1:])

    if not cell_path:
        return []

    walkable_xy = {}
    for (ix, iy, iz) in walkable:
        if (ix, iy) not in walkable_xy or iz < walkable_xy[(ix, iy)]:
            walkable_xy[(ix, iy)] = iz

    def c2w(cell):
        ix, iy, iz = cell
        return [
            min_x + (ix + 0.5) * res,
            min_y + (iy + 0.5) * res,
            min_z + iz * res,
        ]

    points = [c2w(c) for c in cell_path]

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
                new_pts.append(points[i])
        new_pts.append(points[-1])
        points = new_pts

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
    """Sample a point along path_points at normalised t ∈ [0, 1]."""
    if not path_points:
        return Vector((0, 0, 0))
    idx = t * (len(path_points) - 1)
    i = int(idx)
    frac = idx - i
    if i >= len(path_points) - 1:
        return path_points[-1]
    return path_points[i].lerp(path_points[i + 1], frac)


def _travel_direction_target(cam_pos, path_points, t, ahead=0.05):
    """Return a point slightly ahead along the path (forward-look fallback)."""
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
# Step 5b: Line-of-sight  (accepts BVHTree for local mode, depsgraph for global)
# ---------------------------------------------------------------------------

def _has_line_of_sight(cam_pos, target_center, depsgraph_or_bvh):
    """Return True if no geometry blocks cam_pos → target_center."""
    direction = (target_center - cam_pos).normalized()
    distance = (target_center - cam_pos).length
    if distance < 0.1:
        return True
    if isinstance(depsgraph_or_bvh, BVHTree):
        loc, _, _, _ = depsgraph_or_bvh.ray_cast(cam_pos, direction, distance - 0.1)
        return loc is None
    else:
        hit, *_ = bpy.context.scene.ray_cast(
            depsgraph_or_bvh, cam_pos, direction, distance=distance - 0.1
        )
        return not hit


# ---------------------------------------------------------------------------
# Steps 6 + 7: Camera setup & animation
# ---------------------------------------------------------------------------

def _compute_look_at_quaternion(from_pos, to_pos):
    """Quaternion pointing the camera (-Z local) toward to_pos."""
    direction = (to_pos - from_pos).normalized()
    if direction.length < 1e-6:
        direction = Vector((0, 1, 0))
    return direction.to_track_quat("-Z", "Y")


def _setup_and_animate_camera(path_points, interesting_objects, config,
                               depsgraph_or_bvh):
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h         = config["camera_height"] / unit_scale   # metres → BU
    fps           = config["fps"]
    total_frames  = max(1, int(config["duration_seconds"] * fps))
    glance_range  = min(config["look_range"], 5.0)
    glance_duration = fps * 3

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

    prev_quat       = None
    gaze_target     = None
    gaze_remaining  = 0
    glance_cooldown = {}

    rotation_tau  = config.get("rotation_smooth_seconds", 2.0)
    slerp_alpha   = 1.0 - math.exp(-1.0 / max(1, fps * rotation_tau))

    for frame_idx in range(total_frames):
        t        = frame_idx / max(1, total_frames - 1)
        path_pt  = _sample_path(path_points, t)
        cam_pos  = path_pt + Vector((0, 0, cam_h))

        for name in list(glance_cooldown):
            glance_cooldown[name] -= 1
            if glance_cooldown[name] <= 0:
                del glance_cooldown[name]

        if gaze_remaining > 0:
            gaze_remaining -= 1
            if gaze_remaining == 0:
                gaze_target = None

        if gaze_target is None:
            best_candidate = None
            best_dist      = float("inf")
            for obj_info in interesting_objects:
                if obj_info["name"] in glance_cooldown:
                    continue
                dist = (obj_info["center"] - cam_pos).length
                if 0.5 < dist < glance_range and dist < best_dist:
                    if _has_line_of_sight(cam_pos, obj_info["center"],
                                          depsgraph_or_bvh):
                        best_candidate = obj_info
                        best_dist      = dist
            if best_candidate:
                gaze_target    = best_candidate["center"]
                gaze_remaining = glance_duration
                glance_cooldown[best_candidate["name"]] = glance_duration * 4

        if gaze_target is not None:
            look_target = gaze_target
        else:
            # Lift the forward look-target to eye height so the camera looks
            # horizontally ahead rather than down at the floor path point.
            floor_ahead = _travel_direction_target(cam_pos, path_points, t,
                                                   ahead=0.15)
            look_target = floor_ahead + Vector((0.0, 0.0, cam_h))

        target_quat = _compute_look_at_quaternion(cam_pos, look_target)
        if prev_quat is not None:
            target_quat = prev_quat.slerp(target_quat, slerp_alpha)
        prev_quat = target_quat

        cam_obj.location             = cam_pos
        cam_obj.rotation_quaternion  = target_quat
        cam_obj.keyframe_insert(data_path="location",            frame=frame_idx + 1)
        cam_obj.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx + 1)

    if cam_obj.animation_data and cam_obj.animation_data.action:
        for fcurve in cam_obj.animation_data.action.fcurves:
            for kp in fcurve.keyframe_points:
                kp.interpolation = "LINEAR"

    return cam_obj, total_frames


# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------

def _ensure_lights(scene):
    """Add a sun + ambient fill if the scene has no lights.

    EEVEE requires explicit lights; Cycles can work from world HDRI alone.
    Only adds lights when none exist so we never clobber an existing lighting
    rig.
    """
    lights = [o for o in scene.objects if o.type == "LIGHT"]
    if lights:
        return
    print("[Walkthrough] No lights found — adding sun + fill for EEVEE.")
    # Sun (key light)
    sun_data = bpy.data.lights.new("WalkthroughSun", type="SUN")
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new("WalkthroughSun", sun_data)
    sun_obj.rotation_euler = (0.785, 0.0, 0.785)   # 45° down, 45° yaw
    scene.collection.objects.link(sun_obj)
    # Ambient fill (area light high above scene centre)
    fill_data = bpy.data.lights.new("WalkthroughFill", type="AREA")
    fill_data.energy = 500.0
    fill_data.size   = 20.0
    bounds = _scene_bounds()
    cx = (bounds[0] + bounds[2]) * 0.5
    cy = (bounds[1] + bounds[3]) * 0.5
    cz =  bounds[5] + 10.0
    fill_obj = bpy.data.objects.new("WalkthroughFill", fill_data)
    fill_obj.location = (cx, cy, cz)
    scene.collection.objects.link(fill_obj)


def _enable_cycles_gpu(scene):
    """Activate GPU for Cycles.  Skips OPTIX on WSL2 (silent CPU fallback bug)."""
    import os
    is_wsl2 = os.path.exists("/dev/dxg")

    scene.cycles.device = "GPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences

    device_order = ("CUDA", "HIP", "METAL") if is_wsl2 else ("OPTIX", "CUDA", "HIP", "METAL")
    if is_wsl2:
        print("[Walkthrough] WSL2 detected — skipping OPTIX (silent CPU fallback)")

    activated = False
    for device_type in device_order:
        try:
            prefs.compute_device_type = device_type
            prefs.get_devices()
            gpu_devices = [d for d in prefs.devices if d.type != "CPU"]
            if gpu_devices:
                for d in prefs.devices:
                    d.use = (d.type != "CPU")
                bpy.ops.wm.save_userpref()
                print(f"[Walkthrough] GPU ({device_type}): "
                      + ", ".join(d.name for d in prefs.devices if d.use))
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
    t_total_start = time.time()
    timing = {}

    try:
        config, output_blend, output_dir = _parse_args()
    except Exception as exc:
        print("WALKTHROUGH_RESULT:" + json.dumps({"status": "error", "message": str(exc)}))
        return

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        local_area_ratio = config.get("local_area_ratio")

        # ---- Unit scale (metres per Blender unit; needed for grid_res, camera_height) ----
        unit_scale = _get_unit_scale()
        config["_unit_scale"] = unit_scale
        print(f"[Walkthrough] Scene unit scale: {unit_scale:.4f} m/BU "
              f"({'metric' if abs(unit_scale - 1.0) < 0.01 else f'{unit_scale*100:.1f}cm/BU'})")

        # ---- Scene bounds (fast; needed for ratio calculation and global mode) ----
        scene_bounds = _scene_bounds()
        span_x = scene_bounds[2] - scene_bounds[0]
        span_y = scene_bounds[3] - scene_bounds[1]

        # ---- Depsgraph (needed by both modes for camera animation LOS) ----
        t0 = time.time()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        timing["depsgraph_s"] = round(time.time() - t0, 1)
        print(f"[Timing] depsgraph eval: {timing['depsgraph_s']}s")

        # ================================================================
        # LOCAL MODE  (local_area_ratio set)
        # ================================================================
        if local_area_ratio:
            # Radius = ratio × min(span_x, span_y) — uses scene-relative sizing,
            # independent of unit system (cm vs m vs inches).
            scene_char_bu = min(span_x, span_y)
            radius_bu = local_area_ratio * scene_char_bu
            config["_local_radius_bu"] = radius_bu
            height_bu = config.get("local_height", 8.0) / unit_scale
            print(f"[Walkthrough] LOCAL mode: ratio={local_area_ratio}  "
                  f"scene_char={scene_char_bu:.0f} BU ({scene_char_bu * unit_scale:.1f}m)  "
                  f"radius={radius_bu:.0f} BU ({radius_bu * unit_scale:.1f}m)")

            t0 = time.time()
            center = _find_local_center(config)
            nearby = _filter_nearby_objects(
                center, radius_bu, height_bu, height_bu * 0.5
            )
            timing["object_filter_s"] = round(time.time() - t0, 1)
            print(f"[Walkthrough] Centre=({center.x:.1f},{center.y:.1f},{center.z:.1f})  "
                  f"nearby={len(nearby)}/{len(bpy.context.scene.objects)} objects")

            t0 = time.time()
            local_bvh = _build_bvh_from_objects(nearby, depsgraph)
            timing["bvh_build_s"] = round(time.time() - t0, 1)
            print(f"[Timing] local BVH build: {timing['bvh_build_s']}s")

            t0 = time.time()
            solid, nx, ny, nz, _res, local_bounds = _build_local_voxel_grid(
                config, center, local_bvh
            )
            timing["voxel_grid_s"] = round(time.time() - t0, 1)
            print(f"[Timing] local voxel grid: {timing['voxel_grid_s']}s")

            t0 = time.time()
            walkable, camera_seed = _flood_fill_walkable(
                solid, config, local_bounds, nx, ny, nz, center, local_bvh
            )
            timing["walkable_s"] = round(time.time() - t0, 1)

            bounds_for_path = local_bounds
            bvh_for_los     = local_bvh

        # ================================================================
        # GLOBAL MODE  (legacy: full scene.ray_cast)
        # ================================================================
        else:
            t0 = time.time()
            solid, nx, ny, nz, _res = _build_voxel_grid(config, scene_bounds)
            timing["voxel_grid_s"] = round(time.time() - t0, 1)
            print(f"[Timing] global voxel grid: {timing['voxel_grid_s']}s")

            t0 = time.time()
            walkable = _find_walkable_voxels(solid, config, scene_bounds, nx, ny, nz)
            timing["walkable_s"] = round(time.time() - t0, 1)

            bounds_for_path = scene_bounds
            bvh_for_los     = depsgraph

        # ================================================================
        # Shared: path planning, camera, render
        # ================================================================

        if not walkable:
            raise RuntimeError(
                "No walkable voxels found. Check the scene has upward-facing floor "
                "surfaces and sufficient clearance for camera_height."
            )

        # ---- Step 4: Coverage path ----
        t0 = time.time()
        if local_area_ratio:
            component = walkable   # flood-fill already gives reachable set
        else:
            component = _bfs_largest_component(walkable)
            camera_seed = None

        n_wp      = min(config["num_waypoints"], len(component))
        waypoints = _farthest_point_sample(component, n_wp, config["seed"],
                                           fixed_first=camera_seed)
        tour      = _greedy_tsp_tour(waypoints)
        path_points = _build_smooth_path(tour, walkable, config, bounds_for_path)
        timing["path_s"] = round(time.time() - t0, 1)
        print(f"[Timing] path planning: {timing['path_s']}s")

        if not path_points:
            raise RuntimeError("Path planning produced no points.")

        # In local mode, prepend the camera's actual XY position (with the
        # seed voxel's floor Z) as the first path point, so the walkthrough
        # starts directly under the camera before moving to the seed voxel.
        #
        # We use the seed voxel's Z (min_z + seed_iz * res) as the floor level
        # rather than (center.z - cam_h_bu), because camera_height is in metres
        # and cm-scale scenes (unit_scale=0.01) produce very large BU values that
        # may place the floor far below the actual ground.
        if local_area_ratio and camera_seed is not None:
            res = config.get("_effective_grid_resolution", config["grid_resolution"])
            seed_floor_z = bounds_for_path[4] + camera_seed[2] * res  # min_z + iz*res
            cam_floor_start = Vector((center.x, center.y, seed_floor_z))
            path_points = [cam_floor_start] + path_points
            print(f"[Walkthrough] Prepended camera floor start: "
                  f"({cam_floor_start.x:.1f}, {cam_floor_start.y:.1f}, {cam_floor_start.z:.1f})")

        # Auto-calculate duration from path length.
        if not config.get("duration_seconds"):
            path_length = sum(
                (path_points[i + 1] - path_points[i]).length
                for i in range(len(path_points) - 1)
            )
            walk_speed  = config.get("walk_speed_mps", 1.2)
            raw_duration = max(5.0, path_length / walk_speed)
            max_dur      = config.get("max_duration_seconds")
            if max_dur and raw_duration > max_dur:
                config["duration_seconds"] = max_dur
                print(f"[Walkthrough] Path {path_length:.1f}m / {walk_speed}m/s "
                      f"= {raw_duration:.1f}s → capped to {max_dur}s")
            else:
                config["duration_seconds"] = raw_duration
                print(f"[Walkthrough] Path {path_length:.1f}m / {walk_speed}m/s "
                      f"= {config['duration_seconds']:.1f}s")

        # ---- Step 5: Interesting objects ----
        interesting_objects = _find_interesting_objects()

        # ---- Steps 6 & 7: Camera animation ----
        t0 = time.time()
        cam_obj, total_frames = _setup_and_animate_camera(
            path_points, interesting_objects, config, bvh_for_los
        )
        timing["camera_anim_s"] = round(time.time() - t0, 1)
        print(f"[Timing] camera animation: {timing['camera_anim_s']}s")

        # ---- Step 8: Save ----
        output_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

        frames_dir = None
        if config.get("render"):
            t0 = time.time()
            frames_dir = output_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            scene  = bpy.context.scene
            engine = config.get("render_engine", "CYCLES").upper()

            if engine == "WORKBENCH":
                scene.render.engine = "BLENDER_WORKBENCH"
            elif engine in ("EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
                scene.render.engine = "BLENDER_EEVEE_NEXT"
                _ensure_lights(scene)
            else:
                scene.render.engine = "CYCLES"
                scene.cycles.samples               = 32
                scene.cycles.use_adaptive_sampling = True
                scene.cycles.adaptive_threshold    = 0.01
                scene.cycles.adaptive_min_samples  = 4
                scene.view_layers[0].cycles.use_denoising = True
                _enable_cycles_gpu(scene)

            scene.render.resolution_x = 1280
            scene.render.resolution_y = 720
            scene.render.filepath     = str(frames_dir / "frame_")
            scene.render.image_settings.file_format = "PNG"
            scene.render.use_persistent_data = True
            bpy.ops.render.render(animation=True)
            timing["render_s"] = round(time.time() - t0, 1)
            print(f"[Timing] render: {timing['render_s']}s")

        timing["total_s"] = round(time.time() - t_total_start, 1)
        print(f"[Timing] TOTAL: {timing['total_s']}s")

        # ---- Step 9: Report ----
        print("WALKTHROUGH_RESULT:" + json.dumps({
            "status": "success",
            "blend_output":              str(output_blend),
            "frames_dir":                str(frames_dir) if frames_dir else None,
            "path_points_count":         len(path_points),
            "walkable_voxels_count":     len(walkable),
            "solid_voxels_count":        len(solid),
            "interesting_objects_count": len(interesting_objects),
            "timing":                    timing,
            "mode":                      "local" if local_area_ratio else "global",
        }))

    except Exception as exc:
        import traceback
        print("WALKTHROUGH_RESULT:" + json.dumps({
            "status":    "error",
            "message":   str(exc),
            "traceback": traceback.format_exc(),
        }))


main()
