# ScenePreprocessor — Scatter Vegetation Bug & Fix

**Date**: 2026-05-07  
**File**: `genesis_tools/walkthrough_renderer/pipeline/scene_preprocessor.py`  
**Commit**: `21842e6`

---

## Symptom

Forest Paths and Coastal Road renders had **no visible vegetation** — all trees,
bushes, and ground cover were missing from every frame. The terrain surface
rendered correctly, but the scene looked completely bare.

---

## Root Cause

`ScenePreprocessor.convert_particles_to_mesh()` called
`bpy.ops.object.convert(target="MESH")` on every object with a `PARTICLE_SYSTEM`
modifier, including scatter vegetation emitters.

In Blender `--background` mode (no display context), `convert()` evaluates the
modifier stack and produces a plain static mesh — but **only the emitter surface
geometry is kept**. `OBJECT` and `COLLECTION` particle systems distribute their
instances at **render-time**, not as real mesh data. In background mode there is
no render context to materialise those instances, so `convert()` silently discards
them.

Result: the terrain plane (emitter) became a flat static mesh with zero scattered
objects on it. Every tree and bush was gone.

### Why ScenePreprocessor exists at all

Blender's depsgraph marks any object with a live `PARTICLE_SYSTEM` modifier as
geometry-dirty on every frame, even when the particles are completely static. This
forces Cycles to rebuild the BVH for that object every frame, even with
`use_persistent_data=True`. ScenePreprocessor was built to fix this by converting
particle objects to static meshes — which Cycles treats as clean between frames,
allowing the BVH to be built once and reused.

The fix was correct for **Hair** and **Emitter** particle types, which bake their
geometry cleanly. It was wrong for **OBJECT / COLLECTION** scatter types.

### Particle render types

| `render_type` | What it produces | Converts cleanly? |
|---|---|---|
| `HAIR` | Hair strand curves → mesh | ✓ Yes |
| `HALO` | Halo sprites → mesh | ✓ Yes |
| `PATH` | Path curves → mesh | ✓ Yes |
| `OBJECT` | Instances of a linked object | ✗ **No — drops instances in bg mode** |
| `COLLECTION` | Instances of a collection | ✗ **No — drops instances in bg mode** |

Scatter vegetation always uses `OBJECT` or `COLLECTION`. Converting these in
background mode produces only the bare emitter surface.

---

## Fix

Added `_obj_has_only_scatter_particles()` to classify emitters by their particle
render types. If **all** particle systems on an object use scatter render types,
the object is skipped entirely in `convert_particles_to_mesh()`.

```python
_SCATTER_RENDER_TYPES = {"OBJECT", "COLLECTION"}

def _obj_has_only_scatter_particles(obj: bpy.types.Object) -> bool:
    psys_mods = [m for m in obj.modifiers if m.type == "PARTICLE_SYSTEM"]
    if not psys_mods:
        return False
    return all(
        m.particle_system.settings.render_type in _SCATTER_RENDER_TYPES
        for m in psys_mods
    )
```

In `convert_particles_to_mesh()`, before calling `bpy.ops.object.convert()`:

```python
if _obj_has_only_scatter_particles(obj):
    self._log(f"  skip (scatter vegetation): {obj.name}")
    self._report.skipped_linked.append(f"{obj.name} [scatter]")
    continue
```

`scan()` was also updated to report scatter objects separately under
`"scatter_vegetation"` instead of `"particle_systems"`, so the log distinguishes
between objects that were fixed and objects that were intentionally left alone:

```
[ScenePreprocessor]   [scatter_vegetation] ['terrain', 'background']
[ScenePreprocessor] Preprocessing complete — nothing changed
```

Objects with **mixed** particle systems (some scatter, some Hair/Halo) are still
eligible for full conversion, because at least one system bakes cleanly and the
whole emitter is render-hostile anyway.

---

## Trade-off

Scatter vegetation objects are still marked geometry-dirty by depsgraph every
frame, so the per-frame BVH rebuild cost is not eliminated for them. The fix
accepts this cost in exchange for correct rendering. The BVH rebuild overhead is
mitigated separately by switching to the OptiX BVH backend (see
[20260507_WalkthroughRenderer_RenderOptimisations.md](20260507_WalkthroughRenderer_RenderOptimisations.md)).

To fully eliminate the BVH rebuild, `bpy.ops.object.duplicates_make_real()` would
need to be called first to materialise scatter instances as actual mesh objects,
followed by a join. This creates millions of polygons and is not practical for
large outdoor scenes.

---

## Affected Scenes

| Scene | Scatter objects | Status before fix | Status after fix |
|---|---|---|---|
| Forest Paths | `terrain`, `background` | vegetation erased | ✓ preserved |
| Coastal Road | `Terrain` | vegetation erased | ✓ preserved |
| Indoor scenes (Bedroom, AI33, etc.) | none | unaffected | unaffected |
