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
_ALL26_NEIGHBORS = tuple(
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if (dx, dy, dz) != (0, 0, 0)
)


def _bfs_largest_component(walkable: set) -> set:
    """Return the largest 26-connected component of walkable voxels.

    26-connected includes face, edge, and corner neighbours (all dx,dy,dz ∈ {-1,0,1}).
    This connects adjacent terrain columns whose iz differs by ≤1 (gentle slope)
    while still isolating steep cliffs (iz diff ≥2 with no shared neighbour).
    """
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
            for dx, dy, dz in _ALL26_NEIGHBORS:
                nb = (cx+dx, cy+dy, cz+dz)
                if nb in remaining and nb not in component:
                    queue.append(nb)
        remaining -= component
        if len(component) > len(best):
            best = component
    return best


def _farthest_point_sample(cells: set, n: int, rng_seed: int,
                            fixed_first=None, use_xyz: bool = False) -> list:
    """Return n cells using farthest-point sampling.

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


def _held_karp_tsp(waypoints: list, fixed_first=None, use_xyz: bool = False) -> list:
    """Exact open-path TSP via Held-Karp dynamic programming.

    dp[mask][v] = min cost to visit exactly the nodes in `mask`, starting at
    node 0, ending at node v.  Open path (no return edge).
    Time O(n² · 2^n); practical up to n ≈ 20 (typically 1–5 s).

    fixed_first: waypoint placed at index 0 (tour always starts there).
    """
    n = len(waypoints)
    if n <= 3:
        return list(waypoints)

    wps = list(waypoints)
    if fixed_first is not None and fixed_first in wps:
        idx = wps.index(fixed_first)
        wps[0], wps[idx] = wps[idx], wps[0]

    # Distance matrix
    d = np.empty((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            if use_xyz:
                d[i, j] = math.sqrt((wps[i][0]-wps[j][0])**2 +
                                    (wps[i][1]-wps[j][1])**2 +
                                    (wps[i][2]-wps[j][2])**2)
            else:
                d[i, j] = math.sqrt((wps[i][0]-wps[j][0])**2 +
                                    (wps[i][1]-wps[j][1])**2)

    total_masks = 1 << n
    INF = np.float32(1e18)
    dp     = np.full((total_masks, n), INF,  dtype=np.float32)
    parent = np.full((total_masks, n), -1,   dtype=np.int16)

    dp[1, 0] = 0.0   # visited = {node 0}, at node 0, cost = 0

    # Precompute per-node bitmasks for O(1) membership test
    node_bit = np.array([1 << v for v in range(n)], dtype=np.int64)

    arange_n = np.arange(n, dtype=np.int64)

    for mask in range(1, total_masks):
        if not (mask & 1):          # tour must include node 0
            continue
        row = dp[mask]              # (n,)
        if not (row < INF).any():
            continue

        in_mask = (mask & node_bit).astype(bool)   # (n,) bool
        costs_from = np.where(in_mask, row, INF)   # (n,)

        # ext[v, u] = costs_from[v] + d[v, u]  — (n, n)
        ext = costs_from[:, np.newaxis] + d

        # Best cost / best predecessor for each u  — (n,) each
        best_costs = ext.min(axis=0)
        best_prevs = ext.argmin(axis=0).astype(np.int16)

        # Only update u's not already in mask and with finite cost
        not_in = ~in_mask
        update = not_in & (best_costs < INF)
        if not update.any():
            continue

        # new_mask for each u = mask | (1 << u)
        new_masks = (mask | node_bit)[update]          # row indices into dp
        u_idx     = arange_n[update]                   # column indices

        # Vectorised conditional update
        cur = dp[new_masks, u_idx]
        bc  = best_costs[update]
        improve = bc < cur
        if improve.any():
            rows = new_masks[improve]
            cols = u_idx[improve]
            dp    [rows, cols] = bc[improve].astype(np.float32)
            parent[rows, cols] = best_prevs[update][improve]

    full = total_masks - 1
    best_end = int(dp[full].argmin())

    # Reconstruct
    tour_idx = []
    v, mask = best_end, full
    while True:
        tour_idx.append(v)
        pv = int(parent[mask, v])
        mask ^= (1 << v)
        if pv < 0:
            break
        v = pv
    tour_idx.reverse()
    return [wps[i] for i in tour_idx]


def _bfs_path(start: tuple, goal: tuple, walkable: set) -> list:
    """BFS shortest path in walkable voxels using 26-connected movement.

    Includes face, edge, and corner neighbours so gentle slopes (adjacent terrain
    columns whose iz differs by 1) are traversable in a single step.  Steep cliffs
    (iz diff ≥2 with no shared 26-neighbour in walkable) remain disconnected.
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
        for dx, dy, dz in _ALL26_NEIGHBORS:
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
                       n_iters: int = 5) -> list:
    """BFS corridor + Laplacian smoothing + 4x upsample (requires bpy)."""
    import bpy, math
    from mathutils import Vector as _V

    min_x = bounds[0]; min_y = bounds[1]; min_z = bounds[4]
    max_z = bounds[5]
    res = config.get("_effective_grid_resolution", config["grid_resolution"])
    cam_h_bu = config.get("camera_height", 1.7) / config.get("_unit_scale", 1.0)

    # --- Terrain heightmap for Z floor clamping ----------------------------
    # When a terrain_npz is available, every smoothed and upsampled point is
    # guaranteed to have Z >= heightmap[ix, iy] + cam_h_bu.  This prevents
    # Laplacian averaging from pulling the path below the terrain surface
    # (the voxel-grid Z clamp alone is too coarse: one voxel = hundreds of BU).
    heightmap = None
    h_min_x = h_min_y = h_res = 0.0
    h_nx = h_ny = 0
    terrain_npz = config.get("terrain_npz")
    if terrain_npz:
        import numpy as _np
        _td = _np.load(terrain_npz)
        heightmap = _td["heightmap"].astype(float)   # (nx, ny) world-space Z
        _hb = _td["bounds"]
        h_min_x, h_min_y = float(_hb[0]), float(_hb[1])
        h_res = float(_td["res"])
        h_nx, h_ny = heightmap.shape

    def _terrain_floor_z(wx: float, wy: float) -> float | None:
        """Return terrain Z at world (wx, wy), or None if outside grid / NaN."""
        if heightmap is None:
            return None
        ix = max(0, min(h_nx - 1, int((wx - h_min_x) / h_res)))
        iy = max(0, min(h_ny - 1, int((wy - h_min_y) / h_res)))
        z = heightmap[ix, iy]
        return None if math.isnan(z) else float(z)

    def _clamp_above_terrain(pt: list) -> list:
        """Ensure pt[2] >= terrain surface + camera height."""
        floor_z = _terrain_floor_z(pt[0], pt[1])
        if floor_z is not None:
            pt[2] = max(pt[2], floor_z + cam_h_bu)
        return pt

    def _raycast_ground_z(wx: float, wy: float) -> float | None:
        """Shoot a ray straight down from above and return the hit Z, or None."""
        origin = _V((wx, wy, max_z + 10.0))
        depsgraph = bpy.context.evaluated_depsgraph_get()
        hit, loc, normal, *_ = bpy.context.scene.ray_cast(
            depsgraph, origin, _V((0.0, 0.0, -1.0))
        )
        return float(loc.z) if hit else None

    def _best_z(wx: float, wy: float, lin_z: float) -> list:
        """Return camera-above-ground Z using downward ray_cast, with heightmap fallback."""
        gz = _raycast_ground_z(wx, wy)
        if gz is not None:
            return [wx, wy, gz + cam_h_bu]
        return _clamp_above_terrain([wx, wy, lin_z])

    # -----------------------------------------------------------------------

    cell_path = []
    n = len(tour)
    for i in range(n - 1):
        segment = _bfs_path(tour[i], tour[i+1], walkable)
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
            sx = (points[i-1][0]+points[i][0]+points[i+1][0])/3.0
            sy = (points[i-1][1]+points[i][1]+points[i+1][1])/3.0
            sz = (points[i-1][2]+points[i][2]+points[i+1][2])/3.0
            ix = int((sx-min_x)/res); iy = int((sy-min_y)/res)
            if (ix, iy) in walkable_xy:
                # Coarse voxel-grid Z clamp (keeps path inside walkable volume).
                lo_iz, hi_iz = walkable_xy[(ix, iy)]
                sz_min = min_z + (lo_iz + 0.5) * res
                sz_max = min_z + (hi_iz + 0.5) * res
                sz = max(sz_min, min(sz, sz_max))
                candidate = _clamp_above_terrain([sx, sy, sz])
                if not _los_clear(new_pts[-1], candidate):
                    candidate = _clamp_above_terrain(list(points[i]))
                new_pts.append(candidate)
            else:
                new_pts.append(_clamp_above_terrain(list(points[i])))
        new_pts.append(points[-1])
        points = new_pts

    # --- Sub-voxel particle-blocked set -------------------------------------
    # Scatter instances (OBJECT/COLLECTION render type) are invisible to
    # ray_cast, so _los_clear cannot detect them.  Build a 2D blocked set at
    # upsampled-step resolution so each interpolated point can be deflected
    # laterally out of particle tree/rock columns before Z-snapping.
    _SCATTER_RT = {"OBJECT", "COLLECTION"}
    _pstep = res / 4.0  # matches 4× upsample step
    _ptcl_blocked: set = set()
    _ptcl_margin = config.get("particle_block_margin", 1.5)
    try:
        _dg_ptcl = bpy.context.evaluated_depsgraph_get()
        for _obj in bpy.context.scene.objects:
            if _obj.type not in ("MESH", "CURVE", "SURFACE"):
                continue
            _eval_obj = _obj.evaluated_get(_dg_ptcl)
            for _psys in _eval_obj.particle_systems:
                _sett = _psys.settings
                if _sett.render_type not in _SCATTER_RT:
                    continue
                if _sett.render_type == "OBJECT" and _sett.instance_object:
                    _inst = _sett.instance_object
                    _hsz = max(_inst.dimensions) * 0.5 if max(_inst.dimensions) > 0 else _pstep
                elif _sett.render_type == "COLLECTION" and _sett.instance_collection:
                    _dims = [d for _co in _sett.instance_collection.objects
                             for d in _co.dimensions]
                    _hsz = max(_dims) * 0.5 if _dims else _pstep
                else:
                    continue
                for _p in _psys.particles:
                    if _p.alive_state != "ALIVE":
                        continue
                    _px = float(_p.location.x); _py = float(_p.location.y)
                    _r = (_hsz * float(_p.size) if _p.size > 0 else _hsz) * _ptcl_margin
                    # Intersection test: mark every sub-voxel cell whose range
                    # overlaps [px-r, px+r] × [py-r, py+r] (same logic as
                    # _mark_particle_instance_voxels in voxel_grid.py).
                    _ix_lo = int((_px - _r - min_x) / _pstep)
                    _ix_hi = int((_px + _r - min_x) / _pstep)
                    _iy_lo = int((_py - _r - min_y) / _pstep)
                    _iy_hi = int((_py + _r - min_y) / _pstep)
                    for _ix in range(max(0, _ix_lo), _ix_hi + 1):
                        for _iy in range(max(0, _iy_lo), _iy_hi + 1):
                            _ptcl_blocked.add((_ix, _iy))
        print(f"[PathPlan] Particle sub-voxel set: {len(_ptcl_blocked)} blocked cells "
              f"at step={_pstep:.2f} BU")
    except Exception as _e:
        print(f"[PathPlan] Warning: particle sub-voxel set failed ({_e}) — skipping")

    def _deflect_particle(wx: float, wy: float) -> "tuple[float, float]":
        """Return nearest non-particle-blocked XY; original if set is empty or point is clear."""
        if not _ptcl_blocked:
            return wx, wy
        cx = int((wx - min_x) / _pstep)
        cy = int((wy - min_y) / _pstep)
        if (cx, cy) not in _ptcl_blocked:
            return wx, wy
        for r in range(1, 12):
            for ddx in range(-r, r + 1):
                for ddy in range(-r, r + 1):
                    if abs(ddx) == r or abs(ddy) == r:
                        if (cx + ddx, cy + ddy) not in _ptcl_blocked:
                            return (min_x + (cx + ddx + 0.5) * _pstep,
                                    min_y + (cy + ddy + 0.5) * _pstep)
        return wx, wy  # no clear cell within search radius — keep original

    # -----------------------------------------------------------------------

    # 4× upsample; snap every interpolated point to the actual mesh surface via
    # downward ray_cast (falls back to coarse heightmap when ray misses).
    # Each intermediate XY is also deflected laterally out of particle-blocked
    # columns (scatter instances are invisible to ray_cast / _los_clear).
    upsampled = []
    steps = 4
    for i in range(len(points)-1):
        p_start = points[i]; p_end = points[i+1]
        if _los_clear(p_start, p_end):
            for j in range(steps):
                t = j / steps
                wx = p_start[0]+t*(p_end[0]-p_start[0])
                wy = p_start[1]+t*(p_end[1]-p_start[1])
                wz = p_start[2]+t*(p_end[2]-p_start[2])
                wx, wy = _deflect_particle(wx, wy)
                upsampled.append(_best_z(wx, wy, wz))
        else:
            upsampled.append(_best_z(p_start[0], p_start[1], p_start[2]))
    upsampled.append(_best_z(points[-1][0], points[-1][1], points[-1][2]))
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

def build(vg, wk, config: dict, blend_path: str = None) -> PathData:
    """Build PathData from VoxelGridData + WalkableData.

    blend_path: optional path to the .blend file.  When provided, the scene
    is opened in bpy before path smoothing so that particle scatter instances
    (pine trees, rocks, etc.) are visible to the sub-voxel particle-blocked
    detection inside _build_smooth_path.  Without this, pip-bpy runs with an
    empty scene and particle detection always returns 0.

    bpy-dependent smoothing functions are only called if bpy is importable.
    When running under system Python (e.g. in tests), smoothing is skipped
    and raw voxel-centre positions are used.
    """
    if blend_path:
        try:
            import bpy as _bpy
            _bpy.ops.wm.open_mainfile(filepath=str(blend_path))
            print(f"[PathPlan] Opened blend for particle detection: {blend_path}")
        except Exception as _e:
            print(f"[PathPlan] Warning: could not open blend ({_e}) — particle detection unavailable")
    walkable_set = {tuple(r) for r in wk.walkable}
    if not walkable_set:
        return PathData(
            waypoints=np.empty((0,3), dtype=np.int32),
            path_points=np.empty((0,3), dtype=np.float64),
            tour=np.array([], dtype=np.int32),
            camera_height=config.get("camera_height", 1.7),
            bounds=vg.bounds,
        )

    component = _bfs_largest_component(walkable_set)
    n_wp = config.get("num_waypoints", 20)
    seed = config.get("seed", 42)

    # Force first waypoint to the exact camera voxel (ix, iy, iz) regardless
    # of whether it is in the walkable component.  ix/iy are the heightmap array
    # indices for the camera's XY; iz comes from heightmap[ix,iy] (terrain surface
    # at that column), falling back to the camera's actual Z if the column is NaN.
    # The cell is injected into component + walkable_set so FPS spreads from it
    # and BFS can route outward.  If the camera is over disconnected terrain (e.g.
    # water with no walkable 6-neighbour), _bfs_path returns [camera, next_wp] —
    # a direct jump that camera_animate interpolates as a straight approach shot.
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
                h_val = float(tdata["heightmap"][cam_ix, cam_iy])
                if not math.isnan(h_val):
                    cam_iz = max(0, min(vg.nz - 1, int((h_val - min_z_b) / vg.res)))
                else:
                    cam_iz = max(0, min(vg.nz - 1, int((float(cz) - min_z_b) / vg.res)))
                fixed_first = (cam_ix, cam_iy, cam_iz)
                if fixed_first not in component:
                    # Camera voxel was filtered out (e.g. particle-blocked).
                    # March along the camera's XY look-at direction until we reach
                    # the first walkable voxel — the path starts where the camera
                    # is already facing rather than jumping sideways.
                    lookat = (tdata["camera_lookat"]
                              if "camera_lookat" in tdata.files else None)
                    found_near = None
                    if lookat is not None:
                        ldx, ldy = float(lookat[0]), float(lookat[1])
                        mag = (ldx ** 2 + ldy ** 2) ** 0.5
                        if mag > 1e-6:
                            ldx /= mag; ldy /= mag
                            # March in both forward (+) and backward (-) directions;
                            # take whichever finds a walkable voxel first.
                            found_fwd = found_bwd = None
                            prev_fwd = prev_bwd = None
                            for step in range(1, min(vg.nx, vg.ny) * 2):
                                t = step * 0.5  # half-voxel increments
                                if found_fwd is None:
                                    cix = max(0, min(vg.nx-1, int(round(cam_ix + ldx*t))))
                                    ciy = max(0, min(vg.ny-1, int(round(cam_iy + ldy*t))))
                                    c = (cix, ciy, cam_iz)
                                    if c != prev_fwd and c in component:
                                        found_fwd = c
                                    prev_fwd = c
                                if found_bwd is None:
                                    cix = max(0, min(vg.nx-1, int(round(cam_ix - ldx*t))))
                                    ciy = max(0, min(vg.ny-1, int(round(cam_iy - ldy*t))))
                                    c = (cix, ciy, cam_iz)
                                    if c != prev_bwd and c in component:
                                        found_bwd = c
                                    prev_bwd = c
                                if found_fwd is not None and found_bwd is not None:
                                    break
                            # Prefer forward; fall back to backward.
                            found_near = found_fwd if found_fwd is not None else found_bwd
                    if found_near:
                        fixed_first = found_near
                        print(f"[PathPlan] Camera cell ({cam_ix},{cam_iy},{cam_iz}) particle-blocked "
                              f"— moved along lookat to first walkable cell {fixed_first}")
                    else:
                        component.add(fixed_first)
                        walkable_set.add(fixed_first)
                        print(f"[PathPlan] Camera cell {fixed_first} not in walkable — forced (no nearby walkable)")
                else:
                    print(f"[PathPlan] First waypoint forced to camera cell {fixed_first}")
        except Exception as exc:
            print(f"[PathPlan] Could not force first waypoint from camera: {exc}")

    waypoints_list = _farthest_point_sample(component, n_wp, seed,
                                             fixed_first=fixed_first,
                                             use_xyz=config.get("aerial", False))
    use_xyz = config.get("aerial", False)
    t0 = time.time()
    tour_list = _held_karp_tsp(waypoints_list, fixed_first=fixed_first, use_xyz=use_xyz)
    print(f"[PathPlan] Held-Karp tour: {len(tour_list)} waypoints, {time.time()-t0:.1f}s")

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
                                               n_iters=laplacian_iters)
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
            for i in range(n - 1):
                seg = _bfs_path(tour_list[i], tour_list[i+1], walkable_set)
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
                                           n_iters=n_iters)
            if not config.get("aerial"):
                path_vecs, _ = _snap_path_to_floor(path_vecs, config)
            path_vecs = _fine_adjust_path(path_vecs, config)
            path_points_arr = np.array([[p.x, p.y, p.z] for p in path_vecs], dtype=np.float64)
        except ImportError:
            # Running outside bpy: emit voxel centres along BFS corridor
            cell_path = []
            n = len(tour_list)
            for i in range(n - 1):
                seg = _bfs_path(tour_list[i], tour_list[i+1], walkable_set)
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
    parser.add_argument("--blend", required=False, default=None,
                        help="Path to .blend file (enables particle scatter detection)")
    args = parser.parse_args()
    from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import load as vg_load
    from genesis_tools.walkthrough_renderer.pipeline.walkable import load as wk_load
    vg = vg_load(args.voxel_grid)
    wk = wk_load(args.walkable)
    with open(args.config) as f:
        config = json.load(f)
    data = build(vg, wk, config, blend_path=args.blend)
    save(data, args.output)


if __name__ == "__main__":
    _cli()
