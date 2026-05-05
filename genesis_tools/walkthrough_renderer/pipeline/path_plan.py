"""Step 3: walkable voxels -> waypoints + smooth path.

Pure-Python functions (BFS, TSP, farthest-point sampling) run under any Python.
bpy-dependent functions (_build_smooth_path, _snap_path_to_floor,
_fine_adjust_path) are imported from bpy at call-time; they require the
bpy Python interpreter.

Input:  VoxelGridData + WalkableData
Output: PathData -> path.npz
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class PathData:
    waypoints: np.ndarray    # (W, 3) int32  -- waypoint grid indices
    path_points: np.ndarray  # (P, 3) float64 -- world-space path positions
    tour: np.ndarray         # (T,) int32  -- ordered indices into waypoints
    camera_height: float
    bounds: tuple            # (min_x, min_y, max_x, max_y, min_z, max_z)


# ---------------------------------------------------------------------------
# Pure-Python helpers (no bpy)
# ---------------------------------------------------------------------------

_FACE_NEIGHBORS = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
_XY_NEIGHBORS   = ((1,0),(-1,0),(0,1),(0,-1))


def _bfs_largest_component(walkable: set) -> set:
    """Return the largest 6-connected (face-adjacent) component of walkable voxels."""
    remaining = set(walkable)
    best: set = set()
    while remaining:
        start = next(iter(remaining))
        component: set = set()
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if cell in component or cell not in remaining:
                continue
            component.add(cell)
            cx, cy, cz = cell
            for dx, dy, dz in _FACE_NEIGHBORS:
                nb = (cx+dx, cy+dy, cz+dz)
                if nb in remaining and nb not in component:
                    queue.append(nb)
        remaining -= component
        if len(component) > len(best):
            best = component
    return best


def _bfs_largest_component_xy(walkable: set) -> set:
    """Terrain mode: largest XY-4-connected component, Z-agnostic.

    In terrain mode each (ix,iy) column has exactly one walkable voxel whose iz
    is determined by the terrain heightmap.  Two adjacent columns can have any iz
    difference — 3-D 6-connected BFS would disconnect them whenever their iz
    values differ.  This function treats the walkable surface as a pure 2-D XY
    graph: (ix1,iy1,iz1) and (ix2,iy2,iz2) are neighbours iff |ix1-ix2|+
    |iy1-iy2|==1, regardless of iz.
    """
    xy_to_cell = {(c[0], c[1]): c for c in walkable}
    remaining_xy = set(xy_to_cell)
    best_xy: set = set()
    while remaining_xy:
        start_xy = next(iter(remaining_xy))
        comp_xy: set = set()
        queue = deque([start_xy])
        while queue:
            xy = queue.popleft()
            if xy in comp_xy or xy not in remaining_xy:
                continue
            comp_xy.add(xy)
            ix, iy = xy
            for dx, dy in _XY_NEIGHBORS:
                nb = (ix+dx, iy+dy)
                if nb in remaining_xy and nb not in comp_xy:
                    queue.append(nb)
        remaining_xy -= comp_xy
        if len(comp_xy) > len(best_xy):
            best_xy = comp_xy
    return {xy_to_cell[xy] for xy in best_xy}


def _bfs_path_xy(start: tuple, goal: tuple, walkable: set) -> list:
    """Terrain mode: BFS path between two walkable cells using XY-only connectivity.

    Adjacent columns are neighbours regardless of their iz difference.  The
    returned list contains the actual (ix,iy,iz) cells from the walkable set —
    the Z follows the terrain surface, not a straight line through voxel space.
    If no XY path exists, returns [start, goal] (direct jump, same as _bfs_path).
    """
    xy_to_cell = {(c[0], c[1]): c for c in walkable}
    start_xy = (start[0], start[1])
    goal_xy  = (goal[0],  goal[1])
    if start_xy == goal_xy:
        return [start]
    parent: dict = {start_xy: None}
    queue = deque([start_xy])
    while queue:
        xy = queue.popleft()
        if xy == goal_xy:
            path_xy = []
            cur = xy
            while cur is not None:
                path_xy.append(cur)
                cur = parent[cur]
            path_xy.reverse()
            return [xy_to_cell.get(xy, start) for xy in path_xy]
        ix, iy = xy
        for dx, dy in _XY_NEIGHBORS:
            nb = (ix+dx, iy+dy)
            if nb in xy_to_cell and nb not in parent:
                parent[nb] = xy
                queue.append(nb)
    return [start, goal]


def _farthest_point_sample(cells: set, n: int, rng_seed: int,
                            fixed_first=None, use_xyz: bool = False) -> list:
    """Return n cells using farthest-point sampling.

    fixed_first is always used as the first element — even if not in cells
    (caller is responsible for injecting it into cells when needed for routing).

    use_xyz=False: XY distance only (default, ground-level walking).
    use_xyz=True:  XYZ distance (aerial mode, spreads waypoints in 3D).
    """
    import random
    rng = random.Random(rng_seed)
    cells_list = list(cells)
    first = fixed_first if fixed_first is not None else rng.choice(cells_list)
    if len(cells_list) <= n:
        rest = [c for c in cells_list if c != first]
        return [first] + rest
    selected = [first]
    if use_xyz:
        dist = {c: (c[0]-first[0])**2 + (c[1]-first[1])**2 + (c[2]-first[2])**2 for c in cells_list}
    else:
        dist = {c: (c[0]-first[0])**2 + (c[1]-first[1])**2 for c in cells_list}
    for _ in range(n - 1):
        farthest = max(cells_list, key=lambda c: dist[c])
        selected.append(farthest)
        for c in cells_list:
            if use_xyz:
                d = (c[0]-farthest[0])**2 + (c[1]-farthest[1])**2 + (c[2]-farthest[2])**2
            else:
                d = (c[0]-farthest[0])**2 + (c[1]-farthest[1])**2
            if d < dist[c]:
                dist[c] = d
    return selected


def _greedy_tsp_tour(waypoints: list, use_xyz: bool = False) -> list:
    """Nearest-neighbour greedy path; visits each waypoint once.

    use_xyz=False: XY distance only (default).
    use_xyz=True:  XYZ distance (aerial mode, respects altitude in ordering).
    """
    if not waypoints:
        return []
    remaining = list(waypoints)
    tour = [remaining.pop(0)]
    while remaining:
        last = tour[-1]
        if use_xyz:
            nearest = min(remaining,
                          key=lambda c: (c[0]-last[0])**2 + (c[1]-last[1])**2 + (c[2]-last[2])**2)
        else:
            nearest = min(remaining,
                          key=lambda c: (c[0]-last[0])**2 + (c[1]-last[1])**2)
        remaining.remove(nearest)
        tour.append(nearest)
    return tour


def _bfs_path(start: tuple, goal: tuple, walkable: set) -> list:
    """BFS shortest path in walkable voxels using 6-connected face-adjacent movement.

    Each step moves along exactly one axis (±X, ±Y, or ±Z) by one voxel.
    No diagonal moves — every world-space segment is axis-aligned and ≤ res BU,
    which prevents the camera path from clipping through walls or floors.
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
                path.append(c); c = parent[c]
            path.reverse()
            return path
        cx, cy, cz = cell
        for dx, dy, dz in _FACE_NEIGHBORS:
            nb = (cx+dx, cy+dy, cz+dz)
            if nb in walkable and nb not in parent:
                parent[nb] = cell; queue.append(nb)
    return [start, goal]


def _voxel_los(p0: tuple, p1: tuple, walkable: set) -> bool:
    """3D DDA line-of-sight in voxel space. True iff all intermediate voxels are walkable.

    Uses 2× step density to catch diagonal corner leakage through thin walls.
    """
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    steps = max(abs(x1-x0), abs(y1-y0), abs(z1-z0)) * 2  # 2× density
    if steps == 0:
        return p0 in walkable
    for i in range(1, steps):
        t = i / steps
        if (round(x0 + t*(x1-x0)), round(y0 + t*(y1-y0)), round(z0 + t*(z1-z0))) not in walkable:
            return False
    return True


def _smooth_path(bfs_path: list, walkable: set, max_dz: int = 2) -> list:
    """Greedy string-pull (Theta*-style) along an existing BFS path.

    Shortcuts are restricted to segments where |dZ| ≤ max_dz to prevent
    the camera from jumping through thin ceilings/floors when the voxel LOS
    check can't detect sub-voxel surfaces.

    The result always stays within the BFS corridor — it never introduces
    new directions that the BFS path didn't already traverse.
    """
    if len(bfs_path) <= 2:
        return bfs_path
    result = [bfs_path[0]]
    anchor = 0
    while anchor < len(bfs_path) - 1:
        farthest = anchor + 1
        for j in range(len(bfs_path) - 1, anchor + 1, -1):
            dz = abs(bfs_path[j][2] - bfs_path[anchor][2])
            if dz <= max_dz and _voxel_los(bfs_path[anchor], bfs_path[j], walkable):
                farthest = j
                break
        result.append(bfs_path[farthest])
        anchor = farthest
    return result


def _theta_star(start: tuple, goal: tuple, walkable: set) -> list:
    """Theta* any-angle path in voxel space (26-connected, voxel LOS shortcuts).

    Returns list of voxel cells from start to goal. Falls back to BFS if unreachable.
    """
    import heapq

    if start == goal:
        return [start]

    def h(a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

    g = {start: 0.0}
    parent = {start: start}
    open_heap = [(h(start, goal), start)]
    closed: set = set()

    while open_heap:
        _, s = heapq.heappop(open_heap)
        if s in closed:
            continue
        if s == goal:
            path = []
            cur = goal
            while True:
                path.append(cur)
                p = parent[cur]
                if p == cur:
                    break
                cur = p
            path.reverse()
            return path
        closed.add(s)

        sx, sy, sz = s
        ps = parent[s]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == dy == dz == 0:
                        continue
                    nb = (sx+dx, sy+dy, sz+dz)
                    if nb not in walkable or nb in closed:
                        continue
                    if _voxel_los(ps, nb, walkable):
                        new_g = g[ps] + h(ps, nb)
                        if new_g < g.get(nb, float('inf')):
                            g[nb] = new_g
                            parent[nb] = ps
                            heapq.heappush(open_heap, (new_g + h(nb, goal), nb))
                    else:
                        new_g = g[s] + h(s, nb)
                        if new_g < g.get(nb, float('inf')):
                            g[nb] = new_g
                            parent[nb] = s
                            heapq.heappush(open_heap, (new_g + h(nb, goal), nb))

    print(f"[PathPlan] Theta* no path {start}→{goal}, falling back to BFS")
    return _bfs_path(start, goal, walkable)


# ---------------------------------------------------------------------------
# bpy-dependent helpers (must run under bpy Python)
# ---------------------------------------------------------------------------

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
        fwd.append(loc); rem -= (loc-cur).length+step_past; cur = loc+direction*step_past
    end_pt = origin + direction*max_dist
    cur = Vector(end_pt); rev_dir = -direction; rem = max_dist; rev = []
    while rem > step_past:
        hit, loc, _n, *_ = scene.ray_cast(depsgraph, cur, rev_dir, distance=rem)
        if not hit: break
        rev.append(loc); rem -= (loc-cur).length+step_past; cur = loc+rev_dir*step_past
    all_hits = list(fwd)
    for rh in rev:
        if all((rh-fh).length >= step_past*2 for fh in all_hits):
            all_hits.append(rh)
    all_hits.sort(key=lambda h: (h-origin).dot(direction))
    yield from all_hits


def _build_smooth_path(tour: list, walkable: set, config: dict, bounds: tuple,
                       n_iters: int = 5, terrain_mode: bool = False) -> list:
    """BFS corridor + Laplacian smoothing + 4x upsample (requires bpy)."""
    import bpy
    from mathutils import Vector as _V

    min_x = bounds[0]; min_y = bounds[1]; min_z = bounds[4]
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    cam_h_bu = config.get("camera_height", 1.7) / config.get("_unit_scale", 1.0)

    _path_fn = _bfs_path_xy if terrain_mode else _bfs_path
    cell_path = []
    n = len(tour)
    for i in range(n - 1):
        segment = _path_fn(tour[i], tour[i+1], walkable)
        if i == 0:
            cell_path.extend(segment)
        else:
            cell_path.extend(segment[1:])
    if not cell_path:
        return []

    # walkable_xy: Z index range (lo, hi) per XY cell — XY reachability + Z clamping
    walkable_xy = {}
    for (ix, iy, iz) in walkable:
        if (ix, iy) not in walkable_xy:
            walkable_xy[(ix, iy)] = (iz, iz)
        else:
            lo, hi = walkable_xy[(ix, iy)]
            walkable_xy[(ix, iy)] = (min(lo, iz), max(hi, iz))

    def c2w(cell):
        # Place path at voxel centre on all three axes so it aligns with the
        # voxel spheres in the debug visualisation (primitives.py uses +0.5 everywhere).
        ix, iy, iz = cell
        return [min_x+(ix+0.5)*res, min_y+(iy+0.5)*res, min_z+(iz+0.5)*res]

    def _los_clear(p0, p1):
        origin = _V((p0[0], p0[1], p0[2]+cam_h_bu))
        target = _V((p1[0], p1[1], p1[2]+cam_h_bu))
        d = target - origin; dist = d.length
        if dist < 1e-6: return True
        d_norm = d / dist
        depsgraph = bpy.context.evaluated_depsgraph_get()
        hit_fwd, *_ = bpy.context.scene.ray_cast(depsgraph, origin, d_norm, distance=dist*0.99)
        if hit_fwd: return False
        hit_rev, *_ = bpy.context.scene.ray_cast(depsgraph, target, -d_norm, distance=dist*0.99)
        return not hit_rev

    points = [c2w(c) for c in cell_path]
    for _ in range(n_iters):
        new_pts = [points[0]]
        for i in range(1, len(points)-1):
            # Average all three axes — previously only XY was averaged and Z was
            # snapped to the floor voxel, which destroyed aerial height information
            # and caused large dZ jumps at voxel-cell boundaries.
            sx = (points[i-1][0]+points[i][0]+points[i+1][0])/3.0
            sy = (points[i-1][1]+points[i][1]+points[i+1][1])/3.0
            sz = (points[i-1][2]+points[i][2]+points[i+1][2])/3.0
            ix = int((sx-min_x)/res); iy = int((sy-min_y)/res)
            if (ix, iy) in walkable_xy:
                # Clamp Z to the walkable voxel range at this XY cell so the
                # path cannot drift above the scene ceiling or below the floor.
                lo_iz, hi_iz = walkable_xy[(ix, iy)]
                sz_min = min_z + (lo_iz + 0.5) * res
                sz_max = min_z + (hi_iz + 0.5) * res
                sz = max(sz_min, min(sz, sz_max))
                candidate = [sx, sy, sz]
                if not _los_clear(new_pts[-1], candidate):
                    candidate = points[i]
                new_pts.append(candidate)
            else:
                new_pts.append(points[i])
        new_pts.append(points[-1])
        points = new_pts

    upsampled = []
    steps = 4
    for i in range(len(points)-1):
        p_start = points[i]; p_end = points[i+1]
        if _los_clear(p_start, p_end):
            for j in range(steps):
                t = j / steps
                upsampled.append([p_start[0]+t*(p_end[0]-p_start[0]),
                                   p_start[1]+t*(p_end[1]-p_start[1]),
                                   p_start[2]+t*(p_end[2]-p_start[2])])
        else:
            upsampled.append(p_start)
    upsampled.append(points[-1])
    from mathutils import Vector
    return [Vector((p[0], p[1], p[2])) for p in upsampled]


def _snap_path_to_floor(path_points: list, config: dict):
    """Replace each path point's Z with the actual floor Z (requires bpy)."""
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    unit_scale = config.get("_unit_scale", 1.0)
    probe_height = config["camera_height"] / unit_scale
    snapped = []; n_hit = 0
    for pt in path_points:
        origin = Vector((pt.x, pt.y, pt.z+probe_height))
        hit, loc, normal, *_ = scene.ray_cast(dg, origin, Vector((0,0,-1)))
        if hit and normal.z > 0.5:
            snapped.append(Vector((pt.x, pt.y, loc.z))); n_hit += 1
        else:
            snapped.append(Vector((pt.x, pt.y, pt.z)))
    return snapped, n_hit


def _fine_adjust_path(coarse_path: list, config: dict) -> list:
    """Refine coarse path using fine-resolution local voxel patches (requires bpy)."""
    import bpy
    from mathutils import Vector
    if len(coarse_path) < 2:
        return coarse_path
    unit_scale = config.get("_unit_scale", 1.0)
    coarse_res = config.get("_effective_grid_resolution",
                            config["grid_resolution"] / unit_scale)
    fine_res = coarse_res / 4.0
    cam_h_bu = config["camera_height"] / unit_scale
    patch_radius = coarse_res * 2.5
    cam_h_voxels = max(1, int(math.ceil(cam_h_bu / fine_res)))
    fine_n = max(1, int(math.ceil(patch_radius * 2.0 / fine_res)))
    fine_nz = max(1, int(math.ceil((cam_h_bu + 2.0) / fine_res)))
    adjusted = [coarse_path[0]]
    n_nudged = 0
    t0 = time.time()
    _cached_patch_center = None
    _cached_walkable_world = None
    _cached_fine_floor_z = None
    CACHE_REUSE_DIST = patch_radius * 0.4

    def _build_fine_patch(cx, cy, floor_z):
        p_min_x = cx - patch_radius; p_min_y = cy - patch_radius
        p_min_z = floor_z - 0.5;    p_max_z = floor_z + cam_h_bu + 2.0
        solid = set(); ray_span_z = p_max_z - p_min_z + 2.0
        for ix in range(fine_n):
            x = p_min_x + (ix+0.5)*fine_res
            for iy in range(fine_n):
                y = p_min_y + (iy+0.5)*fine_res
                for loc in _cast_all_hits_bidir((x, y, p_max_z+1.0),(0,0,-1),ray_span_z):
                    fix = min(fine_n-1, max(0, int((loc.x-p_min_x)/fine_res)))
                    fiy = min(fine_n-1, max(0, int((loc.y-p_min_y)/fine_res)))
                    fiz = min(fine_nz-1, max(0, int((loc.z-p_min_z)/fine_res)))
                    solid.add((fix, fiy, fiz))
        ray_span_x = patch_radius*2.0+2.0
        for iy in range(fine_n):
            y = p_min_y + (iy+0.5)*fine_res
            for iz in range(fine_nz):
                z = p_min_z + (iz+0.5)*fine_res
                for loc in _cast_all_hits_bidir((p_min_x-1.0, y, z),(1,0,0),ray_span_x):
                    fix = min(fine_n-1, max(0, int((loc.x-p_min_x)/fine_res)))
                    fiy = min(fine_n-1, max(0, int((loc.y-p_min_y)/fine_res)))
                    fiz = min(fine_nz-1, max(0, int((loc.z-p_min_z)/fine_res)))
                    solid.add((fix, fiy, fiz))
        ray_span_y = patch_radius*2.0+2.0
        for ix in range(fine_n):
            x = p_min_x + (ix+0.5)*fine_res
            for iz in range(fine_nz):
                z = p_min_z + (iz+0.5)*fine_res
                for loc in _cast_all_hits_bidir((x, p_min_y-1.0, z),(0,1,0),ray_span_y):
                    fix = min(fine_n-1, max(0, int((loc.x-p_min_x)/fine_res)))
                    fiy = min(fine_n-1, max(0, int((loc.y-p_min_y)/fine_res)))
                    fiz = min(fine_nz-1, max(0, int((loc.z-p_min_z)/fine_res)))
                    solid.add((fix, fiy, fiz))
        walkable_fine = {}
        floor_surfaces = {(ix, iy, iz) for (ix, iy, iz) in solid
                          if (ix, iy, iz+1) not in solid}
        _sc = bpy.context.scene; _dg = bpy.context.evaluated_depsgraph_get()
        for (ix, iy, iz_floor) in floor_surfaces:
            iz_feet = iz_floor + 1
            if all((ix, iy, iz_feet+k) not in solid and iz_feet+k < fine_nz
                   for k in range(cam_h_voxels)):
                cell_x = p_min_x + (ix+0.5)*fine_res
                cell_y = p_min_y + (iy+0.5)*fine_res
                cell_floor_z = p_min_z + iz_feet*fine_res
                _o = Vector((cell_x, cell_y, cell_floor_z+0.05))
                h_up, *_ = _sc.ray_cast(_dg, _o, Vector((0,0,1)), distance=cam_h_bu-0.05)
                if not h_up:
                    _o2 = Vector((cell_x, cell_y, cell_floor_z+cam_h_bu))
                    h_dn, *_ = _sc.ray_cast(_dg, _o2, Vector((0,0,-1)), distance=cam_h_bu-0.05)
                    if not h_dn:
                        walkable_fine[(ix, iy)] = p_min_z + iz_feet*fine_res
        return walkable_fine, (p_min_x, p_min_y, p_min_z)

    def _fine_to_world(fix, fiy, patch_origin, walkable_fine):
        p_min_x, p_min_y, _ = patch_origin
        return Vector((p_min_x+(fix+0.5)*fine_res,
                        p_min_y+(fiy+0.5)*fine_res,
                        walkable_fine.get((fix, fiy), coarse_path[0].z)))

    for i in range(1, len(coarse_path)):
        cur = adjusted[-1]; target = coarse_path[i]
        origin = Vector((cur.x, cur.y, cur.z+cam_h_bu))
        target_eye = Vector((target.x, target.y, target.z+cam_h_bu))
        d = target_eye - origin; dist = d.length
        if dist < 1e-6:
            adjusted.append(target); continue
        d_norm = d / dist
        _sc = bpy.context.scene; _dg = bpy.context.evaluated_depsgraph_get()
        hit_fwd, *_ = _sc.ray_cast(_dg, origin, d_norm, distance=dist*0.99)
        hit_rev, *_ = _sc.ray_cast(_dg, target_eye, -d_norm, distance=dist*0.99)
        if not hit_fwd and not hit_rev:
            adjusted.append(target); continue
        if (_cached_patch_center is not None and
                abs(cur.x-_cached_patch_center[0]) < CACHE_REUSE_DIST and
                abs(cur.y-_cached_patch_center[1]) < CACHE_REUSE_DIST):
            walkable_fine_p = _cached_walkable_world
            patch_origin = _cached_fine_floor_z
        else:
            walkable_fine_p, patch_origin = _build_fine_patch(cur.x, cur.y, cur.z)
            _cached_patch_center = (cur.x, cur.y)
            _cached_walkable_world = walkable_fine_p
            _cached_fine_floor_z = patch_origin
        if not walkable_fine_p:
            adjusted.append(target); continue
        dx = target.x - cur.x; dy = target.y - cur.y
        dlen = math.sqrt(dx*dx + dy*dy)
        if dlen < 1e-6:
            adjusted.append(target); continue
        dx /= dlen; dy /= dlen
        best_cell = None; best_progress = -1e9
        for (fix, fiy), fz in walkable_fine_p.items():
            if fix < 0 or fix >= fine_n or fiy < 0 or fiy >= fine_n: continue
            cell_world = _fine_to_world(fix, fiy, patch_origin, walkable_fine_p)
            cell_dx = cell_world.x - cur.x; cell_dy = cell_world.y - cur.y
            progress = cell_dx*dx + cell_dy*dy
            if progress < -fine_res: continue
            cell_dist = math.sqrt(cell_dx*cell_dx + cell_dy*cell_dy)
            if cell_dist > coarse_res*2.0: continue
            c_origin = Vector((cur.x, cur.y, cur.z+cam_h_bu))
            c_target = Vector((cell_world.x, cell_world.y, cell_world.z+cam_h_bu))
            c_d = c_target - c_origin; c_dist = c_d.length
            if c_dist > 1e-6:
                c_fwd, *_ = _sc.ray_cast(_dg, c_origin, c_d/c_dist, distance=c_dist*0.99)
                if c_fwd: continue
                c_rev, *_ = _sc.ray_cast(_dg, c_target, -c_d/c_dist, distance=c_dist*0.99)
                if c_rev: continue
            lateral = abs(cell_dx*(-dy) + cell_dy*dx)
            score = progress - lateral*0.5
            if score > best_progress:
                best_progress = score; best_cell = cell_world
        if best_cell is not None:
            adjusted.append(best_cell); n_nudged += 1
        else:
            adjusted.append(target)
    elapsed = time.time() - t0
    print(f"[PathPlan] Fine adjust: {n_nudged}/{len(coarse_path)-1} nudged, {elapsed:.2f}s")
    return adjusted


def _sample_path(path_points: list, t: float):
    """Sample a point along path_points at normalised t in [0, 1]."""
    from mathutils import Vector
    if not path_points:
        return Vector((0, 0, 0))
    idx = t * (len(path_points) - 1)
    i = int(idx); frac = idx - i
    if i >= len(path_points) - 1:
        return path_points[-1]
    return path_points[i].lerp(path_points[i+1], frac)


def _travel_direction_target(cam_pos, path_points: list, t: float, ahead: float = 0.05):
    """Return a point slightly ahead along the path."""
    return _sample_path(path_points, min(1.0, t + ahead))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build(vg, wk, config: dict) -> PathData:
    """Build PathData from VoxelGridData + WalkableData.

    bpy-dependent smoothing functions are only called if bpy is importable.
    When running under system Python (e.g. in tests), smoothing is skipped
    and raw voxel-centre positions are used.
    """
    walkable_set = {tuple(r) for r in wk.walkable}
    if not walkable_set:
        return PathData(
            waypoints=np.empty((0,3), dtype=np.int32),
            path_points=np.empty((0,3), dtype=np.float64),
            tour=np.array([], dtype=np.int32),
            camera_height=config.get("camera_height", 1.7),
            bounds=vg.bounds,
        )

    terrain_mode = getattr(vg, "mode", None) == "terrain"
    component = (_bfs_largest_component_xy(walkable_set) if terrain_mode
                 else _bfs_largest_component(walkable_set))
    n_wp = config.get("num_waypoints", 20)
    seed = config.get("seed", 42)

    # Force first waypoint to the exact camera voxel, regardless of walkability.
    # Terrain mode: each column has exactly one walkable voxel whose iz comes
    # from heightmap[ix,iy]. If the camera column is NaN (e.g. over water),
    # iz falls back to the camera's actual Z converted to voxel space.
    # The camera cell is injected into component + walkable_set so that FPS
    # spreads from it and BFS can route outward from it. If BFS finds no
    # walkable neighbours (island camera over water with no adjacent land),
    # _bfs_path returns [camera_cell, next_waypoint] — a direct jump —
    # which camera_animate interpolates as a straight approach shot.
    fixed_first = None
    terrain_npz = config.get("terrain_npz")
    if terrain_npz and component:
        try:
            tdata = np.load(terrain_npz)
            if "camera_xyz" in tdata.files:
                cx, cy, cz = tdata["camera_xyz"]
                min_x_b, min_y_b, min_z_b = vg.bounds[0], vg.bounds[1], vg.bounds[4]
                cam_ix = max(0, min(vg.nx - 1, int((float(cx) - min_x_b) / vg.res)))
                cam_iy = max(0, min(vg.ny - 1, int((float(cy) - min_y_b) / vg.res)))
                # Prefer terrain-surface iz at camera XY; fall back to camera Z.
                hmap = tdata["heightmap"]
                h_val = float(hmap[cam_ix, cam_iy])
                if not math.isnan(h_val):
                    cam_iz = max(0, min(vg.nz - 1, int((h_val - min_z_b) / vg.res)))
                else:
                    cam_iz = max(0, min(vg.nz - 1, int((float(cz) - min_z_b) / vg.res)))
                fixed_first = (cam_ix, cam_iy, cam_iz)
                in_component = fixed_first in component
                if not in_component:
                    component.add(fixed_first)
                    walkable_set.add(fixed_first)
                    print(f"[PathPlan] Camera cell {fixed_first} not in walkable "
                          f"(NaN terrain) — forced as first waypoint")
                else:
                    print(f"[PathPlan] First waypoint forced to camera cell {fixed_first}")
        except Exception as exc:
            print(f"[PathPlan] Could not force first waypoint from camera: {exc}")

    waypoints_list = _farthest_point_sample(component, n_wp, seed,
                                             fixed_first=fixed_first,
                                             use_xyz=config.get("aerial", False))
    tour_list = _greedy_tsp_tour(waypoints_list, use_xyz=config.get("aerial", False))

    # Convert waypoints to array
    waypoints_arr = np.array(waypoints_list, dtype=np.int32)
    tour_arr = np.array([waypoints_list.index(t) for t in tour_list], dtype=np.int32)

    # Compute path points: try bpy smoothing, fall back to voxel centres
    res = vg.res
    min_x = vg.bounds[0]; min_y = vg.bounds[1]; min_z = vg.bounds[4]

    if config.get("path_planner") == "theta_star":
        # BFS (6-connected, no diagonal). Adjacent-voxel steps (≤ res BU) + 4× upsample
        # guarantee the world-space path never crosses a wall. Diagonal shortcuts
        # between non-adjacent walkable voxels (string-pull / Theta*) create
        # world-space segments that slice through walls even when both endpoints
        # are walkable — see v48/v49 post-mortem.
        # Optional Laplacian smoothing: set "laplacian_iters" > 0 in config (default 0).
        config["_effective_grid_resolution"] = res
        laplacian_iters = config.get("laplacian_iters", 0)
        if laplacian_iters > 0:
            try:
                import bpy
                config["_unit_scale"] = vg.unit_scale
                t0 = time.time()
                path_vecs = _build_smooth_path(tour_list, walkable_set, config, vg.bounds,
                                               n_iters=laplacian_iters,
                                               terrain_mode=terrain_mode)
                if not config.get("aerial"):
                    path_vecs, _ = _snap_path_to_floor(path_vecs, config)
                elapsed = time.time() - t0
                print(f"[PathPlan] BFS + Laplacian({laplacian_iters} iters): "
                      f"{len(path_vecs)} pts, {elapsed:.2f}s")
                path_points_arr = np.array([[p.x, p.y, p.z] for p in path_vecs],
                                           dtype=np.float64)
            except ImportError:
                laplacian_iters = 0  # fall through to pure BFS below
        if laplacian_iters == 0:
            t0 = time.time()
            cell_path = []
            n = len(tour_list)
            _path_fn = _bfs_path_xy if terrain_mode else _bfs_path
            for i in range(n - 1):
                seg = _path_fn(tour_list[i], tour_list[i+1], walkable_set)
                cell_path.extend(seg if i == 0 else seg[1:])
            elapsed = time.time() - t0
            print(f"[PathPlan] BFS (pure): {len(cell_path)} cells, {elapsed:.2f}s")
            if cell_path:
                pts = [[min_x+(c[0]+0.5)*res, min_y+(c[1]+0.5)*res, min_z+(c[2]+0.5)*res]
                       for c in cell_path]
                upsampled = []
                for i in range(len(pts) - 1):
                    p0, p1 = pts[i], pts[i+1]
                    for j in range(4):
                        t = j / 4
                        upsampled.append([p0[0]+t*(p1[0]-p0[0]),
                                          p0[1]+t*(p1[1]-p0[1]),
                                          p0[2]+t*(p1[2]-p0[2])])
                upsampled.append(pts[-1])
                path_points_arr = np.array(upsampled, dtype=np.float64)
            else:
                path_points_arr = np.empty((0, 3), dtype=np.float64)
    else:
        try:
            import bpy
            config["_effective_grid_resolution"] = res
            config["_unit_scale"] = vg.unit_scale
            n_iters = config.get("laplacian_iters", 5)
            path_vecs = _build_smooth_path(tour_list, walkable_set, config, vg.bounds,
                                           n_iters=n_iters,
                                           terrain_mode=terrain_mode)
            if not config.get("aerial"):
                path_vecs, _ = _snap_path_to_floor(path_vecs, config)
            path_vecs = _fine_adjust_path(path_vecs, config)
            path_points_arr = np.array([[p.x, p.y, p.z] for p in path_vecs], dtype=np.float64)
        except ImportError:
            # Running outside bpy: emit voxel centres along BFS corridor
            cell_path = []
            n = len(tour_list)
            _path_fn = _bfs_path_xy if terrain_mode else _bfs_path
            for i in range(n - 1):
                seg = _path_fn(tour_list[i], tour_list[i+1], walkable_set)
                cell_path.extend(seg if i == 0 else seg[1:])
            path_points_arr = np.array([
                [min_x+(c[0]+0.5)*res, min_y+(c[1]+0.5)*res, min_z+(c[2]+0.5)*res]
                for c in cell_path
            ], dtype=np.float64) if cell_path else np.empty((0, 3), dtype=np.float64)

    return PathData(
        waypoints=waypoints_arr,
        path_points=path_points_arr,
        tour=tour_arr,
        camera_height=config.get("camera_height", 1.7),
        bounds=vg.bounds,
    )


def save(data: PathData, path: str) -> None:
    np.savez_compressed(
        path,
        waypoints=data.waypoints,
        path_points=data.path_points,
        tour=data.tour,
        camera_height=np.float64(data.camera_height),
        bounds=np.array(data.bounds, dtype=np.float64),
    )
    print(f"[PathPlan] Saved -> {path}")


def load(path: str) -> PathData:
    npz = np.load(path)
    return PathData(
        waypoints=npz["waypoints"],
        path_points=npz["path_points"],
        tour=npz["tour"],
        camera_height=float(npz["camera_height"]),
        bounds=tuple(npz["bounds"].tolist()),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 3: path planning")
    parser.add_argument("--voxel-grid", required=True)
    parser.add_argument("--walkable", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import load as vg_load
    from genesis_tools.walkthrough_renderer.pipeline.walkable import load as wk_load
    vg = vg_load(args.voxel_grid)
    wk = wk_load(args.walkable)
    with open(args.config) as f:
        config = json.load(f)
    data = build(vg, wk, config)
    save(data, args.output)


if __name__ == "__main__":
    _cli()
