"""Visualize TerrainSnake results for arctic_midnight_sun_*.

Usage:
    python visualize_terrain_snake_arctic.py [result_dir]

Default result_dir = results/arctic_midnight_sun_v1.  path.npz is optional —
when missing, fig 1/2 omit the camera-path overlay.

5 figures (same style as Snake3D visualizations):
  fig0 -- initial cloth (flat at z_max) vs final cloth (settled on terrain)
  fig1 -- top-down: raw terrain hits vs snake heightmap
  fig2 -- XZ and YZ side profiles: hits, snake cloth, camera path
  fig3 -- bridging demo: conceptual 2D cross-section showing gap bridging
  fig4 -- convergence: max displacement per iteration
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

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


# ── Figure 3: flat-plane bridging demo (production params) ───────────────
# Synthetic 1-D terrain at constant Z=50 m, with 3 NaN gap patches.  Uses the
# same alpha/gravity/dt as the production fit so the bridging behaviour you
# see here matches what the snake does on the real scene.
from genesis_tools.active_contour.terrain_snake import TerrainSnake

PROD_ALPHA   = 0.5    # matches fit_terrain_contour default
PROD_GRAVITY = 0.1
PROD_DT      = 1.0

N = 200
x1d = np.linspace(-100, 100, N)
flat_z = np.full(N, 50.0)

# Three gap patches where the downward ray missed (vegetation, water, cloud).
gaps = [(40, 20), (100, 15), (155, 12)]
miss = np.zeros(N, bool)
for s, l in gaps:
    miss[s:s + l] = True
hits_1d = np.where(miss, np.nan, flat_z)

# Cloth sized (N, 1) — TerrainSnake is 2-D internally, but a 1-cell strip in
# Y exercises only the X-direction Laplacian, which is what we want to show.
floor_2d = hits_1d.reshape(N, 1)
demo = TerrainSnake(
    terrain_z_floor=floor_2d,
    bounds=(-100.0, -0.5, 100.0, 0.5, 0.0, 100.0),
    res=1.0,
    alpha=PROD_ALPHA, gravity=PROD_GRAVITY, dt=PROD_DT,
    max_iterations=600, convergence_threshold=1e-3,
    # Start every cloth vertex high above the plane so the fall is visible
    # in the figure (mirrors the production "cloth_init_z = camera_z" case
    # where camera_z sits above the terrain).
    cloth_init_z=80.0,
)

# Capture cloth at several iterations so the evolution is visible.
snap_iters = [0, 20, 60, 150]
snaps = {}
for target in snap_iters:
    while demo.iterations_run < target:
        demo.step()
    snaps[target] = demo.to_heightmap()[:, 0].copy()
demo.fit()
snaps["final"] = demo.to_heightmap()[:, 0].copy()
final_iters = demo.iterations_run

fig, ax = plt.subplots(figsize=(14, 6))
fig.suptitle(
    f"TerrainSnake — Cloth bridging on a flat plane (production params: "
    f"α={PROD_ALPHA}, gravity={PROD_GRAVITY}/step, dt={PROD_DT})\n"
    f"Synthetic 1-D profile with 3 gap patches; cloth init Z = 80 m, true plane at 50 m",
    fontsize=11,
)

# Reference plane + ray-cast hits
ax.axhline(50.0, color="k", lw=1.0, ls="--", alpha=0.5,
           label="true terrain plane (Z = 50 m)")
ax.scatter(x1d[~miss], hits_1d[~miss], s=10, c="darkorange", zorder=5,
           label="ray-cast hits (valid columns)")

# Gap shading
for s, l in gaps:
    kw = {"alpha": 0.12, "color": "forestgreen"}
    if s == gaps[0][0]:
        kw["label"] = "NaN gap (no ray hit — bridged by Laplacian)"
    ax.axvspan(x1d[s], x1d[min(s + l, N - 1)], **kw)

# Cloth evolution
evolution_colors = ["#ccccff", "#9999ee", "#6666cc", "#3333aa"]
for it, c in zip(snap_iters, evolution_colors):
    ax.plot(x1d, snaps[it], color=c, lw=0.9, label=f"cloth @ iter {it}")
ax.plot(x1d, snaps["final"], "b-", lw=2.2,
        label=f"final cloth (iter {final_iters})")
ax.plot(x1d, snaps["final"] + 1.7, "r--", lw=1.3,
        label="camera eye (cloth + 1.7 m)")

# Annotate gap droop = how far cloth dips below the plane in each gap
gap_centres = [s + l // 2 for s, l in gaps]
for c_idx in gap_centres:
    droop = 50.0 - float(snaps["final"][c_idx])
    if droop > 0.05:
        ax.annotate(f"droop {droop:.2f} m",
                    xy=(x1d[c_idx], snaps["final"][c_idx]),
                    xytext=(x1d[c_idx], snaps["final"][c_idx] - 3.0),
                    ha="center", fontsize=8, color="#222266",
                    arrowprops=dict(arrowstyle="->", color="#222266", lw=0.7))

ax.set_xlabel("X (m)"); ax.set_ylabel("Z (m)")
# Auto-range to the data with a small pad
all_z = np.concatenate([
    np.array([50.0, 80.0]),
    *[snaps[k] for k in (snap_iters + ["final"])],
])
ax.set_ylim(float(all_z.min()) - 3.0, float(all_z.max()) + 3.0)

handles, labels = ax.get_legend_handles_labels()
seen = {}
for h, l in zip(handles, labels):
    if l not in seen:
        seen[l] = h
ax.legend(seen.values(), seen.keys(), fontsize=9, loc="upper right")

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
