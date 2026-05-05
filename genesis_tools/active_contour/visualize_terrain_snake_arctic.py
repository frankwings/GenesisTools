"""Visualize TerrainSnake results for arctic_midnight_sun_*.

Usage (from the GenesisTools repo root):
    python genesis_tools/active_contour/visualize_terrain_snake_arctic.py [result_dir]

Default result_dir = results/arctic_midnight_sun_v1.  path.npz is optional —
when missing, fig 1/2 omit the camera-path overlay.

Path conventions: `result_dir` is interpreted relative to the current
working directory (the repo root in normal use).  The script writes
figures to `<result_dir>/viz/`.

5 figures (same style as Snake3D visualizations):
  fig0 -- initial cloth (flat at z_max) vs final cloth (settled on terrain)
  fig1 -- top-down: raw terrain hits vs snake heightmap
  fig2 -- XZ and YZ side profiles: hits, snake cloth, camera path
  fig3 -- camera-anchored projections: XY top-down + XZ + YZ cross-sections
  fig4 -- convergence: max displacement per iteration

All 1-D slice / cross-section figures in this file are anchored at the
original scene camera's XY — see `camera_anchored_slice.py` for the
convention and the helpers used to pick the slice indices.
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from genesis_tools.active_contour.camera_anchored_slice import (
    camera_anchored_iy as _camera_anchored_iy,
    camera_anchored_ix as _camera_anchored_ix,
)


RESULT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 \
    else Path("results/arctic_midnight_sun_v1")
OUT_DIR = RESULT_DIR / "viz"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NPZ  = RESULT_DIR / "terrain_snake.npz"
PNPZ = RESULT_DIR / "path.npz"

data  = np.load(NPZ)
heightmap   = data["heightmap"].astype(np.float64)       # (nx,ny)
floor_raw   = data["terrain_z_floor"].astype(np.float64) # (nx,ny)
disps       = data["max_displacements"].astype(np.float64)
bounds      = tuple(data["bounds"])
res         = float(data["res"])
min_x, min_y, max_x, max_y, min_z, max_z = bounds
nx, ny = heightmap.shape

if PNPZ.exists():
    pdata = np.load(PNPZ)
    pts   = pdata["path_points"]      # (N,3) world coords
    wps_v = pdata["waypoints"]        # (20,3) **voxel indices** — see path_plan.py
    camera_height = float(pdata["camera_height"])
    # Convert voxel-index waypoints → world XY for plotting on a world-coord axis.
    # (path_points are already in world coords; waypoints are not — easy bug.)
    wps_world_x = min_x + (wps_v[:, 0].astype(float) + 0.5) * res
    wps_world_y = min_y + (wps_v[:, 1].astype(float) + 0.5) * res
    wps_world_z = min_z + (wps_v[:, 2].astype(float) + 0.5) * res
    wps = np.column_stack([wps_world_x, wps_world_y, wps_world_z])
    has_path = True
else:
    pts = np.empty((0, 3))
    wps = np.empty((0, 3))
    camera_height = 1.7
    has_path = False
    print(f"[viz] {PNPZ} not found — fig 1/2 omit camera-path overlay")

# World XY cell centres
xs = min_x + (np.arange(nx) + 0.5) * res
ys = min_y + (np.arange(ny) + 0.5) * res
XX, YY = np.meshgrid(xs, ys, indexing="ij")

valid_floor = ~np.isnan(floor_raw)
valid_hmap  = ~np.isnan(heightmap)
bridged     = valid_hmap & ~valid_floor   # columns where snake filled NaN

# ── Figure 0: initial cloth vs final cloth (equivalent of figure_2_contour) ──
final_mean_z = float(np.nanmean(heightmap))
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle(
    "TerrainSnake — Arctic Midnight Sun\n"
    f"Initial Cloth (orange, flat at z_max={max_z:.0f} m)  vs  "
    f"Final Cloth (blue, settled at z≈{final_mean_z:.1f} m)",
    fontsize=12,
)

# Subsample grid for scatter legibility
step = 4
xx_s = XX[::step, ::step].ravel()
yy_s = YY[::step, ::step].ravel()
init_z = np.full_like(xx_s, max_z)           # initial: flat at z_max
final_z = heightmap[::step, ::step].ravel()  # final: terrain surface
vh_s = valid_hmap[::step, ::step].ravel()

# Panel A: Top (XY) — both cloths collapsed to same XY, show which columns were bridged
ax = axes[0]
ax.scatter(xx_s[~valid_floor[::step, ::step].ravel()],
           yy_s[~valid_floor[::step, ::step].ravel()],
           s=4, c="orange", alpha=0.5, label="bridged by Laplacian (NaN hit)")
ax.scatter(xx_s[valid_floor[::step, ::step].ravel()],
           yy_s[valid_floor[::step, ::step].ravel()],
           s=4, c="steelblue", alpha=0.3, label="direct ray-cast hit")
ax.set_title("Top (XY) — hit coverage\norange = Laplacian-bridged, blue = direct hit", fontsize=9)
ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
ax.set_aspect("equal"); ax.legend(fontsize=8, markerscale=3)

# Panel B: Front (XZ) — shows the fall from z_max to terrain
ax = axes[1]
ax.scatter(xx_s, init_z, s=3, c="darkorange", alpha=0.15, label=f"initial cloth (z={max_z:.0f} m)")
ax.scatter(xx_s[vh_s], final_z[vh_s], s=3, c="steelblue", alpha=0.3,
           label=f"final cloth (z≈{np.nanmean(heightmap):.1f} m)")
ax.axhline(max_z, color="darkorange", lw=1.2, ls="--", alpha=0.6)
ax.axhline(float(np.nanmean(heightmap)), color="steelblue", lw=1.2, ls="--", alpha=0.6)
arrow_x = float(min_x) * 0.3
ax.annotate("", xy=(arrow_x, float(np.nanmean(heightmap)) + 1),
            xytext=(arrow_x, max_z - 1),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
ax.text(arrow_x + res * 2, (max_z + float(np.nanmean(heightmap))) / 2,
        f"falls {max_z - float(np.nanmean(heightmap)):.0f} m\n"
        f"({int((max_z - float(np.nanmean(heightmap))) / 0.1)} steps\n"
        f"@ gravity=0.1/step)",
        fontsize=8, va="center")
ax.set_title("Front (XZ) — cloth fall from z_max to terrain", fontsize=9)
ax.set_xlabel("X (m)"); ax.set_ylabel("Z (m)")
ax.set_ylim(min(np.nanmin(heightmap), max_z) - 5,
            max(max_z, float(np.nanmax(heightmap))) + 5)
ax.legend(fontsize=8, markerscale=3)

# Panel C: Side (YZ)
ax = axes[2]
ax.scatter(yy_s, init_z, s=3, c="darkorange", alpha=0.15, label=f"initial cloth (flat, z={max_z:.0f} m)")
ax.scatter(yy_s[vh_s], final_z[vh_s], s=3, c="steelblue", alpha=0.3,
           label=f"final cloth (z≈{np.nanmean(heightmap):.1f} m)")
ax.axhline(max_z, color="darkorange", lw=1.2, ls="--", alpha=0.6)
ax.axhline(float(np.nanmean(heightmap)), color="steelblue", lw=1.2, ls="--", alpha=0.6)
ax.set_title("Side (YZ) — cloth fall from z_max to terrain", fontsize=9)
ax.set_xlabel("Y (m)"); ax.set_ylabel("Z (m)")
ax.set_ylim(min(np.nanmin(heightmap), max_z) - 5,
            max(max_z, float(np.nanmax(heightmap))) + 5)
ax.legend(fontsize=8, markerscale=3)

plt.tight_layout()
out0 = OUT_DIR / "figure_0_initial_vs_final.png"
fig.savefig(out0, dpi=150); plt.close(fig)
print(f"Saved {out0}")


# ── Figure 1: top-down comparison ─────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle(
    "TerrainSnake — Arctic Midnight Sun\n"
    "Ray-Cast Hits vs Snake Heightmap (top-down, 180×180 grid, 20 m/cell)",
    fontsize=12,
)

# Panel A: hit coverage
ax = axes[0]
im = ax.imshow(valid_floor.astype(float).T, origin="lower",
               extent=[min_x, max_x, min_y, max_y],
               cmap="RdYlGn", vmin=0, vmax=1, aspect="equal")
ax.set_title(f"Ray-Cast Coverage\n"
             f"{valid_floor.sum():,} / {nx*ny:,} columns with valid hit", fontsize=9)
ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
plt.colorbar(im, ax=ax, label="Hit")

# Panel B: snake heightmap
ax = axes[1]
hm = np.where(valid_hmap, heightmap, np.nan)
vmin = np.nanmin(hm) - 5; vmax = np.nanmax(hm) + 5
im2 = ax.imshow(hm.T, origin="lower",
                extent=[min_x, max_x, min_y, max_y],
                cmap="terrain", vmin=vmin, vmax=vmax, aspect="equal")
if has_path:
    ax.plot(pts[:, 0], pts[:, 1], "r-", lw=0.8, label="camera path")
    ax.scatter(wps[:, 0], wps[:, 1], c="yellow", s=45, zorder=5,
               edgecolor="black", linewidth=0.6,
               label=f"waypoints ({len(wps)})")
    ax.legend(fontsize=8)
ax.set_title("Snake Heightmap (cloth Z)" + (" + Camera Path" if has_path else ""),
             fontsize=9)
ax.set_xlabel("X (m)")
plt.colorbar(im2, ax=ax, label="Z (m)")

# Panel C: bridged columns (Laplacian filled NaN gaps)
ax = axes[2]
im3 = ax.imshow(bridged.astype(float).T, origin="lower",
                extent=[min_x, max_x, min_y, max_y],
                cmap="Oranges", vmin=0, vmax=1, aspect="equal")
ax.set_title(f"Bridged Columns (Laplacian filled NaN)\n"
             f"{bridged.sum():,} columns — {bridged.sum()*100//(nx*ny)}% of grid", fontsize=9)
ax.set_xlabel("X (m)")
plt.colorbar(im3, ax=ax, label="Bridged")

plt.tight_layout()
out1 = OUT_DIR / "figure_1_top_down.png"
fig.savefig(out1, dpi=150); plt.close(fig)
print(f"Saved {out1}")


# ── Figure 2: side profiles ────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(16, 6))
fig.suptitle(
    "TerrainSnake — Arctic Midnight Sun\n"
    "Side Profiles: Ray Hits (orange) vs Snake Cloth (blue) vs Camera Eye (red)",
    fontsize=12,
)

for ax, coord2d, label_c in [(axes[0], XX, "X (m)"), (axes[1], YY, "Y (m)")]:
    coord_f = coord2d.ravel()
    fl_f    = floor_raw.ravel()
    hm_f    = heightmap.ravel()
    vf      = ~np.isnan(fl_f)
    vh      = ~np.isnan(hm_f)

    ax.scatter(coord_f[vf][::8], fl_f[vf][::8],
               s=1, c="darkorange", alpha=0.25, label="ray-cast hit Z")
    ax.scatter(coord_f[vh][::8], hm_f[vh][::8],
               s=1, c="steelblue", alpha=0.15, label="snake cloth Z")

    # camera path overlay (optional)
    if has_path:
        pc = pts[:, 0] if label_c == "X (m)" else pts[:, 1]
        ax.scatter(pc[::15], pts[:, 2][::15] + camera_height,
                   s=3, c="red", alpha=0.7, label=f"camera eye (+{camera_height} m)")

    ax.set_xlabel(label_c); ax.set_ylabel("Z (m)")
    ax.set_title(f"{label_c} profile", fontsize=10)
    # Auto-range to the actual valid-cloth data, with a small padding.
    valid_floor_z = fl_f[vf]
    valid_hm_z    = hm_f[vh]
    if valid_floor_z.size or valid_hm_z.size:
        zs_parts = [
            valid_floor_z if valid_floor_z.size else np.array([]),
            valid_hm_z    if valid_hm_z.size    else np.array([]),
        ]
        if has_path:
            zs_parts.append(np.array([pts[:, 2].min(),
                                       pts[:, 2].max() + camera_height]))
        zs = np.concatenate(zs_parts)
        z_lo, z_hi = float(zs.min()), float(zs.max())
        pad = max(2.0, (z_hi - z_lo) * 0.1)
        ax.set_ylim(z_lo - pad, z_hi + pad)
    else:
        ax.set_ylim(max_z - 50, max_z + 5)
    ax.legend(fontsize=8, markerscale=4)

plt.tight_layout()
out2 = OUT_DIR / "figure_2_side_profiles.png"
fig.savefig(out2, dpi=150); plt.close(fig)
print(f"Saved {out2}")


# ── Figure 3: camera-anchored projections (XY + XZ + YZ) ────────────────
# Three views of the v57 fit, all anchored at the original scene camera:
#   Panel A — XY top-down: cloth heightmap with green overlay marking the
#             bridged (NaN-floor) cells, plus dashed lines showing where
#             Panel B and Panel C take their cuts.
#   Panel B — XZ vertical cross-section (vary X along Y = camera_Y).
#   Panel C — YZ vertical cross-section (vary Y along X = camera_X).
# Same colour key across all three panels (orange = ray-cast hit,
# blue = cloth, red = camera eye, green = bridged region, yellow ★ =
# camera).  Panels B/C share `_draw_vertical_slice()`.  Real v57 data.
PROD_ALPHA   = 0.5
PROD_GRAVITY = 0.1
PROD_DT      = 1.0

camera_xyz = data["camera_xyz"] if "camera_xyz" in data.files else None
if camera_xyz is None:
    cam_x_w = (min_x + max_x) / 2.0
    cam_y_w = (min_y + max_y) / 2.0
    cam_z_w = float(max_z)
else:
    cam_x_w = float(camera_xyz[0])
    cam_y_w = float(camera_xyz[1])
    cam_z_w = float(camera_xyz[2])

slice_iy = _camera_anchored_iy(camera_xyz, min_y, res, ny)
slice_ix = _camera_anchored_ix(camera_xyz, min_x, res, nx)
slice_y_actual = min_y + (slice_iy + 0.5) * res
slice_x_actual = min_x + (slice_ix + 0.5) * res


def _draw_vertical_slice(ax, axis_label: str,
                          coord_along: np.ndarray,
                          floor_1d: np.ndarray, cloth_1d: np.ndarray,
                          coord_lo: float, coord_hi: float,
                          camera_along: float, camera_z: float,
                          slice_other: float, other_label: str):
    """Plot one vertical (XZ or YZ) slice through the camera.

    coord_along: 1-D array of world coords along the slice axis (X or Y).
    floor_1d / cloth_1d: 1-D terrain-floor and cloth Z arrays along the slice.
    coord_lo/hi: world-coord range of the slice axis.
    camera_along: camera position on the slice axis.
    slice_other: the constant value of the perpendicular axis (Y for an
                 XZ slice, X for a YZ slice).
    """
    valid = ~np.isnan(floor_1d)
    nan_   = ~valid
    n_v = int(valid.sum()); n_n = int(nan_.sum())

    # Shade NaN runs
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

    # Hits + cloth (solid over hits, dashed over bridged)
    ax.scatter(coord_along[valid], floor_1d[valid],
               s=12, c="darkorange", zorder=5, label="ray-cast hits (terrain Z)")
    cloth_on_hits = np.where(valid, cloth_1d, np.nan)
    cloth_bridged = np.where(nan_,  cloth_1d, np.nan)
    ax.plot(coord_along, cloth_on_hits, "b-", lw=1.6,
            label="snake cloth (over real hits)")
    if n_n > 0:
        ax.plot(coord_along, cloth_bridged, "b--", lw=1.4, alpha=0.7,
                label="snake cloth (Laplacian-bridged)")

    # Camera eye + camera anchor
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


# Slice arrays
xs_slice = min_x + (np.arange(nx) + 0.5) * res        # (nx,)
ys_slice = min_y + (np.arange(ny) + 0.5) * res        # (ny,)
floor_xz = floor_raw[:, slice_iy]                     # XZ slice (vary X, fix Y)
cloth_xz = heightmap[:, slice_iy]
floor_yz = floor_raw[slice_ix, :]                     # YZ slice (vary Y, fix X)
cloth_yz = heightmap[slice_ix, :]

fig, axes = plt.subplots(1, 3, figsize=(24, 6),
                         gridspec_kw={"width_ratios": [1.0, 1.4, 1.4]})
fig.suptitle(
    f"TerrainSnake — Camera-anchored projections (XY top-down + XZ + YZ cross-sections)\n"
    f"Original scene camera @ ({cam_x_w:.1f}, {cam_y_w:.1f}, {cam_z_w:.2f}) m | "
    f"Production params: α={PROD_ALPHA}, gravity={PROD_GRAVITY}/step, dt={PROD_DT}",
    fontsize=11,
)

# ── Panel A: XY top-down bridging projection ───────────────────────────
# Cloth heightmap as base; overlay a green semi-transparent mask on cells
# whose terrain_z_floor is NaN (i.e. cloth is Laplacian-bridged here, not
# pinned to a real ray-cast hit).  Mirrors the green NaN-gap shading in
# Panels B/C so all three views show "the same bridging" from different
# angles.
ax = axes[0]
hm_disp = np.where(valid_hmap, heightmap, np.nan)
vmin = float(np.nanmin(hm_disp)) - 2; vmax = float(np.nanmax(hm_disp)) + 2
im = ax.imshow(hm_disp.T, origin="lower",
               extent=[min_x, max_x, min_y, max_y],
               cmap="terrain", vmin=vmin, vmax=vmax, aspect="equal")
plt.colorbar(im, ax=ax, label="cloth Z (m)", fraction=0.046, pad=0.04)

# Bridged cells: terrain_z_floor is NaN. Plot as a green RGBA overlay so
# the user sees exactly where (in 2-D) the cloth is bridging without
# floor support — green elsewhere fully transparent.
bridged_xy = np.isnan(floor_raw) & ~np.isnan(heightmap)
overlay = np.zeros((ny, nx, 4), dtype=np.float32)
br_T = bridged_xy.T
overlay[br_T, 0] = 0.13   # R
overlay[br_T, 1] = 0.55   # G — forestgreen-ish
overlay[br_T, 2] = 0.13   # B
overlay[br_T, 3] = 0.55   # A
ax.imshow(overlay, origin="lower",
          extent=[min_x, max_x, min_y, max_y], aspect="equal",
          interpolation="nearest")

n_bridged_xy = int(bridged_xy.sum())
# Slice lines for the XZ (Panel B) and YZ (Panel C) cuts
ax.axhline(slice_y_actual, color="red", lw=1.2, ls="--", alpha=0.85,
           label=f"XZ slice (Y={slice_y_actual:.1f} m)")
ax.axvline(slice_x_actual, color="purple", lw=1.2, ls="--", alpha=0.85,
           label=f"YZ slice (X={slice_x_actual:.1f} m)")
ax.scatter([cam_x_w], [cam_y_w], marker="*", s=180, c="yellow",
           edgecolor="black", linewidth=0.8, zorder=6,
           label="original camera (XY)")
from matplotlib.patches import Patch
bridge_patch = Patch(facecolor=(0.13, 0.55, 0.13, 0.55),
                     edgecolor="none",
                     label=f"bridged cells ({n_bridged_xy:,}, "
                           f"{100*n_bridged_xy//(nx*ny)}% of grid)")
handles, _ = ax.get_legend_handles_labels()
ax.legend(handles=handles + [bridge_patch], fontsize=8, loc="upper right")
ax.set_title("XY top-down — heightmap + bridged cells (green)", fontsize=10)
ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
ax.set_xlim(min_x, max_x); ax.set_ylim(min_y, max_y)

# ── Panel B: XZ cross-section (vary X along camera-Y row) ──────────────
_draw_vertical_slice(
    axes[1], axis_label="X",
    coord_along=xs_slice, floor_1d=floor_xz, cloth_1d=cloth_xz,
    coord_lo=min_x, coord_hi=max_x,
    camera_along=cam_x_w, camera_z=cam_z_w,
    slice_other=slice_y_actual, other_label="Y",
)
# ── Panel C: YZ cross-section (vary Y along camera-X column) ───────────
_draw_vertical_slice(
    axes[2], axis_label="Y",
    coord_along=ys_slice, floor_1d=floor_yz, cloth_1d=cloth_yz,
    coord_lo=min_y, coord_hi=max_y,
    camera_along=cam_y_w, camera_z=cam_z_w,
    slice_other=slice_x_actual, other_label="X",
)

plt.tight_layout()
out3 = OUT_DIR / "figure_3_bridging_demo.png"
fig.savefig(out3, dpi=150); plt.close(fig)
print(f"Saved {out3}")


# ── Figure 4: convergence ──────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
fig.suptitle("TerrainSnake Convergence — Arctic Midnight Sun", fontsize=12)
ax.semilogy(disps, color="steelblue", lw=1.5)
ax.axhline(1e-3, color="grey", ls="--", label="convergence threshold = 1e-3")
ax.set_xlabel("Iteration"); ax.set_ylabel("Max displacement (m, log scale)")
n = len(disps)
final_d = disps[-1]
ax.set_title(
    f"{n} iterations (hit max). Final displacement: {final_d:.4f} m\n"
    f"Flat terrain: cloth free-falls under gravity, no smooth ramp to zero "
    f"(plateau guard prevents false-stop at constant velocity).",
    fontsize=9,
)
ax.legend(fontsize=9)
plt.tight_layout()
out4 = OUT_DIR / "figure_4_convergence.png"
fig.savefig(out4, dpi=150); plt.close(fig)
print(f"Saved {out4}")

print(f"\nAll 4 figures saved to {OUT_DIR}")
