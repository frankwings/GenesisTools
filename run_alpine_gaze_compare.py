"""Compare all 4 gaze modes for alpine_meadow_sunrise — 100 frames each."""
import sys, json, time
from pathlib import Path

sys.path.insert(0, "/home/kingy/Projects/Genesis/GenesisTools")

RESULTS_ROOT = Path("/home/kingy/Projects/Genesis/GenesisTools/results")
BLEND   = RESULTS_ROOT / "alpine_meadow_sunrise" / "scene_fine.blend"
SNAKE   = RESULTS_ROOT / "alpine_meadow_sunrise" / "walkthrough_terrain" / "terrain_snake.npz"

with open("/home/kingy/Projects/Genesis/GenesisTools/configs/terrain_scene.json") as f:
    TERRAIN_BASE = json.load(f)
TERRAIN_BASE.pop("_description", None)

# ~100 frames at 12 fps = 8.33s; use 10s for a bit of headroom
DURATION = 10.0
FPS      = 12

GAZE_MODES = [
    {
        "name": "smooth_adaptive",
        "overrides": {
            "waypoint_gaze_mode":       "smooth_adaptive",
            "smooth_pitch_min_deg":     -8.0,
            "smooth_pitch_max_deg":      5.0,
            "smooth_pitch_lookahead_m": 20.0,
            "smooth_pitch_sigma_s":      1.2,
            "smooth_yaw_sigma_s":        0.6,
        },
    },
    {
        "name": "waypoint",
        "overrides": {
            "waypoint_gaze_mode": "waypoint",
        },
    },
    {
        "name": "eye_level",
        "overrides": {
            "waypoint_gaze_mode": "eye_level",
        },
    },
    {
        "name": "free",
        "overrides": {
            "waypoint_gaze_mode": "free",
        },
    },
]

BASE_CONFIG = dict(TERRAIN_BASE)
BASE_CONFIG.update({
    "camera_height":           1.7,
    "grid_resolution":         "auto",
    "mark_particle_instances": False,
    "walk_speed_mps":          5.0,
    "max_duration_seconds":    DURATION,
    "fps":                     FPS,
    "render_engine":           "CYCLES",
    "render_width":            1280,
    "render_height":           720,
    "render_samples":          64,
    "use_denoise":             True,
    "terrain_npz":             str(SNAKE),
})


def run_mode(mode: dict):
    name = mode["name"]
    out  = RESULTS_ROOT / "alpine_meadow_sunrise" / f"gaze_{name}"
    out.mkdir(parents=True, exist_ok=True)

    # Clear old frames
    frames_dir = out / "frames"
    if frames_dir.exists():
        for f in frames_dir.glob("frame_*.png"):
            f.unlink()

    config = dict(BASE_CONFIG)
    config.update(mode["overrides"])

    print(f"\n{'═'*55}")
    print(f"  [{name}]  → {out}")
    print(f"{'═'*55}")

    from genesis_tools.walkthrough_renderer.walkthrough import run as wt_run
    t0 = time.time()
    wt_run(str(BLEND), config, str(out), render=True)
    elapsed = time.time() - t0

    frames = sorted(frames_dir.glob("frame_*.png"),
                    key=lambda p: int(p.stem.split("_")[1]))
    print(f"  done in {elapsed:.0f}s  |  {len(frames)} frames")

    # GIF
    if frames:
        from genesis_tools.gif_generator import create_gif
        gif = out / f"alpine_{name}.gif"
        create_gif(frames, gif, duration=int(1000 / FPS))
        print(f"  GIF → {gif}")

        # MP4
        import subprocess
        mp4 = out / f"alpine_{name}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-framerate", str(FPS),
            "-pattern_type", "glob", "-i", str(frames_dir / "frame_*.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            str(mp4)
        ], check=True, capture_output=True)
        print(f"  MP4 → {mp4}")
        return mp4
    return None


if __name__ == "__main__":
    print(f"\nGaze mode comparison — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Blend : {BLEND}")
    print(f"Snake : {SNAKE}")
    print(f"Frames: ~{int(DURATION * FPS)} per mode")

    mp4s = []
    for mode in GAZE_MODES:
        mp4 = run_mode(mode)
        if mp4:
            mp4s.append((mode["name"], mp4))

    print(f"\n{'═'*55}")
    print("DONE — MP4s:")
    for name, mp4 in mp4s:
        print(f"  [{name}]  {mp4}")
