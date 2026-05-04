"""Visualize TerrainSnake results for arctic_midnight_sun_v1.

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

OUT_DIR = Path("results/arctic_midnight_sun_v1/viz")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NPZ  = Path("results/arctic_midnight_sun_v1/terrain_snake.npz")
PNPZ = Path("results/arctic_midnight_sun_v1/path.npz")

data  = np.load(NPZ)
heightmap   = data["heightmap"].astype(np.float64)       # (180,180)
floor_raw   = data["terrain_z_floor"].astype(np.float64) # (180,180)
disps       = data["max_displacements"].astype(np.float64)
bounds      = tuple(data["bounds"])
res         = float(data["res"])
min_x, min_y, max_x, max_y, min_z, max_z = bounds
nx, ny = heightmap.shape

pdata = np.load(PNPZ)
pts   = pdata["path_points"]   # (N,3) world coords
wps   = pdata["waypoints"]     # (20,3) world coords
camera_height = float(pdata["camera_height"])

# World XY cell centres
xs = min_x + (np.arange(nx) + 0.5) * res
ys = min_y + (np.arange(ny) + 0.5) * res
XX, YY = np.meshgrid(xs, ys, indexing="ij")

valid_floor = ~np.isnan(floor_raw)
valid_hmap  = ~np.isnan(heightmap)
bridged     = valid_hmap & ~valid_floor   # columns where snake filled NaN

# ── Figure 0: initial cloth vs final cloth (equivalent of figure_2_contour) ──
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle(
    "TerrainSnake — Arctic Midnight Sun\n"
    "Initial Cloth (orange, flat at z_max=130 m)  vs  Final Cloth (blue, settled at z=110 m)",
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
ax.set_ylim(max_z - 30, max_z + 5)
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
ax.set_ylim(max_z - 30, max_z + 5)
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
ax.plot(pts[:, 0], pts[:, 1], "r-", lw=0.8, label="camera path")
ax.scatter(wps[:, 0], wps[:, 1], c="yellow", s=25, zorder=5, label="waypoints")
ax.set_title("Snake Heightmap (cloth Z) + Camera Path", fontsize=9)
ax.set_xlabel("X (m)"); ax.legend(fontsize=8)
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

    # path
    pc = pts[:, 0] if label_c == "X (m)" else pts[:, 1]
    ax.scatter(pc[::15], pts[:, 2][::15] + camera_height,
               s=3, c="red", alpha=0.7, label=f"camera eye (+{camera_height} m)")

    ax.set_xlabel(label_c); ax.set_ylabel("Z (m)")
    ax.set_title(f"{label_c} profile", fontsize=10)
    ax.set_ylim(max_z - 50, max_z + 5)  # zoom to top 50 m where action is
    ax.legend(fontsize=8, markerscale=4)

plt.tight_layout()
out2 = OUT_DIR / "figure_2_side_profiles.png"
fig.savefig(out2, dpi=150); plt.close(fig)
print(f"Saved {out2}")


# ── Figure 3: 2D bridging concept demo ────────────────────────────────────
from genesis_tools.active_contour.terrain_snake import TerrainSnake

np.random.seed(42)
N = 200
x1d = np.linspace(-100, 100, N)
true_z = 10 * np.sin(x1d / 30) + 4 * np.sin(x1d / 9) + 50.0

# Three vegetation / obstacle gaps (no downward hit)
gaps = [(40, 20), (100, 15), (155, 12)]
miss = np.zeros(N, bool)
for s, l in gaps:
    miss[s:s + l] = True
hits_1d = np.where(miss, np.nan, true_z + np.random.randn(N) * 0.2)

floor_2d = hits_1d.reshape(N, 1)
demo = TerrainSnake(
    terrain_z_floor=floor_2d,
    bounds=(-100, -0.5, 100, 0.5, 0.0, 100.0),
    res=1.0, alpha=0.5, gravity=0.5, dt=1.0,
    max_iterations=600, convergence_threshold=1e-3,
    # Large start_height so valid columns also begin at ~z_max (flat at top),
    # matching the conceptual illustration of "cloth falls from high above".
    start_height=float(100.0 - np.nanmean(hits_1d)),
)

snaps = {}
for target in [0, 5, 20, 80]:
    while demo.iterations_run < target:
        demo.step()
    snaps[target] = demo.to_heightmap()[:, 0].copy()
demo.fit()
snaps["final"] = demo.to_heightmap()[:, 0].copy()

fig, ax = plt.subplots(figsize=(14, 6))
fig.suptitle(
    "TerrainSnake — How the Cloth Bridges Vegetation Gaps\n"
    "(synthetic 2-D profile, 3 gap patches in orange)",
    fontsize=12,
)

ax.plot(x1d, true_z, "k--", lw=1.2, alpha=0.35, label="true terrain (not seen by rays)")
ax.scatter(x1d[~miss], hits_1d[~miss], s=14, c="darkorange", zorder=5,
           label="ray-cast hits (sampling points)")
for s, l in gaps:
    kw = {"alpha": 0.12, "color": "forestgreen"}
    if s == gaps[0][0]:
        kw["label"] = "vegetation gap (NaN column)"
    ax.axvspan(x1d[s], x1d[min(s + l, N - 1)], **kw)

evolution_colors = ["#ccccff", "#9999ee", "#6666cc", "#3333aa"]
for (step, c) in zip([0, 5, 20, 80], evolution_colors):
    ax.plot(x1d, snaps[step], color=c, lw=0.9, label=f"cloth @ iter {step}")
ax.plot(x1d, snaps["final"], "b-", lw=2.2, label="final cloth (snake converged)")
ax.plot(x1d, snaps["final"] + 1.7, "r--", lw=1.3, label="camera eye (cloth + 1.7 m)")

ax.set_xlabel("X (m)"); ax.set_ylabel("Z (m)")
ax.set_ylim(30, 105)
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
