"""Check OpaqueTerrain_fine world location and bounding box."""
import bpy
from mathutils import Vector

obj = bpy.data.objects.get("OpaqueTerrain_fine")
if not obj:
    print("NOT FOUND"); exit()

print(f"Object location: {obj.location}")
print(f"Object scale:    {obj.scale}")
print(f"Object rotation: {obj.rotation_euler}")

# World bounding box
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
zvals = [c.z for c in corners]
xvals = [c.x for c in corners]
yvals = [c.y for c in corners]
print(f"World X: [{min(xvals):.2f}, {max(xvals):.2f}]")
print(f"World Y: [{min(yvals):.2f}, {max(yvals):.2f}]")
print(f"World Z: [{min(zvals):.2f}, {max(zvals):.2f}]")

# Also check scatter objects
for obj in bpy.data.objects:
    if obj.name.startswith("scatter:") and obj.type == "MESH":
        cs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        zs = [c.z for c in cs]
        print(f"scatter {obj.name[:40]}: Z=[{min(zs):.1f},{max(zs):.1f}]")
        break
