#!/usr/bin/env python3
"""
Resize GIFs over 50MB to fit under that threshold.
Strategy:
  1. Try 640x360
  2. If still over, try 480x270
  3. If still over, try 480x270 + drop every other frame (6.25fps)
Only downscales — skips files already at target resolution or smaller.
"""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

FFMPEG = "/home/kingy/Projects/Genesis/GenesisLilith/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
ASSETS_DIR = Path(__file__).parent.parent / "docs" / "assets"
MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def get_size(path):
    return os.path.getsize(path)


def get_resolution(path):
    result = subprocess.run(
        [FFMPEG, "-i", str(path)],
        capture_output=True, text=True
    )
    for line in result.stderr.splitlines():
        if "Video:" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if "x" in p and p[0].isdigit():
                    try:
                        w, h = p.split("x")
                        return int(w), int(h.split()[0])
                    except Exception:
                        continue
    return None, None


def resize_gif(input_path, output_path, w, h, drop_frames=False):
    vf = f"scale={w}:{h}:flags=lanczos"
    if drop_frames:
        vf = f"select='not(mod(n\\,2))',setpts=N/(6.25*TB),{vf}"
    vf += ",split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=bayer"
    cmd = [FFMPEG, "-y", "-i", str(input_path), "-vf", vf, str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def process(gif_path):
    size = get_size(gif_path)
    if size <= MAX_BYTES:
        return f"  SKIP  {gif_path.parent.name}/{gif_path.name} ({size // 1048576}MB)"

    cur_w, cur_h = get_resolution(gif_path)
    log = [f"  LARGE {gif_path.parent.name}/{gif_path.name} ({size // 1048576}MB, {cur_w}x{cur_h})"]

    attempts = [
        (640, 360, False),
        (480, 270, False),
        (480, 270, True),   # half fps
    ]

    for tw, th, drop in attempts:
        # Skip if current res is already equal or smaller than target
        if cur_w is not None and cur_w <= tw and cur_h is not None and cur_h <= th and not drop:
            log.append(f"    already {cur_w}x{cur_h}, skipping {tw}x{th} step")
            continue

        tmp = gif_path.with_suffix(".resizing.gif")
        ok = resize_gif(gif_path, tmp, tw, th, drop)
        if not ok or not tmp.exists():
            log.append(f"    ffmpeg failed at {tw}x{th}")
            tmp.unlink(missing_ok=True)
            continue

        new_size = get_size(tmp)
        suffix = " + half-fps" if drop else ""
        log.append(f"    {tw}x{th}{suffix} → {new_size // 1048576}MB")

        if new_size <= MAX_BYTES:
            shutil.move(str(tmp), str(gif_path))
            log.append(f"    DONE ✓")
            break
        else:
            # Keep the smaller version as new input for next attempt
            shutil.move(str(tmp), str(gif_path))
            cur_w, cur_h = tw, th
    else:
        log.append(f"    WARNING: still over 50MB after all attempts")

    return "\n".join(log)


def main():
    gifs = sorted(ASSETS_DIR.rglob("*.gif"))
    print(f"Found {len(gifs)} GIF(s) in {ASSETS_DIR}")
    for gif in gifs:
        print(process(gif))
    print("Done.")


if __name__ == "__main__":
    main()
