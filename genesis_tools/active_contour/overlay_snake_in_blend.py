"""Blender-side script: add the fitted Snake3D mesh as a transparent overlay
and render orthographic + camera views.

Run via Blender headlessly:

    blender --background scene.blend \\
        --python genesis_tools/active_contour/overlay_snake_in_blend.py \\
        -- --snake-npz /path/to/snake_mesh.npz \\
           --output-blend /path/to/output.blend \\
           --render-dir /path/to/renders \\
           [--engine WORKBENCH] [--res-x 1280] [--res-y 720]

Produces:
  output.blend            — original scene + snake overlay saved together
  renders/view_top.png    — orthographic top-down render
  renders/view_front.png  — orthographic front render
  renders/view_side.png   — orthographic side render
  renders/view_camera.png — perspective from the original scene camera (if any)
"""

import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--snake-npz", required=True)
    p.add_argument("--output-blend", required=True)
    p.add_argument("--render-dir", required=True)
    p.add_argument("--engine", default="WORKBENCH",
                   choices=["WORKBENCH", "EEVEE", "CYCLES"])
    p.add_argument("--res-x", type=int, default=1280)
    p.add_argument("--res-y", type=int, default=720)
    return p.parse_args(argv)


def add_snake_mesh(npz_path: str) -> bpy.types.Object:
    """Load snake vertices/faces and create a Blender mesh object."""
    data = np.load(npz_path)
    verts = data["vertices"].tolist()
    faces = data["faces"].tolist()

    mesh = bpy.data.meshes.new("ActiveContour_Snake")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new("ActiveContour_Snake", mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def make_snake_material(color=(0.0, 0.7, 1.0), alpha=0.25) -> bpy.types.Material:
    """Semi-transparent cyan emission material, compatible with Blender 4.x."""
    mat = bpy.data.materials.new("SnakeMaterial")
    mat.use_nodes = True

    # Blend method — attribute name differs between Blender 3.x and 4.x
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"           # Blender ≤ 3.6
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"  # Blender 4.x EEVEE Next

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out         = nodes.new("ShaderNodeOutputMaterial")
    mix         = nodes.new("ShaderNodeMixShader")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    emission    = nodes.new("ShaderNodeEmission")

    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = 1.5
    mix.inputs["Fac"].default_value = alpha  # 0=transparent, 1=opaque

    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def _project_snake_onto_render(
    snake_obj, cam_obj, res_x: int, res_y: int, render_path: str,
    line_color=(0, 217, 255), line_thickness: int = 3,
) -> None:
    """Project the snake's screen-space convex hull outline onto the rendered image.

    Projects all snake vertices to 2D screen coordinates, computes the convex
    hull of those points, and draws the hull boundary.  This gives a clean
    single-polygon outline of the snake's apparent boundary from each viewpoint,
    avoiding the cluttered triangulation lines produced by drawing all edges.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        print(f"  [overlay] Missing dependency ({exc}), skipping 2D projection")
        return

    img = Image.open(render_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    cam_data = cam_obj.data
    verts = [v.co for v in snake_obj.data.vertices]

    # Build camera projection function
    view_mat = cam_obj.matrix_world.inverted()
    if cam_data.type == "ORTHO":
        scale = cam_data.ortho_scale
        def project(v):
            vv = view_mat @ v
            return (( vv.x / scale + 0.5) * res_x,
                    (-vv.y / scale + 0.5) * res_y)
    else:
        aspect = res_x / res_y
        sensor = cam_data.sensor_width
        focal = cam_data.lens
        f_px = (focal / sensor) * res_x
        cx, cy = res_x / 2.0, res_y / 2.0
        def project(v):
            vv = view_mat @ v
            if vv.z >= 0:
                return None
            return ( (vv.x / -vv.z) * f_px + cx,
                    -(vv.y / -vv.z) * f_px / aspect + cy)

    # Project all vertices to 2D
    pts_2d = [project(v) for v in verts]
    pts_2d = [p for p in pts_2d if p is not None]

    if len(pts_2d) < 3:
        print("  [overlay] Too few projected vertices, skipping")
        img.save(render_path)
        return

    # 2D convex hull via gift-wrapping (Jarvis march) — no scipy needed
    def _hull_2d(pts):
        n = len(pts)
        start = min(range(n), key=lambda i: (pts[i][0], pts[i][1]))
        hull_idx, cur = [], start
        while True:
            hull_idx.append(cur)
            nxt = (cur + 1) % n
            for i in range(n):
                ax = pts[nxt][0] - pts[cur][0]
                ay = pts[nxt][1] - pts[cur][1]
                bx = pts[i][0]  - pts[cur][0]
                by = pts[i][1]  - pts[cur][1]
                if ax * by - ay * bx < 0:   # i is more clockwise
                    nxt = i
            cur = nxt
            if cur == start or len(hull_idx) > n:
                break
        return hull_idx

    hull_idx = _hull_2d(pts_2d)
    hull_pts = [pts_2d[i] for i in hull_idx]

    rgba = (*line_color, 230)
    for i in range(len(hull_pts)):
        a = (int(hull_pts[i][0]),                   int(hull_pts[i][1]))
        b = (int(hull_pts[(i + 1) % len(hull_pts)][0]),
             int(hull_pts[(i + 1) % len(hull_pts)][1]))
        draw.line([a, b], fill=rgba, width=line_thickness)

    print(f"  [overlay] Drew convex hull outline ({len(hull_pts)} hull verts "
          f"from {len(pts_2d)} projected)")
    img.save(render_path)


def _setup_freestyle_on_snake(snake_obj, line_color=(0.0, 0.85, 1.0),
                               line_thickness=3.0) -> None:
    pass  # replaced by _project_snake_onto_render


def setup_render(engine: str, res_x: int, res_y: int, snake_obj=None) -> None:
    scene = bpy.context.scene
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.film_transparent = False

    if engine == "WORKBENCH":
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_xray = False
    elif engine == "EEVEE":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 32
        scene.cycles.device = "GPU"

    # Hide the snake solid faces — its presence is drawn as 2D lines afterward
    if snake_obj is not None:
        snake_obj.hide_render = True


def render_orthographic(render_dir: Path, res_x: int, res_y: int,
                         snake_obj=None) -> list:
    """Render top/front/side orthographic views + original camera view."""
    import math
    scene = bpy.context.scene
    render_dir.mkdir(parents=True, exist_ok=True)

    # AABB from ALL mesh verts (world space) — excluding the snake itself
    all_pts = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.name == "ActiveContour_Snake":
            continue
        for v in obj.data.vertices:
            p = obj.matrix_world @ v.co
            all_pts.append((p.x, p.y, p.z))
    if not all_pts:
        return []
    pts_arr = np.array(all_pts)
    lo, hi = pts_arr.min(axis=0), pts_arr.max(axis=0)
    cx, cy, cz = (lo + hi) / 2
    sx, sy, sz = hi - lo
    dist = max(sx, sy, sz) * 2

    views = [
        # (name, location, euler_deg(x,y,z), ortho_scale)
        ("view_top",   (cx, cy, cz + dist), (0,   0, 0),   max(sx, sy) * 1.15),
        ("view_front", (cx, cy - dist, cz), (90,  0, 0),   max(sx, sz) * 1.15),
        ("view_side",  (cx + dist, cy, cz), (90,  0, 90),  max(sy, sz) * 1.15),
    ]

    cam_data = bpy.data.cameras.new("TempOrthoCamera")
    cam_data.type = "ORTHO"
    cam_obj = bpy.data.objects.new("TempOrthoCamera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    rendered = []
    orig_cam = scene.camera
    scene.camera = cam_obj

    for name, loc, rot_deg, scale in views:
        cam_obj.location = loc
        cam_obj.rotation_euler = [math.radians(r) for r in rot_deg]
        cam_data.ortho_scale = scale
        out_path = render_dir / f"{name}.png"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        if snake_obj is not None:
            _project_snake_onto_render(snake_obj, cam_obj, res_x, res_y, str(out_path))
        rendered.append(str(out_path))
        print(f"  rendered → {out_path}")

    # Render from original scene camera if present
    if orig_cam is not None:
        scene.camera = orig_cam
        out_path = render_dir / "view_camera.png"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        if snake_obj is not None:
            _project_snake_onto_render(snake_obj, orig_cam, res_x, res_y, str(out_path))
        rendered.append(str(out_path))
        print(f"  rendered → {out_path}")

    scene.camera = orig_cam
    bpy.data.objects.remove(cam_obj)
    bpy.data.cameras.remove(cam_data)
    return rendered


def main():
    args = parse_args()
    render_dir = Path(args.render_dir)
    output_blend = Path(args.output_blend)
    output_blend.parent.mkdir(parents=True, exist_ok=True)

    print("[overlay] Adding snake mesh …")
    snake_obj = add_snake_mesh(args.snake_npz)
    mat = make_snake_material(color=(0.0, 0.8, 1.0), alpha=0.3)
    snake_obj.data.materials.append(mat)
    snake_obj.show_wire = True

    setup_render(args.engine, args.res_x, args.res_y, snake_obj=snake_obj)

    print("[overlay] Rendering views …")
    rendered = render_orthographic(render_dir, args.res_x, args.res_y,
                                   snake_obj=snake_obj)

    print("[overlay] Saving blend …")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

    result = {"blend": str(output_blend), "renders": rendered}
    print(f"OVERLAY_RESULT:{json.dumps(result)}")


main()
