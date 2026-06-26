#!/usr/bin/env python3
"""Debug walkthrough pipeline — run all steps with full intermediate output.

Usage:
    # Indoor scene (active contour snake):
    python3 scripts/debug_walkthrough.py \
        --blend /path/to/scene.blend \
        --output results/debug_run \
        [--width 480] [--height 360] [--samples 16] \
        [--fps 12] [--duration 10] [--gaze smooth_adaptive] \
        [--no-render] [--visualize]

    # Outdoor/terrain scene (terrain snake via Blender raycasting):
    python3 scripts/debug_walkthrough.py \
        --blend /path/to/outdoor.blend \
        --output results/outdoor_run \
        --config configs/terrain_scene.json \
        [--no-render]

Mode is auto-detected from the config's "aerial" field:
  aerial=true  → indoor mode  → active contour snake (Step 0a)
  aerial=false → outdoor mode → terrain snake via blender --background (Step 0b)

The pipeline computes everything from scratch:
  Step 0: Fit snake mesh (indoor: active contour, outdoor: terrain cloth)
  Step 1: Build voxel grid from snake mesh
  Step 2: Flood-fill walkable voxels
  Step 3: Plan path (waypoints + smooth interpolation)
  Step 4: Compute camera orientations per waypoint
  Step 5: Create keyframed camera animation
  Step 6: Render frames (optional, skip with --no-render)

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
# BPY_PYTHON / BLENDER candidates
# ---------------------------------------------------------------------------
_BPY_CANDIDATES = [
    "/home/kingy/blender/4.5/python/bin/python3.11",        # local WSL
    "/opt/blender/4.5/python/bin/python3.11",                # GCP/Linux
    "/mnt/c/Program Files/Blender Foundation/Blender 4.5/4.5/python/bin/python3.11",
]

_BLENDER_CANDIDATES = [
    "/home/kingy/blender/blender",                           # local WSL
    "/opt/blender/blender",                                  # GCP/Linux
    "/usr/local/bin/blender",                                # system
]


def _find_bpy_python() -> str:
    for p in _BPY_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("No Blender Python found. Tried: " + str(_BPY_CANDIDATES))


def _find_blender() -> str:
    for p in _BLENDER_CANDIDATES:
        if os.path.isfile(p):
            return p
    # fallback: try PATH
    import shutil
    b = shutil.which("blender")
    if b:
        return b
    raise FileNotFoundError("No Blender found. Tried: " + str(_BLENDER_CANDIDATES))


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


def _run_snake_fitting(blend: str, output_dir: Path, blender: str,
                       alpha: float, beta: float, subdiv: int,
                       resume: bool) -> tuple[str, float]:
    """Run Step 0a: Active Contour snake fitting (indoor). Returns (snake_npz_path, elapsed)."""
    snake_dir = output_dir / "snake"
    snake_npz = snake_dir / "snake_mesh.npz"

    if resume and snake_npz.exists():
        print(f"\n[SKIP] snake_fitting (found {snake_npz})")
        return str(snake_npz), 0.0

    print(f"\n{'='*60}")
    print(f"  Step 0a: Snake Fitting (Active Contour — Indoor)")
    print(f"  alpha={alpha}  beta={beta}  subdivision_levels={subdiv}")
    print(f"{'='*60}")

    t0 = time.time()
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from genesis_tools.active_contour.fit_scene_contour import fit_scene_active_contour

    result = fit_scene_active_contour(
        blend_path=Path(blend),
        output_dir=snake_dir,
        alpha=alpha,
        beta=beta,
        subdivision_levels=subdiv,
        blender_command=blender,
    )
    elapsed = time.time() - t0

    print(f"\n  Snake: {result['snake_vertices']} vertices, "
          f"{result['snake_faces']} faces, "
          f"{result['sampled_points']:,} sampled points, "
          f"{result['snake_iterations']} iterations ({elapsed:.1f}s)")

    return str(snake_npz), elapsed


def _run_terrain_fitting(blend: str, output_dir: Path, blender: str,
                         config: dict, resume: bool) -> tuple[str, float]:
    """Run Step 0b: Terrain snake fitting (outdoor). Returns (terrain_npz_path, elapsed).

    Runs fit_terrain_contour.py via `blender --background` because it needs
    bpy's scene.ray_cast which requires a loaded scene.
    """
    terrain_npz = output_dir / "terrain_snake.npz"

    if resume and terrain_npz.exists():
        print(f"\n[SKIP] terrain_fitting (found {terrain_npz})")
        return str(terrain_npz), 0.0

    print(f"\n{'='*60}")
    print(f"  Step 0b: Terrain Snake Fitting (Outdoor)")
    print(f"  grid_resolution={config.get('terrain_snake_resolution', config.get('grid_resolution', 5.0))}")
    print(f"{'='*60}")

    project_root = Path(__file__).resolve().parents[1]
    fit_script = str(project_root / "genesis_tools" / "active_contour" / "fit_terrain_contour.py")

    cmd = [
        blender, "--background", blend,
        "--python-exit-code", "1", "--python", fit_script, "--",
        "--blend", blend,
        "--output-dir", str(output_dir),
        "--grid-resolution",       str(config.get("terrain_snake_resolution", config.get("grid_resolution", 5.0))),
        "--max-grid-cells-xy",     str(config.get("max_grid_cells_xy", 200)),
        "--env-sphere-percentile", str(config.get("env_sphere_percentile", 5.0)),
        "--ray-samples",           str(config.get("terrain_ray_samples", 1)),
        "--alpha",                 str(config.get("terrain_alpha", 0.5)),
        "--gravity",               str(config.get("terrain_gravity", 0.1)),
        "--dt",                    str(config.get("terrain_dt", 1.0)),
        "--max-iterations",        str(config.get("terrain_max_iterations", 200)),
        "--convergence-threshold", str(config.get("terrain_convergence_threshold", 1e-3)),
        "--start-height",          str(config.get("terrain_start_height", 1.7)),
        "--refine-pad-cells",      str(config.get("refine_pad_cells", 2)),
    ]

    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    r = subprocess.run(cmd, env=env)
    elapsed = time.time() - t0

    if r.returncode != 0:
        print(f"\n  FAILED with exit code {r.returncode} ({elapsed:.1f}s)")
        sys.exit(1)

    print(f"\n  Terrain snake saved: {terrain_npz} ({elapsed:.1f}s)")
    return str(terrain_npz), elapsed


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

    # Snake (indoor)
    snake_npz = out / "snake" / "snake_mesh.npz"
    if snake_npz.exists():
        sn = np.load(str(snake_npz), allow_pickle=True)
        print(f"\n  Snake Mesh (Indoor):")
        print(f"    vertices:  {sn['vertices'].shape[0]}")
        print(f"    faces:     {sn['faces'].shape[0]}")

    # Terrain snake (outdoor)
    terrain_npz = out / "terrain_snake.npz"
    if terrain_npz.exists():
        tn = np.load(str(terrain_npz), allow_pickle=True)
        print(f"\n  Terrain Snake (Outdoor):")
        for k in tn.files:
            arr = tn[k]
            if hasattr(arr, 'shape'):
                print(f"    {k:20s}  shape={arr.shape}  dtype={arr.dtype}")
            else:
                print(f"    {k:20s}  {arr}")

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
    parser.add_argument("--config", default=None,
                        help="Base config JSON (default: configs/standard_scene.json)")
    # Snake fitting parameters
    parser.add_argument("--snake-alpha", type=float, default=0.6,
                        help="Snake smoothness weight (default: 0.6)")
    parser.add_argument("--snake-beta", type=float, default=0.3,
                        help="Snake attraction weight (default: 0.3)")
    parser.add_argument("--snake-subdiv", type=int, default=2,
                        help="Snake convex hull subdivision levels (default: 2)")
    # Control flags
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
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    bpy_python = _find_bpy_python()
    blender = _find_blender()
    print(f"Using Blender Python: {bpy_python}")
    print(f"Using Blender:        {blender}")

    timings = {}

    # ── Load base config ──────────────────────────────────────────────────
    config_base = args.config or str(project_root / "configs" / "standard_scene.json")
    with open(config_base) as f:
        config = json.load(f)
    config.pop("_description", None)

    # Auto-detect mode from config: aerial=true → indoor, aerial=false → outdoor
    is_outdoor = not config.get("aerial", True)
    mode_label = "outdoor (terrain)" if is_outdoor else "indoor (active contour)"
    print(f"\nMode: {mode_label}  (aerial={config.get('aerial', True)})")

    # ── Step 0: Snake Fitting ──────────────────────────────────────────────
    if is_outdoor:
        # Outdoor: terrain snake via blender --background
        terrain_npz, t = _run_terrain_fitting(
            blend, out, blender, config, resume=args.resume,
        )
        if t > 0:
            timings["0_terrain_fitting"] = t
        config["terrain_npz"] = terrain_npz
    else:
        # Indoor: active contour snake
        snake_npz, t = _run_snake_fitting(
            blend, out, blender,
            alpha=args.snake_alpha,
            beta=args.snake_beta,
            subdiv=args.snake_subdiv,
            resume=args.resume,
        )
        if t > 0:
            timings["0_snake_fitting"] = t
        config["snake_npz"] = snake_npz

    # ── Build final config ─────────────────────────────────────────────────
    # Override render/playback params from CLI args (do NOT override aerial)
    config.update({
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
    print(f"\nConfig saved: {config_path}")

    # Define step outputs
    vg_path = str(out / "voxel_grid.npz")
    wk_path = str(out / "walkable.npz")
    pd_path = str(out / "path.npz")
    orient_path = str(out / "wp_schedule.json")
    blend_stem = Path(blend).stem
    blend_out = str(out / f"{blend_stem}_walkthrough.blend")

    # ── Step 1: voxel_grid ─────────────────────────────────────────────────
    if args.resume and os.path.exists(vg_path):
        print(f"\n[SKIP] voxel_grid (found {vg_path})")
    else:
        timings["1_voxel_grid"] = _run_step(
            "voxel_grid",
            "genesis_tools.walkthrough_renderer.pipeline.voxel_grid",
            ["--blend", blend, "--config", config_path, "--output", vg_path],
            bpy_python,
        )

    # ── Step 2: walkable ───────────────────────────────────────────────────
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

    # ── Step 3: path_plan ──────────────────────────────────────────────────
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

    # ── Step 4: camera_orient ──────────────────────────────────────────────
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

    # ── Step 5: camera_animate ─────────────────────────────────────────────
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

    # ── Step 6: render (optional) ──────────────────────────────────────────
    if not args.no_render:
        frames_dir = out / "frames"
        if args.resume and frames_dir.exists() and len(list(frames_dir.glob("frame_*.png"))) > 0:
            print(f"\n[SKIP] render (found frames in {frames_dir})")
        else:
            # render.py creates frames/ subdir internally, so pass output_dir=out
            timings["6_render"] = _run_step(
                "render",
                "genesis_tools.walkthrough_renderer.pipeline.render",
                ["--blend", blend_out, "--config", config_path,
                 "--output-dir", str(out)],
                bpy_python,
            )

    # ── Visualize (optional) ───────────────────────────────────────────────
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

    # ── Summary ────────────────────────────────────────────────────────────
    _print_summary(out, timings)

    # Dump comparison data for cross-platform verification
    dump_path = out / "debug_dump.json"
    import numpy as np
    dump = {}

    snake_path = out / "snake" / "snake_mesh.npz"
    if snake_path.exists():
        sn = np.load(str(snake_path), allow_pickle=True)
        dump["snake"] = {
            "vertices": int(sn["vertices"].shape[0]),
            "faces": int(sn["faces"].shape[0]),
        }
    terrain_path = out / "terrain_snake.npz"
    if terrain_path.exists():
        tn = np.load(str(terrain_path), allow_pickle=True)
        dump["terrain_snake"] = {
            k: list(tn[k].shape) if hasattr(tn[k], 'shape') else str(tn[k])
            for k in tn.files
        }
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
