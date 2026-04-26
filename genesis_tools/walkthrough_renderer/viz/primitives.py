"""Shared Blender geometry builders for debug visualization.

All functions operate on the currently-open bpy scene.
All functions require bpy Python.
"""
from __future__ import annotations

import math

_DEBUG_COL = None
_SPHERES_COL = None
_WIREFRAMES_COL = None
_EDGE_TUBE_GROUP = None
_ICO_VERTS = None
_ICO_FACES = None


def _debug_collection():
    """Return (creating if needed) the parent 'DebugViz' collection."""
    global _DEBUG_COL, _SPHERES_COL, _WIREFRAMES_COL
    import bpy
    if _DEBUG_COL is not None:
        return _DEBUG_COL
    parent = bpy.data.collections.new("DebugViz")
    bpy.context.scene.collection.children.link(parent)
    spheres = bpy.data.collections.new("DebugViz_Spheres")
    wires   = bpy.data.collections.new("DebugViz_Wireframes")
    parent.children.link(spheres)
    parent.children.link(wires)
    _DEBUG_COL = parent
    _SPHERES_COL = spheres
    _WIREFRAMES_COL = wires
    return _DEBUG_COL


def _spheres_col():
    _debug_collection()
    return _SPHERES_COL


def _wireframes_col():
    _debug_collection()
    return _WIREFRAMES_COL


def reset_collections():
    """Reset module-level collection caches (call before each visualize() run)."""
    global _DEBUG_COL, _SPHERES_COL, _WIREFRAMES_COL, _EDGE_TUBE_GROUP
    _DEBUG_COL = _SPHERES_COL = _WIREFRAMES_COL = _EDGE_TUBE_GROUP = None


def _flat_material(name, color):
    import bpy
    mat = bpy.data.materials.new(name)
    mat.use_nodes = False
    mat.diffuse_color = (*color, 1.0)
    mat.roughness = 1.0
    mat.specular_intensity = 0.0
    return mat


def _edge_tube_nodegroup():
    global _EDGE_TUBE_GROUP
    import bpy
    if _EDGE_TUBE_GROUP is not None:
        return _EDGE_TUBE_GROUP
    group = bpy.data.node_groups.new("EdgeToTube", 'GeometryNodeTree')
    group.interface.new_socket("Geometry", in_out='INPUT',
                               socket_type='NodeSocketGeometry')
    group.interface.new_socket("Radius", in_out='INPUT',
                               socket_type='NodeSocketFloat')
    group.interface.new_socket("Geometry", in_out='OUTPUT',
                               socket_type='NodeSocketGeometry')
    gi = group.nodes.new('NodeGroupInput')
    go = group.nodes.new('NodeGroupOutput')
    gi.location = (-500, 0); go.location = (400, 0)
    m2c = group.nodes.new('GeometryNodeMeshToCurve')
    m2c.location = (-250, 0)
    circle = group.nodes.new('GeometryNodeCurvePrimitiveCircle')
    circle.location = (-50, -150)
    circle.inputs['Resolution'].default_value = 4
    c2m = group.nodes.new('GeometryNodeCurveToMesh')
    c2m.location = (150, 0)
    group.links.new(gi.outputs[0], m2c.inputs[0])
    group.links.new(m2c.outputs[0], c2m.inputs[0])
    group.links.new(gi.outputs[1], circle.inputs['Radius'])
    group.links.new(circle.outputs[0], c2m.inputs[1])
    group.links.new(c2m.outputs[0], go.inputs[0])
    _EDGE_TUBE_GROUP = group
    return group


def _apply_edge_tube(obj, thickness):
    import bpy
    ng = _edge_tube_nodegroup()
    mod = obj.modifiers.new("ThickEdges", 'NODES')
    mod.node_group = ng
    mod.show_viewport = True
    mod.show_render = False
    for item in ng.interface.items_tree:
        if hasattr(item, 'in_out') and item.in_out == 'INPUT' and item.name == "Radius":
            mod[item.identifier] = thickness
            break


def _ico_template():
    global _ICO_VERTS, _ICO_FACES
    if _ICO_VERTS is not None:
        return _ICO_VERTS, _ICO_FACES
    phi = (1.0 + math.sqrt(5.0)) * 0.5
    t = 1.0 / math.sqrt(1.0 + phi * phi)
    p = phi * t
    _ICO_VERTS = [
        (-t,  p, 0), ( t,  p, 0), (-t, -p, 0), ( t, -p, 0),
        ( 0, -t,  p), ( 0,  t,  p), ( 0, -t, -p), ( 0,  t, -p),
        ( p,  0, -t), ( p,  0,  t), (-p,  0, -t), (-p,  0,  t),
    ]
    _ICO_FACES = [
        (0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),
        (1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),
        (3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),
        (4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1),
    ]
    return _ICO_VERTS, _ICO_FACES


def make_voxel_spheres(name, cells, bounds, res, color):
    """Create ONE merged icosphere mesh at every voxel centre."""
    import bpy
    if not cells:
        return None
    min_x, min_y, min_z = bounds[0], bounds[1], bounds[4]
    radius = res * 0.10
    ico_v, ico_f = _ico_template()
    nv = len(ico_v)
    verts = []; faces = []
    for i, (ix, iy, iz) in enumerate(cells):
        cx = min_x + (ix+0.5)*res; cy = min_y + (iy+0.5)*res; cz = min_z + (iz+0.5)*res
        base = i * nv
        for (vx, vy, vz) in ico_v:
            verts.append((cx+vx*radius, cy+vy*radius, cz+vz*radius))
        for f in ico_f:
            faces.append((base+f[0], base+f[1], base+f[2]))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    _spheres_col().objects.link(obj)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    return obj


def make_voxel_wireframes(name, cells, bounds, res, color):
    """Create ONE edge-mesh object containing wireframe boxes for all given voxels."""
    import bpy
    if not cells:
        return None
    min_x, min_y, min_z = bounds[0], bounds[1], bounds[4]
    EDGE_PAIRS = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
                  (0,4),(1,5),(2,6),(3,7)]
    verts = []; edges = []
    for i, (ix, iy, iz) in enumerate(cells):
        x0, x1 = min_x+ix*res, min_x+(ix+1)*res
        y0, y1 = min_y+iy*res, min_y+(iy+1)*res
        z0, z1 = min_z+iz*res, min_z+(iz+1)*res
        base = i * 8
        verts += [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
                  (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
        for (a, b) in EDGE_PAIRS:
            edges.append((base+a, base+b))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    _wireframes_col().objects.link(obj)
    obj.color = (*color, 1.0)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    _apply_edge_tube(obj, res * 0.015)
    return obj


def make_hit_markers(name, positions, s, color):
    """Draw a small 3-axis cross at each ray hit position."""
    import bpy
    if not positions:
        return None
    verts = []; edges = []
    for (px, py, pz) in positions:
        base = len(verts)
        verts += [(px-s,py,pz),(px+s,py,pz),(px,py-s,pz),(px,py+s,pz),
                  (px,py,pz-s),(px,py,pz+s)]
        edges += [(base,base+1),(base+2,base+3),(base+4,base+5)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    _debug_collection().objects.link(obj)
    obj.color = (*color, 1.0)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    _apply_edge_tube(obj, s * 0.3)
    return obj


def make_sphere(name, location, radius, color):
    """Create a small solid-color sphere at location."""
    import bpy
    import bmesh as _bm
    mesh = bpy.data.meshes.new(name)
    tmp = _bm.new()
    _bm.ops.create_uvsphere(tmp, u_segments=8, v_segments=4, radius=radius)
    tmp.to_mesh(mesh); tmp.free()
    obj = bpy.data.objects.new(name, mesh)
    _debug_collection().objects.link(obj)
    obj.location = location
    obj.data.materials.append(_flat_material(name + "_mat", color))
    return obj


def make_line(name, points, color, thickness=0.02):
    """Create a curve object through points with flat solid color."""
    import bpy
    curve = bpy.data.curves.new(name, type="CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = thickness
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.points[i].co = (p.x, p.y, p.z, 1.0)
    obj = bpy.data.objects.new(name, curve)
    _debug_collection().objects.link(obj)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    return obj


def make_arrow(name, origin, direction, length, color, shaft_r, head_r):
    """Create an arrow (shaft + cone) from origin along direction."""
    import bpy
    import bmesh as _bm
    from mathutils import Vector, Quaternion
    shaft_end = origin + direction * (length * 0.75)
    tip = origin + direction * length
    make_line(f"{name}_shaft", [origin, shaft_end], color, thickness=shaft_r)
    mesh = bpy.data.meshes.new(f"{name}_cone")
    tmp = _bm.new()
    _bm.ops.create_cone(tmp, segments=8, radius1=head_r, radius2=0.0, depth=length*0.25)
    tmp.to_mesh(mesh); tmp.free()
    obj = bpy.data.objects.new(f"{name}_cone", mesh)
    _debug_collection().objects.link(obj)
    obj.data.materials.append(_flat_material(f"{name}_cone_mat", color))
    obj.location = (shaft_end + tip) / 2.0
    obj.rotation_mode = "QUATERNION"
    up = Vector((0, 0, 1))
    rot_axis = up.cross(direction)
    if rot_axis.length > 1e-6:
        rot_axis.normalize()
        angle = math.acos(max(-1, min(1, up.dot(direction))))
        obj.rotation_quaternion = Quaternion(rot_axis, angle)
    elif direction.dot(up) < 0:
        obj.rotation_quaternion = Quaternion((1, 0, 0), math.pi)
    return obj


def add_voxel_type(tag, cells, bounds, res, color):
    """Add both spheres and wireframes for a voxel group."""
    make_voxel_spheres(f"dbg_{tag}_sph", cells, bounds, res, color)
    make_voxel_wireframes(f"dbg_{tag}_wire", cells, bounds, res, color)
