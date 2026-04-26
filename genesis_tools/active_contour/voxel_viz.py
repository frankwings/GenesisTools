"""Blender-side script: visualise a VoxelGrid as wireframe boxes + sphere markers.

Adapted from genesis_tools/walkthrough_renderer/render_walkthrough.py
(_make_voxel_spheres, _make_voxel_wireframes, _flat_material, _edge_tube_nodegroup).

Key difference: this script works directly with world-space voxel centres (K,3)
from VoxelGrid.save(), not with grid indices (ix,iy,iz) + bounds.

Run headlessly:

    blender --background scene.blend \\
        --python genesis_tools/active_contour/voxel_viz.py \\
        -- --voxel-npz path/to/voxel_grid.npz \\
           --snake-npz path/to/snake_mesh.npz \\   (optional, adds contour hull)
           --output-blend path/to/output.blend \\
           --render-dir   path/to/renders/ \\
           [--engine WORKBENCH] [--res-x 1280] [--res-y 720]

Output renders:
    renders/view_top.png    — orthographic top-down
    renders/view_front.png  — orthographic front
    renders/view_side.png   — orthographic side
    renders/view_camera.png — perspective from original scene camera (if any)
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--voxel-npz",    required=True)
    p.add_argument("--snake-npz",    default=None)
    p.add_argument("--output-blend", required=True)
    p.add_argument("--render-dir",   required=True)
    p.add_argument("--engine",       default="WORKBENCH",
                   choices=["WORKBENCH", "EEVEE", "CYCLES"])
    p.add_argument("--res-x",        type=int, default=1280)
    p.add_argument("--res-y",        type=int, default=720)
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _flat_material(name, color):
    """Flat solid-colour material — no nodes, fast, no shader compilation."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = False
    mat.diffuse_color = (*color, 1.0)
    mat.roughness = 1.0
    mat.specular_intensity = 0.0
    return mat


# ---------------------------------------------------------------------------
# Geometry Nodes: edge mesh → thick square tubes (viewport only)
# ---------------------------------------------------------------------------

_EDGE_TUBE_GROUP = None


def _edge_tube_nodegroup():
    global _EDGE_TUBE_GROUP
    if _EDGE_TUBE_GROUP is not None:
        return _EDGE_TUBE_GROUP
    group = bpy.data.node_groups.new("EdgeToTube_VoxViz", 'GeometryNodeTree')
    group.interface.new_socket("Geometry", in_out='INPUT',
                               socket_type='NodeSocketGeometry')
    group.interface.new_socket("Radius",   in_out='INPUT',
                               socket_type='NodeSocketFloat')
    group.interface.new_socket("Geometry", in_out='OUTPUT',
                               socket_type='NodeSocketGeometry')
    gi = group.nodes.new('NodeGroupInput');  gi.location = (-500, 0)
    go = group.nodes.new('NodeGroupOutput'); go.location = ( 400, 0)
    m2c    = group.nodes.new('GeometryNodeMeshToCurve');     m2c.location    = (-250, 0)
    circle = group.nodes.new('GeometryNodeCurvePrimitiveCircle')
    circle.location = (-50, -150)
    circle.inputs['Resolution'].default_value = 4
    c2m = group.nodes.new('GeometryNodeCurveToMesh');        c2m.location    = ( 150, 0)
    group.links.new(gi.outputs[0], m2c.inputs[0])
    group.links.new(m2c.outputs[0], c2m.inputs[0])
    group.links.new(gi.outputs[1], circle.inputs['Radius'])
    group.links.new(circle.outputs[0], c2m.inputs[1])
    group.links.new(c2m.outputs[0], go.inputs[0])
    _EDGE_TUBE_GROUP = group
    return group


def _apply_edge_tube(obj, thickness):
    ng  = _edge_tube_nodegroup()
    mod = obj.modifiers.new("ThickEdges", 'NODES')
    mod.node_group   = ng
    mod.show_viewport = True
    mod.show_render   = False   # skip GN eval during headless save
    for item in ng.interface.items_tree:
        if hasattr(item, 'in_out') and item.in_out == 'INPUT' and item.name == "Radius":
            mod[item.identifier] = thickness
            break


# ---------------------------------------------------------------------------
# Icosahedron template (cached) — 12 verts, 20 faces
# ---------------------------------------------------------------------------

_ICO_VERTS = None
_ICO_FACES = None


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


# ---------------------------------------------------------------------------
# Core geometry builders  (world-space centres, not grid indices)
# ---------------------------------------------------------------------------

_EDGE_PAIRS = [
    (0, 1), (1, 2), (2, 3), (3, 0),   # bottom face
    (4, 5), (5, 6), (6, 7), (7, 4),   # top face
    (0, 4), (1, 5), (2, 6), (3, 7),   # verticals
]


def make_voxel_spheres(name: str, centers: np.ndarray,
                       voxel_size: float, color: tuple) -> bpy.types.Object | None:
    """One merged icosphere mesh, one icosphere per voxel centre.

    Args:
        centers:    (K, 3) world-space voxel centres.
        voxel_size: edge length — sphere radius = voxel_size * 0.10.
        color:      RGB tuple (0-1).
    """
    if len(centers) == 0:
        return None
    radius = voxel_size * 0.10
    ico_v, ico_f = _ico_template()
    nv = len(ico_v)

    verts, faces = [], []
    for i, (cx, cy, cz) in enumerate(centers.tolist()):
        base = i * nv
        for vx, vy, vz in ico_v:
            verts.append((cx + vx * radius, cy + vy * radius, cz + vz * radius))
        for f in ico_f:
            faces.append((base + f[0], base + f[1], base + f[2]))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    print(f"  [voxviz] spheres '{name}': {len(centers)} voxels")
    return obj


def make_voxel_wireframes(name: str, centers: np.ndarray,
                          voxel_size: float, color: tuple) -> bpy.types.Object | None:
    """One merged edge-mesh (wireframe boxes) for all voxel centres.

    Each box is axis-aligned, ±(voxel_size/2) around the centre.
    Thick tubes added via Geometry Nodes (viewport only; render uses thin edges).
    """
    if len(centers) == 0:
        return None
    h = voxel_size / 2.0

    verts, edges = [], []
    for i, (cx, cy, cz) in enumerate(centers.tolist()):
        base = i * 8
        verts += [
            (cx - h, cy - h, cz - h), (cx + h, cy - h, cz - h),
            (cx + h, cy + h, cz - h), (cx - h, cy + h, cz - h),
            (cx - h, cy - h, cz + h), (cx + h, cy - h, cz + h),
            (cx + h, cy + h, cz + h), (cx - h, cy + h, cz + h),
        ]
        for a, b in _EDGE_PAIRS:
            edges.append((base + a, base + b))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.color = (*color, 1.0)
    obj.data.materials.append(_flat_material(name + "_mat", color))
    _apply_edge_tube(obj, voxel_size * 0.015)
    print(f"  [voxviz] wireframes '{name}': {len(centers)} voxels")
    return obj


# ---------------------------------------------------------------------------
# Snake contour overlay (reused from overlay_snake_in_blend logic)
# ---------------------------------------------------------------------------

def _add_snake_overlay(snake_npz: str):
    """Add snake mesh to scene as hidden-render object with cyan material."""
    data  = np.load(snake_npz)
    verts = data["vertices"].tolist()
    faces = data["faces"].tolist()

    mesh = bpy.data.meshes.new("ActiveContour_Snake")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj  = bpy.data.objects.new("ActiveContour_Snake", mesh)
    bpy.context.collection.objects.link(obj)

    mat = bpy.data.materials.new("SnakeMat")
    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out   = nodes.new("ShaderNodeOutputMaterial")
    mix   = nodes.new("ShaderNodeMixShader")
    trans = nodes.new("ShaderNodeBsdfTransparent")
    emit  = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value  = (0.0, 0.85, 1.0, 1.0)
    emit.inputs["Strength"].default_value = 1.2
    mix.inputs["Fac"].default_value = 0.20
    links.new(trans.outputs["BSDF"],    mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"],    out.inputs["Surface"])
    obj.data.materials.append(mat)
    obj.show_wire   = True
    obj.hide_render = True   # not in F12 renders
    return obj


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _setup_render(engine: str, res_x: int, res_y: int):
    scene = bpy.context.scene
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.film_transparent = False
    if engine == "WORKBENCH":
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light      = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_xray  = False
    elif engine == "EEVEE":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 32
        scene.cycles.device  = "GPU"


def _render_views(render_dir: Path, res_x: int, res_y: int):
    """Render top/front/side orthographic views + original camera view."""
    scene = bpy.context.scene
    render_dir.mkdir(parents=True, exist_ok=True)

    # AABB from all mesh objects
    all_pts = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for v in obj.data.vertices:
            p = obj.matrix_world @ v.co
            all_pts.append((p.x, p.y, p.z))
    if not all_pts:
        return []
    pts = np.array(all_pts)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    cx, cy, cz = (lo + hi) / 2
    sx, sy, sz  = hi - lo
    dist = max(sx, sy, sz) * 2

    views = [
        ("view_top",   (cx, cy, cz + dist), (0,  0, 0),  max(sx, sy) * 1.15),
        ("view_front", (cx, cy - dist, cz), (90, 0, 0),  max(sx, sz) * 1.15),
        ("view_side",  (cx + dist, cy, cz), (90, 0, 90), max(sy, sz) * 1.15),
    ]

    cam_data = bpy.data.cameras.new("TempOrtho")
    cam_data.type = "ORTHO"
    cam_obj  = bpy.data.objects.new("TempOrtho", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    rendered   = []
    orig_cam   = scene.camera
    scene.camera = cam_obj

    for name, loc, rot_deg, scale in views:
        cam_obj.location       = loc
        cam_obj.rotation_euler = [math.radians(r) for r in rot_deg]
        cam_data.ortho_scale   = scale
        out = render_dir / f"{name}.png"
        scene.render.filepath  = str(out)
        bpy.ops.render.render(write_still=True)
        rendered.append(str(out))
        print(f"  [voxviz] rendered → {out}")

    if orig_cam is not None:
        scene.camera = orig_cam
        out = render_dir / "view_camera.png"
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        rendered.append(str(out))
        print(f"  [voxviz] rendered → {out}")

    scene.camera = orig_cam
    bpy.data.objects.remove(cam_obj)
    bpy.data.cameras.remove(cam_data)
    return rendered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args       = _parse_args()
    render_dir = Path(args.render_dir)
    output_blend = Path(args.output_blend)
    output_blend.parent.mkdir(parents=True, exist_ok=True)

    # Load voxel grid
    data       = np.load(args.voxel_npz)
    centers    = data["centers"]          # (K, 3)
    voxel_size = float(data["voxel_size"])
    print(f"[voxviz] Loaded {len(centers):,} voxels  voxel_size={voxel_size:.4f}")

    # Add snake contour if provided
    if args.snake_npz:
        print("[voxviz] Adding snake contour overlay …")
        _add_snake_overlay(args.snake_npz)

    # Add voxel geometry — both spheres and wireframes
    print("[voxviz] Building voxel geometry …")
    make_voxel_spheres("voxel_spheres",    centers, voxel_size, color=(0.2, 0.5, 1.0))
    make_voxel_wireframes("voxel_wires",   centers, voxel_size, color=(0.1, 0.3, 0.9))

    # Render
    _setup_render(args.engine, args.res_x, args.res_y)
    print("[voxviz] Rendering views …")
    rendered = _render_views(render_dir, args.res_x, args.res_y)

    # Save blend
    print("[voxviz] Saving blend …")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

    result = {"blend": str(output_blend), "renders": rendered,
              "n_voxels": len(centers), "voxel_size": voxel_size}
    print(f"VOXVIZ_RESULT:{json.dumps(result)}")


main()
