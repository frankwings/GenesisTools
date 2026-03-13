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
   a. LOCAL  (local_radius_xy set): bidirectional scene.ray_cast to
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




def _cast_all_hits_bidir(origin, direction, max_dist):
    """Yield every surface hit along a ray using bidirectional scene.ray_cast.

    scene.ray_cast is front-face only, so we cast both forward and reverse
    to detect back-faces (equivalent to BVHTree double-sided detection).
    """
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = Vector(origin)
    direction = Vector(direction).normalized()

    # Forward pass
    cur_origin = Vector(origin)
    remaining = max_dist
    step_past = 0.05
    fwd_hits = []
    while remaining > step_past:
        hit, loc, _nrm, *_ = scene.ray_cast(depsgraph, cur_origin, direction,
                                              distance=remaining)
        if not hit:
            break
        fwd_hits.append(loc)
        traveled = (loc - cur_origin).length
        remaining -= traveled + step_past
        cur_origin = loc + direction * step_past

    # Reverse pass — catches back-faces missed by forward
    end_pt = origin + direction * max_dist
    cur_origin = Vector(end_pt)
    rev_dir = -direction
    remaining = max_dist
    rev_hits = []
    while remaining > step_past:
        hit, loc, _nrm, *_ = scene.ray_cast(depsgraph, cur_origin, rev_dir,
                                              distance=remaining)
        if not hit:
            break
        rev_hits.append(loc)
        traveled = (loc - cur_origin).length
        remaining -= traveled + step_past
        cur_origin = loc + rev_dir * step_past

    # Merge and deduplicate (hits within step_past are considered same)
    all_hits = list(fwd_hits)
    for rh in rev_hits:
        is_dup = False
        for fh in all_hits:
            if (rh - fh).length < step_past * 2:
                is_dup = True
                break
        if not is_dup:
            all_hits.append(rh)

    # Sort by distance from origin along ray direction
    all_hits.sort(key=lambda h: (h - origin).dot(direction))
    for h in all_hits:
        yield h


def _collect_hits_bidir(origin, direction, max_dist):
    """Return list of hit locations along a ray (reifies _cast_all_hits_bidir)."""
    return list(_cast_all_hits_bidir(origin, direction, max_dist))


def _build_local_voxel_grid(config, center, floor_z_override=None):
    """Tri-axial voxelisation of a fixed local region using scene.ray_cast.

    Unlike the global mode, the grid is anchored at `center` with a fixed
    physical size (local_radius_xy × local_radius_xy × local_height metres),
    so computation cost is O(1) regardless of scene size.

    All config distances are in real metres; they are converted to Blender
    units via _get_unit_scale() before use in ray_cast or coordinate maths.

    The floor level is auto-detected by casting a ray down from `center`,
    unless ``floor_z_override`` is provided (in Blender units), in which case
    that value is used directly.  The override is needed when the camera is
    elevated above a mezzanine.

    Uses bidirectional scene.ray_cast (forward + reverse) to detect both
    front and back faces, replacing the old custom BVHTree approach.

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

    # Determine floor Z for voxel grid anchoring.
    # Priority: floor_z_override (from global scene.ray_cast, bypasses mezzanine
    # interference) > BVH floor detection (fast but picks closest surface which
    # may be a mezzanine rather than the ground floor).
    if floor_z_override is not None:
        actual_floor_z = floor_z_override
        print(f"[Walkthrough] Voxel grid floor anchored to scene floor override: z={actual_floor_z:.1f} BU")
    else:
        # Use scene.ray_cast for floor detection (normal-aware).
        depsgraph = bpy.context.evaluated_depsgraph_get()
        _hit, floor_loc, floor_nrm, *_ = bpy.context.scene.ray_cast(
            depsgraph,
            Vector((center.x, center.y, center.z + height)),
            Vector((0.0, 0.0, -1.0)),
            distance=height * 3.0,
        )
        actual_floor_z = floor_loc.z if _hit else None

    if actual_floor_z is not None:
        min_z = actual_floor_z - 0.5
        max_z = actual_floor_z + height
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

    # Sub-voxel ray sampling density.
    # n=1 → 1 ray/voxel (original); n=3 → 9 rays/voxel face.
    # Higher n catches thin walls and particle geometry smaller than one voxel
    # without changing voxel resolution (and therefore path-planning cost).
    n = config.get("voxel_ray_samples", 3)

    def mark_parity(hits, axis):
        """Parity (odd-even) fill: mark voxels between consecutive hit pairs.

        For each pair of consecutive hits (entry, exit) on a horizontal ray,
        fill every voxel between them as solid.  This correctly marks the
        interior of walls: the X/Y ray enters the wall at the left/front face
        and exits at the right/back face; both surfaces are hit, and voxels
        between them are the wall body.

        Without this fill, only the surface voxels (the face hit points) are
        solid.  Voxels deep inside a thick wall are empty in the solid set,
        so the walkable check incorrectly accepts them (floor below, clear
        space above within cam_h), resulting in the camera walking inside walls.

        axis: 0 = X, 1 = Y, 2 = Z
        """
        for i in range(0, len(hits) - 1, 2):
            p0 = hits[i]
            p1 = hits[i + 1]
            # Mark every voxel along the ray axis between the two hit points.
            if axis == 0:
                ix0 = max(0, min(nx - 1, int((p0.x - min_x) / res)))
                ix1 = max(0, min(nx - 1, int((p1.x - min_x) / res)))
                iy  = max(0, min(ny - 1, int((p0.y - min_y) / res)))
                iz  = max(0, min(nz - 1, int((p0.z - min_z) / res)))
                for ixx in range(min(ix0, ix1), max(ix0, ix1) + 1):
                    solid.add((ixx, iy, iz))
            elif axis == 1:
                iy0 = max(0, min(ny - 1, int((p0.y - min_y) / res)))
                iy1 = max(0, min(ny - 1, int((p1.y - min_y) / res)))
                ix  = max(0, min(nx - 1, int((p0.x - min_x) / res)))
                iz  = max(0, min(nz - 1, int((p0.z - min_z) / res)))
                for iyy in range(min(iy0, iy1), max(iy0, iy1) + 1):
                    solid.add((ix, iyy, iz))
            else:
                iz0 = max(0, min(nz - 1, int((p0.z - min_z) / res)))
                iz1 = max(0, min(nz - 1, int((p1.z - min_z) / res)))
                ix  = max(0, min(nx - 1, int((p0.x - min_x) / res)))
                iy  = max(0, min(ny - 1, int((p0.y - min_y) / res)))
                for izz in range(min(iz0, iz1), max(iz0, iz1) + 1):
                    solid.add((ix, iy, izz))

    # Z-axis rays (one per XY sub-sample pair)
    for ix in range(nx):
        for iy in range(ny):
            for sx in range(n):
                x = min_x + (ix + (sx + 0.5) / n) * res
                for sy in range(n):
                    y = min_y + (iy + (sy + 0.5) / n) * res
                    for loc_v in _cast_all_hits_bidir((x, y, max_z + 1.0),
                                                    (0, 0, -1), ray_span_z):
                        mark(loc_v)

    # X-axis rays — parity fill between hit pairs marks wall interiors solid.
    for iy in range(ny):
        for iz in range(nz):
            for sy in range(n):
                y = min_y + (iy + (sy + 0.5) / n) * res
                for sz in range(n):
                    z = min_z + (iz + (sz + 0.5) / n) * res
                    hits = _collect_hits_bidir((min_x - 1.0, y, z),
                                             (1, 0, 0), ray_span_x)
                    for loc_v in hits:
                        mark(loc_v)
                    mark_parity(hits, axis=0)

    # Y-axis rays — parity fill between hit pairs marks wall interiors solid.
    for ix in range(nx):
        for iz in range(nz):
            for sx in range(n):
                x = min_x + (ix + (sx + 0.5) / n) * res
                for sz in range(n):
                    z = min_z + (iz + (sz + 0.5) / n) * res
                    hits = _collect_hits_bidir((x, min_y - 1.0, z),
                                             (0, 1, 0), ray_span_y)
                    for loc_v in hits:
                        mark(loc_v)
                    mark_parity(hits, axis=1)

    print(f"[Walkthrough] Local voxel grid {nx}×{ny}×{nz} "
          f"({nx * ny * nz} total), {len(solid)} solid voxels  "
          f"ray_samples={n}×{n}={n*n}/face")
    return solid, nx, ny, nz, res, local_bounds


def _flood_fill_walkable(solid, config, local_bounds, nx, ny, nz, center):
    """Find walkable voxels and flood-fill reachable cells from camera seed.

    Step 1 — Find walkable voxels: same as global mode (solid voxel with
    empty space above for camera_height clearance).

    Step 2 — Find seed via downward ray cast from camera (scene.ray_cast).

    Step 3 — Flood fill BFS outward from seed.

    Uses bidirectional scene.ray_cast for clearance checks (replaces BVHTree).

    Returns (reachable, seed) where seed is the voxel index to start the path.
    """
    min_x, min_y, _mx, _my, min_z, _mz = local_bounds
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h = config["camera_height"] / unit_scale   # convert metres → BU
    cam_h_voxels = max(1, int(math.ceil(cam_h / res)))

    # --- Step 1: walkable voxels ---
    # Primary check: solid floor below + cam_h_voxels of empty space above.
    floor_surfaces = {(ix, iy, iz) for (ix, iy, iz) in solid
                      if (ix, iy, iz + 1) not in solid}
    candidates = set()
    for (ix, iy, iz_floor) in floor_surfaces:
        iz_feet = iz_floor + 1
        if all((ix, iy, iz_feet + k) not in solid and iz_feet + k < nz
               for k in range(cam_h_voxels)):
            candidates.add((ix, iy, iz_feet))

    # Secondary check: scene.ray_cast clearance from floor to camera-eye height.
    # Thin walls (< grid_resolution wide) are not captured as solid voxels.
    # Cast a ray straight up from voxel floor to eye height; if hit, obstructed.
    # Also cast horizontal rays at eye height to detect thin vertical walls.
    # Uses bidirectional scene.ray_cast (forward + reverse) for both-face detection.
    horiz_threshold = res * 0.25
    _HORIZ_DIRS = (
        Vector((1.0, 0.0, 0.0)),
        Vector((-1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, -1.0, 0.0)),
    )
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene
    walkable = set()
    rejected_bvh = 0
    rejected_horiz = 0
    for (ix, iy, iz_feet) in candidates:
        floor_z  = min_z + iz_feet * res
        eye_z    = floor_z + cam_h
        cx = min_x + (ix + 0.5) * res
        cy = min_y + (iy + 0.5) * res
        origin   = Vector((cx, cy, floor_z + 0.05))
        # Upward ray: check clearance to eye height
        hit_up, *_ = scene.ray_cast(depsgraph, origin,
                                     Vector((0.0, 0.0, 1.0)),
                                     distance=cam_h - 0.05)
        if hit_up:
            rejected_bvh += 1
            continue
        # Reverse (downward from eye): catches back-faces
        eye_origin = Vector((cx, cy, eye_z))
        hit_dn, *_ = scene.ray_cast(depsgraph, eye_origin,
                                     Vector((0.0, 0.0, -1.0)),
                                     distance=cam_h - 0.05)
        if hit_dn:
            rejected_bvh += 1
            continue
        # Horizontal check at eye height: reject if inside a thin wall.
        inside_wall = False
        for d in _HORIZ_DIRS:
            h_fwd, *_ = scene.ray_cast(depsgraph, eye_origin, d,
                                        distance=horiz_threshold)
            if h_fwd:
                inside_wall = True
                break
            # Reverse horizontal
            h_rev, *_ = scene.ray_cast(depsgraph,
                                        eye_origin + d * horiz_threshold,
                                        -d, distance=horiz_threshold)
            if h_rev:
                inside_wall = True
                break
        if inside_wall:
            rejected_horiz += 1
        else:
            walkable.add((ix, iy, iz_feet))

    print(f"[Walkthrough] Walkable voxels: {len(walkable)}  "
          f"(rejected by BVH clearance: {rejected_bvh}, "
          f"rejected by horizontal wall check: {rejected_horiz})")
    if not walkable:
        return walkable, None

    # --- Step 2: find seed via downward ray from camera ---
    # Cast straight down from camera; the first floor hit gives the precise
    # floor position regardless of voxel size.
    seed = None
    _seed_hit, floor_hit, *_ = scene.ray_cast(
        depsgraph,
        Vector((center.x, center.y, center.z)),
        Vector((0.0, 0.0, -1.0)),
        distance=cam_h * 10.0,
    )
    if _seed_hit:
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
    actual_floor_z = floor_hit.z if floor_hit is not None else None
    return reachable, seed, actual_floor_z


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
       Each candidate smooth step is rejected when a bidirectional
       scene.ray_cast at camera height is blocked.
    3. 4× linear upsampling for dense per-frame path sampling.
       Blocked segments fall back to the straight voxel-centre connection.

    `bounds` must be (min_x, min_y, max_x, max_y, min_z, max_z).
    """
    from mathutils import Vector as _V

    min_x = bounds[0]
    min_y = bounds[1]
    min_z = bounds[4]
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    cam_h_bu = config.get("camera_height", 1.7) / config.get("_unit_scale", 1.0)

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

    def _los_clear(p0, p1):
        """Return True if the segment p0→p1 at camera height is unobstructed.

        Uses bidirectional scene.ray_cast (forward + reverse) to detect
        both front and back faces without needing a custom BVHTree.
        """
        origin = _V((p0[0], p0[1], p0[2] + cam_h_bu))
        target = _V((p1[0], p1[1], p1[2] + cam_h_bu))
        d = target - origin
        dist = d.length
        if dist < 1e-6:
            return True
        d_norm = d / dist

        depsgraph = bpy.context.evaluated_depsgraph_get()
        # Forward ray
        hit_fwd, *_ = bpy.context.scene.ray_cast(
            depsgraph, origin, d_norm, distance=dist * 0.99,
        )
        if hit_fwd:
            return False
        # Reverse ray — catches back-faces
        hit_rev, *_ = bpy.context.scene.ray_cast(
            depsgraph, target, -d_norm, distance=dist * 0.99,
        )
        return not hit_rev

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
                candidate = [sx, sy, sz]
                # LOS check: reject move if camera ray from previous accepted
                # point to candidate is blocked by geometry.
                if not _los_clear(new_pts[-1], candidate):
                    candidate = points[i]
                new_pts.append(candidate)
            else:
                new_pts.append(points[i])
        new_pts.append(points[-1])
        points = new_pts

    upsampled = []
    steps = 4
    for i in range(len(points) - 1):
        p_start = points[i]
        p_end   = points[i + 1]
        if _los_clear(p_start, p_end):
            for j in range(steps):
                t = j / steps
                x = p_start[0] + t * (p_end[0] - p_start[0])
                y = p_start[1] + t * (p_end[1] - p_start[1])
                z = p_start[2] + t * (p_end[2] - p_start[2])
                upsampled.append([x, y, z])
        else:
            # Segment blocked: emit only the start point; the end point will
            # be emitted as the start of the next iteration (or as the final
            # append below), so the camera jumps cleanly between two
            # wall-free positions rather than interpolating through a wall.
            upsampled.append(p_start)
    upsampled.append(points[-1])

    return [Vector((p[0], p[1], p[2])) for p in upsampled]


# ---------------------------------------------------------------------------
# Fine-level path adjustment (Level 2 of coarse-to-fine voxelisation)
# ---------------------------------------------------------------------------

def _fine_adjust_path(coarse_path, config):
    """Refine a coarse path using small, high-resolution local voxel patches.

    The coarse grid (Level 1) produces a globally-planned path, but its
    resolution (~0.4 m) can miss thin walls (<1 voxel wide).  This function
    walks the coarse path step-by-step and, at each step, builds a tiny
    fine-resolution voxel patch centred on the current position.  If the next
    step is blocked in the fine grid, it finds the nearest fine-walkable cell
    that still makes progress toward the coarse target.

    Uses bidirectional scene.ray_cast instead of custom BVHTree.

    Returns
    -------
    list[Vector]
        Adjusted path with wall-avoiding positions.
    """
    if len(coarse_path) < 2:
        return coarse_path

    unit_scale = config.get("_unit_scale", 1.0)
    coarse_res = config.get("_effective_grid_resolution",
                            config["grid_resolution"] / unit_scale)
    fine_res = coarse_res / 4.0       # ~0.1 m at default settings
    cam_h_bu = config["camera_height"] / unit_scale
    patch_radius = coarse_res * 2.5   # patch covers 5×5 coarse voxels
    cam_h_voxels = max(1, int(math.ceil(cam_h_bu / fine_res)))

    # Fine-grid dimensions (fixed for every patch — same allocation each step)
    fine_n = max(1, int(math.ceil(patch_radius * 2.0 / fine_res)))
    fine_nz = max(1, int(math.ceil((cam_h_bu + 2.0) / fine_res)))

    adjusted = [coarse_path[0]]
    n_nudged = 0
    t0 = time.time()

    # Cache: avoid rebuilding the same patch when consecutive points fall
    # within the same patch.
    _cached_patch_center = None
    _cached_walkable_world = None   # set of (world_x_snapped, world_y_snapped)
    _cached_fine_floor_z = None
    CACHE_REUSE_DIST = patch_radius * 0.4   # reuse patch if within 40 % of radius

    def _build_fine_patch(cx, cy, floor_z):
        """Build a fine-resolution 2D walkable set around (cx, cy).

        Returns a dict mapping (fine_ix, fine_iy) → floor_z in BU, plus
        the patch origin (min_x, min_y, min_z) for coordinate conversion.
        """
        p_min_x = cx - patch_radius
        p_min_y = cy - patch_radius
        p_min_z = floor_z - 0.5
        p_max_z = floor_z + cam_h_bu + 2.0

        solid = set()
        ray_span_z = p_max_z - p_min_z + 2.0

        # Z-axis rays — detect floor and ceiling surfaces
        for ix in range(fine_n):
            x = p_min_x + (ix + 0.5) * fine_res
            for iy in range(fine_n):
                y = p_min_y + (iy + 0.5) * fine_res
                for loc in _cast_all_hits_bidir((x, y, p_max_z + 1.0),
                                              (0, 0, -1), ray_span_z):
                    fix = min(fine_n - 1, max(0, int((loc.x - p_min_x) / fine_res)))
                    fiy = min(fine_n - 1, max(0, int((loc.y - p_min_y) / fine_res)))
                    fiz = min(fine_nz - 1, max(0, int((loc.z - p_min_z) / fine_res)))
                    solid.add((fix, fiy, fiz))

        # X-axis rays — catch vertical walls perpendicular to X
        ray_span_x = patch_radius * 2.0 + 2.0
        for iy in range(fine_n):
            y = p_min_y + (iy + 0.5) * fine_res
            for iz in range(fine_nz):
                z = p_min_z + (iz + 0.5) * fine_res
                for loc in _cast_all_hits_bidir((p_min_x - 1.0, y, z),
                                              (1, 0, 0), ray_span_x):
                    fix = min(fine_n - 1, max(0, int((loc.x - p_min_x) / fine_res)))
                    fiy = min(fine_n - 1, max(0, int((loc.y - p_min_y) / fine_res)))
                    fiz = min(fine_nz - 1, max(0, int((loc.z - p_min_z) / fine_res)))
                    solid.add((fix, fiy, fiz))

        # Y-axis rays — catch vertical walls perpendicular to Y
        ray_span_y = patch_radius * 2.0 + 2.0
        for ix in range(fine_n):
            x = p_min_x + (ix + 0.5) * fine_res
            for iz in range(fine_nz):
                z = p_min_z + (iz + 0.5) * fine_res
                for loc in _cast_all_hits_bidir((x, p_min_y - 1.0, z),
                                              (0, 1, 0), ray_span_y):
                    fix = min(fine_n - 1, max(0, int((loc.x - p_min_x) / fine_res)))
                    fiy = min(fine_n - 1, max(0, int((loc.y - p_min_y) / fine_res)))
                    fiz = min(fine_nz - 1, max(0, int((loc.z - p_min_z) / fine_res)))
                    solid.add((fix, fiy, fiz))

        # Find walkable fine cells: floor surface with cam_h clearance above
        walkable_fine = {}
        floor_surfaces = {(ix, iy, iz) for (ix, iy, iz) in solid
                          if (ix, iy, iz + 1) not in solid}
        for (ix, iy, iz_floor) in floor_surfaces:
            iz_feet = iz_floor + 1
            if all((ix, iy, iz_feet + k) not in solid and iz_feet + k < fine_nz
                   for k in range(cam_h_voxels)):
                # Bidirectional scene.ray_cast clearance: floor to eye
                cell_x = p_min_x + (ix + 0.5) * fine_res
                cell_y = p_min_y + (iy + 0.5) * fine_res
                cell_floor_z = p_min_z + iz_feet * fine_res
                _o = Vector((cell_x, cell_y, cell_floor_z + 0.05))
                _sc = bpy.context.scene
                _dg = bpy.context.evaluated_depsgraph_get()
                h_up, *_ = _sc.ray_cast(_dg, _o, Vector((0, 0, 1)),
                                         distance=cam_h_bu - 0.05)
                if not h_up:
                    # Reverse check
                    _o2 = Vector((cell_x, cell_y, cell_floor_z + cam_h_bu))
                    h_dn, *_ = _sc.ray_cast(_dg, _o2, Vector((0, 0, -1)),
                                             distance=cam_h_bu - 0.05)
                    if not h_dn:
                        walkable_fine[(ix, iy)] = p_min_z + iz_feet * fine_res

        return walkable_fine, (p_min_x, p_min_y, p_min_z)

    def _world_to_fine(wx, wy, patch_origin):
        """Convert world XY to fine grid indices."""
        p_min_x, p_min_y, _ = patch_origin
        return (int((wx - p_min_x) / fine_res),
                int((wy - p_min_y) / fine_res))

    def _fine_to_world(fix, fiy, patch_origin, walkable_fine):
        """Convert fine grid indices to world XY + floor Z."""
        p_min_x, p_min_y, _ = patch_origin
        wx = p_min_x + (fix + 0.5) * fine_res
        wy = p_min_y + (fiy + 0.5) * fine_res
        wz = walkable_fine.get((fix, fiy), coarse_path[0].z)
        return Vector((wx, wy, wz))

    for i in range(1, len(coarse_path)):
        cur = adjusted[-1]
        target = coarse_path[i]

        # Check if step is clear via bidirectional scene.ray_cast at camera height
        origin = Vector((cur.x, cur.y, cur.z + cam_h_bu))
        target_eye = Vector((target.x, target.y, target.z + cam_h_bu))
        d = target_eye - origin
        dist = d.length
        if dist < 1e-6:
            adjusted.append(target)
            continue
        d_norm = d / dist

        _sc = bpy.context.scene
        _dg = bpy.context.evaluated_depsgraph_get()
        hit_fwd, *_ = _sc.ray_cast(_dg, origin, d_norm, distance=dist * 0.99)
        hit_rev, *_ = _sc.ray_cast(_dg, target_eye, -d_norm, distance=dist * 0.99)
        if not hit_fwd and not hit_rev:
            # Clear path — keep coarse point
            adjusted.append(target)
            continue

        # Blocked! Build or reuse fine patch around current position.
        if (_cached_patch_center is not None and
                abs(cur.x - _cached_patch_center[0]) < CACHE_REUSE_DIST and
                abs(cur.y - _cached_patch_center[1]) < CACHE_REUSE_DIST):
            walkable_fine = _cached_walkable_world
            patch_origin = _cached_fine_floor_z
        else:
            walkable_fine, patch_origin = _build_fine_patch(cur.x, cur.y, cur.z)
            _cached_patch_center = (cur.x, cur.y)
            _cached_walkable_world = walkable_fine
            _cached_fine_floor_z = patch_origin

        if not walkable_fine:
            # No walkable fine cells — fall back to coarse point
            adjusted.append(target)
            continue

        # Find current and target positions in fine grid
        cur_fi = _world_to_fine(cur.x, cur.y, patch_origin)
        tgt_fi = _world_to_fine(target.x, target.y, patch_origin)

        # Direction toward target in fine grid space
        dx = target.x - cur.x
        dy = target.y - cur.y
        dlen = math.sqrt(dx * dx + dy * dy)
        if dlen < 1e-6:
            adjusted.append(target)
            continue
        dx /= dlen
        dy /= dlen

        # Search for best fine-walkable cell: maximises progress toward target
        # while being reachable (BVH-clear from current position).
        best_cell = None
        best_progress = -1e9

        for (fix, fiy), fz in walkable_fine.items():
            # Must be within the fine patch
            if fix < 0 or fix >= fine_n or fiy < 0 or fiy >= fine_n:
                continue
            cell_world = _fine_to_world(fix, fiy, patch_origin, walkable_fine)
            # Progress = dot product of (cell - cur) with direction to target
            cell_dx = cell_world.x - cur.x
            cell_dy = cell_world.y - cur.y
            progress = cell_dx * dx + cell_dy * dy
            # Must make positive progress (or at least not go backward much)
            if progress < -fine_res:
                continue
            # Cell must be within reasonable distance (don't jump too far)
            cell_dist = math.sqrt(cell_dx * cell_dx + cell_dy * cell_dy)
            if cell_dist > coarse_res * 2.0:
                continue
            # Bidirectional scene.ray_cast: can we reach this cell?
            c_origin = Vector((cur.x, cur.y, cur.z + cam_h_bu))
            c_target = Vector((cell_world.x, cell_world.y, cell_world.z + cam_h_bu))
            c_d = c_target - c_origin
            c_dist = c_d.length
            if c_dist > 1e-6:
                c_fwd, *_ = _sc.ray_cast(_dg, c_origin, c_d / c_dist,
                                          distance=c_dist * 0.99)
                if c_fwd:
                    continue
                c_rev, *_ = _sc.ray_cast(_dg, c_target, -c_d / c_dist,
                                          distance=c_dist * 0.99)
                if c_rev:
                    continue
            # Score: progress toward target, penalised by lateral deviation
            lateral = abs(cell_dx * (-dy) + cell_dy * dx)  # perpendicular component
            score = progress - lateral * 0.5
            if score > best_progress:
                best_progress = score
                best_cell = cell_world

        if best_cell is not None:
            adjusted.append(best_cell)
            n_nudged += 1
        else:
            # No viable fine cell found — keep coarse point anyway
            adjusted.append(target)

    elapsed = time.time() - t0
    print(f"[Walkthrough] Fine path adjustment: {n_nudged}/{len(coarse_path)-1} "
          f"points nudged, {elapsed:.2f}s  "
          f"fine_res={fine_res:.3f} BU  patch={patch_radius:.1f} BU  "
          f"fine_grid={fine_n}×{fine_n}×{fine_nz}")
    return adjusted


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
# Step 5: Density-based look direction via 360° sphere ray sampling
# ---------------------------------------------------------------------------

def _fibonacci_sphere_directions(n=64):
    """Return n uniformly distributed directions on the unit sphere.

    Uses the Fibonacci lattice (golden-angle spiral) for near-uniform coverage.
    Excludes directions pointing mostly straight down (dz < -0.85) since
    the camera rarely needs to look at the floor directly below it.
    """
    dirs = []
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    for i in range(n * 2):   # oversample to allow downward exclusion
        theta = 2.0 * math.pi * i / golden
        phi   = math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * (i + 0.5) / (n * 2))))
        x = math.sin(phi) * math.cos(theta)
        y = math.sin(phi) * math.sin(theta)
        z = math.cos(phi)
        if z > -0.85:   # exclude near-straight-down directions
            dirs.append(Vector((x, y, z)).normalized())
        if len(dirs) >= n:
            break
    return dirs


# Pre-compute once at module level — same directions reused every frame.
_SPHERE_DIRS = None


def _normal_entropy(normals, n_bins=8):
    """Shannon entropy of quantized surface normals.

    Each normal component (nx, ny, nz) is quantized to ``n_bins`` levels,
    giving n_bins³ possible buckets.  The entropy of the resulting histogram
    measures geometric complexity: a flat wall (all normals identical) yields
    entropy ≈ 0, while a furniture cluster (normals pointing everywhere)
    yields high entropy.

    Returns entropy in bits.  Max possible = log2(len(normals)) when every
    normal falls in a unique bin.
    """
    if len(normals) < 2:
        return 0.0
    buckets = {}
    for nx, ny, nz in normals:
        # Components in [-1, 1] → bin index in [0, n_bins-1]
        key = (int((nx + 1.0) * 0.5 * n_bins),
               int((ny + 1.0) * 0.5 * n_bins),
               int((nz + 1.0) * 0.5 * n_bins))
        buckets[key] = buckets.get(key, 0) + 1
    total = len(normals)
    entropy = 0.0
    for count in buckets.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def _find_normal_entropy_target(cam_pos, depsgraph, look_range,
                                n_samples=64):
    """Find the look direction with the highest normal entropy in a 45° cone.

    Shoots ``n_samples`` rays from ``cam_pos`` over a Fibonacci sphere.
    For each ray that hits geometry, records the surface normal.  For each
    hit direction, collects all normals within a 45° cone and computes
    Shannon entropy of the quantized normals.  The direction with the
    highest normal entropy is the most geometrically complex — furniture
    clusters, architectural features, etc.

    Returns (target_point, best_direction, entropy_score) or (None, None, 0).
    ``entropy_score`` is normalised to [0, 1].
    """
    global _SPHERE_DIRS
    if _SPHERE_DIRS is None:
        _SPHERE_DIRS = _fibonacci_sphere_directions(n_samples)

    # depsgraph is passed directly — no BVHTree fallback needed

    hits = []   # list of (direction, normal_tuple_or_None)
    for d in _SPHERE_DIRS:
        result, _loc, nrm, _idx, _obj, _mat = bpy.context.scene.ray_cast(
            depsgraph, cam_pos, d, distance=look_range,
        )
        if result:
            hits.append((d, (nrm.x, nrm.y, nrm.z)))
        else:
            hits.append((d, None))

    if not any(h[1] is not None for h in hits):
        return None, None, 0.0

    COS_THRESHOLD = math.cos(math.pi / 4)   # 45° half-angle cone
    best_dir     = None
    best_entropy = 0.0
    max_possible = math.log2(max(1, n_samples))  # for normalisation

    for d_i, nrm_i in hits:
        if nrm_i is None:
            continue
        cone_normals = [nrm_j for d_j, nrm_j in hits
                        if nrm_j is not None and d_i.dot(d_j) >= COS_THRESHOLD]
        if len(cone_normals) < 2:
            continue
        ent = _normal_entropy(cone_normals)
        if ent > best_entropy:
            best_entropy = ent
            best_dir     = d_i

    if best_dir is None or best_entropy < 0.3:
        return None, None, 0.0

    score = min(1.0, best_entropy / max_possible)
    return cam_pos + best_dir * (look_range * 0.6), best_dir, score


# ---------------------------------------------------------------------------
# Step 5b: Line-of-sight  (bidirectional scene.ray_cast)
# ---------------------------------------------------------------------------

def _has_line_of_sight(cam_pos, target_center):
    """Return True if no geometry blocks cam_pos → target_center.

    Uses bidirectional scene.ray_cast for both-face detection.
    """
    direction = (target_center - cam_pos).normalized()
    distance = (target_center - cam_pos).length
    if distance < 0.1:
        return True
    depsgraph = bpy.context.evaluated_depsgraph_get()
    # Forward
    hit_fwd, *_ = bpy.context.scene.ray_cast(
        depsgraph, cam_pos, direction, distance=distance - 0.1
    )
    if hit_fwd:
        return False
    # Reverse — catches back-faces
    hit_rev, *_ = bpy.context.scene.ray_cast(
        depsgraph, target_center, -direction, distance=distance - 0.1
    )
    return not hit_rev


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
                               initial_rotation_quat=None):
    unit_scale = config.get("_unit_scale", 1.0)
    cam_h         = config["camera_height"] / unit_scale   # metres → BU
    fps           = config["fps"]
    total_frames  = max(1, int(config["duration_seconds"] * fps))
    # look_range is in metres; convert to BU for ray casts
    glance_range  = config["look_range"] / unit_scale
    glance_duration = fps * 3
    # Re-evaluate density gaze every ~2 seconds (when no active gaze target)
    density_update_interval = max(1, int(fps * 2))

    for obj in list(bpy.data.objects):
        if obj.name == "WalkthroughCamera":
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new("WalkthroughCamera")
    cam_data.lens = 35
    # clip_start: 1 mm world-space.  Blender default (0.1 m = 10 BU in cm-scale)
    # clips wall geometry when camera is within 10 cm of a surface → curved dark edge.
    cam_data.clip_start = 0.001 / unit_scale
    # clip_end: 100 m world-space.  Blender default (1000 BU = 10 m in cm-scale)
    # clips geometry beyond 10 m → large blank white areas in long corridors.
    # ratio clip_end/clip_start = 100_000 — safe from z-fighting.
    cam_data.clip_end = 100.0 / unit_scale
    cam_obj = bpy.data.objects.new("WalkthroughCamera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj
    cam_obj.rotation_mode = "QUATERNION"

    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = total_frames

    # Seed prev_quat from the original scene camera so frame 0 shows the
    # exact original camera view and then smoothly SLERPs into the path-based
    # walk-through orientation over the next few seconds.
    prev_quat            = initial_rotation_quat  # None → no override
    gaze_target          = None
    gaze_remaining       = 0
    forced_forward_frames = 0          # C: forced forward look after gaze ends
    gaze_cooldown_dir    = None        # A: direction of last gaze (Vector or None)
    gaze_cooldown_frames = 0           # A: frames remaining on direction cooldown
    glance_cooldown      = {}          # kept for backward compat (unused)

    rotation_tau  = config.get("rotation_smooth_seconds", 3.5)
    slerp_alpha   = 1.0 - math.exp(-1.0 / max(1, fps * rotation_tau))

    # Debug: identify which path-point indices correspond to each frame.
    # Print camera positions for frames in the "known dark" clusters so we can
    # examine exactly where in world space the dark frames occur.
    _DEBUG_FRAMES = {88, 89, 90, 95, 96, 97}  # just before/during/after first dark cluster

    for frame_idx in range(total_frames):
        t        = frame_idx / max(1, total_frames - 1)
        path_pt  = _sample_path(path_points, t)
        cam_pos  = path_pt + Vector((0, 0, cam_h))
        if frame_idx + 1 in _DEBUG_FRAMES:
            print(f"[DEBUG] frame {frame_idx+1:03d}  path_pt=({path_pt.x:.1f},{path_pt.y:.1f},{path_pt.z:.1f})"
                  f"  cam_pos=({cam_pos.x:.1f},{cam_pos.y:.1f},{cam_pos.z:.1f})"
                  f"  t={t:.4f}  path_idx≈{t*(len(path_points)-1):.1f}")

        # Tick direction cooldown (A)
        if gaze_cooldown_frames > 0:
            gaze_cooldown_frames -= 1
            if gaze_cooldown_frames == 0:
                gaze_cooldown_dir = None

        # Tick forced-forward counter (C)
        if forced_forward_frames > 0:
            forced_forward_frames -= 1

        # Tick active gaze
        if gaze_remaining > 0:
            gaze_remaining -= 1
            if gaze_remaining == 0:
                # C: record direction we were gazing, force forward look for 2s
                if gaze_target is not None:
                    raw_dir = (gaze_target - cam_pos)
                    if raw_dir.length > 0:
                        gaze_cooldown_dir    = raw_dir.normalized()
                        gaze_cooldown_frames = int(fps * 6)   # A: 6s direction cooldown
                gaze_target           = None
                forced_forward_frames = int(fps * 2)          # C: 2s forced forward

        # Normal-entropy gaze: only when no active gaze, not forced forward,
        # and direction cooldown allows it.
        if (gaze_target is None
                and forced_forward_frames == 0
                and frame_idx % density_update_interval == 0):
            ent_target, ent_dir, ent_score = _find_normal_entropy_target(
                cam_pos, bpy.context.evaluated_depsgraph_get(), glance_range)
            # A: skip if new direction is too close to the cooldown direction
            if ent_target is not None:
                blocked = (gaze_cooldown_dir is not None
                           and ent_dir.dot(gaze_cooldown_dir) > 0.8)
                if not blocked:
                    gaze_target    = ent_target
                    # Gaze duration scales with entropy: low → 1s, high → 5s
                    gaze_remaining = int(fps * (1.0 + 4.0 * ent_score))

        if gaze_target is not None:
            look_target = gaze_target
        else:
            # Look in the path-travel direction from eye height.
            # floor_ahead is the path point ~0.15 ahead in t-space (floor level).
            # path_pt is the current floor point under cam_pos.
            # Direction = floor_ahead - path_pt preserves terrain slope (tilt
            # up on stairs, horizontal on flat ground) without forcing eye-height.
            floor_ahead = _travel_direction_target(cam_pos, path_points, t,
                                                   ahead=0.15)
            look_target = cam_pos + (floor_ahead - path_pt)

        if frame_idx == 0 and initial_rotation_quat is not None:
            # Frame 1 must exactly match the original scene camera view.
            target_quat = initial_rotation_quat
        else:
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
    """Set world ambient color for EEVEE when scene has no lights.

    Does NOT add light objects to the scene — only modifies world/render
    settings so the original scene geometry is unchanged.
    EEVEE in headless WSL2 runs on CPU (no OpenGL GPU passthrough), so this
    is only a visual improvement; CYCLES+CUDA is preferred for GPU renders.
    """
    lights = [o for o in scene.objects if o.type == "LIGHT"]
    if lights:
        return   # scene already has lighting, leave it alone
    print("[Walkthrough] No lights — enabling EEVEE world ambient (no objects added).")
    if scene.world is None:
        scene.world = bpy.data.worlds.new("WalkthroughWorld")
    scene.world.use_nodes = False
    scene.world.color = (0.8, 0.8, 0.8)   # bright neutral ambient


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

            # Preliminary downward ray to find real floor Z (for voxel grid anchoring).
            _rc_hit, prelim_floor_hit, *_ = bpy.context.scene.ray_cast(
                depsgraph,
                center,
                Vector((0.0, 0.0, -1.0)),
                distance=(config.get("local_height", 8.0) / unit_scale) * 10.0,
            )
            if not _rc_hit:
                prelim_floor_hit = None
            timing["object_filter_s"] = round(time.time() - t0, 1)
            print(f"[Walkthrough] Centre=({center.x:.1f},{center.y:.1f},{center.z:.1f})")

            t0 = time.time()
            # Voxel grid uses bidirectional scene.ray_cast (no custom BVH needed).
            _prelim_floor_z = prelim_floor_hit.z if prelim_floor_hit is not None else None
            solid, nx, ny, nz, _res, local_bounds = _build_local_voxel_grid(
                config, center, floor_z_override=_prelim_floor_z
            )
            timing["voxel_grid_s"] = round(time.time() - t0, 1)
            print(f"[Timing] local voxel grid: {timing['voxel_grid_s']}s")

            t0 = time.time()
            walkable, camera_seed, actual_floor_z = _flood_fill_walkable(
                solid, config, local_bounds, nx, ny, nz, center
            )
            timing["walkable_s"] = round(time.time() - t0, 1)

            bounds_for_path = local_bounds

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
        config["_unit_scale"] = unit_scale
        path_points = _build_smooth_path(tour, walkable, config, bounds_for_path)
        timing["path_s"] = round(time.time() - t0, 1)
        print(f"[Timing] path planning: {timing['path_s']}s")

        if not path_points:
            raise RuntimeError("Path planning produced no points.")

        # ---- Level 2: Fine path adjustment ----
        # Walk the coarse path step-by-step, building small high-res voxel
        # patches to detect thin walls missed by the coarse grid.
        if local_area_ratio:
            t0_fine = time.time()
            path_points = _fine_adjust_path(path_points, config)
            timing["fine_adjust_s"] = round(time.time() - t0_fine, 1)
            print(f"[Timing] fine path adjustment: {timing['fine_adjust_s']}s")

        # In local mode:
        # 1. Correct path Z for voxel quantisation. The voxel grid uses
        #    iz * res as the floor Z, but the actual floor surface is at
        #    actual_floor_z (from BVH ray cast). Shift all path points by the
        #    difference so the camera walks at floor level, not above the ceiling.
        # 2. Prepend the camera's actual XY+Z as the first path point.
        # 3. Use the original scene camera orientation for frame 1 so it renders
        #    exactly the original camera view; SLERP into path direction after.
        initial_rotation_quat = None
        if local_area_ratio and camera_seed is not None:
            cam_h_bu = config["camera_height"] / unit_scale
            res = config.get("_effective_grid_resolution", config["grid_resolution"])

            # Step 1: Z correction — shift voxel-grid floor up/down to actual floor.
            if actual_floor_z is not None:
                voxel_floor_z = bounds_for_path[4] + camera_seed[2] * res
                z_correction = actual_floor_z - voxel_floor_z
                path_points = [Vector((pt.x, pt.y, pt.z + z_correction))
                               for pt in path_points]
                print(f"[Walkthrough] Floor Z correction: voxel={voxel_floor_z:.1f}  "
                      f"actual={actual_floor_z:.1f}  correction={z_correction:.1f} BU")

            # Step 2: prepend camera start.
            # Use actual_floor_z (BVH ray hit) as the floor Z so the first path
            # point is on the real floor surface.  Falling back to center.z - cam_h_bu
            # only when actual_floor_z is unavailable.  This prevents the camera from
            # diving through geometry when the original scene camera is elevated
            # (e.g. on a loft or mezzanine looking down).
            if actual_floor_z is not None:
                cam_floor_start_z = actual_floor_z
            else:
                cam_floor_start_z = center.z - cam_h_bu
            cam_floor_start = Vector((center.x, center.y, cam_floor_start_z))
            path_points = [cam_floor_start] + path_points
            print(f"[Walkthrough] Prepended camera floor start: "
                  f"({cam_floor_start.x:.1f}, {cam_floor_start.y:.1f}, {cam_floor_start.z:.1f})  "
                  f"→ cam z = {cam_floor_start_z + cam_h_bu:.1f} BU "
                  f"({(cam_floor_start_z + cam_h_bu) * unit_scale:.3f}m)")

            # Step 3: original camera rotation for frame 1 — only when the original
            # camera is at roughly floor level (within 50 % of camera_height above
            # the actual floor).  If it is elevated (loft, drone, security cam) the
            # drop from its Z to walk height causes the camera to dive through
            # geometry; in that case just start walking from actual floor level.
            orig_cam = bpy.context.scene.camera
            if orig_cam is not None:
                elev = abs((center.z - cam_h_bu) - cam_floor_start_z)
                if elev < cam_h_bu * 0.5:
                    initial_rotation_quat = orig_cam.matrix_world.to_quaternion()
                    print(f"[Walkthrough] Original camera quat applied (elev={elev:.1f} BU < threshold)")
                else:
                    print(f"[Walkthrough] Original camera elevated {elev:.1f} BU above floor "
                          f"(threshold={cam_h_bu * 0.5:.1f}) — skipping frame-1 original view")

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

        # ---- Steps 6 & 7: Camera animation ----
        t0 = time.time()
        cam_obj, total_frames = _setup_and_animate_camera(
            path_points, [], config,
            initial_rotation_quat=initial_rotation_quat,
        )
        timing["camera_anim_s"] = round(time.time() - t0, 1)
        print(f"[Timing] camera animation: {timing['camera_anim_s']}s")

        # ---- Step 8: Save ----
        output_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.data.use_autopack = False  # skip packing missing external textures
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

            scene.render.resolution_x = config.get("render_width",  1280)
            scene.render.resolution_y = config.get("render_height", 720)
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
            "interesting_objects_count": 0,  # replaced by density-based gaze
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
