"""Visualise 3D Active Contour (Snake) behaviour.

Produces four figures saved to results/active_contour/:

  figure_1_sampling.png       — sampled point cloud vs sparse vertices
  figure_2_evolution.png      — snake surface at 4 stages of contraction
  figure_3_protrusion.png     — HIGH alpha (bypasses spike) vs LOW alpha (wraps spike)
  figure_4_convergence.png    — max-displacement curve over iterations

Usage
-----
    cd GenesisTools
    python genesis_tools/active_contour/visualize.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # headless — no display required
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3D projection)
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
)

OUT_DIR = Path(__file__).resolve().parents[3] / "results" / "active_contour"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Figure 1 — Sampling
# ---------------------------------------------------------------------------

def figure_sampling() -> None:
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
    path = OUT_DIR / "figure_1_sampling.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


# ---------------------------------------------------------------------------
# Figure 2 — Snake evolution
# ---------------------------------------------------------------------------

def figure_evolution() -> None:
    print("[Fig 2] Snake evolution (cube) …")
    v, f = _unit_cube()
    pts = sample_mesh_surface([(v, f)], sampling_resolution=0.12)

    snake = Snake3D(pts, alpha=0.5, beta=0.4, dt=0.05,
                    max_iterations=200, subdivision_levels=2)
    snake.fit(snapshot_every=40)

    # Pick 4 snapshots evenly (including initial and final)
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
    path = OUT_DIR / "figure_2_evolution.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


# ---------------------------------------------------------------------------
# Figure 3 — Protrusion bypass comparison
# ---------------------------------------------------------------------------

def figure_protrusion() -> None:
    print("[Fig 3] Protrusion bypass (high α vs low α) …")
    # Use same geometry + parameters as the passing unit tests
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

    test_pt = np.array([0.5, 0.5, 1.15])   # inside spike, above cube top

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
    path = OUT_DIR / "figure_3_protrusion.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


# ---------------------------------------------------------------------------
# Figure 4 — Convergence curve
# ---------------------------------------------------------------------------

def figure_convergence() -> None:
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
    path = OUT_DIR / "figure_4_convergence.png"
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    figure_sampling()
    figure_evolution()
    figure_protrusion()
    figure_convergence()
    print(f"\nAll figures saved to {OUT_DIR}/")
