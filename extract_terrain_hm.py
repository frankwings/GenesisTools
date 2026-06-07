"""Ray-cast terrain heightmap against OpaqueTerrain_fine only (skip clouds/vegetation)."""
import bpy, numpy as np
from mathutils import Vector
from pathlib import Path

BASE = Path("/home/kingy/Projects/Genesis/GenesisTools/results/alpine_meadow_sunrise/walkthrough_veg_sa")

pdata = np.load(str(BASE / "path.npz"))
path_pts = pdata["path_points"].astype(np.float64)
margin = 20.0
x0 = path_pts[:,0].min() - margin;  x1 = path_pts[:,0].max() + margin
y0 = path_pts[:,1].min() - margin;  y1 = path_pts[:,1].max() + margin
z_start = float(path_pts[:,2].max()) + 50.0

print(f"[TerrainHM] XY: [{x0:.1f},{x1:.1f}] x [{y0:.1f},{y1:.1f}], ray start Z={z_start:.1f}")

# Hide everything except OpaqueTerrain_fine
terrain_obj = bpy.data.objects.get("OpaqueTerrain_fine")
if terrain_obj is None:
    raise RuntimeError("OpaqueTerrain_fine not found in scene!")
print(f"[TerrainHM] Targeting: {terrain_obj.name}  verts={len(terrain_obj.data.vertices)}")

hidden = []
for obj in bpy.data.objects:
    if obj.name != terrain_obj.name and obj.hide_viewport == False:
        obj.hide_viewport = True
        hidden.append(obj)

dg = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene
down = Vector((0, 0, -1))

grid_n = 100
xs = np.linspace(x0, x1, grid_n)
ys = np.linspace(y0, y1, grid_n)
hm = np.full((grid_n, grid_n), np.nan)
hits = 0

for ix, wx in enumerate(xs):
    for iy, wy in enumerate(ys):
        origin = Vector((wx, wy, z_start))
        hit, loc, *_ = scene.ray_cast(dg, origin, down, distance=z_start + 600)
        if hit:
            hm[ix, iy] = loc.z
            hits += 1

# Restore visibility
for obj in hidden:
    obj.hide_viewport = False

print(f"[TerrainHM] Hits: {hits}/{grid_n*grid_n}  Z: [{np.nanmin(hm):.2f}, {np.nanmax(hm):.2f}]")

out = str(BASE / "terrain_raycast.npz")
np.savez_compressed(out,
    heightmap=hm.astype(np.float32),
    bounds=np.array([x0, y0, x1, y1], dtype=np.float64),
    grid_n=np.int32(grid_n))
print(f"[TerrainHM] Saved → {out}")
