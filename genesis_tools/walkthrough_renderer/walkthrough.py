"""Walkthrough orchestrator: runs the full pipeline with implicit resume.

Steps (in order):
  voxel_grid -> walkable -> path -> camera_orient -> camera_animate -> (render)

Implicit resume: each step checks for its output file in output_dir.
If the file exists, the step is skipped and its data loaded from disk.
To re-run from a step, delete that file and all subsequent output files.

All bpy-dependent steps are invoked by spawning a subprocess using
/home/kingy/blender/4.5/python/bin/python3.11 (pip bpy).

Rendering uses blender --background via BlenderRunner.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BPY_PYTHON = "/home/kingy/blender/4.5/python/bin/python3.11"

STEP_FILES = {
    "voxel_grid":    "voxel_grid.npz",
    "walkable":      "walkable.npz",
    "path":          "path.npz",
    "camera_orient": "wp_schedule.json",
    "camera_animate": None,  # name comes from blend stem
    "render":        None,   # frames dir
}

STEPS = ["voxel_grid", "walkable", "path", "camera_orient", "camera_animate", "render"]


def _bpy_python() -> str:
    """Return path to pip bpy Python interpreter."""
    return BPY_PYTHON


def _run_bpy_module(module: str, args: list[str]) -> None:
    """Run a pipeline module under bpy Python as a subprocess."""
    cmd = [_bpy_python(), "-m", module] + args
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"Step {module} failed (exit {result.returncode})")


def run(blend_path: str, config: dict, output_dir: str,
        render: bool = False) -> dict:
    """Run the full walkthrough pipeline with implicit resume.

    Args:
        blend_path:  Path to input .blend file.
        config:      Pipeline configuration dict.
        output_dir:  Directory for all intermediate and output files.
        render:      If True, run the render step.

    Returns:
        dict with keys: blend_output, frames (if rendered), step_outputs.
    """
    from genesis_tools.walkthrough_renderer.pipeline.voxel_grid import (
        load as vg_load, build as vg_build, save as vg_save)
    from genesis_tools.walkthrough_renderer.pipeline.walkable import (
        load as wk_load, build as wk_build, save as wk_save)
    from genesis_tools.walkthrough_renderer.pipeline.path_plan import (
        load as pd_load, build as pd_build, save as pd_save)
    from genesis_tools.walkthrough_renderer.pipeline.camera_orient import (
        load as orient_load, build as orient_build, save as orient_save)
    from genesis_tools.walkthrough_renderer.pipeline.camera_animate import (
        build as animate_build)
    from genesis_tools.walkthrough_renderer.pipeline.render import (
        build as render_build)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    blend_path = str(blend_path)
    blend_stem = Path(blend_path).stem

    vg_path       = output_dir / "voxel_grid.npz"
    wk_path       = output_dir / "walkable.npz"
    pd_path       = output_dir / "path.npz"
    orient_path   = output_dir / "wp_schedule.json"
    blend_out     = output_dir / f"{blend_stem}_walkthrough.blend"

    # Write config to temp file for subprocess-based steps
    import tempfile
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config, tf); tf.close()
    config_path = tf.name

    try:
        # ----- Step 1: voxel_grid -----
        if vg_path.exists():
            print(f"[Walkthrough] Skipping voxel_grid (found {vg_path})")
            vg = vg_load(str(vg_path))
        else:
            print("[Walkthrough] Step 1: voxel_grid")
            _run_bpy_module(
                "genesis_tools.walkthrough_renderer.pipeline.voxel_grid",
                ["--blend", blend_path, "--config", config_path,
                 "--output", str(vg_path)],
            )
            vg = vg_load(str(vg_path))

        # ----- Step 2: walkable -----
        if wk_path.exists():
            print(f"[Walkthrough] Skipping walkable (found {wk_path})")
            wk = wk_load(str(wk_path))
        else:
            print("[Walkthrough] Step 2: walkable")
            _run_bpy_module(
                "genesis_tools.walkthrough_renderer.pipeline.walkable",
                ["--blend", blend_path, "--voxel-grid", str(vg_path),
                 "--config", config_path, "--output", str(wk_path)],
            )
            wk = wk_load(str(wk_path))

        # ----- Step 3: path -----
        if pd_path.exists():
            print(f"[Walkthrough] Skipping path (found {pd_path})")
            pd = pd_load(str(pd_path))
        else:
            print("[Walkthrough] Step 3: path")
            _run_bpy_module(
                "genesis_tools.walkthrough_renderer.pipeline.path_plan",
                ["--voxel-grid", str(vg_path), "--walkable", str(wk_path),
                 "--blend", blend_path,
                 "--config", config_path, "--output", str(pd_path)],
            )
            pd = pd_load(str(pd_path))

        # ----- Step 4: camera_orient -----
        if orient_path.exists():
            print(f"[Walkthrough] Skipping camera_orient (found {orient_path})")
            orient = orient_load(str(orient_path))
        else:
            print("[Walkthrough] Step 4: camera_orient")
            _run_bpy_module(
                "genesis_tools.walkthrough_renderer.pipeline.camera_orient",
                ["--blend", blend_path, "--path", str(pd_path),
                 "--config", config_path, "--output", str(orient_path)],
            )
            orient = orient_load(str(orient_path))

        # ----- Step 5: camera_animate -----
        if blend_out.exists():
            print(f"[Walkthrough] Skipping camera_animate (found {blend_out})")
        else:
            print("[Walkthrough] Step 5: camera_animate")
            _run_bpy_module(
                "genesis_tools.walkthrough_renderer.pipeline.camera_animate",
                ["--blend", blend_path,
                 "--path", str(pd_path),
                 "--orient", str(orient_path),
                 "--config", config_path,
                 "--output-blend", str(blend_out)],
            )

        result: dict = {
            "blend_output": str(blend_out),
            "step_outputs": {
                "voxel_grid":    str(vg_path),
                "walkable":      str(wk_path),
                "path":          str(pd_path),
                "camera_orient": str(orient_path),
            },
        }

        # ----- Step 6 (optional): render -----
        if render:
            print("[Walkthrough] Step 6: render")
            frames = render_build(str(blend_out), config, str(output_dir))
            result["frames"] = frames

        return result

    finally:
        os.unlink(config_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(
        description="Walkthrough pipeline orchestrator (implicit resume)")
    parser.add_argument("--blend", required=True, help="Path to .blend file")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--render", action="store_true",
                        help="Also render frames via blender --background")
    args = parser.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    result = run(args.blend, config, args.output_dir, render=args.render)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
