#!/usr/bin/env python3
"""Debug walkthrough pipeline — run all steps with full intermediate output.

Usage:
    python3 scripts/debug_walkthrough.py \
        --blend /path/to/scene.blend \
        --snake results/active_contour/my_scene/snake_mesh.npz \
        --output results/debug_run \
        [--width 480] [--height 360] [--samples 16] \
        [--fps 12] [--duration 10] [--gaze smooth_adaptive] \
        [--no-render] [--visualize]

Each step outputs its intermediate files. After all steps complete, a summary
report is printed showing data shapes, path stats, and file sizes.

If --visualize is passed, a Blender debug .blend is generated with all layers
(voxel grid, walkable, path, camera) overlaid on the original scene.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# BPY_PYTHON candidates (try local Blender first, then system)
# ---------------------------------------------------------------------------
_BPY_CANDIDATES = [
    "/home/kingy/blender/4.5/python/bin/python3.11",        # local WSL
    "/opt/blender/4.5/python/bin/python3.11",                # GCP/Linux
    "/mnt/c/Program Files/Blender Foundation/Blender 4.5/4.5/python/bin/python3.11",
]


def _find_bpy_python() -> str:
    for p in _BPY_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("No Blender Python found. Tried: " + str(_BPY_CANDIDATES))


def _run_step(name: str, mod: str, args: list, bpy_python: str) -> float:
    """Run a pipeline step and return elapsed seconds."""
    print(f"\n{'='*60}")
    print(f"  Step: {name}")
    print(f"  Module: {mod}")
    print(f"  Args: {' '.join(args)}")
    print(f"{'='*60}")
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    cmd = [bpy_python, "-m", mod] + args
    r = subprocess.run(cmd, env=env)
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"\n  FAILED with exit code {r.returncode} ({elapsed:.1f}s)")
        sys.exit(1)
    print(f"\n  OK ({elapsed:.1f}s)")
    return elapsed


def _print_summary(out: Path, timings: dict):
    """Print data summary from intermediate files."""
    import numpy as np

    print(f"\n{'='*60}")
    print("  PIPELINE SUMMARY")
    print(f"{'='*60}")

    # Timings
    print("\n  Step Timings:")
    total = 0
    for step, t in timings.items():
        print(f"    {step:20s}  {t:7.1f}s")
        total += t
    print(f"    {'TOTAL':20s}  {total:7.1f}s")

    # File sizes
    print("\n  Output Files:")
    for f in sorted(out.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            size = f.stat().st_size
            if size > 1024 * 1024:
                print(f"    {f.relative_to(out)!s:40s}  {size/1024/1024:.1f} MB")
            else:
                print(f"    {f.relative_to(out)!s:40s}  {size/1024:.1f} KB")

    # Voxel grid
    vg_path = out / "voxel_grid.npz"
    if vg_path.exists():
        vg = np.load(str(vg_path), allow_pickle=True)
        print(f"\n  Voxel Grid:")
        print(f"    grid size:    {vg['nx']}x{vg['ny']}x{vg['nz']}")
        print(f"    resolution:   {float(vg['res']):.2f} BU")
        print(f"    candidates:   {vg['candidates'].shape[0]}")
        print(f"    solid:        {vg['solid'].shape[0]}")
        print(f"    mode:         {vg['mode']}")
        print(f"    bounds:       {vg['bounds']}")

    # Walkable
    wk_path = out / "walkable.npz"
    if wk_path.exists():
        wk = np.load(str(wk_path), allow_pickle=True)
        print(f"\n  Walkable:")
        print(f"    walkable voxels:  {wk['walkable'].shape[0]}")

    # Path
    pd_path = out / "path.npz"
    if pd_path.exists():
        pd = np.load(str(pd_path), allow_pickle=True)
        pp = pd["path_points"]
        wp = pd["waypoints"]
        print(f"\n  Path:")
        print(f"    waypoints:    {wp.shape[0]}")
        print(f"    path_points:  {pp.shape[0]}")
        print(f"    tour order:   {pd['tour']}")
        print(f"    X range:      [{pp[:,0].min():.1f}, {pp[:,0].max():.1f}]")
        print(f"    Y range:      [{pp[:,1].min():.1f}, {pp[:,1].max():.1f}]")
        print(f"    Z range:      [{pp[:,2].min():.1f}, {pp[:,2].max():.1f}]")
        # Path length
        diffs = np.diff(pp, axis=0)
        lengths = np.linalg.norm(diffs, axis=1)
        total_len = lengths.sum()
        print(f"    total length: {total_len:.1f} BU")

    # Camera orient
    wp_path = out / "wp_schedule.json"
    if wp_path.exists():
        with open(wp_path) as f:
            wps = json.load(f)
        print(f"\n  Camera Orient:")
        print(f"    waypoint orientations: {len(wps)}")
        for i, w in enumerate(wps[:3]):
            print(f"      wp[{i}]: t={w['t']:.3f}  quat={w['quat']}")
        if len(wps) > 3:
            print(f"      ... ({len(wps) - 3} more)")

    # Frames
    frames_dir = out / "frames"
    if frames_dir.exists():
        frames = sorted(frames_dir.glob("frame_*.png"))
        print(f"\n  Rendered Frames:")
        print(f"    count:  {len(frames)}")
        if frames:
            from PIL import Image
            img = Image.open(frames[0])
            print(f"    size:   {img.size[0]}x{img.size[1]}")


def main():
    parser = argparse.ArgumentParser(
        description="Debug walkthrough pipeline with full intermediate output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--blend", required=True, help="Input .blend file")
    parser.add_argument("--snake", required=True, help="Path to snake_mesh.npz")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--width", type=int, default=480, help="Render width (default: 480)")
    parser.add_argument("--height", type=int, default=360, help="Render height (default: 360)")
    parser.add_argument("--samples", type=int, default=16, help="Render samples (default: 16)")
    parser.add_argument("--fps", type=int, default=12, help="FPS (default: 12)")
    parser.add_argument("--duration", type=float, default=10, help="Max duration seconds (default: 10)")
    parser.add_argument("--gaze", default="smooth_adaptive",
                        choices=["smooth_adaptive", "waypoint", "eye_level", "free"],
                        help="Gaze mode (default: smooth_adaptive)")
    parser.add_argument("--engine", default="BLENDER_WORKBENCH",
                        choices=["BLENDER_WORKBENCH", "CYCLES", "BLENDER_EEVEE"],
                        help="Render engine (default: BLENDER_WORKBENCH)")
    parser.add_argument("--config", default=None, help="Base config JSON (default: configs/standard_scene.json)")
    parser.add_argument("--no-render", action="store_true", help="Skip render step")
    parser.add_argument("--visualize", action="store_true",
                        help="Generate debug .blend with all visualization layers")
    parser.add_argument("--resume", action="store_true",
                        help="Skip steps whose output files already exist")
    args = parser.parse_args()

    # Resolve paths
    project_root = Path(__file__).resolve().parents[1]
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))

    blend = str(Path(args.blend).resolve())
    snake = str(Path(args.snake).resolve())
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    bpy_python = _find_bpy_python()
    print(f"Using Blender Python: {bpy_python}")

    # Build config
    config_base = args.config or str(project_root / "configs" / "standard_scene.json")
    with open(config_base) as f:
        config = json.load(f)

    config.update({
        "aerial": True,
        "snake_npz": snake,
        "waypoint_gaze_mode": args.gaze,
        "render_engine": args.engine,
        "render_width": args.width,
        "render_height": args.height,
        "render_samples": args.samples,
        "fps": args.fps,
        "max_duration_seconds": args.duration,
    })

    config_path = str(out / "_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config saved: {config_path}")

    # Define step outputs
    vg_path = str(out / "voxel_grid.npz")
    wk_path = str(out / "walkable.npz")
    pd_path = str(out / "path.npz")
    orient_path = str(out / "wp_schedule.json")
    blend_stem = Path(blend).stem
    blend_out = str(out / f"{blend_stem}_walkthrough.blend")

    timings = {}

    # Step 1: voxel_grid
    if args.resume and os.path.exists(vg_path):
        print(f"\n[SKIP] voxel_grid (found {vg_path})")
    else:
        timings["1_voxel_grid"] = _run_step(
            "voxel_grid",
            "genesis_tools.walkthrough_renderer.pipeline.voxel_grid",
            ["--blend", blend, "--config", config_path, "--output", vg_path],
            bpy_python,
        )

    # Step 2: walkable
    if args.resume and os.path.exists(wk_path):
        print(f"\n[SKIP] walkable (found {wk_path})")
    else:
        timings["2_walkable"] = _run_step(
            "walkable",
            "genesis_tools.walkthrough_renderer.pipeline.walkable",
            ["--blend", blend, "--voxel-grid", vg_path,
             "--config", config_path, "--output", wk_path],
            bpy_python,
        )

    # Step 3: path_plan
    if args.resume and os.path.exists(pd_path):
        print(f"\n[SKIP] path_plan (found {pd_path})")
    else:
        timings["3_path_plan"] = _run_step(
            "path_plan",
            "genesis_tools.walkthrough_renderer.pipeline.path_plan",
            ["--voxel-grid", vg_path, "--walkable", wk_path,
             "--blend", blend, "--config", config_path, "--output", pd_path],
            bpy_python,
        )

    # Step 4: camera_orient
    if args.resume and os.path.exists(orient_path):
        print(f"\n[SKIP] camera_orient (found {orient_path})")
    else:
        timings["4_camera_orient"] = _run_step(
            "camera_orient",
            "genesis_tools.walkthrough_renderer.pipeline.camera_orient",
            ["--blend", blend, "--path", pd_path,
             "--config", config_path, "--output", orient_path],
            bpy_python,
        )

    # Step 5: camera_animate
    if args.resume and os.path.exists(blend_out):
        print(f"\n[SKIP] camera_animate (found {blend_out})")
    else:
        timings["5_camera_animate"] = _run_step(
            "camera_animate",
            "genesis_tools.walkthrough_renderer.pipeline.camera_animate",
            ["--blend", blend, "--path", pd_path, "--orient", orient_path,
             "--config", config_path, "--output-blend", blend_out],
            bpy_python,
        )

    # Step 6: render (optional)
    if not args.no_render:
        frames_dir = out / "frames"
        if args.resume and frames_dir.exists() and len(list(frames_dir.glob("frame_*.png"))) > 0:
            print(f"\n[SKIP] render (found frames in {frames_dir})")
        else:
            timings["6_render"] = _run_step(
                "render",
                "genesis_tools.walkthrough_renderer.pipeline.render",
                ["--blend", blend_out, "--config", config_path,
                 "--output", str(out / "frames")],
                bpy_python,
            )

    # Visualize (optional)
    if args.visualize:
        viz_blend = str(out / f"{blend_stem}_debug_viz.blend")
        viz_args = [
            "--blend", blend,
            "--output", viz_blend,
            "--voxel-grid", vg_path,
            "--walkable", wk_path,
            "--path", pd_path,
            "--config", config_path,
        ]
        if os.path.exists(blend_out):
            viz_args += ["--camera", blend_out]
        timings["viz"] = _run_step(
            "visualize",
            "genesis_tools.walkthrough_renderer.visualize",
            viz_args,
            bpy_python,
        )

    # Summary
    _print_summary(out, timings)

    # Dump comparison data for cross-platform verification
    dump_path = out / "debug_dump.json"
    import numpy as np
    dump = {}
    if os.path.exists(vg_path):
        vg = np.load(vg_path, allow_pickle=True)
        dump["voxel_grid"] = {
            "grid": f"{vg['nx']}x{vg['ny']}x{vg['nz']}",
            "res": float(vg["res"]),
            "candidates": int(vg["candidates"].shape[0]),
            "solid": int(vg["solid"].shape[0]),
        }
    if os.path.exists(wk_path):
        wk = np.load(wk_path, allow_pickle=True)
        dump["walkable"] = {"count": int(wk["walkable"].shape[0])}
    if os.path.exists(pd_path):
        pd = np.load(pd_path, allow_pickle=True)
        pp = pd["path_points"]
        dump["path"] = {
            "waypoints": int(pd["waypoints"].shape[0]),
            "path_points": int(pp.shape[0]),
            "tour": pd["tour"].tolist(),
            "first_point": pp[0].tolist(),
            "last_point": pp[-1].tolist(),
            "z_range": [float(pp[:, 2].min()), float(pp[:, 2].max())],
        }
    with open(dump_path, "w") as f:
        json.dump(dump, f, indent=2)
    print(f"\n  Debug dump saved: {dump_path}")
    print(f"  (Use this file for cross-platform comparison)")


if __name__ == "__main__":
    main()
