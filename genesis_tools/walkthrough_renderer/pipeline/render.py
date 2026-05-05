"""Step 6 (optional): render camera animation via blender --background.

Input:  animated .blend (from camera_animate step)
Output: rendered PNG frames
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

BLENDER_WSL  = "/home/kingy/blender/blender"
BLENDER_WIN  = "/mnt/c/Program Files/Blender Foundation/Blender 4.5/blender.exe"


def _find_blender() -> str:
    """Prefer Windows Blender (GPU Cycles) when available, else WSL Blender."""
    if Path(BLENDER_WIN).exists():
        return BLENDER_WIN
    import shutil
    return shutil.which("blender") or BLENDER_WSL


def _is_win_blender(blender_exe: str) -> bool:
    return str(blender_exe).endswith(".exe")


def _to_win_path(path: str) -> str:
    """Convert WSL path to Windows path via wslpath."""
    import subprocess
    r = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True)
    return r.stdout.strip()


def build(blend_path: str, config: dict, output_dir: str) -> List[str]:
    """Render the animated .blend to PNG frames via blender --background.

    When Windows Blender is detected, paths are converted to Windows format.

    Returns list of rendered frame paths.
    """
    import os, subprocess, tempfile

    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    blender_exe = _find_blender()
    render_script = Path(__file__).parent / "_render_frames.py"

    render_config = {
        "render_engine": config.get("render_engine", "CYCLES"),
        "render_width":  config.get("render_width", 1280),
        "render_height": config.get("render_height", 720),
        "render_samples": config.get("render_samples", 32),
        "panoramic": config.get("panoramic", False),
        "fps": config.get("fps", 12),
        "frames_dir": str(frames_dir),
        "frame_end": config.get("frame_end"),  # optional: cap render at frame N
        "use_denoise": config.get("use_denoise", True),  # Cycles OIDN denoise toggle
    }

    if _is_win_blender(blender_exe):
        # Write config to Windows-accessible location
        win_tmp = Path("/mnt/c/tmp/genesis_render")
        win_tmp.mkdir(parents=True, exist_ok=True)
        cfg_path = win_tmp / "render_config.json"
        render_config["frames_dir"] = _to_win_path(str(frames_dir))
        render_config["_windows_blender"] = True
        cfg_path.write_text(json.dumps(render_config))

        cmd = [
            blender_exe, "--background", _to_win_path(str(blend_path)),
            "--python", _to_win_path(str(render_script)),
            "--", "--config", _to_win_path(str(cfg_path)),
        ]
        tf_to_clean = None
    else:
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(render_config, tf)
        tf.close()
        tf_to_clean = tf.name
        cmd = [
            blender_exe, "--background", str(blend_path),
            "--python", str(render_script), "--", "--config", tf.name,
        ]

    print(f"[Render] Using {'Windows' if _is_win_blender(blender_exe) else 'Linux'} Blender: {blender_exe}")
    try:
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            raise RuntimeError(f"Render step failed (exit {result.returncode})")
    finally:
        if tf_to_clean:
            os.unlink(tf_to_clean)

    frames = sorted(frames_dir.glob("frame_*.png"))
    print(f"[Render] {len(frames)} frames rendered -> {frames_dir}")
    return [str(f) for f in frames]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Walkthrough step 6: render frames")
    parser.add_argument("--blend", required=True, help="Path to animated .blend")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    with open(args.config) as f:
        config = json.load(f)
    frames = build(args.blend, config, args.output_dir)
    print(f"Rendered {len(frames)} frames")


if __name__ == "__main__":
    _cli()
