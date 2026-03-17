# AI33_001 Walkthrough Debug Viz — v29 to v33

**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Date range**: 2026-03-15 → 2026-03-17

---

# v33 — V2-Only Mode: Floor Check Removed (2026-03-17)

**Base**: v32 → v33 removes Standard walkable mode entirely; V2 is now the only algorithm in both Local and Global mode. Floor detection disabled (interface preserved for future use).

## Algorithm Changes

| Component | Before (v32) | After (v33) |
|-----------|-------------|-------------|
| Walkable algorithm | Standard (default) or V2 (opt-in via `walkable_algorithm=v2`) | V2 only — no opt-in needed |
| Floor detection | `_check_walkable_v2`: ray cast down + `normal.z > 0.5` | Disabled — all BFS-reachable candidates = walkable |
| Global mode walkable | `_find_walkable_voxels` (solid-voxel floor surface check) | Flood fill from camera via `_find_local_center()` |
| `_bfs_largest_component` | Used in global mode path planning | Removed — flood fill already gives reachable set |
| `candidates_v2` in debug viz | Only passed when `walkable_algorithm=v2` | Always passed — Cyan always rendered |

**Walkable definition (v33)**: A voxel is walkable if and only if it is reachable from the camera voxel by 6-face BFS through non-solid voxels. No floor distance or clearance check.

## Color Scheme (V2, now universal)

| Color | Meaning |
|-------|---------|
| 🔴 Red | Solid voxel (geometry) |
| 🟡 Yellow | Free voxel — not reachable from camera (BFS-disconnected) |
| 🔵 Blue | Candidate — BFS-reachable from camera, no floor below (future floor check placeholder) |
| 🔵 Cyan | Walkable — currently same as blue (floor check disabled) |
| 🟢 Green | Waypoint (farthest-point sampled from walkable set) |

## Result

| Metric | Value |
|--------|-------|
| Date | 2026-03-17 |
| Resolution | 1280×720 |
| Render engine | WORKBENCH |
| Frames | 720 |
| Path points | 2175 |

**Screenshots** (Blender viewport, debug viz):

![v33 1](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.1.png)
![v33 2](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.2.png)
![v33 3](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.3.png)
![v33 4](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.4.png)
![v33 5](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.5.png)
![v33 6](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.6.png)
![v33 7](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.7.png)

**GIF**:

![v33](../results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.gif)

## Files

- **GIF**: `results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v33/AI33_001_280_walkthrough.blend`
- **Frames**: `results/ai33_001_walkthrough_v33/frames/` (720 × 1280×720 PNG)

---

# v32 — Fix: Debug Viz Visible in Rendered GIF (2026-03-16)

**Base**: v31 → v32 fixes debug geometry (spheres + wireframes) not appearing in rendered frames.

## Algorithm Changes

No walkable or path planning changes. Fix only.

| Component | Before (v31) | After (v32) |
|-----------|-------------|-------------|
| DebugViz in GIF | `hide_render=True` on `DebugViz_Spheres` and `DebugViz_Wireframes` — invisible in render | `hide_render` removed from both sub-collections — spheres and wireframes appear in rendered frames |
| Viewport visibility | Visible | Visible (unchanged) |

**Root cause**: The `hide_render=True` set on the DebugViz sub-collections in v31 (added as a perf attempt) hid the debug geometry from Cycles/WORKBENCH render output, so the rendered GIF showed only the scene with no colored voxels.

## Result

| Metric | Value |
|--------|-------|
| Date | 2026-03-16 |
| Resolution | 1280×720 |
| Render engine | WORKBENCH |
| Frames | 720 |

**GIF** (debug spheres and wireframes now visible in render):

![v32](../results/ai33_001_walkthrough_v32/AI33_001_280_walkthrough.gif)

## Files

- **GIF**: `results/ai33_001_walkthrough_v32/AI33_001_280_walkthrough.gif`
- **.blend**: `results/ai33_001_walkthrough_v32/AI33_001_280_walkthrough_v32.blend`
- **Frames**: `results/ai33_001_walkthrough_v32/frames/`

---

# v31 — Dual-Group Debug Viz + Waypoint Orientation Refactor + from_pydata Perf (2026-03-15)

**Base**: v30 → v31 adds Spheres+Wireframes dual collection, refactors waypoint orientation, and replaces slow per-object mesh creation with bulk `from_pydata`.

## Algorithm Changes

### 1. Dual-Group Debug Collections

| Before (v30) | After (v31) |
|-------------|-------------|
| Single `DebugViz` collection with wireframe boxes only | `DebugViz_Spheres` + `DebugViz_Wireframes` — independently toggleable in Outliner |

Both groups created for every voxel category (solid/free/candidate/walkable/waypoint). Allows switching between sphere and wireframe view without re-running.

### 2. Waypoint Orientation

| Before (v30) | After (v31) |
|-------------|-------------|
| 32-direction angular sweep to find best facing direction | Mean of unit vectors toward all visible waypoints |

The angular sweep could miss all waypoints and return an arbitrary direction. Mean-of-unit-vectors always produces a meaningful orientation toward the centroid of visible targets.

### 3. Bulk `from_pydata` Performance

| Object | Before (v30) | After (v31) |
|--------|-------------|-------------|
| Voxel wireframes | N × `curve.splines.new()` calls (480k+ for 40k voxels) | Single `mesh.from_pydata(verts, edges, [])` |
| Voxel spheres | N × `bmesh.ops.create_uvsphere()` calls | Pre-computed icosahedron template (12v/20f), offset per cell, single `from_pydata()` |
| Hit markers | N × 3 `curve.splines.new()` calls | 6 verts + 3 edges per marker, single `from_pydata()` |

Debug viz build time: **minutes → milliseconds** for large grids.

## Result

| Metric | Value |
|--------|-------|
| Date | 2026-03-15 |
| Resolution | 1280×720 |
| Render engine | WORKBENCH |

**Screenshots** (10 viewport captures — full voxel grid inspection):

![v31 1](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough1.png)
![v31 2](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough2.png)
![v31 3](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough3.png)
![v31 4](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough4.png)
![v31 5](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough5.png)
![v31 6](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough6.png)
![v31 7](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough7.png)
![v31 8](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough8.png)
![v31 9](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough9.png)
![v31 10](../results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough10.png)

## Files

- **.blend**: `results/ai33_001_walkthrough_v31/AI33_001_280_walkthrough.blend`

---

# v30 — 5-Color V2 Debug Viz + Flood-Fill Walkable (2026-03-15)

**Base**: v29 (3-color: red/blue/green) → v30 introduces 5-color V2 debug viz with flood-fill candidate detection.

## Algorithm Changes

### 1. V2 Walkable Algorithm

| Component | Before (v29) | After (v30) |
|-----------|-------------|-------------|
| Candidate detection | Solid voxel top-surface check | `_flood_fill_free_from_camera()`: 6-face BFS from camera through non-solid voxels |
| Walkable check | Voxel-grid headroom only | `_check_walkable_v2()`: downward ray cast + `normal.z > 0.5` |
| Disconnected voxels | Not shown | Yellow — free but not reachable from camera |
| Candidates (reachable, not walkable) | Not shown | Blue |
| Walkable (reachable + floor) | Blue | Cyan |

### 2. Hit Markers

White cross markers placed at every `ray_cast` hit position during voxel grid construction — shows ground-truth solid surface positions for debugging classification accuracy.

### 3. mark_parity() Removed

X/Y ray loops no longer call `mark_parity()`. Solid voxels now only marked from actual ray hits, eliminating false solid classifications from parity-fill on open-boundary geometry.

## Known Issue: Unexpected Red

The `_unexpected_red` screenshots capture a debugging session where solid voxels (red) appeared in locations that should have been free space. Root cause was `mark_parity()` marking interior voxels solid on open-boundary meshes — fixed in this version.

## Result

| Metric | Value |
|--------|-------|
| Date | 2026-03-15 |
| Resolution | 1280×720 |

**Screenshots**:

![v30 1](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough.png)
![v30 2](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough1.png)
![v30 3](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough2.png)
![v30 4](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough3.png)

**Unexpected red investigation**:

![v30 unexpected red](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough_unexpected_red.png)
![v30 unexpected red 2](../results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough_unexpected_red1.png)

## Files

- **.blend**: `results/ai33_001_walkthrough_v30/AI33_001_280_walkthrough.blend`

---

# v29 — 3-Color Full Voxel Grid Debug: Red + Blue + Green (2026-03-15)

**Base**: v28 (walkable + waypoints + path only) → v29 adds red solid voxels, completing the full 3-color grid visualization.

## Algorithm Changes

| Color | Meaning |
|-------|---------|
| 🔴 Red | Solid voxels — contain geometry (walls, floor, furniture, ceiling) |
| 🔵 Blue | Walkable voxels — empty space, floor below, sufficient cam_h clearance |
| 🟢 Green | Waypoints — farthest-point sampled from walkable set |

**Solid voxel placement**: Red spheres placed at `vz + cam_h` (grid center Z + camera height). Not floor-snapped — solid voxels are inside geometry where ray casts are unreliable. Placed at eye level for a consistent top-down heat map of where the camera cannot walk.

## Result

| Metric | Value |
|--------|-------|
| Date | 2026-03-15 |
| Render engine | Cycles GPU |
| Samples | 32 |
| Frames | 720 |
| Solid voxels (red) | 873 |
| Walkable voxels (blue) | 145 |
| Waypoints (green) | 8 |

**GIF**:

![v29](../results/ai33_001_walkthrough_v29/walkthrough_v29.gif)

**Screenshots**:

![v29 1](../results/ai33_001_walkthrough_v29/AI33_001_280_walkthrough.png)
![v29 2](../results/ai33_001_walkthrough_v29/AI33_001_280_walkthrough1.png)

## Files

- **GIF**: `results/ai33_001_walkthrough_v29/walkthrough_v29.gif`
- **.blend**: `results/ai33_001_walkthrough_v29/AI33_001_280_walkthrough.blend`
