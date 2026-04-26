"""Step 6 (optional): render camera animation via blender --background.

Input:  animated .blend (from camera_animate step)
Output: rendered PNG frames
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


def build(blend_path: str, config: dict, output_dir: str) -> List[str]:
    """Render the animated .blend to PNG frames via BlenderRunner.

    Returns list of rendered frame paths.
    """
    from genesis_tools.blender_runner import BlenderRunner
    import tempfile, os

    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    render_config = {
        "render_engine": config.get("render_engine", "CYCLES"),
        "render_width":  config.get("render_width", 1280),
        "render_height": config.get("render_height", 720),
        "render_samples": config.get("render_samples", 32),
        "panoramic": config.get("panoramic", False),
        "fps": config.get("fps", 12),
        "frames_dir": str(frames_dir),
    }

    render_script = Path(__file__).parent / "_render_frames.py"
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(render_config, tf)
    tf.close()
    try:
        runner = BlenderRunner()
        runner.run(
            blend_path=blend_path,
            script=str(render_script),
            extra_args=["--", "--config", tf.name],
        )
    finally:
        os.unlink(tf.name)

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
