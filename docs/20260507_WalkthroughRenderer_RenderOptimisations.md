# Walkthrough Renderer — Render Optimisations

**Date:** 2026-05-07  
**Scope:** `genesis_tools/walkthrough_renderer/pipeline/`  
**GPU tested on:** NVIDIA GeForce RTX 5090 (Windows Blender 4.5, OptiX)

---

## Benchmark Results

| Scene | Before | After | Speedup |
|---|---|---|---|
| Forest Paths (terrain v1) | ~7 s/frame | ~4.5 s/frame | **1.56× (~36%)** |
| Coastal Road (standard v2) | ~5 s/frame | ~3.2 s/frame | **1.56× (~36%)** |

Both runs: Cycles 64 spp, OIDN → OptiX denoiser, 640×480, 1000 frames.

The remaining bottleneck (~4–4.5 s/frame) is per-frame BVH rebuild for scatter particle
objects — OptiX accelerates each rebuild but cannot eliminate it (depsgraph marks scatter
emitters geometry-dirty every frame unconditionally).

---

## 1. OptiX BVH + OptiX Denoiser

**File:** `pipeline/_render_frames.py`  
**Commits:** current HEAD

### Problem
Blender was inheriting the GPU device setting from user preferences. No guarantee OptiX
was active. Denoiser was hardcoded to `OPENIMAGEDENOISE` (CPU OIDN), which adds ~0.5–1 s
per frame as a PCIe roundtrip from GPU framebuffer to CPU and back.

### Fix
Track the successfully enabled backend and select the matching denoiser:

```python
active_backend = None
for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
    prefs.compute_device_type = backend
    prefs.refresh_devices()
    gpu_devices = [d for d in prefs.devices if d.type == backend]
    if gpu_devices:
        for d in prefs.devices:
            d.use = (d.type == backend)
        scene.cycles.device = "GPU"
        active_backend = backend
        break

# Denoiser: OptiX runs fully on GPU (no PCIe roundtrip)
scene.cycles.denoiser = "OPTIX" if active_backend == "OPTIX" else "OPENIMAGEDENOISE"
```

### Why OptiX BVH matters
Every frame, Blender rebuilds the BVH for scatter particle objects (depsgraph marks them
dirty unconditionally). With CUDA/CPU, each BVH construction takes ~4–6 s. With OptiX,
RT Core hardware accelerates construction to ~1–2 s. `use_persistent_data = True` is
still necessary so all *static* meshes (non-dirty) are cached and never rebuilt.

---

## 2. ScenePreprocessor — Scatter Vegetation Fix

**File:** `pipeline/scene_preprocessor.py`  
**Commit:** `21842e6`

### Problem
`bpy.ops.object.convert(target="MESH")` in Blender `--background` mode evaluates
the modifier stack but **drops** OBJECT/COLLECTION particle scatter instances — only the
bare emitter surface is kept. All scattered trees/bushes were silently erased, producing
renders with invisible vegetation.

### Root cause
Scatter particle systems distribute instances at render-time. In background mode without
a display context, `convert()` cannot materialise those instances into geometry.

### Fix
Classify particle systems by `render_type`. Skip conversion for scatter types entirely:

```python
_SCATTER_RENDER_TYPES = {"OBJECT", "COLLECTION"}

def _obj_has_only_scatter_particles(obj):
    psys_mods = [m for m in obj.modifiers if m.type == "PARTICLE_SYSTEM"]
    return bool(psys_mods) and all(
        m.particle_system.settings.render_type in _SCATTER_RENDER_TYPES
        for m in psys_mods
    )

# In convert_particles_to_mesh():
if _obj_has_only_scatter_particles(obj):
    self._log(f"  skip (scatter vegetation): {obj.name}")
    continue
```

Non-scatter types (Hair, Halo, Path, Emitter) still convert cleanly and are still
processed — only OBJECT/COLLECTION scatter is skipped.

---

## 3. Particle-Aware Walkable Voxels

**File:** `pipeline/voxel_grid.py`

### Problem
`scene.ray_cast()` only hits actual mesh objects. Scatter particle instances are
render-time — invisible to ray casting. In forest/outdoor scenes, scatter trees occupied
ground columns that the path planner treated as freely walkable, routing the camera
through tree trunks.

### Fix A — Local / Global voxel mode
New function `_mark_particle_instance_voxels()`: after ray-cast solid detection, iterates
all scatter emitters via the evaluated depsgraph, marks a bounding-box volume of voxels
solid around each particle's world-space location:

```python
for obj in bpy.context.scene.objects:
    eval_obj = obj.evaluated_get(dg)
    for psys in eval_obj.particle_systems:
        if psys.settings.render_type not in {"OBJECT", "COLLECTION"}:
            continue
        half_size = max(instance_obj.dimensions) * 0.5
        for p in psys.particles:
            if p.alive_state != "ALIVE":
                continue
            scaled = half_size * p.size
            # mark voxel box [ix_lo..ix_hi, iy_lo..iy_hi, iz_lo..iz_hi] as solid
```

Called after `_mark_vertex_voxels` in both local and global build paths. Controlled by
`mark_particle_instances` config key (default `true`).

### Fix B — Terrain mode
Terrain mode produces one walkable candidate per heightmap column with no further
filtering. New function `_filter_terrain_by_particles()`: opens the blend file (only when
`mark_particle_instances=true`), builds the particle solid set, then removes any candidate
whose camera-eye column `[iz, iz + camera_height_voxels]` intersects a scatter instance:

```python
camera_height_voxels = max(1, int(round(camera_height_bu / vgd.res)))
for ix, iy, iz in candidates:
    iz_top = min(nz-1, iz + camera_height_voxels)
    blocked = any((ix, iy, iz_col) in particle_solid
                  for iz_col in range(iz, iz_top + 1))
```

**Forest Paths benchmark:** 824 terrain candidates → 699 after particle filter
(125 columns removed, ~15%).

---

## 4. Frame Count Cap — render.py

**File:** `pipeline/render.py`

### Problem
`_render_frames.py` caps `scene.frame_end` only when `frame_end` is explicitly set in the
config. But the pipeline config uses `max_duration_seconds`, not `frame_end`. If
camera_animate was skipped (reusing a cached blend), the old blend's frame count was used
— leading to renders exceeding 1000 frames.

### Fix
Derive `frame_end` from `max_duration_seconds × fps` in `render.py` when not explicitly set:

```python
"frame_end": config.get("frame_end") or (
    int(config["max_duration_seconds"] * config.get("fps", 12))
    if config.get("max_duration_seconds") else None
),
```

With `standard_scene.json` (`max_duration_seconds=83.4`, `fps=12`): `frame_end=1000`
always enforced, regardless of what the blend file contains.

---

## 5. Combined MP4 Even-Dimension Fix

**File:** `walkthrough_renderer/combined_gif.py`

### Problem
`make_combined_mp4` used `macro_block_size=None`, disabling imageio's dimension rounding.
libx264 with `yuv420p` requires even width **and** height. Composite frames at
`output_scale=1.0` produced 917×393 (odd width) → ffmpeg broken pipe / 0-byte output.

### Fix
```python
# Before
writer = imageio.get_writer(..., macro_block_size=None)
# After
writer = imageio.get_writer(..., macro_block_size=2)
```

imageio pads to the next even dimension (917 → 918, 393 → 394) before passing to ffmpeg.

---

## Config Reference

```json
{
    "max_duration_seconds": 83.4,
    "fps": 12,
    "render_engine": "CYCLES",
    "render_samples": 64,
    "use_denoise": true,
    "mark_particle_instances": true
}
```

Set `mark_particle_instances: false` to skip the particle voxel pass (faster pipeline
startup, legacy behaviour, or scenes with no scatter vegetation).
