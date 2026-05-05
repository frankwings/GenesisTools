"""Visualise active-contour 3D snakes (Snake3D and TerrainSnake).

Two modes — invoked from the GenesisTools repo root:

  Snake3D — synthetic cube + spike contraction demo (default mode):
      python genesis_tools/active_contour/visualize.py
    Output: 4 figures in `results/active_contour/`
      figure_1_sampling.png       — sampled point cloud vs sparse vertices
      figure_2_evolution.png      — snake surface at 4 stages of contraction
      figure_3_protrusion.png     — HIGH α (bypass spike) vs LOW α (wrap spike)
      figure_4_convergence.png    — max-displacement curve over iterations

  TerrainSnake — real terrain fit (cloth simulation result, e.g. arctic):
      python genesis_tools/active_contour/visualize.py terrain [result_dir]
    Default result_dir = results/arctic_midnight_sun_v1.  `path.npz` is
    optional — when missing, fig 1/2 omit the camera-path overlay.
    Output: 5 figures in `<result_dir>/viz/`
      figure_0_initial_vs_final.png — initial cloth (z_max) vs final cloth
      figure_1_top_down.png         — coverage / heightmap / bridged
      figure_2_side_profiles.png    — XZ / YZ projections (full grid)
      figure_3_bridging_demo.png    — camera-anchored XY + XZ + YZ
      figure_4_convergence.png      — max displacement per iteration

────────────────────────────────────────────────────────────────────────
CONVENTION — camera-anchored 1-D slices (TerrainSnake mode)
────────────────────────────────────────────────────────────────────────
Every 1-D slice / cross-section figure is anchored at the original scene
camera's XY position (read from `terrain_snake.npz` → `camera_xyz`).
For an XZ slice we pick the row whose iy is closest to `camera_xyz[1]`;
for a YZ slice we pick the column whose ix is closest to `camera_xyz[0]`.
The helpers live in `camera_anchored_slice.py`; do not re-derive the
slice index inline. Synthetic flat / mid-bbox / arbitrary-Y slices are
not allowed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless — no display required
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3D projection)
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
)
from genesis_tools.active_contour.camera_anchored_slice import (
    camera_anchored_iy,
    camera_anchored_ix,
)


# =====================================================================
# Snake3D mode — synthetic cube + spike demo
# =====================================================================

SNAKE3D_OUT_DIR = (Path(__file__).resolve().parents[3]
                   / "results" / "active_contour")


# ---------------------------------------------------------------------
# Geometry helpers (Snake3D)
# ---------------------------------------------------------------------

def _unit_cube() -> tuple:
    v = np.array([
        [0,0,0],[1,0,0],[1,1,0],[0,1,0],
        [0,0,1],[1,0,1],[1,1,1],[0,1,1],
    ], dtype=float)
    f = np.array([
        [0,2,1],[0,3,2],
        [4,5,6],[4,6,7],
        [0,1,5],[0,5,4],
        [2,3,7],[2,7,6],
        [0,4,7],[0,7,3],
        [1,2,6],[1,6,5],
    ], dtype=int)
    return v, f


def _cube_with_spike(spike_h: float = 0.22, spike_b: float = 0.12) -> tuple:
    cv, cf = _unit_cube()
    cx, cy = 0.5, 0.5
    tip_idx = len(cv)
    base_start = tip_idx + 1
    extra_v = np.array([
        [cx,       cy,       1.0 + spike_h],   # tip
        [cx - spike_b, cy - spike_b, 1.0],
        [cx + spike_b, cy - spike_b, 1.0],
        [cx + spike_b, cy + spike_b, 1.0],
        [cx - spike_b, cy + spike_b, 1.0],
    ])
    t  = tip_idx
    b0, b1, b2, b3 = base_start, base_start+1, base_start+2, base_start+3
    spike_f = np.array([[t,b0,b1],[t,b1,b2],[t,b2,b3],[t,b3,b0]], dtype=int)
    return np.vstack([cv, extra_v]), np.vstack([cf, spike_f])


def _draw_mesh(ax, verts: np.ndarray, faces: np.ndarray,
               color: str = "steelblue", alpha: float = 0.18,
               edge_color: str = "navy", lw: float = 0.3) -> None:
    tris = [[verts[f[0]], verts[f[1]], verts[f[2]]] for f in faces]
    poly = Poly3DCollection(tris, alpha=alpha, linewidths=lw)
    poly.set_facecolor(color)
    poly.set_edgecolor(edge_color)
    ax.add_collection3d(poly)


def _set_equal_axes(ax, pts: np.ndarray) -> None:
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    mid = (lo + hi) / 2
    span = (hi - lo).max() / 2 * 1.2
    ax.set_xlim(mid[0] - span, mid[0] + span)
    ax.set_ylim(mid[1] - span, mid[1] + span)
    ax.set_zlim(mid[2] - span, mid[2] + span)
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")


# ---------------------------------------------------------------------
# Snake3D figures
# ---------------------------------------------------------------------

def figure_sampling(out_dir: Path) -> None:
    print("[Fig 1] Sampling comparison …")
    v, f = _unit_cube()
    pts = sample_mesh_surface([(v, f)], sampling_resolution=0.12)

    fig, axes = plt.subplots(1, 2, figsize=(11, 5),
                             subplot_kw={"projection": "3d"})
    fig.suptitle("Mesh Surface Sampling", fontsize=13, fontweight="bold")

    for ax, (pts_show, label, color, size) in zip(axes, [
        (v,   f"Sparse vertices only\n({len(v)} points)", "crimson",  30),
        (pts, f"Area-weighted face sampling\n({len(pts)} points)", "royalblue", 4),
    ]):
        ax.scatter(*pts_show.T, c=color, s=size, depthshade=False)
        _draw_mesh(ax, v, f, color="gold", alpha=0.08, edge_color="goldenrod", lw=0.5)
        ax.set_title(label, fontsize=10)
        _set_equal_axes(ax, v)

    plt.tight_layout()
    path = out_dir / "figure_1_sampling.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


def figure_evolution(out_dir: Path) -> None:
    print("[Fig 2] Snake evolution (cube) …")
    v, f = _unit_cube()
    pts = sample_mesh_surface([(v, f)], sampling_resolution=0.12)

    snake = Snake3D(pts, alpha=0.5, beta=0.4, dt=0.05,
                    max_iterations=200, subdivision_levels=2)
    snake.fit(snapshot_every=40)

    snaps = snake.snapshots
    indices = [0,
               len(snaps) // 3,
               2 * len(snaps) // 3,
               len(snaps) - 1]
    chosen = [snaps[i] for i in indices]
    labels = ["Initial (convex hull)", "Early contraction",
              "Mid contraction", f"Final (iter {snake.iterations_run})"]
    colors = ["#4CAF50", "#FFC107", "#FF5722", "#2196F3"]

    fig, axes = plt.subplots(1, 4, figsize=(16, 4.5),
                             subplot_kw={"projection": "3d"})
    fig.suptitle("Snake 3D Evolution — Unit Cube", fontsize=13, fontweight="bold")

    for ax, verts, label, color in zip(axes, chosen, labels, colors):
        ax.scatter(*pts.T, c="lightgray", s=2, depthshade=False, alpha=0.4)
        _draw_mesh(ax, verts, snake.faces, color=color, alpha=0.25,
                   edge_color=color, lw=0.25)
        ax.set_title(label, fontsize=9)
        _set_equal_axes(ax, pts)

    plt.tight_layout()
    path = out_dir / "figure_2_evolution.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


def figure_protrusion(out_dir: Path) -> None:
    print("[Fig 3] Protrusion bypass (high α vs low α) …")
    v, f = _cube_with_spike(spike_h=0.20, spike_b=0.12)
    pts = sample_mesh_surface([(v, f)], sampling_resolution=0.05)

    configs = [
        ("High α = 0.85  β = 0.15  dt = 0.04\n(spike bypassed)",
         0.85, 0.15, 0.04, "#2196F3"),
        ("Low  α = 0.10  β = 0.80  dt = 0.02\n(spike wrapped)",
         0.10, 0.80, 0.02, "#E91E63"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5),
                             subplot_kw={"projection": "3d"})
    fig.suptitle("Active Contour: Protrusion Bypass vs Wrap\n"
                 "Spike tip at z=1.20 · Test point at z=1.15 (inside spike)",
                 fontsize=12, fontweight="bold")

    test_pt = np.array([0.5, 0.5, 1.15])

    for ax, (title, alpha, beta, dt, color) in zip(axes, configs):
        snake = Snake3D(pts, alpha=alpha, beta=beta, dt=dt,
                        max_iterations=300, subdivision_levels=2).fit()
        inside = snake.contains(test_pt)
        status = "INSIDE contour ✓" if inside else "OUTSIDE contour ✓"

        ax.scatter(*pts.T, c="lightgray", s=2, depthshade=False, alpha=0.35)
        _draw_mesh(ax, snake.vertices, snake.faces, color=color,
                   alpha=0.28, edge_color=color, lw=0.2)

        pt_color = "lime" if inside else "red"
        ax.scatter(*test_pt, c=pt_color, s=100, zorder=10,
                   label=f"Test point: {status}")

        ax.set_title(f"{title}\nTest point: {status}", fontsize=8.5)
        ax.legend(fontsize=7, loc="upper left")
        _set_equal_axes(ax, pts)

    plt.tight_layout()
    path = out_dir / "figure_3_protrusion.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


def figure_convergence(out_dir: Path) -> None:
    print("[Fig 4] Convergence curves …")
    v, f = _unit_cube()
    pts = sample_mesh_surface([(v, f)], sampling_resolution=0.12)

    fig, ax = plt.subplots(figsize=(8, 4))
    fig.suptitle("Snake Convergence — Max Vertex Displacement per Iteration",
                 fontsize=12, fontweight="bold")

    for alpha, beta, label, color in [
        (0.8, 0.2, "α=0.8  β=0.2  (smooth)", "royalblue"),
        (0.5, 0.4, "α=0.5  β=0.4  (balanced)", "darkorange"),
        (0.1, 0.8, "α=0.1  β=0.8  (tight fit)", "crimson"),
    ]:
        snake = Snake3D(pts, alpha=alpha, beta=beta, dt=0.05,
                        max_iterations=200, subdivision_levels=2).fit()
        ax.semilogy(snake.max_displacements, label=label, color=color, lw=1.5)

    ax.axhline(1e-4, ls="--", color="gray", lw=0.8, label="convergence threshold")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Max displacement (log scale)")
    ax.legend(fontsize=9)
    ax.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    path = out_dir / "figure_4_convergence.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


def run_snake3d() -> None:
    """Run the four Snake3D demo figures."""
    SNAKE3D_OUT_DIR.mkdir(parents=True, exist_ok=True)
    figure_sampling(SNAKE3D_OUT_DIR)
    figure_evolution(SNAKE3D_OUT_DIR)
    figure_protrusion(SNAKE3D_OUT_DIR)
    figure_convergence(SNAKE3D_OUT_DIR)
    print(f"\nAll Snake3D figures saved to {SNAKE3D_OUT_DIR}/")


# =====================================================================
# TerrainSnake mode — real terrain fit (cloth simulation result)
# =====================================================================

@dataclass
class TerrainData:
    """Everything the terrain visualisations need, loaded once."""
    heightmap: np.ndarray              # (nx, ny) float64 — cloth Z
    floor_raw: np.ndarray              # (nx, ny) float64 — terrain_z_floor (NaN-friendly)
    disps:     np.ndarray              # (n_iter,) float64 — max displacement per iter
    bounds:    tuple                   # (min_x, min_y, max_x, max_y, min_z, max_z)
    res:       float
    nx:        int
    ny:        int
    valid_floor: np.ndarray            # (nx, ny) bool
    valid_hmap:  np.ndarray            # (nx, ny) bool
    bridged:     np.ndarray            # (nx, ny) bool — heightmap valid AND floor NaN
    XX: np.ndarray                     # (nx, ny) world-X grid centres
    YY: np.ndarray                     # (nx, ny) world-Y grid centres
    camera_xyz: Optional[np.ndarray]   # 3-vector or None
    # Optional path overlay
    pts: np.ndarray                    # (N,3) world-coord path points
    wps: np.ndarray                    # (W,3) world-coord waypoints (converted from voxel idx)
    camera_height: float
    has_path: bool


def _load_terrain_data(result_dir: Path) -> TerrainData:
    """Load `terrain_snake.npz` (required) and `path.npz` (optional)."""
    npz_path  = result_dir / "terrain_snake.npz"
    pnpz_path = result_dir / "path.npz"

    data = np.load(npz_path)
    heightmap = data["heightmap"].astype(np.float64)
    floor_raw = data["terrain_z_floor"].astype(np.float64)
    disps     = data["max_displacements"].astype(np.float64)
    bounds    = tuple(data["bounds"])
    res       = float(data["res"])
    min_x, min_y, max_x, max_y, _min_z, _max_z = bounds
    nx, ny = heightmap.shape

    camera_xyz = data["camera_xyz"] if "camera_xyz" in data.files else None

    if pnpz_path.exists():
        pdata = np.load(pnpz_path)
        pts   = pdata["path_points"]
        wps_v = pdata["waypoints"]            # voxel indices (int32)
        camera_height = float(pdata["camera_height"])
        # Convert voxel-index waypoints → world XY for plotting on a
        # world-coord axis. (path_points are already in world coords;
        # waypoints are not — easy bug.)
        wx = min_x + (wps_v[:, 0].astype(float) + 0.5) * res
        wy = min_y + (wps_v[:, 1].astype(float) + 0.5) * res
        wz = bounds[4] + (wps_v[:, 2].astype(float) + 0.5) * res
        wps = np.column_stack([wx, wy, wz])
        has_path = True
    else:
        pts = np.empty((0, 3))
        wps = np.empty((0, 3))
        camera_height = 1.7
        has_path = False
        print(f"[viz] {pnpz_path} not found — fig 1/2 omit camera-path overlay")

    xs = min_x + (np.arange(nx) + 0.5) * res
    ys = min_y + (np.arange(ny) + 0.5) * res
    XX, YY = np.meshgrid(xs, ys, indexing="ij")

    valid_floor = ~np.isnan(floor_raw)
    valid_hmap  = ~np.isnan(heightmap)
    bridged     = valid_hmap & ~valid_floor

    return TerrainData(
        heightmap=heightmap, floor_raw=floor_raw, disps=disps,
        bounds=bounds, res=res, nx=nx, ny=ny,
        valid_floor=valid_floor, valid_hmap=valid_hmap, bridged=bridged,
        XX=XX, YY=YY, camera_xyz=camera_xyz,
        pts=pts, wps=wps, camera_height=camera_height, has_path=has_path,
    )


# ---------------------------------------------------------------------
# TerrainSnake figures
# ---------------------------------------------------------------------

def terrain_figure_0(td: TerrainData, out_dir: Path) -> None:
    """Initial cloth (z_max) vs final cloth (settled on terrain)."""
    min_x, min_y, max_x, max_y, _min_z, max_z = td.bounds
    final_mean_z = float(np.nanmean(td.heightmap))

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(
        "TerrainSnake — Arctic Midnight Sun\n"
        f"Initial Cloth (orange, flat at z_max={max_z:.0f} m)  vs  "
        f"Final Cloth (blue, settled at z≈{final_mean_z:.1f} m)",
        fontsize=12,
    )

    step = 4
    xx_s = td.XX[::step, ::step].ravel()
    yy_s = td.YY[::step, ::step].ravel()
    init_z  = np.full_like(xx_s, max_z)
    final_z = td.heightmap[::step, ::step].ravel()
    vh_s    = td.valid_hmap[::step, ::step].ravel()
    vf_s    = td.valid_floor[::step, ::step].ravel()

    ax = axes[0]
    ax.scatter(xx_s[~vf_s], yy_s[~vf_s], s=4, c="orange", alpha=0.5,
               label="bridged by Laplacian (NaN hit)")
    ax.scatter(xx_s[vf_s],  yy_s[vf_s],  s=4, c="steelblue", alpha=0.3,
               label="direct ray-cast hit")
    ax.set_title("Top (XY) — hit coverage\norange = Laplacian-bridged, blue = direct hit",
                 fontsize=9)
    ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
    ax.set_aspect("equal"); ax.legend(fontsize=8, markerscale=3)

    for ax, coord, label_axis in [(axes[1], xx_s, "X (m)"),
                                  (axes[2], yy_s, "Y (m)")]:
        ax.scatter(coord, init_z, s=3, c="darkorange", alpha=0.15,
                   label=f"initial cloth (z={max_z:.0f} m)")
        ax.scatter(coord[vh_s], final_z[vh_s], s=3, c="steelblue", alpha=0.3,
                   label=f"final cloth (z≈{final_mean_z:.1f} m)")
        ax.axhline(max_z, color="darkorange", lw=1.2, ls="--", alpha=0.6)
        ax.axhline(final_mean_z, color="steelblue", lw=1.2, ls="--", alpha=0.6)
        ax.set_xlabel(label_axis); ax.set_ylabel("Z (m)")
        ax.set_ylim(min(np.nanmin(td.heightmap), max_z) - 5,
                    max(max_z, float(np.nanmax(td.heightmap))) + 5)
        ax.legend(fontsize=8, markerscale=3)

    # Drop arrow on the XZ panel
    ax = axes[1]
    arrow_x = float(min_x) * 0.3
    ax.annotate("", xy=(arrow_x, final_mean_z + 1),
                xytext=(arrow_x, max_z - 1),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.text(arrow_x + td.res * 2, (max_z + final_mean_z) / 2,
            f"falls {max_z - final_mean_z:.0f} m\n"
            f"({int((max_z - final_mean_z) / 0.1)} steps\n"
            f"@ gravity=0.1/step)",
            fontsize=8, va="center")
    axes[1].set_title("Front (XZ) — cloth fall from z_max to terrain", fontsize=9)
    axes[2].set_title("Side (YZ) — cloth fall from z_max to terrain", fontsize=9)

    plt.tight_layout()
    out = out_dir / "figure_0_initial_vs_final.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


def terrain_figure_1(td: TerrainData, out_dir: Path) -> None:
    """Top-down: ray-cast coverage vs snake heightmap vs bridged columns."""
    min_x, min_y, max_x, max_y, _, _ = td.bounds

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(
        "TerrainSnake — Arctic Midnight Sun\n"
        f"Ray-Cast Hits vs Snake Heightmap (top-down, "
        f"{td.nx}×{td.ny} grid, {td.res:.0f} m/cell)",
        fontsize=12,
    )

    ax = axes[0]
    im = ax.imshow(td.valid_floor.astype(float).T, origin="lower",
                   extent=[min_x, max_x, min_y, max_y],
                   cmap="RdYlGn", vmin=0, vmax=1, aspect="equal")
    ax.set_title(f"Ray-Cast Coverage\n"
                 f"{td.valid_floor.sum():,} / {td.nx*td.ny:,} columns with valid hit",
                 fontsize=9)
    ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
    plt.colorbar(im, ax=ax, label="Hit")

    ax = axes[1]
    hm = np.where(td.valid_hmap, td.heightmap, np.nan)
    vmin = float(np.nanmin(hm)) - 5; vmax = float(np.nanmax(hm)) + 5
    im2 = ax.imshow(hm.T, origin="lower",
                    extent=[min_x, max_x, min_y, max_y],
                    cmap="terrain", vmin=vmin, vmax=vmax, aspect="equal")
    if td.has_path:
        ax.plot(td.pts[:, 0], td.pts[:, 1], "r-", lw=0.8, label="camera path")
        ax.scatter(td.wps[:, 0], td.wps[:, 1], c="yellow", s=45, zorder=5,
                   edgecolor="black", linewidth=0.6,
                   label=f"waypoints ({len(td.wps)})")
        ax.legend(fontsize=8)
    ax.set_title("Snake Heightmap (cloth Z)" +
                 (" + Camera Path" if td.has_path else ""), fontsize=9)
    ax.set_xlabel("X (m)")
    plt.colorbar(im2, ax=ax, label="Z (m)")

    ax = axes[2]
    im3 = ax.imshow(td.bridged.astype(float).T, origin="lower",
                    extent=[min_x, max_x, min_y, max_y],
                    cmap="Oranges", vmin=0, vmax=1, aspect="equal")
    ax.set_title(f"Bridged Columns (Laplacian filled NaN)\n"
                 f"{td.bridged.sum():,} columns — "
                 f"{td.bridged.sum()*100//(td.nx*td.ny)}% of grid",
                 fontsize=9)
    ax.set_xlabel("X (m)")
    plt.colorbar(im3, ax=ax, label="Bridged")

    plt.tight_layout()
    out = out_dir / "figure_1_top_down.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


def terrain_figure_2(td: TerrainData, out_dir: Path) -> None:
    """XZ + YZ side profiles (full grid projected, not single-slice)."""
    _, _, _, _, _, max_z = td.bounds

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(
        "TerrainSnake — Arctic Midnight Sun\n"
        "Side Profiles: Ray Hits (orange) vs Snake Cloth (blue) vs Camera Eye (red)",
        fontsize=12,
    )

    for ax, coord2d, label_c in [(axes[0], td.XX, "X (m)"),
                                 (axes[1], td.YY, "Y (m)")]:
        coord_f = coord2d.ravel()
        fl_f    = td.floor_raw.ravel()
        hm_f    = td.heightmap.ravel()
        vf      = ~np.isnan(fl_f)
        vh      = ~np.isnan(hm_f)

        ax.scatter(coord_f[vf][::8], fl_f[vf][::8],
                   s=1, c="darkorange", alpha=0.25, label="ray-cast hit Z")
        ax.scatter(coord_f[vh][::8], hm_f[vh][::8],
                   s=1, c="steelblue", alpha=0.15, label="snake cloth Z")

        if td.has_path:
            pc = td.pts[:, 0] if label_c == "X (m)" else td.pts[:, 1]
            ax.scatter(pc[::15], td.pts[:, 2][::15] + td.camera_height,
                       s=3, c="red", alpha=0.7,
                       label=f"camera eye (+{td.camera_height} m)")

        ax.set_xlabel(label_c); ax.set_ylabel("Z (m)")
        ax.set_title(f"{label_c} profile", fontsize=10)

        valid_floor_z = fl_f[vf]
        valid_hm_z    = hm_f[vh]
        if valid_floor_z.size or valid_hm_z.size:
            zs_parts = [
                valid_floor_z if valid_floor_z.size else np.array([]),
                valid_hm_z    if valid_hm_z.size    else np.array([]),
            ]
            if td.has_path:
                zs_parts.append(np.array([td.pts[:, 2].min(),
                                           td.pts[:, 2].max() + td.camera_height]))
            zs = np.concatenate(zs_parts)
            # Use 2nd/98th percentile to clip seabed outlier hits; ensure
            # camera-path Z extremes are always included in the range.
            z_lo = float(np.percentile(zs, 2))
            z_hi = float(np.percentile(zs, 98))
            if td.has_path:
                z_lo = min(z_lo, float(td.pts[:, 2].min()))
                z_hi = max(z_hi, float(td.pts[:, 2].max()) + td.camera_height)
            pad = max(2.0, (z_hi - z_lo) * 0.1)
            ax.set_ylim(z_lo - pad, z_hi + pad)
        else:
            ax.set_ylim(max_z - 50, max_z + 5)
        ax.legend(fontsize=8, markerscale=4)

    plt.tight_layout()
    out = out_dir / "figure_2_side_profiles.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------
# Figure 3 helper — vertical (XZ or YZ) slice through the camera
# ---------------------------------------------------------------------

def _draw_vertical_slice(ax, axis_label: str,
                         coord_along: np.ndarray,
                         floor_1d: np.ndarray, cloth_1d: np.ndarray,
                         coord_lo: float, coord_hi: float,
                         camera_along: float, camera_z: float,
                         slice_other: float, other_label: str) -> None:
    """Plot one vertical (XZ or YZ) slice through the camera column.

    coord_along: 1-D array of world coords along the slice axis.
    floor_1d / cloth_1d: 1-D terrain-floor and cloth Z arrays along the slice.
    coord_lo/hi: world-coord range of the slice axis.
    camera_along: camera position on the slice axis.
    slice_other: constant value of the perpendicular axis (Y for XZ, X for YZ).
    """
    valid = ~np.isnan(floor_1d)
    nan_   = ~valid
    n_v = int(valid.sum()); n_n = int(nan_.sum())

    nan_label_used = False
    in_nan = False
    nan_start = 0
    n = len(coord_along)
    cell = (coord_hi - coord_lo) / max(1, n)
    for i in range(n):
        if nan_[i] and not in_nan:
            nan_start = i; in_nan = True
        elif not nan_[i] and in_nan:
            kw = {"alpha": 0.13, "color": "forestgreen"}
            if not nan_label_used:
                kw["label"] = "NaN gap (Laplacian-bridged)"
                nan_label_used = True
            ax.axvspan(coord_along[nan_start] - cell/2,
                       coord_along[i-1]      + cell/2, **kw)
            in_nan = False
    if in_nan:
        kw = {"alpha": 0.13, "color": "forestgreen"}
        if not nan_label_used:
            kw["label"] = "NaN gap (Laplacian-bridged)"
        ax.axvspan(coord_along[nan_start] - cell/2,
                   coord_along[n-1]      + cell/2, **kw)

    ax.scatter(coord_along[valid], floor_1d[valid],
               s=12, c="darkorange", zorder=5, label="ray-cast hits (terrain Z)")
    cloth_on_hits = np.where(valid, cloth_1d, np.nan)
    cloth_bridged = np.where(nan_,  cloth_1d, np.nan)
    ax.plot(coord_along, cloth_on_hits, "b-", lw=1.6,
            label="snake cloth (over real hits)")
    if n_n > 0:
        ax.plot(coord_along, cloth_bridged, "b--", lw=1.4, alpha=0.7,
                label="snake cloth (Laplacian-bridged)")

    camera_eye = cloth_1d + 1.7
    ax.plot(coord_along, camera_eye, "r-", lw=1.0, alpha=0.8,
            label="camera eye (cloth + 1.7 m)")
    ax.scatter([camera_along], [camera_z], marker="*", s=180, c="yellow",
               edgecolor="black", linewidth=0.8, zorder=6,
               label=f"original camera @ Z={camera_z:.2f} m")

    title = f"{axis_label}Z cross-section ({other_label} = {slice_other:.1f} m) " \
            f"— {n_v} valid / {n_n} NaN"
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(f"{axis_label} (m)"); ax.set_ylabel("Z (m)")
    all_z = np.concatenate([floor_1d[valid], cloth_1d, camera_eye,
                            np.array([camera_z])])
    z_lo, z_hi = float(np.nanmin(all_z)), float(np.nanmax(all_z))
    pad = max(2.0, (z_hi - z_lo) * 0.1)
    ax.set_ylim(z_lo - pad, z_hi + pad)
    ax.set_xlim(coord_lo, coord_hi)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="upper right")


def terrain_figure_3(td: TerrainData, out_dir: Path) -> None:
    """Camera-anchored projections: XY top-down + XZ + YZ cross-sections.

    Three views, all anchored at the original scene camera (see CONVENTION
    in the module docstring):
      Panel A — XY top-down: cloth heightmap with green overlay marking the
                bridged (NaN-floor) cells, plus dashed lines showing where
                Panel B and Panel C take their cuts.
      Panel B — XZ vertical cross-section (vary X along Y = camera_Y).
      Panel C — YZ vertical cross-section (vary Y along X = camera_X).
    Same colour key across all three panels.
    """
    PROD_ALPHA, PROD_GRAVITY, PROD_DT = 0.5, 0.1, 1.0
    min_x, min_y, max_x, max_y, _, max_z = td.bounds

    if td.camera_xyz is None:
        cam_x_w = (min_x + max_x) / 2.0
        cam_y_w = (min_y + max_y) / 2.0
        cam_z_w = float(max_z)
    else:
        cam_x_w = float(td.camera_xyz[0])
        cam_y_w = float(td.camera_xyz[1])
        cam_z_w = float(td.camera_xyz[2])

    slice_iy = camera_anchored_iy(td.camera_xyz, min_y, td.res, td.ny)
    slice_ix = camera_anchored_ix(td.camera_xyz, min_x, td.res, td.nx)
    slice_y_actual = min_y + (slice_iy + 0.5) * td.res
    slice_x_actual = min_x + (slice_ix + 0.5) * td.res

    xs_slice = min_x + (np.arange(td.nx) + 0.5) * td.res
    ys_slice = min_y + (np.arange(td.ny) + 0.5) * td.res
    floor_xz = td.floor_raw[:, slice_iy]
    cloth_xz = td.heightmap[:, slice_iy]
    floor_yz = td.floor_raw[slice_ix, :]
    cloth_yz = td.heightmap[slice_ix, :]

    fig, axes = plt.subplots(1, 3, figsize=(24, 6),
                             gridspec_kw={"width_ratios": [1.0, 1.4, 1.4]})
    fig.suptitle(
        f"TerrainSnake — Camera-anchored projections (XY top-down + XZ + YZ cross-sections)\n"
        f"Original scene camera @ ({cam_x_w:.1f}, {cam_y_w:.1f}, {cam_z_w:.2f}) m | "
        f"Production params: α={PROD_ALPHA}, gravity={PROD_GRAVITY}/step, dt={PROD_DT}",
        fontsize=11,
    )

    # Panel A: XY top-down + green bridging overlay + slice lines
    ax = axes[0]
    hm_disp = np.where(td.valid_hmap, td.heightmap, np.nan)
    vmin = float(np.nanmin(hm_disp)) - 2; vmax = float(np.nanmax(hm_disp)) + 2
    im = ax.imshow(hm_disp.T, origin="lower",
                   extent=[min_x, max_x, min_y, max_y],
                   cmap="terrain", vmin=vmin, vmax=vmax, aspect="equal")
    plt.colorbar(im, ax=ax, label="cloth Z (m)", fraction=0.046, pad=0.04)

    bridged_xy = np.isnan(td.floor_raw) & ~np.isnan(td.heightmap)
    overlay = np.zeros((td.ny, td.nx, 4), dtype=np.float32)
    br_T = bridged_xy.T
    overlay[br_T, 0] = 0.13
    overlay[br_T, 1] = 0.55
    overlay[br_T, 2] = 0.13
    overlay[br_T, 3] = 0.55
    ax.imshow(overlay, origin="lower",
              extent=[min_x, max_x, min_y, max_y], aspect="equal",
              interpolation="nearest")

    n_bridged_xy = int(bridged_xy.sum())
    ax.axhline(slice_y_actual, color="red", lw=1.2, ls="--", alpha=0.85,
               label=f"XZ slice (Y={slice_y_actual:.1f} m)")
    ax.axvline(slice_x_actual, color="purple", lw=1.2, ls="--", alpha=0.85,
               label=f"YZ slice (X={slice_x_actual:.1f} m)")
    ax.scatter([cam_x_w], [cam_y_w], marker="*", s=180, c="yellow",
               edgecolor="black", linewidth=0.8, zorder=6,
               label="original camera (XY)")
    bridge_patch = Patch(facecolor=(0.13, 0.55, 0.13, 0.55),
                         edgecolor="none",
                         label=f"bridged cells ({n_bridged_xy:,}, "
                               f"{100*n_bridged_xy//(td.nx*td.ny)}% of grid)")
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles=handles + [bridge_patch], fontsize=8, loc="upper right")
    ax.set_title("XY top-down — heightmap + bridged cells (green)", fontsize=10)
    ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
    ax.set_xlim(min_x, max_x); ax.set_ylim(min_y, max_y)

    # Panels B/C: vertical slices through the camera
    _draw_vertical_slice(
        axes[1], axis_label="X",
        coord_along=xs_slice, floor_1d=floor_xz, cloth_1d=cloth_xz,
        coord_lo=min_x, coord_hi=max_x,
        camera_along=cam_x_w, camera_z=cam_z_w,
        slice_other=slice_y_actual, other_label="Y",
    )
    _draw_vertical_slice(
        axes[2], axis_label="Y",
        coord_along=ys_slice, floor_1d=floor_yz, cloth_1d=cloth_yz,
        coord_lo=min_y, coord_hi=max_y,
        camera_along=cam_y_w, camera_z=cam_z_w,
        slice_other=slice_x_actual, other_label="X",
    )

    plt.tight_layout()
    out = out_dir / "figure_3_bridging_demo.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


def terrain_figure_4(td: TerrainData, out_dir: Path) -> None:
    """Convergence — max displacement per iteration (log scale)."""
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.suptitle("TerrainSnake Convergence — Arctic Midnight Sun", fontsize=12)
    ax.semilogy(td.disps, color="steelblue", lw=1.5)
    ax.axhline(1e-3, color="grey", ls="--", label="convergence threshold = 1e-3")
    ax.set_xlabel("Iteration"); ax.set_ylabel("Max displacement (m, log scale)")
    n = len(td.disps); final_d = td.disps[-1]
    ax.set_title(
        f"{n} iterations (hit max). Final displacement: {final_d:.4f} m\n"
        f"Flat terrain: cloth free-falls under gravity, no smooth ramp to zero "
        f"(plateau guard prevents false-stop at constant velocity).",
        fontsize=9,
    )
    ax.legend(fontsize=9)
    plt.tight_layout()
    out = out_dir / "figure_4_convergence.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


def terrain_figure_5(td: TerrainData, out_dir: Path) -> None:
    """Phase 2 — XY top-down walkthrough path + numbered waypoints.

    Left panel: full terrain heightmap + path coloured by progress + waypoints.
    Right panel: zoomed view around the path bounding box.
    Skipped (no-op) if no path.npz was found.
    """
    if not td.has_path:
        print("[viz] figure_5 skipped — no path.npz")
        return

    min_x, min_y, max_x, max_y, _, _ = td.bounds
    hm = np.where(td.valid_hmap, td.heightmap, np.nan)
    vmin = float(np.nanmin(hm)) - 5
    vmax = float(np.nanmax(hm)) + 5

    # Arc-length fraction for path colouring (0=start, 1=end)
    diffs = np.diff(td.pts[:, :2], axis=0)
    seg_len = np.sqrt((diffs**2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    t_frac = cum / max(cum[-1], 1e-6)   # (N,) ∈ [0,1]

    def _draw_panel(ax, xlim, ylim, title, label_wps=True):
        im = ax.imshow(hm.T, origin="lower",
                       extent=[min_x, max_x, min_y, max_y],
                       cmap="terrain", vmin=vmin, vmax=vmax,
                       aspect="equal", interpolation="bilinear")

        # Path coloured by progress: blue=start → yellow=end
        from matplotlib.collections import LineCollection
        pts2 = td.pts[:, :2]
        segs = np.stack([pts2[:-1], pts2[1:]], axis=1)
        lc = LineCollection(segs, cmap="plasma",
                            norm=plt.Normalize(0, 1), linewidths=1.4)
        lc.set_array(t_frac[:-1])
        ax.add_collection(lc)

        # Waypoints numbered in tour order
        n_wps = len(td.wps)
        ax.scatter(td.wps[:, 0], td.wps[:, 1],
                   c="white", s=60, zorder=6,
                   edgecolor="black", linewidths=0.8)
        if label_wps:
            for i, (wx, wy, _) in enumerate(td.wps):
                ax.annotate(str(i + 1), (wx, wy),
                            fontsize=6, ha="center", va="center",
                            fontweight="bold", zorder=7)

        # Start (green diamond) and end (red square)
        ax.scatter(*td.pts[0, :2],  marker="D", c="lime",  s=90, zorder=8,
                   edgecolor="black", linewidths=0.8, label="start")
        ax.scatter(*td.pts[-1, :2], marker="s", c="red",   s=90, zorder=8,
                   edgecolor="black", linewidths=0.8, label="end")

        # Original scene camera
        if td.camera_xyz is not None:
            cx, cy = float(td.camera_xyz[0]), float(td.camera_xyz[1])
            ax.scatter(cx, cy, marker="*", c="yellow", s=160, zorder=9,
                       edgecolor="black", linewidths=0.6, label="scene camera")

        ax.set_xlim(xlim); ax.set_ylim(ylim)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
        ax.legend(fontsize=7, loc="upper right")

        # Colourbar for path progress
        sm = plt.cm.ScalarMappable(cmap="plasma", norm=plt.Normalize(0, 1))
        sm.set_array([])
        plt.colorbar(sm, ax=ax, label="Path progress (0=start, 1=end)",
                     fraction=0.03, pad=0.01)

    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    fig.suptitle(
        "Phase 2 — Walkthrough Path (XY top-down)\n"
        "Path coloured by progress (plasma: blue=start → yellow=end), white circles = waypoints (numbered in tour order)",
        fontsize=11,
    )

    _draw_panel(ax, (min_x, max_x), (min_y, max_y),
                f"Full terrain ({td.nx}×{td.ny} grid, {td.res:.0f} m/cell) — "
                f"{len(td.pts)} path points, {len(td.wps)} waypoints")

    plt.tight_layout()
    out = out_dir / "figure_5_walkthrough_path.png"
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"Saved {out}")


def run_terrain_snake(result_dir: Path) -> None:
    """Generate all 6 TerrainSnake figures for `result_dir`."""
    out_dir = result_dir / "viz"
    out_dir.mkdir(parents=True, exist_ok=True)
    td = _load_terrain_data(result_dir)
    terrain_figure_0(td, out_dir)
    terrain_figure_1(td, out_dir)
    terrain_figure_2(td, out_dir)
    terrain_figure_3(td, out_dir)
    terrain_figure_4(td, out_dir)
    terrain_figure_5(td, out_dir)
    print(f"\nAll TerrainSnake figures saved to {out_dir}")


# =====================================================================
# Main — CLI dispatch
# =====================================================================

def main(argv: list = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "terrain":
        result_dir = Path(argv[1]) if len(argv) > 1 \
                     else Path("results/arctic_midnight_sun_v1")
        run_terrain_snake(result_dir)
    elif argv and argv[0] == "snake":
        run_snake3d()
    elif not argv:
        run_snake3d()
    else:
        print(f"unknown mode: {argv[0]!r}\n"
              f"usage: python {Path(__file__).name} [snake | terrain [result_dir]]",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
