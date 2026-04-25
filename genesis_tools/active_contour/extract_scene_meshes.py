"""Blender-side script: extract world-space mesh geometry from a .blend scene.

Run via Blender headlessly:

    blender --background scene.blend \\
        --python genesis_tools/active_contour/extract_scene_meshes.py \\
        -- --output /tmp/meshes.npz [--max-tris 500000]

Outputs a .npz file containing arrays:
    verts_{i}   shape (N, 3) float32  world-space vertex positions
    faces_{i}   shape (M, 3) int32    triangle vertex indices
    n_meshes    scalar int             number of mesh objects exported

Prints: MESH_EXTRACT_RESULT:{"npz_path": "...", "n_meshes": N, "total_tris": T}
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
    p.add_argument("--output", required=True)
    p.add_argument("--max-tris", type=int, default=500_000,
                   help="Max triangles per mesh object (random face subset if exceeded)")
    return p.parse_args(argv)


def main():
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    rng = np.random.default_rng(42)

    arrays = {}
    total_tris = 0
    mesh_idx = 0

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        if mesh is None:
            continue

        # Triangulate in-place
        mesh.calc_loop_triangles()
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            eval_obj.to_mesh_clear()
            continue

        # World-space vertex positions
        matrix = obj.matrix_world
        verts_local = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", verts_local)
        verts_local = verts_local.reshape(-1, 3)

        # Apply matrix_world: (N,3) → (N,3)
        ones = np.ones((len(verts_local), 1), dtype=np.float32)
        v_h = np.hstack([verts_local, ones])           # (N, 4)
        m = np.array(matrix, dtype=np.float32)         # (4, 4)
        verts_world = (m @ v_h.T).T[:, :3]             # (N, 3)

        # Face indices from triangulated loops
        faces = np.empty(n_tris * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", faces)
        faces = faces.reshape(-1, 3)

        # Subsample if too many triangles
        if n_tris > args.max_tris:
            idx = rng.choice(n_tris, size=args.max_tris, replace=False)
            faces = faces[idx]
            n_tris = args.max_tris

        eval_obj.to_mesh_clear()

        arrays[f"verts_{mesh_idx}"] = verts_world
        arrays[f"faces_{mesh_idx}"] = faces
        total_tris += n_tris
        mesh_idx += 1

        if mesh_idx % 50 == 0:
            print(f"  [extract] {mesh_idx} meshes exported, {total_tris} tris so far")

    arrays["n_meshes"] = np.array(mesh_idx, dtype=np.int32)
    np.savez_compressed(str(output_path), **arrays)

    result = {"npz_path": str(output_path), "n_meshes": mesh_idx, "total_tris": total_tris}
    print(f"MESH_EXTRACT_RESULT:{json.dumps(result)}")


main()
