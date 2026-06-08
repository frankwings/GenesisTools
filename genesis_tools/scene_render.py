"""Unified scene renderer for Genesis blend files.

Three rendering modes:
  - object   : Orbiting camera rotation GIF (render_scene_rotation_gif).
                Best for isolated single-object .blend files with no environment.
  - indoor   : Aerial walkthrough (render_scene_walkthrough, aerial=True).
                Best for room / interior scenes with walls and furniture.
  - outdoor  : Terrain walkthrough (Phase 1: TerrainSnake fit → Phase 2: ground-level render).
                Best for large Infinigen nature scenes.

Auto-detection (when mode="auto") — three-stage geometric classifier:

  Stage 1 — File size  (fast, no Blender needed):
    < _OBJECT_SIZE_MB (50 MB)   → object   (small isolated mesh)
    ≥ _OBJECT_SIZE_MB           → Stage 2

  Stage 2 — Scene bounds  (Blender subprocess, 90 s timeout):
    > _SKIP_BOUNDS_MB (1500 MB) → outdoor  (too large to inspect quickly;
                                            only Infinigen terrain produces files this big)
    50–1500 MB                  → load blend, measure world-space extents → Stage 3

  Stage 3 — Flatness ratio = max(X_extent, Y_extent) / Z_extent:
    ratio > _FLAT_RATIO (5.0)   → outdoor  (wide, flat terrain plane)
    ratio ≤ _FLAT_RATIO         → indoor   (cube-like room or 3-D object)
    Z ≈ 0                       → object   (degenerate flat mesh)

  Real-world examples:
    Infinigen alpine meadow  200 × 200 × 25 m  ratio=8.0  → outdoor ✓
    Living room                8 ×  5 ×  3 m  ratio=2.7  → indoor  ✓
    Ceramic teapot           0.4 × 0.4 × 1.2 m ratio=0.3  → indoor  ✓
    Desert canyon            180 × 180 × 30 m  ratio=6.0  → outdoor ✓

  Tune thresholds at top of file:  _OBJECT_SIZE_MB, _SKIP_BOUNDS_MB, _FLAT_RATIO

CLI usage::

    python -m genesis_tools.scene_render \\
        --blend scene.blend --mode outdoor --output-dir out/walkthrough

    python -m genesis_tools.scene_render \\
        --blend obj.blend --mode object --frames 36 --elevation 30

Python usage::

    from genesis_tools.scene_render import render

    result = render(
        blend_path="scene.blend",
        mode="outdoor",          # "object" | "indoor" | "outdoor" | "auto"
        output_dir="out/",
    )
    print(result["gif"])
    print(result["mode_used"])
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Union

# ── Paths ─────────────────────────────────────────────────────────────────────
_TOOLS_ROOT  = Path(__file__).resolve().parent.parent   # GenesisTools/
_CONFIGS_DIR = _TOOLS_ROOT / "configs"
_FIT_SCRIPT  = _TOOLS_ROOT / "genesis_tools" / "active_contour" / "fit_terrain_contour.py"
_BLENDER     = "/home/kingy/blender/blender"

# ── Auto-detection thresholds (tune here) ─────────────────────────────────────
_OBJECT_SIZE_MB      = 50      # files smaller than this → object mode
_SKIP_BOUNDS_MB      = 1500    # files larger than this skip bounds check → outdoor
_FLAT_RATIO          = 5.0     # max(X,Y) / Z > threshold → outdoor (flat terrain)
_BOUNDS_TIMEOUT_S    = 90      # seconds to wait for the bounds subprocess


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def render(
    blend_path: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    mode: str = "auto",
    # ── object mode overrides ─────────────────────────────────────────────────
    obj_frames: int = 36,
    obj_resolution: int = 720,
    obj_elevation: int = 25,
    obj_duration_ms: int = 60,
    # ── indoor / outdoor shared overrides ────────────────────────────────────
    render_engine: str = "CYCLES",
    render_width: int = 1280,
    render_height: int = 720,
    render_samples: int = 64,
    use_denoise: bool = True,
    fps: int = 12,
    max_duration_seconds: float = 60.0,
    num_waypoints: int = 20,
    # ── indoor-specific overrides ─────────────────────────────────────────────
    indoor_grid_resolution: float = 0.5,
    indoor_max_grid_cells_xy: int = 80,
    indoor_max_grid_cells_z: int = 40,
    indoor_camera_height: float = 1.7,
    indoor_walk_speed: float = 2.0,
    # ── outdoor-specific overrides ────────────────────────────────────────────
    outdoor_camera_height: float = None,   # None = auto-detect from scene camera + terrain
    outdoor_walk_speed: float = 5.0,
    outdoor_mark_particles: bool = True,
    outdoor_particle_block_margin: float = 1.5,
    outdoor_terrain_boundary_margin: int = 1,
    # ── optional pre-computed terrain npz (skips Phase 1 if given) ────────────
    terrain_npz: Union[str, Path, None] = None,
    # ── Blender executable ────────────────────────────────────────────────────
    blender: str = _BLENDER,
    # ── re-render control ─────────────────────────────────────────────────────
    force_rerender: bool = False,   # clear walkthrough intermediates and re-render
                                    # (terrain_snake.npz is always preserved)
) -> dict:
    """Render a blend file using the appropriate mode.

    Args:
        blend_path:   Path to the .blend file.
        output_dir:   Directory for all output files.
        mode:         "auto" | "object" | "indoor" | "outdoor"
        ...           See module docstring for per-mode parameters.
        blender:      Path to Blender executable.

    Returns:
        dict with keys:
          gif         – Path to output GIF (str)
          mode_used   – Resolved mode ("object" / "indoor" / "outdoor")
          extras      – Mode-specific extra outputs (terrain_npz, blend_output, …)
    """
    blend_path = Path(blend_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not blend_path.exists():
        raise FileNotFoundError(f"blend not found: {blend_path}")

    # ── Mode resolution ────────────────────────────────────────────────────────
    mode = _resolve_mode(blend_path, mode, terrain_npz, blender=blender)
    print(f"[scene_render] mode={mode}  blend={blend_path.name}")

    if mode == "object":
        return _render_object(blend_path, output_dir,
                              frames=obj_frames, resolution=obj_resolution,
                              elevation=obj_elevation, duration=obj_duration_ms,
                              blender=blender)

    if mode == "indoor":
        return _render_indoor(blend_path, output_dir,
                              render_engine=render_engine,
                              render_width=render_width, render_height=render_height,
                              render_samples=render_samples, use_denoise=use_denoise,
                              fps=fps, max_duration_seconds=max_duration_seconds,
                              num_waypoints=num_waypoints,
                              grid_resolution=indoor_grid_resolution,
                              max_grid_cells_xy=indoor_max_grid_cells_xy,
                              max_grid_cells_z=indoor_max_grid_cells_z,
                              camera_height=indoor_camera_height,
                              walk_speed=indoor_walk_speed)

    if mode == "outdoor":
        return _render_outdoor(blend_path, output_dir,
                               render_engine=render_engine,
                               render_width=render_width, render_height=render_height,
                               render_samples=render_samples, use_denoise=use_denoise,
                               fps=fps, max_duration_seconds=max_duration_seconds,
                               num_waypoints=num_waypoints,
                               camera_height=outdoor_camera_height,
                               walk_speed=outdoor_walk_speed,
                               mark_particles=outdoor_mark_particles,
                               particle_block_margin=outdoor_particle_block_margin,
                               terrain_boundary_margin=outdoor_terrain_boundary_margin,
                               terrain_npz=terrain_npz,
                               blender=blender,
                               force_rerender=force_rerender)

    raise ValueError(f"Unknown mode: {mode}")


# ══════════════════════════════════════════════════════════════════════════════
# Mode-specific renderers
# ══════════════════════════════════════════════════════════════════════════════

def _render_object(blend_path: Path, output_dir: Path, *,
                   frames: int, resolution: int, elevation: int,
                   duration: int, blender: str) -> dict:
    """Orbit camera rotation GIF — for isolated single-object scenes."""
    sys.path.insert(0, str(_TOOLS_ROOT))
    from genesis_tools.rotation_renderer import render_scene_rotation_gif

    t0 = time.time()
    gif = render_scene_rotation_gif(
        blend_path=blend_path,
        output_dir=output_dir,
        frames=frames,
        resolution=resolution,
        elevation=elevation,
        blender_command=blender,
        duration=duration,
    )
    print(f"[scene_render] object rotation done in {time.time()-t0:.0f}s → {gif}")
    # Assemble MP4 from rotation frames (named scene_y_*.png)
    rot_frames = sorted((output_dir / "frames").glob("scene_y_*.png"),
                        key=lambda p: int(p.stem.split("_")[-1]))
    mp4 = _assemble_mp4(output_dir, blend_path.stem + "_rotation.mp4",
                        fps=int(1000 / duration), frames=rot_frames or None)
    result = {"gif": str(gif), "mode_used": "object",
              "extras": {"mp4": str(mp4) if mp4 else None}}
    _write_render_readme(output_dir, "object", blend_path, gif, mp4, result["extras"])
    return result


def _render_indoor(blend_path: Path, output_dir: Path, *,
                   render_engine, render_width, render_height,
                   render_samples, use_denoise, fps, max_duration_seconds,
                   num_waypoints, grid_resolution, max_grid_cells_xy,
                   max_grid_cells_z, camera_height, walk_speed) -> dict:
    """Aerial walkthrough — for indoor / room scenes."""
    sys.path.insert(0, str(_TOOLS_ROOT))
    from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run
    from genesis_tools.gif_generator import create_gif

    config = _load_config("standard_scene.json")
    config.update({
        "aerial":               True,
        "path_planner":         "theta_star",
        "grid_resolution":      grid_resolution,
        "max_grid_cells_xy":    max_grid_cells_xy,
        "max_grid_cells_z":     max_grid_cells_z,
        "camera_height":        camera_height,
        "walk_speed_mps":       walk_speed,
        "fps":                  fps,
        "max_duration_seconds": max_duration_seconds,
        "num_waypoints":        num_waypoints,
        "render_engine":        render_engine,
        "render_width":         render_width,
        "render_height":        render_height,
        "render_samples":       render_samples,
        "use_denoise":          use_denoise,
    })

    t0 = time.time()
    wt_run(str(blend_path), config, str(output_dir), render=True)
    print(f"[scene_render] indoor walkthrough done in {time.time()-t0:.0f}s")

    gif = _assemble_gif(output_dir, blend_path.stem + "_indoor_walkthrough.gif", fps=fps)
    mp4 = _assemble_mp4(output_dir, blend_path.stem + "_indoor_walkthrough.mp4", fps=fps)
    extras = {"blend_output": str(next(output_dir.glob("*.blend"), "")),
              "mp4": str(mp4) if mp4 else None}
    _write_render_readme(output_dir, "indoor", blend_path, gif, mp4, extras)
    return {"gif": str(gif), "mode_used": "indoor", "extras": extras}


def _render_outdoor(blend_path: Path, output_dir: Path, *,
                    render_engine, render_width, render_height,
                    render_samples, use_denoise, fps, max_duration_seconds,
                    num_waypoints, camera_height, walk_speed,
                    mark_particles, particle_block_margin,
                    terrain_boundary_margin, terrain_npz, blender: str,
                    force_rerender: bool = False) -> dict:
    """Terrain walkthrough — Phase 1: TerrainSnake fit, Phase 2: ground-level render."""
    sys.path.insert(0, str(_TOOLS_ROOT))
    from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run
    from genesis_tools.gif_generator import create_gif
    from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif
    import shutil

    # ── force_rerender: clear walkthrough intermediates (preserve terrain_snake.npz) ──
    if force_rerender:
        _INTERMEDIATES = ["voxel_grid.npz", "walkable.npz", "path.npz",
                          "camera_orient.npz", "camera_animate.npz"]
        for name in _INTERMEDIATES:
            p = output_dir / name
            if p.exists():
                p.unlink()
                print(f"[scene_render] force_rerender: removed {p.name}")
        frames_dir = output_dir / "frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
            print(f"[scene_render] force_rerender: cleared frames/")
        for blend_out in output_dir.glob("walkthrough*.blend"):
            blend_out.unlink()
            print(f"[scene_render] force_rerender: removed {blend_out.name}")

    config = _load_config("terrain_scene.json")
    config.update({
        "aerial":                    False,
        "grid_resolution":           "auto",
        "waypoint_gaze_mode":        "smooth_adaptive",  # offline bidir Gaussian yaw+pitch
        "walk_speed_mps":            walk_speed,
        "fps":                       fps,
        "max_duration_seconds":      max_duration_seconds,
        "num_waypoints":             num_waypoints,
        "render_engine":             render_engine,
        "render_width":              render_width,
        "render_height":             render_height,
        "render_samples":            render_samples,
        "use_denoise":               use_denoise,
        "mark_particle_instances":   mark_particles,
        "particle_block_margin":     particle_block_margin,
        "terrain_boundary_margin":   terrain_boundary_margin,
    })

    npz_path = Path(terrain_npz) if terrain_npz else (output_dir / "terrain_snake.npz")

    # ── Phase 1: fit TerrainSnake (skip if npz already present) ───────────────
    if npz_path.exists():
        print(f"[scene_render] Phase 1: reusing {npz_path}")
    else:
        print(f"[scene_render] Phase 1: fitting TerrainSnake cloth…")
        t0 = time.time()
        subprocess.run([
            blender, "--background", str(blend_path),
            "--python-exit-code", "1", "--python", str(_FIT_SCRIPT), "--",
            "--blend",                    str(blend_path),
            "--output-dir",               str(output_dir),
            "--grid-resolution",          str(config.get("terrain_snake_resolution", 2.0)),
            "--max-grid-cells-xy",        str(config["max_grid_cells_xy"]),
            "--env-sphere-percentile",    str(config["env_sphere_percentile"]),
            "--ray-samples",              str(config["terrain_ray_samples"]),
            "--alpha",                    str(config["terrain_alpha"]),
            "--gravity",                  str(config["terrain_gravity"]),
            "--dt",                       str(config["terrain_dt"]),
            "--max-iterations",           str(config["terrain_max_iterations"]),
            "--convergence-threshold",    str(config["terrain_convergence_threshold"]),
            "--start-height",             str(config["terrain_start_height"]),
            "--refine-pad-cells",         str(config["refine_pad_cells"]),
        ], check=True)
        print(f"[scene_render] Phase 1 done in {time.time()-t0:.0f}s → {npz_path}")

    # ── Auto camera height from initial scene camera ────────────────────────────
    if camera_height is None:
        camera_height = _camera_height_from_terrain_npz(npz_path)
    config["camera_height"] = camera_height

    config["terrain_npz"] = str(npz_path)

    # ── Phase 2: walkthrough render ────────────────────────────────────────────
    print(f"[scene_render] Phase 2: terrain walkthrough render…")
    t0 = time.time()
    wt_run(str(blend_path), config, str(output_dir), render=True)
    print(f"[scene_render] Phase 2 done in {time.time()-t0:.0f}s")

    gif    = _assemble_gif(output_dir, blend_path.stem + "_outdoor_walkthrough.gif", fps=fps)
    mp4    = _assemble_mp4(output_dir, blend_path.stem + "_outdoor_walkthrough.mp4", fps=fps)

    # ── Optional combined GIF with path overlay ────────────────────────────────
    combined_gif = None
    try:
        frames = _get_frames(output_dir)
        combined_gif = output_dir / (blend_path.stem + "_outdoor_walkthrough_combined.gif")
        make_combined_gif(frames, path_npz=output_dir / "path.npz",
                          terrain_npz=npz_path,
                          output_gif=combined_gif,
                          fps=fps, step=3, output_scale=0.5)
        print(f"[scene_render] combined GIF → {combined_gif}")
    except Exception as e:
        print(f"[scene_render] WARN: combined GIF failed: {e}")

    extras = {
        "terrain_npz":  str(npz_path),
        "combined_gif": str(combined_gif) if combined_gif else None,
        "blend_output": str(next(output_dir.glob("*.blend"), "")),
        "mp4":          str(mp4) if mp4 else None,
    }
    _write_render_readme(output_dir, "outdoor", blend_path, gif, mp4, extras)
    return {"gif": str(gif), "mode_used": "outdoor", "extras": extras}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_mode(blend_path: Path, mode: str,
                  terrain_npz: "Union[str, Path, None]",
                  blender: str = _BLENDER) -> str:
    """Three-stage auto-detection.

    Stage 1 — size: small → object.
    Stage 2 — bounds check: load blend, measure extents.
    Stage 3 — flatness ratio: flat → outdoor, cubic → indoor.
    """
    if mode != "auto":
        return mode

    size_mb = blend_path.stat().st_size / (1024 * 1024)
    print(f"[auto-detect] {blend_path.name}  size={size_mb:.0f} MB")

    # ── Stage 1: size ──────────────────────────────────────────────────────────
    if size_mb < _OBJECT_SIZE_MB:
        print(f"[auto-detect] → object  (size {size_mb:.0f} MB < {_OBJECT_SIZE_MB} MB)")
        return "object"

    # ── Stage 2: bounds ────────────────────────────────────────────────────────
    if size_mb > _SKIP_BOUNDS_MB:
        print(f"[auto-detect] file too large ({size_mb:.0f} MB > {_SKIP_BOUNDS_MB} MB)"
              f" — skipping bounds check → outdoor")
        return "outdoor"

    extents = _get_scene_extents(blend_path, blender)
    if extents is None:
        print(f"[auto-detect] bounds check failed — defaulting to outdoor")
        return "outdoor"

    x, y, z = extents
    print(f"[auto-detect] extents  X={x:.1f}  Y={y:.1f}  Z={z:.1f}")

    # ── Stage 3: flatness ratio ────────────────────────────────────────────────
    if z < 0.01:
        # Degenerate Z (flat mesh, no height) → treat as object
        print(f"[auto-detect] → object  (Z extent near-zero: {z:.3f})")
        return "object"

    ratio = max(x, y) / z
    print(f"[auto-detect] flatness ratio = {ratio:.2f}  (threshold {_FLAT_RATIO})")

    if ratio > _FLAT_RATIO:
        print(f"[auto-detect] → outdoor  (flat, ratio {ratio:.2f} > {_FLAT_RATIO})")
        return "outdoor"
    else:
        print(f"[auto-detect] → indoor   (cubic, ratio {ratio:.2f} ≤ {_FLAT_RATIO})")
        return "indoor"


def _get_scene_extents(blend_path: Path, blender: str) -> "tuple[float,float,float] | None":
    """Run a quick Blender subprocess to measure scene bounding box extents.

    Returns (x_extent, y_extent, z_extent) in Blender Units, or None on failure.
    Uses a timeout to avoid hanging on broken blends.
    """
    # Inline Python script — printed line "EXTENTS:x,y,z" is parsed back
    _BOUNDS_SCRIPT = (
        "import bpy, mathutils\n"
        "lo = mathutils.Vector((1e9,)*3)\n"
        "hi = mathutils.Vector((-1e9,)*3)\n"
        "objs = [o for o in bpy.data.objects if o.type in ('MESH','SURFACE','CURVES','VOLUME')]\n"
        "for o in objs:\n"
        "    for v in o.bound_box:\n"
        "        wv = o.matrix_world @ mathutils.Vector(v)\n"
        "        for i in range(3):\n"
        "            lo[i]=min(lo[i],wv[i]); hi[i]=max(hi[i],wv[i])\n"
        "if objs:\n"
        "    e=hi-lo; print(f'EXTENTS:{e.x:.4f},{e.y:.4f},{e.z:.4f}')\n"
        "else:\n"
        "    print('EXTENTS:0,0,0')\n"
    )

    print(f"[auto-detect] loading blend to measure extents (timeout {_BOUNDS_TIMEOUT_S}s)…")
    try:
        result = subprocess.run(
            [blender, "--background", str(blend_path),
             "--python-expr", _BOUNDS_SCRIPT],
            capture_output=True, text=True,
            timeout=_BOUNDS_TIMEOUT_S,
        )
        for line in result.stdout.splitlines():
            if line.startswith("EXTENTS:"):
                x, y, z = map(float, line[8:].split(","))
                return x, y, z
        # Print stderr snippet for debugging
        if result.stderr:
            for ln in result.stderr.splitlines()[-5:]:
                print(f"  [blender] {ln}")
        return None
    except subprocess.TimeoutExpired:
        print(f"[auto-detect] bounds check timed out after {_BOUNDS_TIMEOUT_S}s")
        return None
    except Exception as e:
        print(f"[auto-detect] bounds check error: {e}")
        return None


def _camera_height_from_terrain_npz(npz_path: Path) -> float:
    """Infer camera eye-height from the initial camera stored in terrain_snake.npz.

    Phase 1 (fit_terrain_contour) saves the active Blender camera position as
    `camera_xyz = [cam_x, cam_y, cam_z]` in the npz.  We look up the terrain
    surface height at that (x, y) cell and return the vertical offset.

    Falls back to 1.7 m if any required key is missing or the maths goes wrong.
    """
    import numpy as np
    try:
        data = np.load(str(npz_path))
        if "camera_xyz" not in data.files or "heightmap" not in data.files:
            print(f"[scene_render] camera_height: npz missing keys → fallback 1.7")
            return 1.7
        camera_xyz = data["camera_xyz"]             # [cam_x, cam_y, cam_z]
        heightmap  = data["heightmap"].astype(np.float64)  # (fine_nx, fine_ny)
        bounds     = [float(b) for b in data["bounds"]]    # [min_x, min_y, max_x, max_y, ...]
        fine_res   = float(data["res"])
        unit_scale = float(data["unit_scale"]) if "unit_scale" in data.files else 1.0

        cam_x, cam_y, cam_z = float(camera_xyz[0]), float(camera_xyz[1]), float(camera_xyz[2])
        min_x, min_y = bounds[0], bounds[1]
        fine_nx, fine_ny = heightmap.shape
        ix = int((cam_x - min_x) / fine_res)
        iy = int((cam_y - min_y) / fine_res)
        ix = max(0, min(fine_nx - 1, ix))
        iy = max(0, min(fine_ny - 1, iy))

        terrain_z   = heightmap[ix, iy]
        height_bu   = cam_z - terrain_z           # Blender units
        height_m    = height_bu * unit_scale       # metres
        height_m    = max(1.0, height_m)           # at least 1 m
        print(f"[scene_render] camera_height auto-detected: {height_m:.2f} m "
              f"(cam_z={cam_z:.2f}, terrain_z={terrain_z:.2f}, scale={unit_scale})")
        return float(height_m)
    except Exception as exc:
        print(f"[scene_render] camera_height auto-detect failed ({exc}) → fallback 1.7")
        return 1.7


def _load_config(filename: str) -> dict:
    with open(_CONFIGS_DIR / filename) as f:
        cfg = json.load(f)
    cfg.pop("_description", None)
    return cfg


def _get_frames(output_dir: Path):
    return sorted((output_dir / "frames").glob("frame_*.png"),
                  key=lambda p: int(p.stem.split("_")[1]))


def _assemble_gif(output_dir: Path, gif_name: str, fps: int) -> Path:
    sys.path.insert(0, str(_TOOLS_ROOT))
    from genesis_tools.gif_generator import create_gif
    frames = _get_frames(output_dir)
    gif = output_dir / gif_name
    if frames:
        create_gif(frames, gif, duration=int(1000 / fps))
        print(f"[scene_render] GIF → {gif}  ({len(frames)} frames)")
    else:
        print(f"[scene_render] WARN: no frames found in {output_dir}/frames")
    return gif


def _assemble_mp4(output_dir: Path, mp4_name: str, fps: int,
                  frames: "list | None" = None) -> "Path | None":
    """Assemble rendered frames into an MP4 using ffmpeg.

    Uses a concat file-list so frame numbers need not be zero-padded or
    sequential — works with any glob-sorted list.
    Returns the output Path, or None if ffmpeg is unavailable or no frames exist.
    """
    if frames is None:
        frames = _get_frames(output_dir)
    if not frames:
        print(f"[scene_render] WARN: no frames for MP4 in {output_dir}/frames")
        return None

    mp4 = output_dir / mp4_name
    list_file = output_dir / "_ffmpeg_list.txt"
    try:
        with open(list_file, "w") as fh:
            for f in frames:
                fh.write(f"file '{f.resolve()}'\n"
                         f"duration {1.0 / fps}\n")
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-crf", "18", "-movflags", "+faststart",
                str(mp4),
            ],
            capture_output=True, text=True,
        )
        list_file.unlink(missing_ok=True)
        if result.returncode == 0:
            print(f"[scene_render] MP4 → {mp4}  ({len(frames)} frames)")
            return mp4
        else:
            print(f"[scene_render] WARN: ffmpeg failed: {result.stderr[-200:]}")
            return None
    except FileNotFoundError:
        print("[scene_render] WARN: ffmpeg not found — skipping MP4")
        list_file.unlink(missing_ok=True)
        return None
    except Exception as e:
        print(f"[scene_render] WARN: MP4 assembly error: {e}")
        list_file.unlink(missing_ok=True)
        return None


def _write_render_readme(output_dir: Path, mode: str, blend_path: Path,
                         gif: Path, mp4: "Path | None",
                         extras: dict) -> None:
    """Write a human-readable README.md describing what was rendered and how."""
    from datetime import datetime
    lines = [
        f"# Render Output — {blend_path.name}",
        f"",
        f"**Mode**: `{mode}`  ",
        f"**Source**: `{blend_path}`  ",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"",
        f"## Output Files",
        f"",
        f"| File | Description |",
        f"|------|-------------|",
        f"| `{gif.name}` | Animated GIF walkthrough |",
    ]
    if mp4:
        lines.append(f"| `{mp4.name}` | MP4 video (H.264, faststart) |")
    if mode == "outdoor":
        npz = extras.get("terrain_npz", "")
        combined = extras.get("combined_gif", "")
        blend_out = extras.get("blend_output", "")
        if combined:
            lines.append(f"| `{Path(combined).name}` | Combined GIF: rendered frames + path overlay on heightmap |")
        if blend_out:
            lines.append(f"| `{Path(blend_out).name}` | Animated Blender scene with WalkthroughCamera keyframes |")
        if npz:
            lines.append(f"| `terrain_snake.npz` | TerrainSnake cloth heightmap (Phase 1 output) |")
        lines += [
            f"",
            f"## Outdoor Pipeline",
            f"",
            f"### Phase 1 — TerrainSnake Fit (`fit_terrain_contour.py`)",
            f"Runs a cloth-simulation active-contour over the terrain mesh to produce a smooth",
            f"heightmap stored in `terrain_snake.npz`.  Skipped automatically if the file already exists.",
            f"",
            f"Keys saved in `terrain_snake.npz`:",
            f"- `heightmap` — 2-D float array of terrain surface Z values (Blender Units)",
            f"- `bounds` — world-space `[min_x, min_y, max_x, max_y, min_z, max_z]`",
            f"- `res` — cell size (BU)",
            f"- `unit_scale` — Blender scene unit scale (BU→m)",
            f"- `camera_xyz` — original Blender active-camera world position",
            f"- `camera_lookat` — XY-projected forward direction of original camera",
            f"",
            f"### Phase 2 — Walkthrough Render",
            f"Six-step pipeline (each step saves a `.npz` / `.json` intermediate):",
            f"",
            f"| Step | File | Description |",
            f"|------|------|-------------|",
            f"| 1 | `voxel_grid.npz` | Occupancy voxel grid (walkable surface detection) |",
            f"| 2 | `walkable.npz` | Walkable cells extracted from voxel grid |",
            f"| 3 | `path.npz` | Camera path (waypoints + dense path points) |",
            f"| 4 | `wp_schedule.json` | Per-waypoint camera orientation quaternions |",
            f"| 5 | `*_walkthrough.blend` | Animated blend with WalkthroughCamera keyframes |",
            f"| 6 | `frames/` | Rendered PNG frames |",
            f"",
            f"### Camera Orientation — `smooth_adaptive` mode",
            f"",
            f"Yaw and pitch are computed independently, then smoothed offline with",
            f"**bidirectional zero-phase Gaussian filtering** (no real-time causal lag):",
            f"",
            f"```",
            f"Yaw   : path tangent direction → np.unwrap → bidir Gaussian (σ≈1.5 s)",
            f"Pitch : heightmap lookup 15 m ahead → atan2 → clamp [-15°, +8°]",
            f"              → bidir Gaussian (σ≈0.8 s)",
            f"```",
            f"",
            f"Bidirectional = forward pass + backward pass, each with σ/√2,",
            f"so the combined effective σ equals the configured value.",
            f"This gives symmetric ease-in / ease-out unlike one-way EMA.",
            f"",
            f"### Combined GIF",
            f"",
            f"`{Path(combined).name if combined else 'N/A'}` overlays the rendered frames",
            f"(right) with a top-down 2-D map (left) showing:",
            f"- Heightmap colour-coded by elevation",
            f"- Planned path (white line)",
            f"- Current camera position (red dot)",
            f"",
            f"Generated by `genesis_tools/walkthrough_renderer/combined_gif.py`.",
        ]
    elif mode == "indoor":
        lines += [
            f"",
            f"## Indoor Pipeline (Aerial Walkthrough)",
            f"",
            f"Uses theta-star 3-D pathfinding with `aerial=True`.",
            f"Camera flies through the space rather than walking on the floor.",
            f"Render engine: WORKBENCH (fast preview).",
        ]
    elif mode == "object":
        lines += [
            f"",
            f"## Object Mode (Rotation GIF)",
            f"",
            f"Orbiting camera circles the scene bounding box at a fixed elevation.",
            f"Rendered via `genesis_tools/rotation_renderer.py`.",
        ]

    lines.append("")
    readme = output_dir / "README.md"
    readme.write_text("\n".join(lines), encoding="utf-8")
    print(f"[scene_render] README → {readme}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

def _main():
    p = argparse.ArgumentParser(
        description="Unified Genesis scene renderer (object / indoor / outdoor)"
    )
    p.add_argument("--blend",        required=True,  help="Path to .blend file")
    p.add_argument("--output-dir",   required=True,  help="Output directory")
    p.add_argument("--mode",         default="auto",
                   choices=["auto", "object", "indoor", "outdoor"],
                   help="Render mode (default: auto)")
    p.add_argument("--blender",      default=_BLENDER, help="Path to Blender")
    p.add_argument("--terrain-npz",  default=None,
                   help="[outdoor] Pre-computed terrain_snake.npz (skips Phase 1)")

    # Object mode
    p.add_argument("--frames",       type=int,   default=36,    help="[object] Rotation frames")
    p.add_argument("--resolution",   type=int,   default=720,   help="[object] Render resolution px")
    p.add_argument("--elevation",    type=int,   default=25,    help="[object] Camera elevation degrees")

    # Shared
    p.add_argument("--engine",       default="CYCLES",
                   choices=["CYCLES", "EEVEE", "WORKBENCH"],
                   help="Render engine (indoor/outdoor)")
    p.add_argument("--width",        type=int,   default=1280,  help="Render width px")
    p.add_argument("--height",       type=int,   default=720,   help="Render height px")
    p.add_argument("--samples",      type=int,   default=64,    help="Render samples")
    p.add_argument("--fps",          type=int,   default=12,    help="GIF fps")
    p.add_argument("--max-duration", type=float, default=60.0,  help="Max walkthrough seconds")
    p.add_argument("--waypoints",    type=int,   default=20,    help="Walkthrough waypoints")

    # Indoor
    p.add_argument("--indoor-grid-res",  type=float, default=0.5,  help="[indoor] Voxel grid resolution")
    p.add_argument("--indoor-cam-height",type=float, default=1.7,  help="[indoor] Camera height m")

    # Outdoor
    p.add_argument("--outdoor-cam-height",type=float, default=None,
                   help="[outdoor] Camera height m (default: auto-detect from scene camera)")
    p.add_argument("--no-particles",  action="store_true",
                   help="[outdoor] Skip particle blocking (open terrain)")
    p.add_argument("--force-rerender", action="store_true",
                   help="[outdoor] Clear walkthrough intermediates and re-render (preserves terrain_snake.npz)")

    args = p.parse_args()

    result = render(
        blend_path=args.blend,
        output_dir=args.output_dir,
        mode=args.mode,
        blender=args.blender,
        terrain_npz=args.terrain_npz,
        # object
        obj_frames=args.frames,
        obj_resolution=args.resolution,
        obj_elevation=args.elevation,
        # shared
        render_engine=args.engine,
        render_width=args.width,
        render_height=args.height,
        render_samples=args.samples,
        fps=args.fps,
        max_duration_seconds=args.max_duration,
        num_waypoints=args.waypoints,
        # indoor
        indoor_grid_resolution=args.indoor_grid_res,
        indoor_camera_height=args.indoor_cam_height,
        # outdoor
        outdoor_camera_height=args.outdoor_cam_height,
        outdoor_mark_particles=not args.no_particles,
        force_rerender=args.force_rerender,
    )

    print(f"\n✓ Render complete")
    print(f"  mode   : {result['mode_used']}")
    print(f"  gif    : {result['gif']}")
    if result.get("extras"):
        for k, v in result["extras"].items():
            if v:
                print(f"  {k:14}: {v}")


if __name__ == "__main__":
    _main()
