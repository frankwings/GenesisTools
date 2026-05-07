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
    heightmap = data["heightmap"].astype(np.float64)   # (nx, ny)
    bounds = tuple(float(b) for b in data["bounds"])   # 6-tuple
    res = float(data["res"])
    unit_scale = float(data["unit_scale"]) if "unit_scale" in data else 1.0

    # terrain_z_floor distinguishes columns with real geometry from those that
    # were only Laplacian-bridged (e.g. corners outside a circular terrain disk).
    if "terrain_z_floor" in data:
        terrain_floor = data["terrain_z_floor"].astype(np.float64)
        valid_domain = ~np.isnan(terrain_floor)
    else:
        valid_domain = None   # legacy npz without terrain_z_floor — fall back to heightmap NaN check

    nx, ny = heightmap.shape
    min_z = bounds[4]
    max_z = bounds[5]
    nz = max(1, int(math.ceil((max_z - min_z) / res)))

    candidates = []
    for ix in range(nx):
        for iy in range(ny):
            # Skip columns outside the terrain domain (no real ray-cast hit)
            if valid_domain is not None and not valid_domain[ix, iy]:
                continue
            z_val = float(heightmap[ix, iy])
            if not math.isnan(z_val):
                iz = int((z_val - min_z) / res)  # floor: voxel that contains terrain surface
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
# Public API
# ---------------------------------------------------------------------------

def build(blend_path: str, config: dict) -> VoxelGridData:
    """Build VoxelGridData from a .blend file or terrain_snake.npz.

    When config["terrain_npz"] is set, the heightmap is read directly without
    bpy.  If mark_particle_instances is True (default), the blend file is then
    opened to filter candidates blocked by scatter instances.  Set
    mark_particle_instances=false to skip the particle pass and avoid opening
    the blend file entirely (legacy / test behaviour).
    """
    if config.get("terrain_npz"):
        vgd = _build_terrain_candidates(config)
        if config.get("mark_particle_instances", True):
            import bpy
            bpy.ops.wm.open_mainfile(filepath=blend_path)
            vgd = _filter_terrain_by_particles(vgd, config)
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
