# AI33_001 Walkthrough Dark Frame Fix — v1 to v26

**Date**: 2026-03-12
**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Commits**: v14 `c7497e0`, v15 `05055e1`, v17 `5cd8916`, v18 `87f3094`, v19 `8c9739b`, v20 `c0918ce`, v21 `ef06c71`

## Problem

23 persistent dark frames at frames [89-96, 119-126, 216-222] — camera walking through walls into geometry, rendering black.

## Root Cause (discovered at v14)

In local mode (`local_area_ratio=0.3`), `_build_local_voxel_grid` detects the floor by casting a BVH ray downward from the camera position. The AI33_001 camera is elevated ~5m above the real floor (camera z ≈ 497 BU). The local BVH hit a mezzanine surface at z=649 BU instead of the actual floor at z=0.

Cascade of failures:
1. **Voxel grid anchored at wrong height**: Grid z-range = [649, 1149] instead of [0, 500]
2. **Walkable cells computed at mezzanine level**: 256 walkable voxels, none corresponding to floor-level geometry
3. **Z-correction shifted path to floor**: Path moved down to floor z, but XY positions still from mezzanine-level walkable cells
4. **Camera inside walls at floor level**: Those XY positions were inside walls → dark frames

**Fix**: Use `scene.ray_cast` (normal-aware, detects upward-facing floor) for floor detection instead of BVH. Pass real floor Z as `floor_z_override` to anchor voxel grid at actual floor.

## Summary Table

| Version | Resolution | Mode | Frames | Dark Frames | Render Time | Key Change | Fixed? |
|---------|-----------|------|--------|-------------|-------------|------------|--------|
| v26 | 640×480 | local | 720 | 0 | ~624s | No-loop tour (visit each waypoint once) + 8wp constrained | Yes |
| **v25** | **640×480** | **local** | **720** | **0** | **~680s** | **8 waypoints + constrained gaze (min frame 417KB)** | **Yes** |
| v24a | 640×480 | local | 720 | 0 | ~606s | Waypoint mutual-visibility orientations (force_only, 20 wp) | Yes |
| v24b | 640×480 | local | 720 | 0 | ~631s | Waypoint orientations + constrained gaze ±60° (20 wp) | Yes |
| v23 | 640×480 | local | 720 | 0 | ~608s | Blended raw+contrast scoring, infinite rays, short-arc SLERP | Yes |
| v22 | 640×480 | local | 720 | 0 | ~552s | Void punishment + EMA gaze smoothing (anti-ping-pong) | Yes |
| v21 | 640×480 | local | 720 | 0 | ~593s | Three-feature gaze (depth CV + normal entropy + edge density) + context contrast | Yes |
| v20 | 640×480 | local | 720 | 0 | ~598s | Remove custom BVH → bidirectional scene.ray_cast | Yes |
| v19 | 640×480 | local | 720 | 0 | ~594s | Normal entropy gaze + slower rotation | Yes |
| v18 | 640×480 | local | 720 | 0 | ~626s | Direction cooldown + forced forward after gaze | Yes |
| v17 | 640×480 | local | 720 | 0 | ~559s | 360° density look-at + remove forced eye-height | Yes |
| v16 | 640×480 | local | 720 | 0 | 616s | Fine adjustment triggered (0 nudges needed) | Yes |
| v15 | 640×480 | global | 720 | 0 | 566s | Fine path adjustment added (not triggered) | Yes |
| **v14** | **640×480** | **local** | **240** | **0** | **~570s** | **Floor anchor override** | **Yes** |
| v13 | 640×480 | local | 240 | 23 | ~560s | Parity fill wall interiors | No |
| v12 | 640×480 | local | 240 | 23 | ~560s | Horizontal BVH wall check | No |
| v11 | 640×480 | local | 240 | 23 | ~560s | Bidirectional LOS | No |
| v10 | 640×480 | local | 240 | 23 | ~560s | render_width/height API | No |
| v9 | 1280×720 | local | 240 | 23 | ~700s | Reverted v8 | No |
| v8 | 1280×720 | local | 240 | Partial | ~700s | Different seed/path (accidental) | Partial |
| v7 | 1280×720 | local | 240 | 23 | ~700s | Path snapping | No |
| v6 | 1280×720 | local | 240 | 23 | ~700s | Path constraint tweaks | No |
| v5 | 1280×720 | local | 240 | 23 | ~700s | Walkable detection tweaks | No |
| v4 | 1280×720 | local | 240 | 23 | ~700s | clip_start = 1mm | No |
| v3 | 1280×720 | local | 240 | 23 | ~700s | Path smoothing tweaks | No |
| v2 | 1280×720 | local | 240 | 23 | ~700s | Path planning tweaks | No |
| v1 | 1280×720 | local | 240 | 23 | ~700s | Baseline | No |

## Version History (newest first)

### v26 — No-Loop Tour (Visit Each Waypoint Once)
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: TBD
- **Changes**:
  1. **Removed tour loop closure**: `_greedy_tsp_tour()` no longer appends `tour[0]` at the end. Camera visits each of the 8 farthest-point waypoints exactly once without returning to start.
  2. **Path continuity**: BFS still connects consecutive waypoints, so the path is smooth. The final waypoint is the last destination — no jump back to origin.
  3. **Same constrained gaze as v25**: Three-feature gaze restricted to ±60° of lerped waypoint base direction.
- **Motivation**: User observed a "jump" in v25 where the camera teleported between distant waypoints due to loop closure. With only 8 waypoints, the greedy TSP tour's return segment often connected distant endpoints, causing a discontinuous path.
- **Dark frames**: 0
- **GIF**: TBD

---

### v25 — 8 Waypoints + Constrained Gaze
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~680s (render ~676s)
- **Changes**:
  1. **Reduced waypoints from 20 → 8**: Fewer farthest-point samples = longer path segments between waypoints. Each waypoint covers a larger area of the room, leading to more varied orientations.
  2. **Constrained mode** (same as v24b): Three-feature gaze restricted to ±60° of lerped base direction.
  3. **Path points**: 322 (vs 418 with 20 waypoints) — shorter, more focused path.
- **Min frame size**: **417KB** — best so far (v24b: 288KB, v24a: 301KB, v23: 207KB). Indicates significantly less wall staring.
- **Dark frames**: **0**
- **GIF**: ![v25](../results/ai33_001_walkthrough_v25/AI33_001_280_walkthrough.gif)

---

### v24a — Waypoint Mutual-Visibility Orientations (force_only)
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~606s (render ~602s)
- **Changes**:
  1. **Waypoint orientation system**: After farthest-point sampling 20 waypoints, compute mutual visibility (ray_cast between all pairs at eye height). For each waypoint, sample 32 azimuth directions and pick the one where the ±90° cone contains the most visible waypoints. This naturally points toward open room space, not walls.
  2. **Orientation schedule**: Map each waypoint to its closest path_point index. Build a sorted (path_fraction, direction) schedule. At any frame, lerp the two surrounding waypoint orientations → smooth base direction along the entire path.
  3. **force_only mode**: When no active three-feature gaze target, camera follows the lerped waypoint base direction. Three-feature gaze can still override with interesting local targets (free gaze between waypoints).
- **Min frame size**: 300KB (vs 207KB in v23) — less wall content per frame
- **Dark frames**: **0**
- **GIF**: ![v24a](../results/ai33_001_walkthrough_v24a/AI33_001_280_walkthrough.gif)

### v24b — Waypoint Orientations + Constrained Gaze
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~631s (render ~627s)
- **Changes**:
  - Same waypoint orientation system as v24a
  - **constrained mode**: Three-feature gaze targets must fall within ±60° (cos>0.5) of the lerped base direction. Targets outside the cone are blocked. When no gaze target found, camera follows the base direction.
- **Min frame size**: 288KB
- **Dark frames**: **0**
- **GIF**: ![v24b](../results/ai33_001_walkthrough_v24b/AI33_001_280_walkthrough.gif)

---

### v23 — Blended Scoring + Infinite Rays + Short-Arc SLERP
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~608s (render ~605s, camera anim 0.6s)
- **Changes**:
  1. **Blended scoring** (`0.6 × raw_score + 0.4 × contrast`): Pure context contrast rewarded boundaries (wall→object edge) not the objects themselves. A table surrounded by furniture had high raw score but zero contrast — walls won. Now raw score (absolute interest) dominates, with contrast as a saliency bonus.
  2. **Infinite ray range**: Removed `distance=look_range` (15m cap) from `scene.ray_cast`. Rays now reach all geometry regardless of distance, so distant objects are properly scored.
  3. **Actual hit depth for gaze target**: Target point is at the average hit depth of the winning block, not an arbitrary `look_range × 0.6`. Camera looks AT the object, not past or short of it.
  4. **Short-arc SLERP**: Added `dot(prev, target) < 0 → negate` check before SLERP. Ensures rotation always takes the shorter path (<180°), preventing unnecessary full turns.
- **v22 problems fixed**:
  - Wall staring: blended scoring prioritises high-complexity objects (tables, computers) over wall boundaries
  - Ray range: all objects visible regardless of distance
  - >180° rotation: short-arc SLERP eliminates unnecessary spins
- **Dark frames**: **0**
- **GIF**: ![v23](../results/ai33_001_walkthrough_v23/AI33_001_280_walkthrough.gif)

---

### v22 — Void Punishment + EMA Gaze Smoothing
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~552s (render ~548s, camera anim 0.6s)
- **Changes**:
  1. **Void punishment**: Tracks hit rate per equirectangular block (hits / checked cells). Applies penalty `0.3 × void_rate` — blocks where many rays miss (windows, gaps) get their score actively reduced, potentially below zero. Indoor cameras now avoid staring through openings.
  2. **EMA gaze smoothing** (`alpha=0.4`): When a new gaze direction is selected, it's blended with the previous smoothed direction via `lerp(prev, new, 0.4)`. Prevents ping-pong head turning when two directions score similarly — the EMA settles toward whichever direction has more consistent support across evaluations.
  3. **Wall-floor boundaries**: Normal entropy already scores LOW for 2-cluster junctions (~0.2 normalized for wall+floor = 1 bit / log2(N)). Void punishment further suppresses wall areas near windows/gaps. No explicit wall detection needed.
- **v21 problems fixed**:
  - White wall staring: void punishment penalises directions with ray misses near wall openings
  - Ping-pong turning: EMA dampens alternating direction selections
- **Dark frames**: **0**
- **GIF**: ![v22](../results/ai33_001_walkthrough_v22/AI33_001_280_walkthrough.gif)

---

### v21 — Three-Feature Gaze with Context Contrast
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~593s (render ~584s)
- **Commits**: `ef06c71`
- **Changes**:
  1. **Equirectangular grid**: replaced Fibonacci sphere (64 rays) with 32×16 equirectangular grid (512 rays). Natural 4-connected adjacency enables edge detection without Delaunay triangulation.
  2. **Three features** (no color, no object name — both unreliable):
     - **Depth CV** (w=0.3): `std(depths) / mean(depths)` — captures spatial layering without the floor/horizon false-positive of raw depth variance.
     - **Normal entropy** (w=0.4): Shannon entropy of quantised normals — geometric complexity.
     - **Edge density** (w=0.3): fraction of adjacent ray pairs where normals differ by >45° — silhouette/contour detection.
  3. **Context contrast**: each block's score minus mean of 8 neighbours. Camera looks at the locally most distinctive direction (saliency), not just the globally highest score.
  4. **512 rays ≈ 25ms** per evaluation (every 2s) — negligible overhead.
- **Why this over alternatives**:
  - Color entropy: `diffuse_color` unreliable with texture maps
  - Object count: fails when scene is one joined mesh
  - Raw depth variance: inflated by floor/horizon gradients
  - Semantic weight from obj.name: fragile naming conventions
- **Dark frames**: **0**
- **GIF**: ![v21](../results/ai33_001_walkthrough_v21/AI33_001_280_walkthrough.gif)

---

### v20 — Remove Custom BVH → Bidirectional scene.ray_cast
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~598s (render ~589s)
- **Commits**: `c0918ce`
- **Changes**:
  1. **Deleted custom BVHTree entirely** — removed `_build_bvh_from_objects`, `_filter_nearby_objects`, `_cast_all_hits_bvh`, `_collect_hits_bvh` (~150 lines, net -106 lines).
  2. **All ray casting now uses bidirectional `scene.ray_cast`** (forward + reverse). Blender's internal BVH is built during depsgraph eval at zero cost. Reverse rays catch back-faces that single-direction `scene.ray_cast` misses.
  3. **Why cheaper**: custom BVH cost ~1.2s to build from extracted mesh data. With ~8,400 rays total, bidirectional `scene.ray_cast` (0.05ms/ray × 2) = 0.84s vs BVH build (1.2s) + BVH rays (0.02ms × 8,400 = 0.17s) = 1.37s.
  4. **Additional benefit**: `scene.ray_cast` includes particles and GN instances automatically (custom BVH required manual extraction).
- **Dark frames**: **0**
- **GIF**: ![v20](../results/ai33_001_walkthrough_v20/AI33_001_280_walkthrough.gif)

---

### v19 — Normal Entropy Gaze + Slower Rotation
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~594s (render ~584s)
- **Commits**: `8c9739b`
- **Changes**:
  1. **Normal entropy scoring**: replaced object-density gaze with surface-normal Shannon entropy. 64 Fibonacci sphere rays → quantize hit normals to 8³ bins → entropy per 45° cone. Flat wall (uniform normals) → entropy ≈ 0 → skip. Furniture cluster (diverse normals) → high entropy → gaze.
  2. **Entropy-scaled gaze duration**: low entropy → 1s glance, high entropy → 5s gaze. More complex geometry gets longer attention.
  3. **Slower rotation**: `rotation_smooth_seconds` 2.0 → 3.5 (tau for SLERP exponential smoothing). Head turns are more natural and less jerky.
  4. **LD_LIBRARY_PATH fix**: `__init__.py` now injects `/tmp/deb_extract/usr/lib/x86_64-linux-gnu` into subprocess env so Blender finds libSM.so.6 without parent shell setup.
- **Why normal entropy over alternatives**:
  - Color entropy: `diffuse_color` unreliable with texture maps (returns white)
  - Object count: fails when scene is one joined mesh
  - Depth variance: inflated by floor/horizon gradients (half near, half far ≠ interesting)
  - Normal entropy: unit-free, robust to all above cases, captures geometric complexity
- **Dark frames**: **0**
- **GIF**: ![v19](../results/ai33_001_walkthrough_v19/AI33_001_280_walkthrough.gif)

---

### v18 — Direction Cooldown + Forced Forward
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~626s (render ~616s)
- **Commits**: `87f3094`
- **Changes**:
  1. **Direction cooldown (A)**: after gaze ends, block any new gaze within 37° of the previous direction for 6s. Prevents re-locking onto the same spot.
  2. **Forced forward (C)**: after each gaze ends, force 2s of forward look before re-evaluating density. Camera looks where it's going between gazes.
  3. **Bug fix**: `glance_range` was capped at 5 BU = 5cm in cm-scale. Fixed to `look_range / unit_scale` (15m → 1500 BU).
  4. **Bug fix**: forward look was `floor_ahead` (floor-level point below eye) → always looked down. Fixed to `cam_pos + (floor_ahead - path_pt)` — looks in path direction from eye height.
  5. **Bug fix**: density always uses `scene.ray_cast(depsgraph)` — BVH triangle index can't identify objects.
  6. **Speed**: `walk_speed_mps` default raised 1.2 → 2.5 m/s.
- **Gaze cycle**: gaze 3s → forced forward 2s → direction cooldown 6s → new gaze
- **Dark frames**: **0**
- **GIF**: ![v18](../results/ai33_001_walkthrough_v18/AI33_001_280_walkthrough.gif)

---

### v17 — 360° Density Look-At + Natural Tilt
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total ~559s (render ~549s)
- **Commits**: `5cd8916`, `92e8019`
- **Changes**:
  1. **Remove forced eye-height offset**: Forward look was `floor_ahead + Vector((0,0,cam_h))` — always horizontal. Now `floor_ahead` only — camera tilts naturally with terrain/stairs.
  2. **360° density gaze**: Replace keyword/volume-filtered `interesting_objects` scan with `_find_density_look_target()`. Every ~2s, casts 64 Fibonacci-sphere rays from camera position, scores each direction by number of distinct objects within a 45° cone, gazes toward highest-density direction. No object metadata required.
- **Walkable voxels**: 145 (solid: 874) — same floor-level grid as v16
- **Dark frames**: **0**
- **GIF**: ![v17](../results/ai33_001_walkthrough_v17/AI33_001_280_walkthrough.gif)

---

### v16 — Fine Adjustment Triggered
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 720
- **Timing**: total 616s | render 613s | BVH build 1.3s | voxel 0.0s | path 0.4s | **fine_adjust 0.0s**
- **Changes**: Same code as v15, but run in local mode so `_fine_adjust_path` is triggered
- **Fine adjustment result**: 0 points nudged — coarse path already clean after floor anchor fix; fine adjustment is a safety net that activates only when coarse path hits a wall
- **Walkable voxels**: 145 (solid: 874) — correctly detected at floor level
- **Dark frames**: **0** (previously dark frames: 317KB-632KB)
- **GIF**: ![v16](../results/ai33_001_walkthrough_v16/AI33_001_280_walkthrough.gif)

---

### v15 — Fine Path Adjustment Added (global mode)
- **Resolution**: 640×480 | **Mode**: global (no `local_area_ratio`) | **Frames**: 720
- **Timing**: total 566s | render 562s | voxel 2.4s | path 0.1s | fine_adjust N/A
- **Changes**: Added `_fine_adjust_path()` — Level 2 fine-resolution voxel patches during path execution. Fine adjustment only activates in local mode (needs BVH); ran in global mode so not triggered.
- **Walkable voxels**: 4135 (solid: 18481) — full scene coverage
- **Dark frames**: **0**
- **Note**: v15 looks very different from v14 — global mode covers full scene (4135 walkable cells, longer path) vs local mode's 7m radius (231 cells). Frame count difference (720 vs 240) is from longer auto-calculated duration.
- **GIF**: ![v15](../results/ai33_001_walkthrough_v15/AI33_001_280_walkthrough.gif)

---

### v14 — ROOT FIX (floor anchor)
- **Resolution**: 640×480 | **Mode**: local (`local_area_ratio=0.3`) | **Frames**: 240
- **Timing**: total ~570s | render ~560s | BVH build 1.3s | voxel 0.0s | path 0.5s
- **Changes**: Floor anchor fix — pass `prelim_floor_hit.z` from `scene.ray_cast` to `_build_local_voxel_grid` via `floor_z_override`. Also: bidirectional LOS, horizontal BVH check, parity fill, particle/GN instances in BVH.
- **Debug confirmed**:
  - Before: grid z=[649.3, 1149.8], solid=256, walkable=256
  - After: grid z=[-0.5, 500.0], solid=1033, walkable=231
- **Dark frames**: **0** (all 23 fixed, previously-dark frames now 232KB-480KB)
- **GIF**: ![v14](../results/ai33_001_walkthrough_v14/AI33_001_280_walkthrough.gif)

---

### v13
- **Resolution**: 640×480 | **Mode**: local | **Frames**: 240
- **Timing**: ~560s total
- **Changes**: Parity fill — X/Y ray hit pairs mark wall interior voxels solid
- **Dark frames**: 23 — grid still at wrong Z (z=[649, 1149]), parity fill marked wrong voxels
- **Dark frame size**: ~9.6KB (black)
- **GIF**: ![v13](../results/ai33_001_walkthrough_v13/AI33_001_280_walkthrough.gif)

---

### v12
- **Resolution**: 640×480 | **Mode**: local | **Frames**: 240
- **Timing**: ~560s total
- **Changes**: Horizontal BVH check — 4-direction rays at eye height reject cells inside thin walls
- **Dark frames**: 23 — 0 cells rejected (grid floating at mezzanine, walls not in BVH at that height)
- **Dark frame size**: ~9.6KB (black)
- **GIF**: ![v12](../results/ai33_001_walkthrough_v12/AI33_001_280_walkthrough.gif)

---

### v11
- **Resolution**: 640×480 | **Mode**: local | **Frames**: 240
- **Timing**: ~560s total
- **Changes**: Bidirectional LOS — reverse `scene.ray_cast` in `_los_clear()` catches back-facing wall normals
- **Dark frames**: 23 — LOS affects path smoothing only, not walkable detection
- **Dark frame size**: ~9.6KB (black)
- **GIF**: ![v11](../results/ai33_001_walkthrough_v11/AI33_001_280_walkthrough.gif)

---

### v10
- **Resolution**: 640×480 | **Mode**: local | **Frames**: 240
- **Timing**: ~560s total
- **Changes**: Added `render_width` and `render_height` to public API
- **Dark frames**: 23 — smaller resolution, same bug
- **Dark frame size**: ~9.6KB (black at 640×480)
- **GIF**: ![v10](../results/ai33_001_walkthrough_v10/AI33_001_280_walkthrough.gif)

---

### v9
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Reverted v8 experiment
- **Dark frames**: 23
- **Dark frame size**: ~30KB (black)
- **GIF**: ![v9](../results/ai33_001_walkthrough_v9/AI33_001_280_walkthrough.gif)

---

### v8
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Different path seed / walkable detection experiment
- **Dark frames**: Partial — some frames lit (868KB) by chance (path avoided those walls), underlying bug not fixed
- **GIF**: ![v8](../results/ai33_001_walkthrough_v8/AI33_001_280_walkthrough.gif)

---

### v7
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Additional path snapping
- **Dark frames**: 23 | **Dark frame size**: ~30KB
- **GIF**: ![v7](../results/ai33_001_walkthrough_v7/AI33_001_280_walkthrough.gif)

---

### v6
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Path constraint improvements
- **Dark frames**: 23 | **Dark frame size**: ~30KB
- **GIF**: ![v6](../results/ai33_001_walkthrough_v6/AI33_001_280_walkthrough.gif)

---

### v5
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Walkable voxel detection adjustments
- **Dark frames**: 23 | **Dark frame size**: ~30KB
- **GIF**: ![v5](../results/ai33_001_walkthrough_v5/AI33_001_280_walkthrough.gif)

---

### v4
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: clip_start = 1mm (eliminate near-clip wall artifacts)
- **Dark frames**: 23 | **Dark frame size**: ~30KB
- **GIF**: ![v4](../results/ai33_001_walkthrough_v4/AI33_001_280_walkthrough.gif)

---

### v3
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Path smoothing adjustments
- **Dark frames**: 23 | **Dark frame size**: ~31KB
- **GIF**: ![v3](../results/ai33_001_walkthrough_v3/AI33_001_280_walkthrough.gif)

---

### v2
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Minor path planning adjustments
- **Dark frames**: 23 | **Dark frame size**: ~31KB
- **GIF**: ![v2](../results/ai33_001_walkthrough_v2/AI33_001_280_walkthrough.gif)

---

### v1 — Baseline
- **Resolution**: 1280×720 | **Mode**: local | **Frames**: 240
- **Timing**: ~700s total
- **Changes**: Initial walkthrough render
- **Dark frames**: 23 (frames 89-96, 119-126, 216-222) | **Dark frame size**: ~30KB
- **GIF**: ![v1](../results/ai33_001_walkthrough/AI33_001_280_walkthrough.gif)

---

## Architecture: Two-Level Coarse-to-Fine Voxelisation

```
Level 1: Coarse Grid (res ≈ 0.4m)
├── Path planning: BFS + farthest-point sampling + TSP + Laplacian smooth + 4× upsample
└── Output: coarse_path[]

Level 2: Fine Local Patches (res ≈ 0.1m)  ← added v15
├── Per coarse step: BVH ray → blocked?
├── If blocked: build fine patch (5×5 coarse voxels, tri-axial rays)
├── Find nearest fine-walkable cell with forward progress
├── Patch caching (reuse within 40% of patch radius)
└── Output: adjusted_path[]
```

## Files Modified

- `genesis_tools/walkthrough_renderer/__init__.py` — render_width/render_height params
- `genesis_tools/walkthrough_renderer/render_walkthrough.py` — all fixes + fine adjustment
