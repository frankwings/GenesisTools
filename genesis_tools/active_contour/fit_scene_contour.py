"""Fit a 3D Active Contour (Snake) to a Blender scene and visualise the result.

Usage
-----
    cd GenesisTools
    python genesis_tools/active_contour/fit_scene_contour.py \\
        --blend /path/to/scene.blend \\
        --output-dir results/active_contour/<scene_name> \\
        [--alpha 0.6] [--beta 0.3] [--sampling-res 0.5] \\
        [--max-iter 300] [--blender blender]

Pipeline
--------
1. Run Blender headlessly to extract world-space mesh geometry → meshes.npz
2. Sample mesh surfaces (area-weighted face sampling)
3. Fit Snake3D: constrict from convex hull toward sampled points
4. Generate four output figures:
   - figure_1_pointcloud.png   — raw sampled point cloud (top / side / front)
   - figure_2_contour.png      — initial hull vs final snake (top / side)
   - figure_3_slices.png       — XY / XZ cross-section inside/outside test
   - figure_4_convergence.png  — max-displacement per iteration

Outputs a result JSON summary and prints the output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from genesis_tools.active_contour.snake_3d import Snake3D, sample_mesh_surface

EXTRACT_SCRIPT  = Path(__file__).parent / "extract_scene_meshes.py"
OVERLAY_SCRIPT  = Path(__file__).parent / "overlay_snake_in_blend.py"


# ---------------------------------------------------------------------------
# Blender extraction
# ---------------------------------------------------------------------------

def extract_meshes_from_blend(
    blend_path: Path,
    npz_path: Path,
    max_tris: int = 500_000,
    blender_command: str = "blender",
) -> dict:
    """Call Blender headlessly to dump world-space mesh geometry to a .npz."""
    cmd = [
        blender_command,
        "--background", str(blend_path),
        "--python", str(EXTRACT_SCRIPT),
        "--",
        "--output", str(npz_path),
        "--max-tris", str(max_tris),
    ]
    env = os.environ.copy()
    _extra_lib = "/tmp/deb_extract/usr/lib/x86_64-linux-gnu"
    if os.path.isdir(_extra_lib):
        env["LD_LIBRARY_PATH"] = _extra_lib + ":" + env.get("LD_LIBRARY_PATH", "")

    print(f"[contour] Running Blender extraction …")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = time.time() - t0
    stdout = proc.stdout + proc.stderr

    prefix = "MESH_EXTRACT_RESULT:"
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            result = json.loads(line[len(prefix):])
            result["extraction_seconds"] = round(elapsed, 1)
            print(f"  meshes={result['n_meshes']}  tris={result['total_tris']:,}  "
                  f"time={elapsed:.1f}s")
            return result

    raise RuntimeError(f"No MESH_EXTRACT_RESULT in Blender output:\n{stdout[-3000:]}")


def _run_blender_overlay(
    blend_path: Path,
    snake_npz: Path,
    output_blend: Path,
    render_dir: Path,
    engine: str = "WORKBENCH",
    blender_command: str = "blender",
) -> dict:
    """Call Blender to add the snake mesh as a transparent overlay and render views."""
    cmd = [
        blender_command,
        "--background", str(blend_path),
        "--python", str(OVERLAY_SCRIPT),
        "--",
        "--snake-npz", str(snake_npz),
        "--output-blend", str(output_blend),
        "--render-dir", str(render_dir),
        "--engine", engine,
    ]
    env = os.environ.copy()
    _extra_lib = "/tmp/deb_extract/usr/lib/x86_64-linux-gnu"
    if os.path.isdir(_extra_lib):
        env["LD_LIBRARY_PATH"] = _extra_lib + ":" + env.get("LD_LIBRARY_PATH", "")

    print(f"[contour] Rendering Blender overlay views …")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    stdout = proc.stdout + proc.stderr

    prefix = "OVERLAY_RESULT:"
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            result = json.loads(line[len(prefix):])
            print(f"  overlay done in {time.time()-t0:.1f}s — "
                  f"{len(result.get('renders', []))} renders")
            return result

    print(f"  [warn] No OVERLAY_RESULT in Blender output — skipping overlay")
    return {"renders": []}


# ---------------------------------------------------------------------------
# Mesh loading
# ---------------------------------------------------------------------------

def load_mesh_list(npz_path: Path) -> list:
    """Load (verts, faces) list from .npz produced by extract_scene_meshes."""
    data = np.load(str(npz_path))
    n = int(data["n_meshes"])
    return [(data[f"verts_{i}"].astype(np.float64),
             data[f"faces_{i}"].astype(np.int64)) for i in range(n)]


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _add_point_cloud_views(fig, axes, pts: np.ndarray, title_prefix: str) -> None:
    """3-panel orthographic scatter (XY top, XZ front, YZ side)."""
    views = [
        (axes[0], pts[:, 0], pts[:, 1], "X", "Y", "Top  (XY)"),
        (axes[1], pts[:, 0], pts[:, 2], "X", "Z", "Front (XZ)"),
        (axes[2], pts[:, 1], pts[:, 2], "Y", "Z", "Side  (YZ)"),
    ]
    for ax, xa, ya, xl, yl, subtitle in views:
        # Draw up to 50k pts to keep rendering fast
        idx = np.random.default_rng(0).choice(len(pts), min(len(pts), 50_000), replace=False)
        ax.scatter(xa[idx], ya[idx], s=1, alpha=0.3, c="royalblue", rasterized=True)
        ax.set_xlabel(xl); ax.set_ylabel(yl)
        ax.set_title(f"{title_prefix}\n{subtitle}", fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.2)


def figure_pointcloud(pts: np.ndarray, out_dir: Path, scene_name: str) -> Path:
    print("[Fig 1] Point cloud …")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(f"Sampled Surface Points — {scene_name}\n({len(pts):,} points)",
                 fontsize=12, fontweight="bold")
    _add_point_cloud_views(fig, axes, pts, f"{len(pts):,} pts")
    plt.tight_layout()
    path = out_dir / "figure_1_pointcloud.png"
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")
    return path


def _project_mesh_outline(ax, verts: np.ndarray, faces: np.ndarray,
                           dim_x: int, dim_y: int,
                           color: str, alpha: float, lw: float) -> None:
    """Draw face edge projections onto a 2D axis (only unique edges)."""
    seen = set()
    edges_x, edges_y = [], []
    for f in faces:
        for a, b in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])]:
            key = (min(int(a), int(b)), max(int(a), int(b)))
            if key in seen:
                continue
            seen.add(key)
            edges_x += [verts[a, dim_x], verts[b, dim_x], None]
            edges_y += [verts[a, dim_y], verts[b, dim_y], None]
    ax.plot(edges_x, edges_y, color=color, alpha=alpha, lw=lw)


def figure_contour(pts: np.ndarray, snake: Snake3D,
                   init_verts: np.ndarray, out_dir: Path, scene_name: str) -> Path:
    print("[Fig 2] Initial hull vs final contour …")
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(f"Active Contour — {scene_name}\nInitial hull (green) → Final snake (blue)",
                 fontsize=12, fontweight="bold")

    views = [
        (axes[0], 0, 1, "X", "Y", "Top  (XY)"),
        (axes[1], 0, 2, "X", "Z", "Front (XZ)"),
        (axes[2], 1, 2, "Y", "Z", "Side  (YZ)"),
    ]
    for ax, dx, dy, xl, yl, subtitle in views:
        idx = np.random.default_rng(0).choice(len(pts), min(len(pts), 30_000), replace=False)
        ax.scatter(pts[idx, dx], pts[idx, dy], s=1, alpha=0.15,
                   c="lightgray", rasterized=True, label="Point cloud")
        # Initial hull outline
        _project_mesh_outline(ax, init_verts, snake.faces,
                               dx, dy, color="limegreen", alpha=0.6, lw=0.6)
        # Final snake outline
        _project_mesh_outline(ax, snake.vertices, snake.faces,
                               dx, dy, color="dodgerblue", alpha=0.8, lw=0.8)
        ax.set_xlabel(xl); ax.set_ylabel(yl)
        ax.set_title(subtitle, fontsize=9)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.2)

    # Legend proxy
    from matplotlib.lines import Line2D
    legend_items = [
        Line2D([0], [0], color="limegreen", lw=1.5, label="Initial convex hull"),
        Line2D([0], [0], color="dodgerblue", lw=1.5, label="Final snake contour"),
        Line2D([0], [0], marker=".", color="lightgray", lw=0, ms=4, label="Sampled points"),
    ]
    axes[0].legend(handles=legend_items, fontsize=8, loc="upper left")

    plt.tight_layout()
    path = out_dir / "figure_2_contour.png"
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")
    return path


def figure_slices(pts: np.ndarray, snake: Snake3D,
                  out_dir: Path, scene_name: str,
                  n_slices: int = 5) -> Path:
    """Sample cross-sections: for each Z slice, test a grid of (x,y) points."""
    print("[Fig 3] Inside/outside slices …")

    lo, hi = pts.min(axis=0), pts.max(axis=0)
    z_vals = np.linspace(lo[2] + (hi[2] - lo[2]) * 0.1,
                         lo[2] + (hi[2] - lo[2]) * 0.9,
                         n_slices)

    grid_n = 40  # grid resolution per axis
    xs = np.linspace(lo[0], hi[0], grid_n)
    ys = np.linspace(lo[1], hi[1], grid_n)
    XX, YY = np.meshgrid(xs, ys)

    fig, axes = plt.subplots(1, n_slices, figsize=(4 * n_slices, 4))
    if n_slices == 1:
        axes = [axes]
    fig.suptitle(f"Snake Cross-Sections (Z slices) — {scene_name}",
                 fontsize=12, fontweight="bold")

    for ax, z in zip(axes, z_vals):
        test_pts = np.column_stack([XX.ravel(), YY.ravel(),
                                    np.full(XX.size, z)])
        inside = snake.contains_batch(test_pts).reshape(grid_n, grid_n)
        ax.contourf(XX, YY, inside.astype(float), levels=[0.5, 1.5],
                    colors=["#4FC3F7"], alpha=0.45)
        ax.contour(XX, YY, inside.astype(float), levels=[0.5],
                   colors=["dodgerblue"], linewidths=1.5)

        # Scatter pts near this z
        mask = np.abs(pts[:, 2] - z) < (hi[2] - lo[2]) / (2 * n_slices)
        if mask.sum() > 0:
            ax.scatter(pts[mask, 0], pts[mask, 1], s=3, c="gray", alpha=0.4,
                       rasterized=True)

        ax.set_title(f"Z = {z:.2f}", fontsize=9)
        ax.set_xlabel("X"); ax.set_ylabel("Y")
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.2)

    plt.tight_layout()
    path = out_dir / "figure_3_slices.png"
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")
    return path


def figure_convergence(snake: Snake3D, out_dir: Path, scene_name: str) -> Path:
    print("[Fig 4] Convergence curve …")
    fig, ax = plt.subplots(figsize=(8, 4))
    fig.suptitle(f"Snake Convergence — {scene_name}", fontsize=12, fontweight="bold")
    ax.semilogy(snake.max_displacements, color="dodgerblue", lw=1.5)
    ax.axhline(snake.convergence_threshold, ls="--", color="gray", lw=0.8,
               label=f"threshold = {snake.convergence_threshold:.0e}")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Max displacement (log scale)")
    ax.legend(fontsize=9)
    ax.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    path = out_dir / "figure_4_convergence.png"
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  saved → {path}")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fit_scene_active_contour(
    blend_path: Path,
    output_dir: Path,
    *,
    alpha: float = 0.6,
    beta: float = 0.3,
    dt: float = 0.05,
    sampling_resolution: float = 0.5,
    max_iter: int = 300,
    subdivision_levels: int = 0,
    max_tris: int = 500_000,
    blender_command: str = "blender",
    reuse_npz: bool = False,
) -> dict:
    blend_path = Path(blend_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_name = blend_path.stem

    # --- 1. Extract meshes from Blender ---
    npz_path = output_dir / "meshes.npz"
    if reuse_npz and npz_path.exists():
        print(f"[contour] Reusing existing {npz_path}")
        extract_meta = {"n_meshes": "?", "total_tris": "?"}
    else:
        extract_meta = extract_meshes_from_blend(
            blend_path, npz_path, max_tris=max_tris,
            blender_command=blender_command,
        )

    # --- 2. Load meshes ---
    mesh_list = load_mesh_list(npz_path)
    print(f"[contour] Loaded {len(mesh_list)} mesh objects")

    # --- 3. Sample surface points ---
    print(f"[contour] Sampling surface (resolution={sampling_resolution}) …")
    t0 = time.time()
    pts = sample_mesh_surface(mesh_list, sampling_resolution=sampling_resolution)
    print(f"  {len(pts):,} points sampled in {time.time()-t0:.1f}s")

    # --- 4. Fit Snake ---
    print(f"[contour] Fitting Snake3D (alpha={alpha} beta={beta} "
          f"max_iter={max_iter}) …")
    t0 = time.time()
    snake = Snake3D(pts, alpha=alpha, beta=beta, dt=dt,
                    max_iterations=max_iter,
                    subdivision_levels=subdivision_levels)
    init_verts = snake.vertices.copy()  # save hull before contraction
    snake.fit(snapshot_every=max(1, max_iter // 8))
    fit_time = time.time() - t0
    print(f"  converged in {snake.iterations_run} iterations ({fit_time:.1f}s)")

    # --- 5. Save snake mesh for Blender overlay ---
    snake_npz = output_dir / "snake_mesh.npz"
    np.savez_compressed(
        str(snake_npz),
        vertices=snake.vertices.astype(np.float32),
        faces=snake.faces.astype(np.int32),
    )
    print(f"[contour] Snake mesh saved → {snake_npz}")

    # --- 6. Figures ---
    p1 = figure_pointcloud(pts, output_dir, scene_name)
    p2 = figure_contour(pts, snake, init_verts, output_dir, scene_name)
    p3 = figure_slices(pts, snake, output_dir, scene_name)
    p4 = figure_convergence(snake, output_dir, scene_name)

    # --- 7. Blender overlay ---
    overlay_blend = output_dir / f"{scene_name}_with_contour.blend"
    render_dir = output_dir / "renders"
    overlay_result = _run_blender_overlay(
        blend_path, snake_npz, overlay_blend, render_dir,
        blender_command=blender_command,
    )

    # --- 8. Summary ---
    summary = {
        "scene": scene_name,
        "blend_path": str(blend_path),
        "n_mesh_objects": len(mesh_list),
        "total_tris": extract_meta.get("total_tris"),
        "sampled_points": len(pts),
        "snake_alpha": alpha,
        "snake_beta": beta,
        "snake_iterations": snake.iterations_run,
        "snake_vertices": len(snake.vertices),
        "snake_faces": len(snake.faces),
        "fit_seconds": round(fit_time, 1),
        "figures": [str(p1), str(p2), str(p3), str(p4)],
        "overlay_blend": str(overlay_blend),
        "renders": overlay_result.get("renders", []),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\n[contour] Done. Output → {output_dir}/")
    return summary


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--alpha", type=float, default=0.6)
    p.add_argument("--beta", type=float, default=0.3)
    p.add_argument("--dt", type=float, default=0.05)
    p.add_argument("--sampling-res", type=float, default=0.5)
    p.add_argument("--max-iter", type=int, default=300)
    p.add_argument("--subdivision-levels", type=int, default=0)
    p.add_argument("--max-tris", type=int, default=500_000)
    p.add_argument("--blender", default="blender")
    p.add_argument("--render-engine", default="WORKBENCH",
                   choices=["WORKBENCH", "EEVEE", "CYCLES"])
    p.add_argument("--reuse-npz", action="store_true",
                   help="Skip Blender extraction if meshes.npz already exists")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = fit_scene_active_contour(
        blend_path=Path(args.blend),
        output_dir=Path(args.output_dir),
        alpha=args.alpha,
        beta=args.beta,
        dt=args.dt,
        sampling_resolution=args.sampling_res,
        max_iter=args.max_iter,
        subdivision_levels=args.subdivision_levels,
        max_tris=args.max_tris,
        blender_command=args.blender,
        reuse_npz=args.reuse_npz,
    )
    print(json.dumps(result, indent=2))
