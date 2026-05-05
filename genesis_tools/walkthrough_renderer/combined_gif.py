"""Side-by-side GIF: rendered walkthrough frames + live XY map.

For each frame the XY map shows:
  - terrain heightmap background (rendered once)
  - full path in light-grey
  - visited trail coloured by progress (plasma)
  - current camera position as a white circle + crosshair
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import List, Union

import numpy as np
from PIL import Image, ImageDraw


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_terrain_bg(heightmap: np.ndarray, bounds: tuple,
                        path_pts: np.ndarray, map_px: int) -> Image.Image:
    """Render terrain heightmap + full path (grey) as a PIL image (map_px × map_px)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    min_x, min_y, max_x, max_y = bounds[0], bounds[1], bounds[2], bounds[3]
    hm = heightmap.copy().astype(np.float64)
    hm[np.isnan(hm)] = np.nanmin(hm)

    dpi = 100
    fig_size = map_px / dpi
    fig, ax = plt.subplots(figsize=(fig_size, fig_size), dpi=dpi)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.axis("off")

    ax.imshow(hm.T, origin="lower",
              extent=[min_x, max_x, min_y, max_y],
              cmap="terrain",
              vmin=float(np.nanmin(hm)) - 5,
              vmax=float(np.nanmax(hm)) + 5,
              aspect="auto")

    # Full path in light grey
    if len(path_pts) > 1:
        ax.plot(path_pts[:, 0], path_pts[:, 1],
                color="white", alpha=0.25, linewidth=0.8, zorder=2)

    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB").resize((map_px, map_px), Image.LANCZOS)
    return img.copy()


def _world_to_px(xy: np.ndarray, bounds: tuple, map_px: int) -> np.ndarray:
    """Convert world XY → pixel coords (origin top-left, Y flipped)."""
    min_x, min_y, max_x, max_y = bounds[0], bounds[1], bounds[2], bounds[3]
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    px = (xy[:, 0] - min_x) / span_x * (map_px - 1)
    py = (1.0 - (xy[:, 1] - min_y) / span_y) * (map_px - 1)
    return np.stack([px, py], axis=1)


def _plasma_color(t: float) -> tuple:
    """plasma colormap value at t ∈ [0,1] → (R,G,B) uint8."""
    import matplotlib.cm as cm
    r, g, b, _ = cm.plasma(float(np.clip(t, 0.0, 1.0)))
    return (int(r * 255), int(g * 255), int(b * 255))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_combined_gif(
    frames: List[Union[str, Path]],
    path_npz: Union[str, Path],
    terrain_npz: Union[str, Path],
    output_gif: Union[str, Path],
    fps: int = 12,
    map_px: int = 480,
    step: int = 3,
    output_scale: float = 0.5,
) -> Path:
    """Create side-by-side GIF combining rendered frames with a live XY map.

    Args:
        frames:      Ordered list of rendered frame paths (already subsampled if desired).
        path_npz:    path.npz from the walkthrough pipeline.
        terrain_npz: terrain_snake.npz from fit_terrain_contour.
        output_gif:  Output GIF path.
        fps:         Playback frame rate.
        map_px:      Size of the square XY map panel in pixels.
        step:         Take every Nth frame (default 3).
        output_scale: Scale the combined image before encoding (default 0.5).
                      Combined frames are 1120×480 at full scale; 0.5 → 560×240,
                      which reduces file size by ~4×.

    Returns:
        Path to the saved GIF.
    """
    frames = [Path(f) for f in frames][::step]
    output_gif = Path(output_gif)

    pdata = np.load(path_npz)
    path_pts = pdata["path_points"].astype(np.float64)   # (P, 3)

    tdata = np.load(terrain_npz)
    heightmap = tdata["heightmap"].astype(np.float64)
    bounds = tuple(float(v) for v in tdata["bounds"])    # (min_x,min_y,max_x,max_y,min_z,max_z)

    n_frames = len(frames)
    P = len(path_pts)

    print(f"[CombinedGIF] Pre-rendering terrain background ({map_px}×{map_px})…")
    bg = _render_terrain_bg(heightmap, bounds, path_pts, map_px)

    # Pre-compute pixel coords for all path points
    all_px = _world_to_px(path_pts[:, :2], bounds, map_px)

    # Arc-length fractions for trail colouring
    diffs = np.diff(path_pts[:, :2], axis=0)
    seg_len = np.sqrt((diffs**2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = max(cum[-1], 1e-6)
    t_frac = cum / total   # (P,)

    dot_r = max(4, map_px // 80)       # camera dot radius
    trail_w = max(1, map_px // 200)    # trail line width

    combined_frames: List[Image.Image] = []

    print(f"[CombinedGIF] Compositing {n_frames} frames…")
    for fi, frame_path in enumerate(frames):
        render = Image.open(frame_path).convert("RGB")
        render_w, render_h = render.size

        # Resize map to match render height
        mh = render_h
        mw = render_h   # keep square

        map_img = bg.resize((mw, mh), Image.LANCZOS).copy()
        draw = ImageDraw.Draw(map_img)

        # Current path position: t ∈ [0,1] → path index
        t = fi / max(1, n_frames - 1)
        p_idx = t * (P - 1)
        p_lo = int(p_idx)
        p_hi = min(p_lo + 1, P - 1)
        frac = p_idx - p_lo
        cur_world = path_pts[p_lo] + frac * (path_pts[p_hi] - path_pts[p_lo])
        cur_px = _world_to_px(cur_world[:2].reshape(1, 2), bounds, mw)[0]

        # Scale pre-computed pixel coords to current map size
        scale = mw / map_px
        scaled_px = all_px * scale

        # Draw trail from start to current path index
        trail_end = max(p_lo + 1, 2)
        if trail_end > 1:
            for k in range(trail_end - 1):
                x0, y0 = int(scaled_px[k, 0]),   int(scaled_px[k, 1])
                x1, y1 = int(scaled_px[k+1, 0]), int(scaled_px[k+1, 1])
                color = _plasma_color(t_frac[k])
                draw.line([(x0, y0), (x1, y1)], fill=color, width=trail_w)

        # Current position: white circle + crosshair
        cx, cy = int(cur_px[0]), int(cur_px[1])
        draw.ellipse([(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)],
                     fill="white", outline="black")
        draw.line([(cx - dot_r*2, cy), (cx + dot_r*2, cy)],
                  fill="white", width=max(1, dot_r//2))
        draw.line([(cx, cy - dot_r*2), (cx, cy + dot_r*2)],
                  fill="white", width=max(1, dot_r//2))

        combined = Image.new("RGB", (render_w + mw, render_h))
        combined.paste(render, (0, 0))
        combined.paste(map_img, (render_w, 0))
        if output_scale != 1.0:
            ow = int((render_w + mw) * output_scale)
            oh = int(render_h * output_scale)
            combined = combined.resize((ow, oh), Image.LANCZOS)
        combined_frames.append(combined)

    if not combined_frames:
        raise RuntimeError("No frames to combine.")

    duration_ms = int(1000 / fps)
    output_gif.parent.mkdir(parents=True, exist_ok=True)
    combined_frames[0].save(
        output_gif,
        save_all=True,
        append_images=combined_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    size_mb = output_gif.stat().st_size / 1e6
    print(f"[CombinedGIF] -> {output_gif}  ({size_mb:.1f} MB)")
    return output_gif
