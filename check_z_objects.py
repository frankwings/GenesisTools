"""Find all objects with world Z overlapping 110-125 BU."""
import bpy
from mathutils import Vector

target_z_lo, target_z_hi = 100.0, 130.0
found = []
for obj in bpy.data.objects:
    if obj.type not in ("MESH", "EMPTY"):
        continue
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    zs = [c.z for c in corners]
    if max(zs) >= target_z_lo and min(zs) <= target_z_hi:
        found.append((obj.name, obj.type, min(zs), max(zs)))

found.sort(key=lambda x: x[2])
print(f"Objects with world Z overlapping [{target_z_lo}, {target_z_hi}]:")
for name, typ, z0, z1 in found[:30]:
    print(f"  [{z0:7.2f}, {z1:7.2f}]  {typ:6}  {name}")
print(f"Total: {len(found)}")
