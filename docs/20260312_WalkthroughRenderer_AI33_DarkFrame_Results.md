# AI33_001 Walkthrough Dark Frame Fix — v1 to v17

**Date**: 2026-03-12
**Scene**: `AI33_001_280.blend` (cm-scale scene, unit_scale=0.01, 1 BU = 1 cm)
**Commits**: v14 `c7497e0`, v15 `05055e1`, v17 `5cd8916`

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
| **v17** | **640×480** | **local** | **720** | **0** | **~559s** | **360° density look-at + remove forced eye-height** | **Yes** |
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
