"""Step 1: ray_cast -> solid voxel grid.

Four build modes (selected by config keys):
  - "terrain" -- config["terrain_npz"] set: uses pre-computed terrain_snake.npz (no bpy)
  - "snake"   -- config["snake_npz"] set: uses pre-computed VoxelGrid centers
  - "local"   -- config["local_area_ratio"] set: bidirectional ray_cast in local AABB
  - "global"  -- neither: tri-axial sweep over full scene bounds

Input:  open bpy scene (must be called under bpy Python)
Output: VoxelGridData -> voxel_grid.npz
"""
from __future__ import annotations

import argparse
import json
import math
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class VoxelGridData:
    solid: np.ndarray        # (N, 3) int32 -- grid indices of solid voxels
    candidates: np.ndarray   # (K, 3) int32 -- flood-fill reachable voxels
    nx: int
    ny: int
    nz: int
    res: float               # voxel size in Blender units
    bounds: tuple            # (min_x, min_y, max_x, max_y, min_z, max_z)
    unit_scale: float        # metres per Blender unit
    mode: str                # "terrain" | "snake" | "local" | "global"
    hits: np.ndarray | None  # (H, 3) float64 -- ray hit positions (debug only)


# ---------------------------------------------------------------------------
# bpy-dependent helpers (only called at runtime under bpy Python)
# ---------------------------------------------------------------------------

def _get_unit_scale():
    import bpy
    scale = bpy.context.scene.unit_settings.scale_length
    return scale if scale > 0 else 1.0


def _scene_bounds():
    import bpy
    from mathutils import Vector
    xs, ys, zs = [], [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            xs.append(world.x); ys.append(world.y); zs.append(world.z)
    if not xs:
        raise RuntimeError("No mesh objects in scene.")
    return min(xs), min(ys), max(xs), max(ys), min(zs), max(zs)


def _find_local_center(config):
    import bpy
    from mathutils import Vector
    cam = bpy.context.scene.camera
    if cam is not None:
        return cam.location.copy()
    for obj in bpy.context.scene.objects:
        if obj.type == "CAMERA":
            return obj.location.copy()
    xs, ys, zs = [], [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    if xs:
        return Vector(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2,
                       min(zs)+(max(zs)-min(zs))*0.6))
    return Vector((0.0, 0.0, 1.7))


def _cast_all_hits_bidir(origin, direction, max_dist):
    """Yield every surface hit along a bidirectional ray via scene.ray_cast."""
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = Vector(origin)
    direction = Vector(direction).normalized()

    step_past = 0.05
    cur = Vector(origin); rem = max_dist; fwd = []
    while rem > step_past:
        hit, loc, _n, *_ = scene.ray_cast(depsgraph, cur, direction, distance=rem)
        if not hit: break
        fwd.append(loc)
        rem -= (loc - cur).length + step_past
        cur = loc + direction * step_past

    end_pt = origin + direction * max_dist
    cur = Vector(end_pt); rev_dir = -direction; rem = max_dist; rev = []
    while rem > step_past:
        hit, loc, _n, *_ = scene.ray_cast(depsgraph, cur, rev_dir, distance=rem)
        if not hit: break
        rev.append(loc)
        rem -= (loc - cur).length + step_past
        cur = loc + rev_dir * step_past

    all_hits = list(fwd)
    for rh in rev:
        if all((rh - fh).length >= step_past * 2 for fh in all_hits):
            all_hits.append(rh)
    all_hits.sort(key=lambda h: (h - origin).dot(direction))
    yield from all_hits


def _collect_hits_bidir(origin, direction, max_dist):
    return list(_cast_all_hits_bidir(origin, direction, max_dist))


def _load_snake_mesh(config):
    """Load AC snake mesh (vertices + faces only). No voxel_grid_npz needed."""
    path = config.get("snake_npz")
    if not path:
        return None
    data = np.load(path)
    return {
        "verts": data["vertices"].astype(np.float64),
        "faces": data["faces"].astype(np.int64),
    }


def _build_raw_voxels_from_snake(snake_mesh, config):
    """Step 1 (snake mode): mark raw voxels by inside-AC test.

    Builds a grid from the AC mesh AABB, then for each voxel centre fires a
    +X ray through the BVHTree of the AC mesh and counts intersections.
    Odd count → inside → raw voxel.  No scene ray-cast used here.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    verts = snake_mesh["verts"]
    faces = snake_mesh["faces"]
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)

    unit_scale = _get_unit_scale()
    res = config.get("grid_resolution", 0.5) / unit_scale
    span = hi - lo
    max_xy = config.get("max_grid_cells_xy", 80)
    max_nz = config.get("max_grid_cells_z", 40)
    res = max(res, span[0] / max_xy, span[1] / max_xy, span[2] / max_nz)

    nx = max(1, int(math.ceil(span[0] / res)))
    ny = max(1, int(math.ceil(span[1] / res)))
    nz = max(1, int(math.ceil(span[2] / res)))
    bounds = (lo[0], lo[1], lo[0] + nx * res, lo[1] + ny * res, lo[2], lo[2] + nz * res)

    bvh = BVHTree.FromPolygons(
        [Vector(v) for v in verts.tolist()],
        [tuple(int(i) for i in f) for f in faces.tolist()],
    )

    direction = Vector((1.0, 0.0, 0.0))
    # Total X span of mesh + margin — enough for the ray to exit the mesh
    x_span = float(hi[0]) - float(lo[0]) + res * 2.0
    step = res * 0.01  # step past each surface to count the next one

    raw = set()
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                cx = float(lo[0]) + (ix + 0.5) * res
                cy = float(lo[1]) + (iy + 0.5) * res
                cz = float(lo[2]) + (iz + 0.5) * res
                cur = Vector((cx, cy, cz))
                count = 0
                rem = x_span
                while rem > step:
                    loc, _, _, dist = bvh.ray_cast(cur, direction, rem)
                    if loc is None:
                        break
                    count += 1
                    advance = max(dist, 0.0) + step
                    cur = loc + direction * step
                    rem -= advance
                if count % 2 == 1:
                    raw.add((ix, iy, iz))

    print(f"[VoxelGrid] Snake inside-test: {len(raw)}/{nx*ny*nz} raw voxels "
          f"in {nx}×{ny}×{nz} grid (res={res:.2f} BU)")
    return raw, nx, ny, nz, res, bounds


def _build_local_voxel_grid(config, center, hit_collector=None):
    """Bidirectional ray_cast voxelisation of a local AABB around center."""
    import bpy
    from mathutils import Vector
    unit_scale = _get_unit_scale()
    radius_xy = config["_local_radius_bu"]
    height    = config.get("local_height", 8.0) / unit_scale
    res       = config["grid_resolution"] / unit_scale

    min_x = center.x - radius_xy; max_x = center.x + radius_xy
    min_y = center.y - radius_xy; max_y = center.y + radius_xy

    min_z = center.z - height; max_z = center.z + height

    local_bounds = (min_x, min_y, max_x, max_y, min_z, max_z)
    span_x = max_x-min_x; span_y = max_y-min_y; span_z = max_z-min_z

    max_xy = config.get("max_local_cells_xy", 80)
    max_nz = config.get("max_local_cells_z", 40)
    res = max(res, span_x/max_xy, span_y/max_xy, span_z/max_nz)
    config["_effective_grid_resolution"] = res

    nx = max(1, int(math.ceil(span_x/res)))
    ny = max(1, int(math.ceil(span_y/res)))
    nz = max(1, int(math.ceil(span_z/res)))
    solid = set()
    n = config.get("voxel_ray_samples", 3)

    def mark(loc_v):
        ix = min(nx-1, max(0, int((loc_v.x-min_x)/res)))
        iy = min(ny-1, max(0, int((loc_v.y-min_y)/res)))
        iz = min(nz-1, max(0, int((loc_v.z-min_z)/res)))
        solid.add((ix,iy,iz))
        if hit_collector is not None:
            hit_collector.append((loc_v.x, loc_v.y, loc_v.z))

    ray_span_z = span_z+2.0; ray_span_x = span_x+2.0; ray_span_y = span_y+2.0
    for ix in range(nx):
        for iy in range(ny):
            for sx in range(n):
                x = min_x+(ix+(sx+0.5)/n)*res
                for sy in range(n):
                    y = min_y+(iy+(sy+0.5)/n)*res
                    for lv in _cast_all_hits_bidir((x,y,max_z+1.0),(0,0,-1),ray_span_z):
                        mark(lv)
    for iy in range(ny):
        for iz in range(nz):
            for sy in range(n):
                y = min_y+(iy+(sy+0.5)/n)*res
                for sz in range(n):
                    z = min_z+(iz+(sz+0.5)/n)*res
                    for lv in _collect_hits_bidir((min_x-1.0,y,z),(1,0,0),ray_span_x):
                        mark(lv)
    for ix in range(nx):
        for iz in range(nz):
            for sx in range(n):
                x = min_x+(ix+(sx+0.5)/n)*res
                for sz in range(n):
                    z = min_z+(iz+(sz+0.5)/n)*res
                    for lv in _collect_hits_bidir((x,min_y-1.0,z),(0,1,0),ray_span_y):
                        mark(lv)

    return solid, nx, ny, nz, res, local_bounds


def _mark_vertex_voxels(solid: set, nx: int, ny: int, nz: int,
                        res: float, bounds: tuple,
                        clip: tuple | None = None) -> int:
    """Mark voxels that contain at least one mesh vertex as solid.

    Supplements ray-cast solid detection: thin walls whose faces never
    intersect a ray axis are still caught because their vertices land in
    a voxel.

    clip: optional (min_x, min_y, max_x, max_y, min_z, max_z) world-space
          bounding box — vertices outside it are ignored (used in local mode).
    """
    import bpy
    min_x, min_y, max_x, max_y, min_z, max_z = bounds
    added = 0
    dg = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        eval_obj = obj.evaluated_get(dg)
        mesh = eval_obj.to_mesh()
        mat = eval_obj.matrix_world
        for v in mesh.vertices:
            wv = mat @ v.co
            x, y, z = float(wv.x), float(wv.y), float(wv.z)
            if clip is not None:
                cx0, cy0, cx1, cy1, cz0, cz1 = clip
                if x < cx0 or x > cx1 or y < cy0 or y > cy1 or z < cz0 or z > cz1:
                    continue
            ix = min(nx - 1, max(0, int((x - min_x) / res)))
            iy = min(ny - 1, max(0, int((y - min_y) / res)))
            iz = min(nz - 1, max(0, int((z - min_z) / res)))
            cell = (ix, iy, iz)
            if cell not in solid:
                solid.add(cell)
                added += 1
        eval_obj.to_mesh_clear()
    return added


_SCATTER_RENDER_TYPES = {"OBJECT", "COLLECTION"}


def _mark_particle_instance_voxels(solid: set, nx: int, ny: int, nz: int,
                                    res: float, bounds: tuple,
                                    clip: tuple | None = None,
                                    margin: float = 1.0) -> int:
    """Mark voxels occupied by scatter particle instances as solid.

    ray_cast() only hits actual mesh objects; OBJECT/COLLECTION scatter
    instances are render-time and invisible to it.  This function iterates
    particle data directly: for each alive particle, it marks a box of voxels
    around the particle location using the instance object's bounding radius.

    Only OBJECT and COLLECTION render types are processed (scatter vegetation).
    Hair/Halo/Path emitters produce actual geometry and are handled by ray_cast.

    clip: optional world-space AABB — particles outside it are skipped.
    """
    import bpy

    min_x, min_y, max_x, max_y, min_z, max_z = bounds

    dg = bpy.context.evaluated_depsgraph_get()
    added = 0

    for obj in bpy.context.scene.objects:
        if obj.type not in ("MESH", "CURVE", "SURFACE"):
            continue
        eval_obj = obj.evaluated_get(dg)
        for psys in eval_obj.particle_systems:
            settings = psys.settings
            if settings.render_type not in _SCATTER_RENDER_TYPES:
                continue

            # Determine instance half-size from the instance object's bbox.
            if settings.render_type == "OBJECT" and settings.instance_object:
                inst = settings.instance_object
                half_size = max(inst.dimensions) * 0.5 if max(inst.dimensions) > 0 else res
            elif settings.render_type == "COLLECTION" and settings.instance_collection:
                dims = [d for col_obj in settings.instance_collection.objects
                        for d in col_obj.dimensions]
                half_size = max(dims) * 0.5 if dims else res
            else:
                continue  # no instance target — nothing to mark

            for p in psys.particles:
                if p.alive_state != "ALIVE":
                    continue

                wx, wy, wz = float(p.location.x), float(p.location.y), float(p.location.z)
                # particle.size scales the instance — apply to half_size and margin
                scaled = (half_size * float(p.size) if p.size > 0 else half_size) * margin

                if clip is not None:
                    cx0, cy0, cx1, cy1, cz0, cz1 = clip
                    if wx + scaled < cx0 or wx - scaled > cx1:
                        continue
                    if wy + scaled < cy0 or wy - scaled > cy1:
                        continue
                    if wz + scaled < cz0 or wz - scaled > cz1:
                        continue

                ix_lo = max(0,    int((wx - scaled - min_x) / res))
                ix_hi = min(nx-1, int((wx + scaled - min_x) / res))
                iy_lo = max(0,    int((wy - scaled - min_y) / res))
                iy_hi = min(ny-1, int((wy + scaled - min_y) / res))
                iz_lo = max(0,    int((wz - scaled - min_z) / res))
                iz_hi = min(nz-1, int((wz + scaled - min_z) / res))

                for ix in range(ix_lo, ix_hi + 1):
                    for iy in range(iy_lo, iy_hi + 1):
                        for iz in range(iz_lo, iz_hi + 1):
                            cell = (ix, iy, iz)
                            if cell not in solid:
                                solid.add(cell)
                                added += 1

    return added


def _build_global_voxel_grid(config, scene_bounds, hit_collector=None):
    """Tri-axial sweep voxelisation over the full scene."""
    import bpy
    from mathutils import Vector
    unit_scale = _get_unit_scale()
    min_x, min_y, max_x, max_y, min_z, max_z = scene_bounds
    max_xy    = config.get("max_grid_cells_xy", 80)
    max_z_c   = config.get("max_grid_cells_z", 40)
    res_bu    = config.get("grid_resolution", 0.5) / unit_scale

    span_x = max_x-min_x; span_y = max_y-min_y; span_z = max_z-min_z
    res_bu = max(res_bu, span_x/max_xy, span_y/max_xy, span_z/max_z_c)
    nx = max(1, int(math.ceil(span_x/res_bu)))
    ny = max(1, int(math.ceil(span_y/res_bu)))
    nz = max(1, int(math.ceil(span_z/res_bu)))

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    solid = set(); step = 0.05

    def _cast_hits(origin, direction, max_d):
        org = Vector(origin); d = Vector(direction).normalized(); rem = max_d
        while rem > step:
            hit, loc, *_ = scene.ray_cast(depsgraph, org, d, distance=rem)
            if not hit: break
            yield loc
            rem -= (loc-org).length+step; org = loc+d*step

    def mark(loc_v):
        ix = min(nx-1, max(0, int((loc_v.x-min_x)/res_bu)))
        iy = min(ny-1, max(0, int((loc_v.y-min_y)/res_bu)))
        iz = min(nz-1, max(0, int((loc_v.z-min_z)/res_bu)))
        solid.add((ix,iy,iz))
        if hit_collector is not None:
            hit_collector.append((loc_v.x, loc_v.y, loc_v.z))

    for ix in range(nx):
        for iy in range(ny):
            x = min_x+(ix+0.5)*res_bu; y = min_y+(iy+0.5)*res_bu
            for lv in _cast_hits((x,y,max_z+1.0),(0,0,-1),span_z+2.0): mark(lv)
    for iy in range(ny):
        for iz in range(nz):
            y = min_y+(iy+0.5)*res_bu; z = min_z+(iz+0.5)*res_bu
            for lv in _cast_hits((min_x-1.0,y,z),(1,0,0),span_x+2.0): mark(lv)
    for ix in range(nx):
        for iz in range(nz):
            x = min_x+(ix+0.5)*res_bu; z = min_z+(iz+0.5)*res_bu
            for lv in _cast_hits((x,min_y-1.0,z),(0,1,0),span_y+2.0): mark(lv)

    return solid, nx, ny, nz, res_bu, scene_bounds


# ---------------------------------------------------------------------------
# Flood-fill candidates helper
# ---------------------------------------------------------------------------

def _flood_fill_candidates(solid: set, center_ijk: tuple,
                            nx: int, ny: int, nz: int) -> np.ndarray:
    """BFS flood fill through non-solid voxels from center_ijk."""
    cx, cy, cz = center_ijk
    if (cx, cy, cz) in solid:
        best, best_d = None, float("inf")
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    if (ix,iy,iz) not in solid:
                        d = (ix-cx)**2+(iy-cy)**2+(iz-cz)**2
                        if d < best_d:
                            best_d, best = d, (ix,iy,iz)
        if best is None:
            return np.empty((0,3), dtype=np.int32)
        cx, cy, cz = best
    visited = {(cx,cy,cz)}
    q = deque([(cx,cy,cz)])
    while q:
        ix,iy,iz = q.popleft()
        for dx,dy,dz in [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]:
            ni,nj,nk = ix+dx,iy+dy,iz+dz
            if 0<=ni<nx and 0<=nj<ny and 0<=nk<nz:
                cell = (ni,nj,nk)
                if cell not in visited and cell not in solid:
                    visited.add(cell); q.append(cell)
    if visited:
        return np.array(sorted(visited), dtype=np.int32)
    return np.empty((0,3), dtype=np.int32)


# ---------------------------------------------------------------------------
# Terrain mode (no bpy required)
# ---------------------------------------------------------------------------

def _filter_terrain_by_particles(vgd: VoxelGridData, config: dict) -> VoxelGridData:
    """Remove terrain candidates whose camera-eye column is blocked by scatter instances.

    For each candidate (ix, iy, iz), checks all voxels in the vertical column
    [iz, iz + camera_height_voxels] against the scatter particle solid set.
    Any column that intersects a particle instance is excluded from the walkable set.

    Must be called with an open bpy scene (particle data requires evaluated depsgraph).
    """
    unit_scale = _get_unit_scale()
    camera_height_bu = config.get("camera_height", 1.7) / unit_scale
    camera_height_voxels = max(1, int(round(camera_height_bu / vgd.res)))

    particle_solid: set = set()
    _mark_particle_instance_voxels(
        particle_solid, vgd.nx, vgd.ny, vgd.nz, vgd.res, vgd.bounds,
        margin=config.get("particle_block_margin", 1.0),
    )

    if not particle_solid:
        print("[VoxelGrid] Terrain particle filter: no scatter instances found — all candidates kept")
        return vgd

    filtered = []
    for row in vgd.candidates:
        ix, iy, iz = int(row[0]), int(row[1]), int(row[2])
        iz_top = min(vgd.nz - 1, iz + camera_height_voxels)
        blocked = any((ix, iy, iz_col) in particle_solid for iz_col in range(iz, iz_top + 1))
        if not blocked:
            filtered.append((ix, iy, iz))

    filtered_arr = (np.array(sorted(filtered), dtype=np.int32)
                    if filtered else np.empty((0, 3), dtype=np.int32))
    n_removed = len(vgd.candidates) - len(filtered_arr)
    print(f"[VoxelGrid] Terrain particle filter: -{n_removed} blocked by scatter, "
          f"{len(filtered_arr)} candidates remain")

    return VoxelGridData(
        solid=vgd.solid, candidates=filtered_arr,
        nx=vgd.nx, ny=vgd.ny, nz=vgd.nz,
        res=vgd.res, bounds=vgd.bounds, unit_scale=vgd.unit_scale,
        mode=vgd.mode, hits=vgd.hits,
    )


def _filter_terrain_by_mesh_objects(vgd: VoxelGridData, config: dict) -> VoxelGridData:
    """Remove terrain candidates whose camera-eye falls inside any mesh object.

    Ray parity test: fire a +Z ray from the camera-eye position, counting only
    hits against SMALL discrete objects (trees, rocks).  Large landscape objects
    (terrain, background, sky dome) are auto-detected by XY bounding-box size
    and excluded from the count — they would otherwise cause false positives
    because their geometry can extend above the camera-eye position.

    Actual terrain Z is obtained by firing a downward ray and taking the lowest
    hit above the scene floor, which correctly handles cases where the cloth
    heightmap under-estimates terrain Z (cloth bridged over a bump).

    Must be called with an open bpy scene.
    """
    import bpy
    from mathutils import Vector
    import numpy as _np

    unit_scale = _get_unit_scale()
    cam_h     = config.get("camera_height", 1.7) / unit_scale
    min_x, min_y   = vgd.bounds[0], vgd.bounds[1]
    scene_floor    = vgd.bounds[4]
    scene_top      = vgd.bounds[5]
    up   = Vector((0.0, 0.0,  1.0))
    down = Vector((0.0, 0.0, -1.0))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    # --- Identify large landscape objects to exclude from the parity count ---
    # Heuristic: any mesh whose world-space XY span exceeds 40% of the scene XY
    # span is terrain / background / sky dome, not a discrete obstacle.
    scene_x_span = vgd.bounds[2] - vgd.bounds[0]
    scene_y_span = vgd.bounds[3] - vgd.bounds[1]
    excluded_objs: set = set()
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        wbb  = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        ox   = max(v.x for v in wbb) - min(v.x for v in wbb)
        oy   = max(v.y for v in wbb) - min(v.y for v in wbb)
        if ox > 0.4 * scene_x_span or oy > 0.4 * scene_y_span:
            excluded_objs.add(obj.name)
    if excluded_objs:
        print(f"[VoxelGrid] Mesh filter: excluding large objects from parity: "
              f"{sorted(excluded_objs)}")

    # --- Get actual terrain Z by collecting all downward hits, taking minimum ---
    def _actual_terrain_z(wx: float, wy: float) -> "float | None":
        pos     = Vector((wx, wy, scene_top + 10.0))
        lowest  = None
        while True:
            hit, loc, _n, _i, _o, _m = scene.ray_cast(depsgraph, pos, down)
            if not hit or loc.z < scene_floor - 0.5:
                break
            if lowest is None or loc.z < lowest:
                lowest = loc.z
            pos = loc + Vector((0.0, 0.0, -1e-4))
        return lowest

    # Cloth heightmap as fallback when the downward ray finds nothing.
    _hm_lookup = None
    terrain_npz = config.get("terrain_npz")
    if terrain_npz:
        _td     = _np.load(terrain_npz)
        _hm     = _td["heightmap"].astype(_np.float64)
        _fres   = float(_td["res"])
        _hm_mx  = float(_td["bounds"][0])
        _hm_my  = float(_td["bounds"][1])
        _hm_nx, _hm_ny = _hm.shape

        def _hm_lookup(wx: float, wy: float) -> "float | None":
            fx = (wx - _hm_mx) / _fres - 0.5
            fy = (wy - _hm_my) / _fres - 0.5
            ix = max(0, min(_hm_nx - 2, int(fx)))
            iy = max(0, min(_hm_ny - 2, int(fy)))
            tx = max(0.0, min(1.0, fx - ix)); ty = max(0.0, min(1.0, fy - iy))
            z00=_hm[ix,iy]; z10=_hm[ix+1,iy]; z01=_hm[ix,iy+1]; z11=_hm[ix+1,iy+1]
            if any(_np.isnan(v) for v in (z00,z10,z01,z11)):
                return None
            return float((1-tx)*(1-ty)*z00+tx*(1-ty)*z10+(1-tx)*ty*z01+tx*ty*z11)

    # --- Parity test (excludes large landscape objects) ---
    MAX_DIST = (scene_top - scene_floor + 20.0)
    def _inside_mesh(wx: float, wy: float, wz: float) -> bool:
        pos       = Vector((wx, wy, wz))
        remaining = MAX_DIST
        count     = 0
        while remaining > 1e-3:
            hit, loc, _n, _i, obj, _m = scene.ray_cast(
                depsgraph, pos, up, distance=remaining)
            if not hit:
                break
            if obj is None or obj.name not in excluded_objs:
                count += 1
            remaining -= (loc - pos).length + 1e-4
            pos = loc + Vector((0.0, 0.0, 1e-4))
        return (count % 2) == 1

    filtered  = []
    n_blocked = 0
    for row in vgd.candidates:
        ix, iy, iz = int(row[0]), int(row[1]), int(row[2])
        cx = min_x + (ix + 0.5) * vgd.res
        cy = min_y + (iy + 0.5) * vgd.res
        terrain_z = _actual_terrain_z(cx, cy)
        if terrain_z is None:
            terrain_z = (_hm_lookup(cx, cy) if _hm_lookup is not None
                         else vgd.bounds[4] + (iz + 0.5) * vgd.res)
        eye_z = terrain_z + cam_h
        if _inside_mesh(cx, cy, eye_z):
            n_blocked += 1
        else:
            filtered.append((ix, iy, iz))

    filtered_arr = (np.array(sorted(filtered), dtype=np.int32)
                    if filtered else np.empty((0, 3), dtype=np.int32))
    print(f"[VoxelGrid] Terrain mesh filter: -{n_blocked} inside mesh objects, "
          f"{len(filtered_arr)} candidates remain")
    return VoxelGridData(
        solid=vgd.solid, candidates=filtered_arr,
        nx=vgd.nx, ny=vgd.ny, nz=vgd.nz,
        res=vgd.res, bounds=vgd.bounds, unit_scale=vgd.unit_scale,
        mode=vgd.mode, hits=vgd.hits,
    )


def _filter_terrain_by_boundary_margin(vgd: VoxelGridData, config: dict) -> VoxelGridData:
    """Remove terrain candidates within N coarse cells of the scene boundary.

    Infinigen terrain typically ends at scene boundaries with a vertical cliff
    wall (the world just stops there).  Excluding the outermost N coarse cells
    prevents the camera from being placed at these cliff edges where it would
    look into a void and produce black renders.

    N = config["terrain_boundary_margin"] (default 1 coarse cell = grid_resolution BU).
    """
    margin = int(config.get("terrain_boundary_margin", 1))
    if margin <= 0:
        return vgd

    filtered = []
    n_removed = 0
    for row in vgd.candidates:
        ix, iy, iz = int(row[0]), int(row[1]), int(row[2])
        if (ix >= margin and ix < vgd.nx - margin and
                iy >= margin and iy < vgd.ny - margin):
            filtered.append((ix, iy, iz))
        else:
            n_removed += 1

    filtered_arr = (np.array(sorted(filtered), dtype=np.int32)
                    if filtered else np.empty((0, 3), dtype=np.int32))
    print(f"[VoxelGrid] Terrain boundary-margin filter: margin={margin} coarse cells, "
          f"-{n_removed} boundary voxels, {len(filtered_arr)} candidates remain")
    return VoxelGridData(
        solid=vgd.solid, candidates=filtered_arr,
        nx=vgd.nx, ny=vgd.ny, nz=vgd.nz,
        res=vgd.res, bounds=vgd.bounds, unit_scale=vgd.unit_scale,
        mode=vgd.mode, hits=vgd.hits,
    )


def _filter_terrain_by_surface_normal(vgd: VoxelGridData, config: dict) -> VoxelGridData:
    """Remove terrain candidates that sit on cliff faces (no floor-facing surface).

    Strategy: fire a downward ray at each candidate's XY centre.  If every hit
    has abs(surface_normal.z) < surface_normal_z_threshold, the surface is
    nearly vertical (cliff wall) and the candidate is removed.

    Sanity check: if ray_cast returns zero hits across the first 10 candidates,
    the scene uses geometry-nodes / procedural terrain that is not visible to
    pip-bpy ray_cast.  In that case the function falls back automatically to
    _filter_terrain_by_boundary_margin (which requires no ray_cast).

    Must be called with an open bpy scene.
    """
    import bpy
    from mathutils import Vector

    if not vgd.candidates.shape[0]:
        return vgd

    threshold = float(config.get("surface_normal_z_threshold", 0.1))
    min_x, min_y = vgd.bounds[0], vgd.bounds[1]
    scene_top    = vgd.bounds[5]
    scene_floor  = vgd.bounds[4]
    down = Vector((0.0, 0.0, -1.0))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    # Sanity check: verify ray_cast actually hits something in this scene.
    # Infinigen geometry-nodes terrain is invisible to pip-bpy ray_cast.
    n_test = min(10, len(vgd.candidates))
    n_hits = 0
    for i in range(n_test):
        ix = int(vgd.candidates[i, 0]); iy = int(vgd.candidates[i, 1])
        cx = min_x + (ix + 0.5) * vgd.res
        cy = min_y + (iy + 0.5) * vgd.res
        hit, *_ = scene.ray_cast(depsgraph, Vector((cx, cy, scene_top + 10.0)), down)
        if hit:
            n_hits += 1

    if n_hits == 0:
        print("[VoxelGrid] Terrain surface-normal filter: ray_cast returned no hits "
              "(geometry-nodes terrain?) — falling back to boundary-margin filter")
        return _filter_terrain_by_boundary_margin(vgd, config)

    # ray_cast works — filter by surface normal (abs to handle inverted-normal meshes)
    def _has_non_cliff_face(wx: float, wy: float) -> bool:
        pos = Vector((wx, wy, scene_top + 10.0))
        while True:
            hit, loc, normal, _i, _o, _m = scene.ray_cast(depsgraph, pos, down)
            if not hit or loc.z < scene_floor - 0.5:
                return False
            if abs(normal.z) >= threshold:
                return True
            pos = loc + Vector((0.0, 0.0, -1e-4))

    filtered = []
    n_removed = 0
    for row in vgd.candidates:
        ix, iy, iz = int(row[0]), int(row[1]), int(row[2])
        cx = min_x + (ix + 0.5) * vgd.res
        cy = min_y + (iy + 0.5) * vgd.res
        if _has_non_cliff_face(cx, cy):
            filtered.append((ix, iy, iz))
        else:
            n_removed += 1

    filtered_arr = (np.array(sorted(filtered), dtype=np.int32)
                    if filtered else np.empty((0, 3), dtype=np.int32))
    print(f"[VoxelGrid] Terrain surface-normal filter: -{n_removed} cliff-edge voxels, "
          f"{len(filtered_arr)} candidates remain")
    return VoxelGridData(
        solid=vgd.solid, candidates=filtered_arr,
        nx=vgd.nx, ny=vgd.ny, nz=vgd.nz,
        res=vgd.res, bounds=vgd.bounds, unit_scale=vgd.unit_scale,
        mode=vgd.mode, hits=vgd.hits,
    )


def _build_terrain_candidates(config: dict) -> VoxelGridData:
    """Load terrain_snake.npz and map heightmap Z → one walkable voxel per column.

    No bpy required — reads the pre-computed terrain_snake.npz produced by
    genesis_tools.active_contour.fit_terrain_contour.

    Only columns with a valid original ray-cast hit (terrain_z_floor not NaN)
    become walkable candidates.  Columns outside the terrain bounding region
    (NaN in terrain_z_floor — e.g. grid corners outside a circular terrain disk)
    are excluded regardless of any Laplacian-interpolated heightmap value.
    """
    data = np.load(config["terrain_npz"])
    heightmap = data["heightmap"].astype(np.float64)   # (fine_nx, fine_ny)
    bounds = list(float(b) for b in data["bounds"])    # 6-element list [minx,miny,maxx,maxy,minz,maxz]
    fine_res = float(data["res"])
    unit_scale = float(data["unit_scale"]) if "unit_scale" in data else 1.0

    # terrain_z_floor distinguishes columns with real geometry from those that
    # were only Laplacian-bridged (e.g. corners outside a circular terrain disk).
    if "terrain_z_floor" in data:
        terrain_floor = data["terrain_z_floor"].astype(np.float64)
        valid_domain = ~np.isnan(terrain_floor)   # bool (fine_nx, fine_ny)
    else:
        valid_domain = None

    fine_nx, fine_ny = heightmap.shape

    # Downsample the fine TerrainSnake heightmap to the coarser voxel-grid
    # resolution.  The snake runs at terrain_snake_resolution (e.g. 2 BU) so the
    # cloth can distinguish tree-scale bumps from real terrain features; the path
    # planner only needs grid_resolution (e.g. 20 BU) voxels.
    coarse_res = config.get("grid_resolution", fine_res * unit_scale) / unit_scale
    if coarse_res > fine_res * 1.01:
        scale = coarse_res / fine_res          # e.g. 10.0
        coarse_nx = max(1, int(math.ceil(fine_nx / scale)))
        coarse_ny = max(1, int(math.ceil(fine_ny / scale)))
        coarse_hm = np.full((coarse_nx, coarse_ny), np.nan, dtype=np.float64)
        coarse_valid = np.zeros((coarse_nx, coarse_ny), dtype=bool)
        for ix_c in range(coarse_nx):
            for iy_c in range(coarse_ny):
                ix_lo = int(ix_c * scale)
                ix_hi = min(fine_nx, int(math.ceil((ix_c + 1) * scale)))
                iy_lo = int(iy_c * scale)
                iy_hi = min(fine_ny, int(math.ceil((iy_c + 1) * scale)))
                sub = heightmap[ix_lo:ix_hi, iy_lo:iy_hi]
                if valid_domain is not None:
                    mask = valid_domain[ix_lo:ix_hi, iy_lo:iy_hi] & ~np.isnan(sub)
                else:
                    mask = ~np.isnan(sub)
                vals = sub[mask]
                if len(vals) > 0:
                    coarse_hm[ix_c, iy_c] = float(np.mean(vals))
                    coarse_valid[ix_c, iy_c] = True
        heightmap = coarse_hm
        valid_domain = coarse_valid
        res = coarse_res
        nx, ny = coarse_nx, coarse_ny
        # Update XY extents in bounds to match the coarse grid
        bounds[2] = bounds[0] + coarse_nx * coarse_res
        bounds[3] = bounds[1] + coarse_ny * coarse_res
        print(f"[VoxelGrid] Downsampled heightmap {fine_nx}×{fine_ny} "
              f"({fine_res:.2f} BU) → {nx}×{ny} ({res:.2f} BU)")
    else:
        res = fine_res
        nx, ny = fine_nx, fine_ny

    bounds = tuple(bounds)
    min_z = bounds[4]
    max_z = bounds[5]
    nz = max(1, int(math.ceil((max_z - min_z) / res)))

    candidates = []
    for ix in range(nx):
        for iy in range(ny):
            if valid_domain is not None and not valid_domain[ix, iy]:
                continue
            z_val = float(heightmap[ix, iy])
            if not math.isnan(z_val):
                iz = int((z_val - min_z) / res)
                iz = max(0, min(nz - 1, iz))
                candidates.append((ix, iy, iz))

    candidates_arr = (np.array(sorted(candidates), dtype=np.int32)
                      if candidates else np.empty((0, 3), dtype=np.int32))
    print(f"[VoxelGrid] Terrain mode: {len(candidates)}/{nx*ny} columns have "
          f"walkable voxels ({nx}×{ny}×{nz} grid, res={res:.2f} BU)")
    return VoxelGridData(
        solid=np.empty((0, 3), dtype=np.int32),
        candidates=candidates_arr,
        nx=nx, ny=ny, nz=nz,
        res=res,
        bounds=bounds,
        unit_scale=unit_scale,
        mode="terrain",
        hits=None,
    )


# ---------------------------------------------------------------------------
# Camera-cell force-walkable
# ---------------------------------------------------------------------------

def _force_camera_walkable(vgd: VoxelGridData, config: dict) -> VoxelGridData:
    """Ensure the original scene camera's coarse cell is always in candidates.

    Particle and mesh filters can remove the camera cell if the Blender scene
    camera was placed inside a tree canopy or object bounding sphere.  Since
    the scene designer chose that position intentionally, we re-insert it so
    path_plan always starts from (or very near) the actual camera.

    The iz for the forced cell is read from the terrain heightmap so the
    camera height on the path is consistent with surrounding walkable cells.
    Controlled by config["force_camera_walkable"] (default True).
    """
    if not config.get("force_camera_walkable", True):
        return vgd
    terrain_npz = config.get("terrain_npz")
    if not terrain_npz:
        return vgd

    ts = np.load(terrain_npz)
    if "camera_xyz" not in ts.files:
        return vgd
    cam_xyz = ts["camera_xyz"]
    cx, cy = float(cam_xyz[0]), float(cam_xyz[1])
    cam_ix = max(0, min(vgd.nx - 1, int((cx - vgd.bounds[0]) / vgd.res)))
    cam_iy = max(0, min(vgd.ny - 1, int((cy - vgd.bounds[1]) / vgd.res)))

    if any(int(r[0]) == cam_ix and int(r[1]) == cam_iy for r in vgd.candidates):
        return vgd  # already walkable

    # Compute terrain Z for this coarse cell by averaging the fine heightmap patch
    hm        = ts["heightmap"].astype(np.float64)
    fine_res  = float(ts["res"])
    unit_scale = float(ts["unit_scale"]) if "unit_scale" in ts.files else 1.0
    scale     = (vgd.res * unit_scale) / fine_res  # fine pixels per coarse cell
    ix_lo = int(cam_ix * scale)
    ix_hi = min(hm.shape[0], int(math.ceil((cam_ix + 1) * scale)))
    iy_lo = int(cam_iy * scale)
    iy_hi = min(hm.shape[1], int(math.ceil((cam_iy + 1) * scale)))
    sub   = hm[ix_lo:ix_hi, iy_lo:iy_hi]
    valid = ~np.isnan(sub)
    if not valid.any():
        return vgd  # no terrain data — can't force

    z_val = float(np.mean(sub[valid]))
    min_z = vgd.bounds[4]
    iz    = max(0, min(vgd.nz - 1, int((z_val - min_z) / vgd.res)))

    forced = np.array([[cam_ix, cam_iy, iz]], dtype=np.int32)
    new_candidates = np.vstack([forced, vgd.candidates])
    print(f"[VoxelGrid] Camera cell ({cam_ix},{cam_iy}) was filtered out — "
          f"force-added to candidates (z={z_val:.1f} BU, iz={iz})")

    return VoxelGridData(
        solid=vgd.solid, candidates=new_candidates,
        nx=vgd.nx, ny=vgd.ny, nz=vgd.nz, res=vgd.res,
        bounds=vgd.bounds, unit_scale=vgd.unit_scale,
        mode=vgd.mode, hits=vgd.hits,
    )


# ---------------------------------------------------------------------------
# Auto-resolution terrain build
# ---------------------------------------------------------------------------

def _camera_walkable(vgd: VoxelGridData, camera_xyz) -> bool:
    """Return True if the camera's XY maps to a walkable candidate cell."""
    if camera_xyz is None or not len(vgd.candidates):
        return False
    cx, cy = float(camera_xyz[0]), float(camera_xyz[1])
    cam_ix = max(0, min(vgd.nx - 1, int((cx - vgd.bounds[0]) / vgd.res)))
    cam_iy = max(0, min(vgd.ny - 1, int((cy - vgd.bounds[1]) / vgd.res)))
    cands_xy = {(int(r[0]), int(r[1])) for r in vgd.candidates}
    return (cam_ix, cam_iy) in cands_xy


def _build_terrain_auto_resolution(blend_path: str, config: dict) -> VoxelGridData:
    """Terrain build with automatic resolution halving until camera voxel is walkable.

    Starting from config["grid_resolution_start"] (default 20.0 BU), the
    resolution is halved each iteration until:
      (a) the camera's coarse cell appears in the final walkable candidate set, OR
      (b) the next halving would produce a grid with more than
          config["max_total_voxels_xy"] cells (default 14400).

    bpy is opened exactly once regardless of how many iterations are needed.
    If config["mark_particle_instances"] is False, bpy is not opened at all.

    The chosen resolution is printed at the end; downstream steps read
    VoxelGridData.res to know the actual resolution used.
    """
    start_res = float(config.get("grid_resolution_start", 20.0))
    max_cells = int(config.get("max_total_voxels_xy", 14400))
    use_particles = config.get("mark_particle_instances", True)

    # Camera position for walkability check (from terrain_snake.npz)
    ts_data  = np.load(config["terrain_npz"])
    cam_xyz  = ts_data["camera_xyz"] if "camera_xyz" in ts_data.files else None

    # Open bpy once so particle/mesh filters can run without re-opening each iter
    if use_particles:
        import bpy as _bpy
        _bpy.ops.wm.open_mainfile(filepath=blend_path)
        print(f"[VoxelGrid] Auto-res: blend opened for particle filtering")

    current_res = start_res
    vgd: VoxelGridData | None = None

    for iteration in range(1, 32):   # 31 halvings = sub-millimetre, never reached in practice
        cfg = dict(config)
        cfg["grid_resolution"] = current_res

        vgd = _build_terrain_candidates(cfg)
        if use_particles:
            vgd = _filter_terrain_by_particles(vgd, cfg)
            vgd = _filter_terrain_by_mesh_objects(vgd, cfg)
        vgd = _filter_terrain_by_boundary_margin(vgd, cfg)

        walkable = _camera_walkable(vgd, cam_xyz)
        # Note: _force_camera_walkable is NOT called here — the auto-res loop
        # uses natural walkability to decide resolution.  It is applied once
        # after the loop exits (via build() which calls _force_camera_walkable).
        # Predict next grid size (halving res ≈ doubling cells per axis)
        next_cells = (vgd.nx * 2) * (vgd.ny * 2)

        print(f"[VoxelGrid] Auto-res iter {iteration}: "
              f"res={current_res:.2f} BU  grid {vgd.nx}×{vgd.ny} ({vgd.nx * vgd.ny} cells)  "
              f"walkable={len(vgd.candidates)}  camera_walkable={walkable}")

        if walkable:
            print(f"[VoxelGrid] Auto-res: camera walkable ✓  final res={current_res:.2f} BU")
            break

        if next_cells > max_cells:
            print(f"[VoxelGrid] Auto-res: next step {current_res/2:.2f} BU would give "
                  f"~{next_cells} cells > max_total_voxels_xy={max_cells} — "
                  f"stopping at {current_res:.2f} BU "
                  f"(camera not walkable; path_plan will route to nearest walkable cell)")
            break

        current_res /= 2.0
    else:
        print(f"[VoxelGrid] Auto-res: iteration limit reached at res={current_res:.2f} BU")

    return _force_camera_walkable(vgd, config)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(blend_path: str, config: dict) -> VoxelGridData:
    """Build VoxelGridData from a .blend file or terrain_snake.npz.

    When config["terrain_npz"] is set, the heightmap is read directly without
    bpy.  If mark_particle_instances is True (default), the blend file is then
    opened to filter candidates blocked by scatter instances.  Set
    mark_particle_instances=false to skip the particle pass and avoid opening
    the blend file entirely (legacy / test behaviour).

    grid_resolution may be set to the string "auto" to enable automatic
    resolution halving until the original scene camera's voxel is walkable.
    See _build_terrain_auto_resolution for details.
    """
    if config.get("terrain_npz"):
        if str(config.get("grid_resolution", "")).lower() == "auto":
            return _build_terrain_auto_resolution(blend_path, config)
        vgd = _build_terrain_candidates(config)
        if config.get("mark_particle_instances", True):
            import bpy
            bpy.ops.wm.open_mainfile(filepath=blend_path)
            vgd = _filter_terrain_by_particles(vgd, config)
            vgd = _filter_terrain_by_mesh_objects(vgd, config)
            # Note: _filter_terrain_by_surface_normal is NOT called here because Infinigen
            # terrain geometry (geometry-nodes/displacement base meshes) reports all face
            # normals as horizontal (nz≈0) in pip-bpy, making the ray_cast normal check
            # unreliable.  _filter_terrain_by_boundary_margin handles the same use-case
            # (removing scene-boundary cliff-edge candidates) without any ray_cast.
        vgd = _filter_terrain_by_boundary_margin(vgd, config)
        vgd = _force_camera_walkable(vgd, config)
        return vgd

    import bpy
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    unit_scale = _get_unit_scale()
    hit_collector = [] if config.get("debug_viz") else None
    snake_mesh = _load_snake_mesh(config)

    if snake_mesh is not None:
        # Snake mode: inside-AC test → raw voxels.
        # solid is empty — geometry intersection is handled in walkable step 2.
        # candidates = raw (inside AC) voxels passed to walkable.py.
        raw, nx, ny, nz, res, bounds = _build_raw_voxels_from_snake(snake_mesh, config)
        mode = "snake"
        solid_arr = np.empty((0, 3), dtype=np.int32)
        candidates = np.array(sorted(raw), dtype=np.int32) if raw else np.empty((0, 3), dtype=np.int32)
        hits_arr = None
        return VoxelGridData(
            solid=solid_arr, candidates=candidates,
            nx=nx, ny=ny, nz=nz,
            res=float(res), bounds=tuple(float(b) for b in bounds),
            unit_scale=float(unit_scale),
            mode=mode, hits=hits_arr,
        )
    elif config.get("local_area_ratio"):
        center = _find_local_center(config)
        scene_bds = _scene_bounds()
        span_xy = min(scene_bds[2]-scene_bds[0], scene_bds[3]-scene_bds[1])
        config["_local_radius_bu"] = config["local_area_ratio"] * span_xy * 0.5
        solid, nx, ny, nz, res, bounds = _build_local_voxel_grid(
            config, center, hit_collector=hit_collector)
        n_vtx = _mark_vertex_voxels(solid, nx, ny, nz, res, bounds, clip=bounds)
        print(f"[VoxelGrid] Vertex check: +{n_vtx} solid voxels")
        if config.get("mark_particle_instances", True):
            n_ptcl = _mark_particle_instance_voxels(solid, nx, ny, nz, res, bounds, clip=bounds,
                                                     margin=config.get("particle_block_margin", 1.0))
            print(f"[VoxelGrid] Particle instances: +{n_ptcl} solid voxels")
        mode = "local"
        from mathutils import Vector
        ix = max(0, min(nx-1, int((center.x-bounds[0])/res)))
        iy = max(0, min(ny-1, int((center.y-bounds[1])/res)))
        iz = max(0, min(nz-1, int((center.z-bounds[4])/res)))
        center_ijk = (ix, iy, iz)
    else:
        scene_bds = _scene_bounds()
        solid, nx, ny, nz, res, bounds = _build_global_voxel_grid(
            config, scene_bds, hit_collector=hit_collector)
        n_vtx = _mark_vertex_voxels(solid, nx, ny, nz, res, bounds)
        print(f"[VoxelGrid] Vertex check: +{n_vtx} solid voxels")
        if config.get("mark_particle_instances", True):
            n_ptcl = _mark_particle_instance_voxels(solid, nx, ny, nz, res, bounds,
                                                     margin=config.get("particle_block_margin", 1.0))
            print(f"[VoxelGrid] Particle instances: +{n_ptcl} solid voxels")
        mode = "global"
        cam = _find_local_center(config)
        ix = max(0, min(nx-1, int((cam.x-bounds[0])/res)))
        iy = max(0, min(ny-1, int((cam.y-bounds[1])/res)))
        iz = max(0, min(nz-1, int((cam.z-bounds[4])/res)))
        center_ijk = (ix, iy, iz)

    solid_arr = np.array(sorted(solid), dtype=np.int32) if solid else np.empty((0,3), dtype=np.int32)
    candidates = _flood_fill_candidates(solid, center_ijk, nx, ny, nz)
    hits_arr = np.array(hit_collector, dtype=np.float64) if hit_collector else None

    return VoxelGridData(
        solid=solid_arr, candidates=candidates,
        nx=nx, ny=ny, nz=nz,
        res=float(res), bounds=tuple(float(b) for b in bounds),
        unit_scale=float(unit_scale),
        mode=mode, hits=hits_arr,
    )


def save(data: VoxelGridData, path: str) -> None:
    arrays = dict(
        solid=data.solid, candidates=data.candidates,
        nx=np.int32(data.nx), ny=np.int32(data.ny), nz=np.int32(data.nz),
        res=np.float64(data.res),
        bounds=np.array(data.bounds, dtype=np.float64),
        unit_scale=np.float64(data.unit_scale),
        mode=np.array(data.mode),
    )
    if data.hits is not None:
        arrays["hits"] = data.hits
    np.savez_compressed(path, **arrays)
    print(f"[VoxelGrid] Saved -> {path}")


def load(path: str) -> VoxelGridData:
    npz = np.load(path)
    hits = npz["hits"] if "hits" in npz else None
    return VoxelGridData(
        solid=npz["solid"],
        candidates=npz["candidates"],
        nx=int(npz["nx"]),
        ny=int(npz["ny"]),
        nz=int(npz["nz"]),
        res=float(npz["res"]),
        bounds=tuple(npz["bounds"].tolist()),
        unit_scale=float(npz["unit_scale"]),
        mode=str(npz["mode"]),
        hits=hits,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 1: voxel grid")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    data = build(args.blend, config)
    save(data, args.output)


if __name__ == "__main__":
    _cli()
