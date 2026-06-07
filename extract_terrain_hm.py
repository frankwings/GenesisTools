"""Run inside Blender to ray-cast a 100x100 terrain heightmap over the path XY extent."""
import bpy, sys, math, json
import numpy as np
from mathutils import Vector
from pathlib import Path

BASE = Path("/home/kingy/Projects/Genesis/GenesisTools/results/alpine_meadow_sunrise/walkthrough_veg_sa")

# Load path bounds
pdata = np.load(str(BASE / "path.npz"))
path_pts = pdata["path_points"].astype(np.float64)
margin = 20.0
x0 = path_pts[:,0].min() - margin;  x1 = path_pts[:,0].max() + margin
y0 = path_pts[:,1].min() - margin;  y1 = path_pts[:,1].max() + margin
z_start = float(path_pts[:,2].max()) + 50.0   # cast from above

print(f"[TerrainHM] XY: [{x0:.1f},{x1:.1f}] x [{y0:.1f},{y1:.1f}], ray start Z={z_start:.1f}")

grid_n = 100
xs = np.linspace(x0, x1, grid_n)
ys = np.linspace(y0, y1, grid_n)

scene = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()
down = Vector((0, 0, -1))

hm = np.full((grid_n, grid_n), np.nan)
hits = 0
for ix, wx in enumerate(xs):
    for iy, wy in enumerate(ys):
        origin = Vector((wx, wy, z_start))
        hit, loc, *_ = scene.ray_cast(dg, origin, down, distance=z_start + 600)
        if hit:
            hm[ix, iy] = loc.z
            hits += 1

print(f"[TerrainHM] Hits: {hits}/{grid_n*grid_n}  Z: [{np.nanmin(hm):.2f}, {np.nanmax(hm):.2f}]")

out = str(BASE / "terrain_raycast.npz")
np.savez_compressed(out,
    heightmap=hm.astype(np.float32),
    bounds=np.array([x0, y0, x1, y1], dtype=np.float64),
    grid_n=np.int32(grid_n))
print(f"[TerrainHM] Saved → {out}")
