"""Batch walkthrough for 6 new Code2Worlds scenes.

Outdoor (terrain mode — Phase1 TerrainSnake + Phase2 ground-level render):
  - alpine_meadow_sunrise
  - ancient_forest_waterfall
  - desert_canyon_sunset

Indoor (aerial mode — standard_scene config, Theta* path planner):
  - vintage_armchair
  - modern_dining_table
  - ceramic_teapot_set

Usage:
    python run_batch_walkthrough_new_scenes.py [--only outdoor|indoor|<name>]
"""
import sys, json, subprocess, shutil, argparse, time
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

RESULTS_ROOT = Path("/home/kingy/Projects/Genesis/GenesisTools/results")
ASSETS_ROOT  = Path("/home/kingy/Projects/Genesis/GenesisTools/docs/assets")
BLENDER      = "/home/kingy/blender/blender"
FIT_SCRIPT   = "/home/kingy/Projects/Genesis/GenesisTools/genesis_tools/active_contour/fit_terrain_contour.py"

# ── Config templates ───────────────────────────────────────────────────────────
with open("/home/kingy/Projects/Genesis/GenesisTools/configs/terrain_scene.json") as f:
    TERRAIN_BASE = json.load(f)
TERRAIN_BASE.pop("_description", None)

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/standard_scene.json") as f:
    STANDARD_BASE = json.load(f)
STANDARD_BASE.pop("_description", None)


# ══════════════════════════════════════════════════════════════════════════════
# OUTDOOR (terrain mode)
# ══════════════════════════════════════════════════════════════════════════════

OUTDOOR_SCENES = [
    {
        "name":  "alpine_meadow_sunrise",
        "blend": RESULTS_ROOT / "alpine_meadow_sunrise" / "scene_fine.blend",
        "out":   RESULTS_ROOT / "alpine_meadow_sunrise" / "walkthrough_terrain",
        "assets": ASSETS_ROOT / "alpine_meadow_sunrise",
        # Infinigen meadow scenes are open → no dense scatter filter needed
        "config_overrides": {
            "camera_height":            1.7,
            "grid_resolution":          "auto",
            "mark_particle_instances":  False,
            "walk_speed_mps":           5.0,
            "max_duration_seconds":     60.0,
            "render_engine":            "CYCLES",
            "render_width":             1280,
            "render_height":            720,
            "render_samples":           64,
            "use_denoise":              True,
            # Camera gaze: smooth_adaptive looks forward along terrain rather
            # than pitching down toward ground-level waypoints.
            "waypoint_gaze_mode":       "smooth_adaptive",
            "smooth_pitch_min_deg":     -8.0,   # max 8° downward
            "smooth_pitch_max_deg":      5.0,   # max 5° upward
            "smooth_pitch_lookahead_m": 20.0,   # look 20m ahead
            "smooth_pitch_sigma_s":      1.2,   # smooth pitch over 1.2s
            "smooth_yaw_sigma_s":        0.6,
        }
    },
    {
        "name":  "ancient_forest_waterfall",
        "blend": RESULTS_ROOT / "ancient_forest_waterfall" / "scene_fine.blend",
        "out":   RESULTS_ROOT / "ancient_forest_waterfall" / "walkthrough_terrain",
        "assets": ASSETS_ROOT / "ancient_forest_waterfall",
        # Dense forest — enable particle blocking to avoid walking through trees
        "config_overrides": {
            "camera_height":            1.7,
            "grid_resolution":          "auto",
            "particle_block_margin":    1.0,
            "terrain_boundary_margin":  2,
            "walk_speed_mps":           4.0,
            "max_duration_seconds":     60.0,
            "render_engine":            "CYCLES",
            "render_width":             1280,
            "render_height":            720,
            "render_samples":           64,
            "use_denoise":              True,
        }
    },
    {
        "name":  "desert_canyon_sunset",
        "blend": RESULTS_ROOT / "desert_canyon_sunset" / "scene_fine.blend",
        "out":   RESULTS_ROOT / "desert_canyon_sunset" / "walkthrough_terrain",
        "assets": ASSETS_ROOT / "desert_canyon_sunset",
        # Desert canyon — slightly elevated camera to clear scrub
        "config_overrides": {
            "camera_height":            2.5,
            "grid_resolution":          "auto",
            "mark_particle_instances":  False,
            "walk_speed_mps":           5.0,
            "max_duration_seconds":     60.0,
            "render_engine":            "CYCLES",
            "render_width":             1280,
            "render_height":            720,
            "render_samples":           64,
            "use_denoise":              True,
        }
    },
]

# ══════════════════════════════════════════════════════════════════════════════
# INDOOR (aerial mode)
# ══════════════════════════════════════════════════════════════════════════════

INDOOR_SCENES = [
    {
        "name":  "vintage_armchair",
        "blend": RESULTS_ROOT / "vintage_armchair" / "obj.blend",
        "out":   RESULTS_ROOT / "vintage_armchair" / "walkthrough_aerial",
        "assets": ASSETS_ROOT / "vintage_armchair",
        "config_overrides": {
            "grid_resolution":       0.15,
            "max_grid_cells_xy":     120,
            "max_grid_cells_z":      60,
            "camera_height":         0.4,     # orbit above small object
            "walk_speed_mps":        0.3,
            "max_duration_seconds":  30.0,
            "num_waypoints":         12,
            "render_engine":         "CYCLES",
            "render_width":          1280,
            "render_height":         720,
            "render_samples":        64,
            "use_denoise":           True,
            "waypoint_gaze_mode":    "free",
        }
    },
    {
        "name":  "modern_dining_table",
        "blend": RESULTS_ROOT / "modern_dining_table" / "obj.blend",
        "out":   RESULTS_ROOT / "modern_dining_table" / "walkthrough_aerial",
        "assets": ASSETS_ROOT / "modern_dining_table",
        "config_overrides": {
            "grid_resolution":       0.2,
            "max_grid_cells_xy":     100,
            "max_grid_cells_z":      50,
            "camera_height":         0.5,
            "walk_speed_mps":        0.4,
            "max_duration_seconds":  30.0,
            "num_waypoints":         12,
            "render_engine":         "CYCLES",
            "render_width":          1280,
            "render_height":         720,
            "render_samples":        64,
            "use_denoise":           True,
            "waypoint_gaze_mode":    "free",
        }
    },
    {
        "name":  "ceramic_teapot_set",
        "blend": RESULTS_ROOT / "ceramic_teapot_set" / "obj.blend",
        "out":   RESULTS_ROOT / "ceramic_teapot_set" / "walkthrough_aerial",
        "assets": ASSETS_ROOT / "ceramic_teapot_set",
        "config_overrides": {
            "grid_resolution":       0.1,
            "max_grid_cells_xy":     80,
            "max_grid_cells_z":      40,
            "camera_height":         0.3,
            "walk_speed_mps":        0.2,
            "max_duration_seconds":  25.0,
            "num_waypoints":         10,
            "render_engine":         "CYCLES",
            "render_width":          1280,
            "render_height":         720,
            "render_samples":        64,
            "use_denoise":           True,
            "waypoint_gaze_mode":    "free",
        }
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# Runner functions
# ══════════════════════════════════════════════════════════════════════════════

def run_outdoor(scene: dict):
    name  = scene["name"]
    blend = Path(scene["blend"])
    out   = Path(scene["out"])
    assets = Path(scene["assets"])

    print(f"\n{'═'*60}")
    print(f"  [OUTDOOR / terrain] {name}")
    print(f"{'═'*60}")

    if not blend.exists():
        print(f"  ERROR: blend not found: {blend}")
        return False

    out.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    config = dict(TERRAIN_BASE)
    config.update(scene["config_overrides"])

    npz = out / "terrain_snake.npz"

    # Phase 1: fit terrain snake
    if npz.exists():
        print(f"  Phase 1: reusing {npz}")
    else:
        print(f"  Phase 1: fitting TerrainSnake cloth…")
        t0 = time.time()
        subprocess.run([
            BLENDER, "--background", str(blend),
            "--python-exit-code", "1", "--python", FIT_SCRIPT, "--",
            "--blend",                    str(blend),
            "--output-dir",               str(out),
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
        print(f"  Phase 1 done in {time.time()-t0:.0f}s")

    config["terrain_npz"] = str(npz)

    # Phase 2: walkthrough
    from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run
    print(f"  Phase 2: walkthrough render → {out}")
    t0 = time.time()
    wt_run(str(blend), config, str(out), render=True)
    print(f"  Phase 2 done in {time.time()-t0:.0f}s")

    # Assemble GIF
    from genesis_tools.gif_generator import create_gif
    frames = sorted((out / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
    if frames:
        gif = assets / f"{name}_terrain_walkthrough.gif"
        create_gif(frames, gif, duration=int(1000 / config["fps"]))
        print(f"  GIF → {gif}  ({len(frames)} frames)")

        # Combined GIF with path overlay
        try:
            from genesis_tools.walkthrough_renderer.combined_gif import make_combined_gif
            make_combined_gif(frames, path_npz=out / "path.npz",
                              terrain_npz=npz,
                              output_gif=assets / f"{name}_terrain_walkthrough_combined.gif",
                              fps=config["fps"], step=3, output_scale=0.5)
            print(f"  Combined GIF → {assets / f'{name}_terrain_walkthrough_combined.gif'}")
        except Exception as e:
            print(f"  WARN: combined GIF failed: {e}")
    else:
        print(f"  WARN: no frames found in {out}/frames")

    print(f"  ✓ {name} outdoor done")
    return True


def run_indoor(scene: dict):
    name  = scene["name"]
    blend = Path(scene["blend"])
    out   = Path(scene["out"])
    assets = Path(scene["assets"])

    print(f"\n{'═'*60}")
    print(f"  [INDOOR / aerial] {name}")
    print(f"{'═'*60}")

    if not blend.exists():
        print(f"  ERROR: blend not found: {blend}")
        return False

    out.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    config = dict(STANDARD_BASE)
    config.update(scene["config_overrides"])

    from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run
    print(f"  Aerial walkthrough render → {out}")
    t0 = time.time()
    wt_run(str(blend), config, str(out), render=True)
    print(f"  Walkthrough done in {time.time()-t0:.0f}s")

    from genesis_tools.gif_generator import create_gif
    frames = sorted((out / "frames").glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
    if frames:
        gif = assets / f"{name}_aerial_walkthrough.gif"
        create_gif(frames, gif, duration=int(1000 / config["fps"]))
        print(f"  GIF → {gif}  ({len(frames)} frames)")
    else:
        print(f"  WARN: no frames found in {out}/frames")

    print(f"  ✓ {name} indoor done")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None,
                        help="Run only 'outdoor', 'indoor', or a specific scene name")
    args = parser.parse_args()

    only = args.only

    print(f"\nBatch walkthrough — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Only: {only or 'all'}")

    results = {}

    # Indoor
    for scene in INDOOR_SCENES:
        if only and only not in ("indoor", scene["name"]):
            continue
        ok = run_indoor(scene)
        results[scene["name"]] = "✓" if ok else "✗"

    # Outdoor
    for scene in OUTDOOR_SCENES:
        if only and only not in ("outdoor", scene["name"]):
            continue
        ok = run_outdoor(scene)
        results[scene["name"]] = "✓" if ok else "✗"

    print(f"\n{'═'*60}")
    print(f"  SUMMARY — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*60}")
    for name, status in results.items():
        print(f"  {status}  {name}")
