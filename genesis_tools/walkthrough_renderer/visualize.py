"""Visualization CLI and importable API.

Reads the original .blend + any pipeline step outputs, adds colored debug
geometry to a new output .blend file.  Layers are additive: pass only
the flags you have data for.

Requires bpy Python (/home/kingy/blender/4.5/python/bin/python3.11).
"""
from __future__ import annotations

import argparse
from pathlib import Path


def visualize(
    blend_path: str,
    output_blend: str,
    *,
    voxel_grid: str | None = None,    # path to voxel_grid.npz
    walkable: str | None = None,      # path to walkable.npz
    path: str | None = None,          # path to path.npz
    camera_blend: str | None = None,  # path to animated .blend
    config: dict | None = None,
) -> None:
    """Add debug visualization layers to a copy of blend_path.

    Each layer is only added when the corresponding data file is provided.

    Args:
        blend_path:     Input .blend scene (original, unmodified).
        output_blend:   Where to save the debug .blend.
        voxel_grid:     Path to voxel_grid.npz  (adds red/yellow voxel layer).
        walkable:       Path to walkable.npz     (adds blue/cyan walkable layer).
        path:           Path to path.npz         (adds green/pink path layer).
        camera_blend:   Path to animated .blend  (adds RGB camera axes layer).
        config:         Optional config dict for display scale parameters.
    """
    import bpy
    from genesis_tools.walkthrough_renderer.viz.primitives import reset_collections

    if config is None:
        config = {}

    # Pre-read camera poses BEFORE opening the main blend (open_mainfile replaces
    # the current scene, so we must read the animated blend first if provided).
    camera_poses = None
    if camera_blend is not None:
        from genesis_tools.walkthrough_renderer.viz.layers import read_camera_poses
        fps = config.get("fps", 12)
        camera_poses = read_camera_poses(camera_blend, fps)
        print(f"[Visualize] pre-read {len(camera_poses)} camera poses from {camera_blend}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    reset_collections()

    unit_scale = float(bpy.context.scene.unit_settings.scale_length or 1.0)
    config.setdefault("_unit_scale", unit_scale)

    if voxel_grid is not None:
        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import load as vg_load
        from genesis_tools.walkthrough_renderer.viz.layers import add_voxel_grid_layer
        vg = vg_load(voxel_grid)
        add_voxel_grid_layer(vg, config)
        print(f"[Visualize] voxel_grid layer added ({len(vg.solid)} solid, {len(vg.candidates)} candidates)")

    if walkable is not None and voxel_grid is not None:
        from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import load as vg_load
        from genesis_tools.walkthrough_renderer.pipeline.walkable import load as wk_load
        from genesis_tools.walkthrough_renderer.viz.layers import add_walkable_layer
        vg = vg_load(voxel_grid)
        wk = wk_load(walkable)
        add_walkable_layer(vg, wk, config)
        print(f"[Visualize] walkable layer added ({len(wk.walkable)} walkable)")
    elif walkable is not None:
        print("[Visualize] WARNING: --walkable requires --voxel-grid for full layer; skipping walkable.")

    if path is not None:
        from genesis_tools.walkthrough_renderer.pipeline.path_plan import load as pd_load
        from genesis_tools.walkthrough_renderer.viz.layers import add_path_layer
        pd = pd_load(path)
        add_path_layer(pd, config)
        print(f"[Visualize] path layer added ({len(pd.waypoints)} waypoints, "
              f"{len(pd.path_points)} path points)")

    if camera_poses is not None:
        from genesis_tools.walkthrough_renderer.viz.layers import add_camera_arrows
        res_bu = config.get("grid_resolution", 0.5) / config.get("_unit_scale", 1.0)
        add_camera_arrows(camera_poses, res_bu)
        print(f"[Visualize] camera layer added ({len(camera_poses)} poses)")

    Path(output_blend).parent.mkdir(parents=True, exist_ok=True)
    bpy.data.use_autopack = False
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    print(f"[Visualize] Saved -> {output_blend}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Add debug visualization to a .blend")
    parser.add_argument("--blend", required=True, help="Input .blend file")
    parser.add_argument("--output", required=True, help="Output debug .blend")
    parser.add_argument("--voxel-grid", default=None, help="Path to voxel_grid.npz")
    parser.add_argument("--walkable",   default=None, help="Path to walkable.npz")
    parser.add_argument("--path",       default=None, help="Path to path.npz")
    parser.add_argument("--camera",     default=None, help="Path to animated .blend")
    parser.add_argument("--config",     default=None, help="Path to config JSON")
    args = parser.parse_args()

    config = {}
    if args.config:
        import json
        with open(args.config) as f:
            config = json.load(f)

    visualize(
        blend_path=args.blend,
        output_blend=args.output,
        voxel_grid=args.voxel_grid,
        walkable=args.walkable,
        path=args.path,
        camera_blend=args.camera,
        config=config,
    )


if __name__ == "__main__":
    _cli()
