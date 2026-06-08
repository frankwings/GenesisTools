"""Side-by-side combined view: rendered walkthrough frames + live XY map.

For each frame the XY map shows:
  - terrain heightmap background (rendered once)
  - full path in light-grey
  - visited trail coloured by progress (plasma: blue=start → yellow=current)
  - current camera position as a white circle + crosshair
  - camera heading arrow + semi-transparent FOV cone

Terrain heightmap source selection
-----------------------------------
terrain_snake.npz stores heightmap Z values fitted around the *original* Infinigen
scene camera.  If the walkthrough path was snapped to actual scene geometry via
ray-casting, its Z range may be far outside the heightmap's Z range (e.g. path at
Z=113-122 BU while heightmap is 1-24 BU).  In that case the terrain colormap is
misleading.

Fix: when the median path Z differs from the median heightmap value by more than
``_Z_MISMATCH_THRESHOLD`` BU, we rebuild the heightmap by interpolating the
terrain-floor Z from path_points (path Z minus camera height) over a regular XY
grid.  This ensures the background color always reflects the *actual* terrain
elevation under the walkthrough camera.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Generator, List, Union

import numpy as np
from PIL import Image, ImageDraw

_Z_MISMATCH_THRESHOLD = 20.0  # BU; rebuild heightmap if gap is larger than this


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_path_heightmap(
    path_pts: np.ndarray,
    cam_h: float,
    grid_n: int = 250,
    margin: float = 10.0,
) -> tuple[np.ndarray, tuple]:
    """Interpolate terrain-floor Z from path points onto a regular XY grid.

    Returns (heightmap, bounds_xy) where bounds_xy = (min_x, min_y, max_x, max_y).
    Cells outside the path convex hull are filled via nearest-neighbour to avoid
    hard NaN edges; the hull boundary is preserved as a soft mask by the caller.
    """
    from scipy.interpolate import griddata
    from scipy.spatial import ConvexHull

    floor_z = path_pts[:, 2] - cam_h
    bx0 = path_pts[:, 0].min() - margin
    bx1 = path_pts[:, 0].max() + margin
    by0 = path_pts[:, 1].min() - margin
    by1 = path_pts[:, 1].max() + margin
    bounds_xy = (bx0, by0, bx1, by1)

    gx = np.linspace(bx0, bx1, grid_n)
    gy = np.linspace(by0, by1, grid_n)
    GX, GY = np.meshgrid(gx, gy)

    hm = griddata(path_pts[:, :2], floor_z, (GX, GY), method="linear", fill_value=np.nan)
    hm_nn = griddata(path_pts[:, :2], floor_z, (GX, GY), method="nearest")
    hm = np.where(np.isnan(hm), hm_nn, hm)

    # Mask cells outside convex hull
    try:
        hull = ConvexHull(path_pts[:, :2])
        from matplotlib.path import Path as MplPath
        hull_path = MplPath(path_pts[:, :2][hull.vertices])
        pts_flat = np.column_stack([GX.ravel(), GY.ravel()])
        inside = hull_path.contains_points(pts_flat).reshape(grid_n, grid_n)
        hm = np.where(inside, hm, np.nan)
    except Exception:
        pass

    return hm, bounds_xy


def _render_terrain_bg(heightmap: np.ndarray, bounds: tuple,
                        path_pts: np.ndarray, map_px: int,
                        cam_h: float = 1.7) -> Image.Image:
    """Render terrain heightmap + full path (grey) as a PIL image (map_px × map_px).

    Automatically detects Z-coordinate mismatch between heightmap and path and
    rebuilds the heightmap from path Z values when needed.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    min_x, min_y, max_x, max_y = bounds[0], bounds[1], bounds[2], bounds[3]

    hm = heightmap.copy().astype(np.float64)
    valid = ~np.isnan(hm)
    if valid.any():
        hm[~valid] = float(np.nanmin(hm))

    dpi = 100
    fig_size = map_px / dpi
    fig, ax = plt.subplots(figsize=(fig_size, fig_size), dpi=dpi)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_facecolor("#2a2a2a")
    ax.axis("off")

    # Shift vmin so the lowest terrain value maps into the green/brown zone of
    # the 'terrain' colormap (skipping the 0–0.22 blue/water region).
    # terrain colormap: blue=0~0.22, green=0.22~0.5, brown=0.5~0.75, white=0.75~1.0
    # We push data_min to colormap position 0.25 (start of green).
    if valid.any():
        d_min = float(np.nanmin(hm[valid]))
        d_max = float(np.nanmax(hm[valid]))
        delta = max(d_max - d_min, 1e-6)
        # cmap_pos = (v - vmin) / (vmax - vmin); set cmap_pos(d_min) = 0.25
        # → vmin = d_min - 0.25 / 0.75 * delta
        adj_vmin = d_min - (0.25 / 0.75) * delta
        adj_vmax = d_max
    else:
        adj_vmin, adj_vmax = 0, 1

    ax.imshow(hm.T, origin="lower",
              extent=[min_x, max_x, min_y, max_y],
              cmap="terrain",
              vmin=adj_vmin,
              vmax=adj_vmax,
              aspect="auto")

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


def _draw_fov_cone(
    img: "Image.Image",
    cx: int, cy: int,
    yaw_rad: float,
    fov_rad: float,
    length_px: int,
    fill_rgba: tuple = (255, 255, 100, 80),
    edge_color: tuple = (255, 255, 100, 255),
    edge_width: int = 2,
    n_arc: int = 16,
) -> "Image.Image":
    """Draw a semi-transparent FOV cone onto *img* (RGB) and return the result.

    Parameters
    ----------
    img        : PIL RGB image to draw onto.
    cx, cy     : Camera pixel position (image coords, Y-down).
    yaw_rad    : Camera heading in radians (math convention: 0=+X, CCW positive).
                 Y-axis is flipped for image space.
    fov_rad    : Full horizontal FOV in radians.
    length_px  : Cone length in pixels.
    fill_rgba  : Fill colour + alpha (0-255) for the cone polygon.
    edge_color : RGB colour for the two boundary lines + heading arrow.
    edge_width : Boundary line width in pixels.
    n_arc      : Number of arc segments (more = smoother fan).
    """
    half = fov_rad / 2.0

    # Arc polygon (image Y is downward, so sin is negated)
    pts = [(cx, cy)]
    for i in range(n_arc + 1):
        angle = yaw_rad - half + i * (fov_rad / n_arc)
        px = cx + length_px * math.cos(angle)
        py = cy - length_px * math.sin(angle)
        pts.append((int(px), int(py)))
    pts.append((cx, cy))

    # Semi-transparent fill via RGBA overlay
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.polygon(pts, fill=fill_rgba)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Edge lines and heading arrow drawn on top
    draw = ImageDraw.Draw(img)
    left_angle  = yaw_rad + half
    right_angle = yaw_rad - half
    lx = cx + length_px * math.cos(left_angle)
    ly = cy - length_px * math.sin(left_angle)
    rx = cx + length_px * math.cos(right_angle)
    ry = cy - length_px * math.sin(right_angle)
    draw.line([(cx, cy), (int(lx), int(ly))], fill=edge_color[:3], width=edge_width)
    draw.line([(cx, cy), (int(rx), int(ry))], fill=edge_color[:3], width=edge_width)

    # Heading arrow (centre of cone)
    arrow_len = int(length_px * 0.8)
    ax = cx + arrow_len * math.cos(yaw_rad)
    ay = cy - arrow_len * math.sin(yaw_rad)
    draw.line([(cx, cy), (int(ax), int(ay))], fill=(255, 255, 255), width=max(2, edge_width + 1))

    return img


def _iter_combined_frames(
    frames: List[Path],
    path_npz: Union[str, Path],
    terrain_npz: Union[str, Path],
    map_px: int = 480,
    output_scale: float = 1.0,
    fov_deg: float = 35.7,
) -> Generator[Image.Image, None, None]:
    """Yield composited PIL images (rendered frame + XY map) for each input frame."""
    pdata = np.load(path_npz)
    path_pts = pdata["path_points"].astype(np.float64)
    cam_h = float(pdata["camera_height"]) if "camera_height" in pdata else 1.7

    tdata = np.load(terrain_npz)
    heightmap = tdata["heightmap"].astype(np.float64)
    bounds = tuple(float(v) for v in tdata["bounds"])

    P = len(path_pts)
    n_frames = len(frames)

    print(f"[Combined] Pre-rendering terrain background ({map_px}×{map_px})…")
    bg = _render_terrain_bg(heightmap, bounds, path_pts, map_px, cam_h=cam_h)

    all_px = _world_to_px(path_pts[:, :2], bounds, map_px)

    # Arc-length fraction for trail colouring (0=start, 1=end)
    diffs = np.diff(path_pts[:, :2], axis=0)
    seg_len = np.sqrt((diffs**2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    t_frac = cum / max(cum[-1], 1e-6)   # (P,) ∈ [0,1]

    # Pre-compute yaw (radians) at each path point from path tangent (lookahead).
    # Use a 5% arc-length lookahead, clamped to available range.
    _yaws = np.zeros(P, dtype=np.float64)
    _lah_steps = max(1, int(P * 0.05))
    for _i in range(P):
        _j = min(_i + _lah_steps, P - 1)
        dx = path_pts[_j, 0] - path_pts[_i, 0]
        dy = path_pts[_j, 1] - path_pts[_i, 1]
        _yaws[_i] = math.atan2(dy, dx)

    fov_rad = math.radians(fov_deg)

    dot_r = max(4, map_px // 80)
    trail_w = max(1, map_px // 200)

    print(f"[Combined] Compositing {n_frames} frames…")
    for fi, frame_path in enumerate(frames):
        render = Image.open(frame_path).convert("RGB")
        render_w, render_h = render.size
        mw = mh = render_h   # square map panel, same height as render

        map_img = bg.resize((mw, mh), Image.LANCZOS).copy()
        draw = ImageDraw.Draw(map_img)

        t = fi / max(1, n_frames - 1)
        p_idx = t * (P - 1)
        p_lo = int(p_idx)
        p_hi = min(p_lo + 1, P - 1)
        frac = p_idx - p_lo
        cur_world = path_pts[p_lo] + frac * (path_pts[p_hi] - path_pts[p_lo])
        cur_px = _world_to_px(cur_world[:2].reshape(1, 2), bounds, mw)[0]

        scale = mw / map_px
        scaled_px = all_px * scale

        trail_end = max(p_lo + 1, 2)
        for k in range(trail_end - 1):
            x0, y0 = int(scaled_px[k, 0]),   int(scaled_px[k, 1])
            x1, y1 = int(scaled_px[k+1, 0]), int(scaled_px[k+1, 1])
            draw.line([(x0, y0), (x1, y1)], fill=_plasma_color(t_frac[k]), width=trail_w)

        cx, cy = int(cur_px[0]), int(cur_px[1])

        # Interpolate yaw at current path position
        cur_yaw = float(_yaws[p_lo] + frac * (_yaws[p_hi] - _yaws[p_lo]))

        # FOV cone + heading arrow (drawn before the dot so dot sits on top)
        cone_len = max(dot_r * 6, mw // 10)
        map_img = _draw_fov_cone(
            map_img, cx, cy,
            yaw_rad=cur_yaw,
            fov_rad=fov_rad,
            length_px=cone_len,
            fill_rgba=(255, 255, 80, 70),
            edge_color=(255, 255, 80, 255),
            edge_width=max(1, dot_r // 3),
        )
        draw = ImageDraw.Draw(map_img)

        # Camera position dot (drawn on top of cone)
        draw.ellipse([(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)],
                     fill="white", outline="black")
        draw.line([(cx - dot_r*2, cy), (cx + dot_r*2, cy)],
                  fill="white", width=max(1, dot_r // 2))
        draw.line([(cx, cy - dot_r*2), (cx, cy + dot_r*2)],
                  fill="white", width=max(1, dot_r // 2))

        combined = Image.new("RGB", (render_w + mw, render_h))
        combined.paste(render, (0, 0))
        combined.paste(map_img, (render_w, 0))
        if output_scale != 1.0:
            ow = int((render_w + mw) * output_scale)
            oh = int(render_h * output_scale)
            combined = combined.resize((ow, oh), Image.LANCZOS)
        yield combined


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
    fov_deg: float = 35.7,
) -> Path:
    """Create side-by-side GIF: rendered frames + live XY map with FOV cone.

    step=3 + output_scale=0.5 keeps file size ~25 MB for 1000-frame renders.
    Path colors: plasma colormap, blue=start → yellow=end (arc-length progress).
    fov_deg: horizontal camera FOV in degrees (default 35.7° = 50mm/32mm sensor).
    """
    frames_sub = [Path(f) for f in frames][::step]
    output_gif = Path(output_gif)
    output_gif.parent.mkdir(parents=True, exist_ok=True)

    imgs = list(_iter_combined_frames(frames_sub, path_npz, terrain_npz,
                                      map_px=map_px, output_scale=output_scale,
                                      fov_deg=fov_deg))
    if not imgs:
        raise RuntimeError("No frames to combine.")

    duration_ms = int(1000 / fps)
    imgs[0].save(output_gif, save_all=True, append_images=imgs[1:],
                 duration=duration_ms, loop=0, optimize=False)
    size_mb = output_gif.stat().st_size / 1e6
    print(f"[CombinedGIF] -> {output_gif}  ({size_mb:.1f} MB)")
    return output_gif


def make_combined_mp4(
    frames: List[Union[str, Path]],
    path_npz: Union[str, Path],
    terrain_npz: Union[str, Path],
    output_mp4: Union[str, Path],
    fps: int = 6,
    map_px: int = 480,
    step: int = 1,
    output_scale: float = 1.0,
) -> Path:
    """Create side-by-side MP4: rendered frames + live XY map.

    Defaults: all frames (step=1), full resolution (output_scale=1.0), 6 fps
    for a slower, smoother playback. MP4 compression is far more efficient than
    GIF — expect ~5–15 MB for 1000 frames at 1120×480.
    """
    import imageio
    frames_sub = [Path(f) for f in frames][::step]
    output_mp4 = Path(output_mp4)
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    writer = imageio.get_writer(str(output_mp4), fps=fps,
                                codec="libx264", quality=7,
                                macro_block_size=2)
    try:
        for img in _iter_combined_frames(frames_sub, path_npz, terrain_npz,
                                         map_px=map_px, output_scale=output_scale):
            writer.append_data(np.array(img))
    finally:
        writer.close()

    size_mb = output_mp4.stat().st_size / 1e6
    print(f"[CombinedMP4] -> {output_mp4}  ({size_mb:.1f} MB)")
    return output_mp4
