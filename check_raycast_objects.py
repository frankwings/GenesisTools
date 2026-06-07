"""Check which objects the terrain ray-cast is hitting."""
import bpy, numpy as np
from mathutils import Vector
from pathlib import Path
from collections import Counter

BASE = Path("/home/kingy/Projects/Genesis/GenesisTools/results/alpine_meadow_sunrise/walkthrough_veg_sa")

pdata = np.load(str(BASE / "path.npz"))
path_pts = pdata["path_points"].astype(np.float64)
z_start = float(path_pts[:,2].max()) + 50.0

scene = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()
down = Vector((0, 0, -1))

# Sample 20x20 = 400 points
xs = np.linspace(path_pts[:,0].min(), path_pts[:,0].max(), 20)
ys = np.linspace(path_pts[:,1].min(), path_pts[:,1].max(), 20)
hit_objects = Counter()

for wx in xs:
    for wy in ys:
        origin = Vector((wx, wy, z_start))
        hit, loc, nrm, idx, obj, mat = scene.ray_cast(dg, origin, down, distance=z_start+600)
        if hit:
            hit_objects[obj.name if obj else "unknown"] += 1

print("Top objects hit by downward ray-cast:")
for name, cnt in hit_objects.most_common(15):
    print(f"  {cnt:4d}x  {name}")
