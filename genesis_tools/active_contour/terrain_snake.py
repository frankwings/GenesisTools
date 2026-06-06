"""Cloth-simulation and expand-diffusion snakes for outdoor terrain surface detection.

TerrainSnake (mode="contract")
    Classic cloth-simulation: starts at z_max, falls under gravity, hard floor
    constraints stop descent.  Analogous to CSF for lidar ground extraction.

ExpandSnake (mode="expand")  [terrain mode only]
    Inverse approach: seeds from known ray-cast floor hits, diffuses outward via
    iterative Laplacian propagation.  Unknown cells are initialised to NaN and
    pulled toward the weighted mean of their known neighbours each step, clamped
    to [floor-tolerance, floor+tolerance] when a floor hit exists.  Converges
    when all cells are filled and displacements fall below threshold.

    Advantages over contract:
    - No dependence on absolute scene Z or camera position.
    - Correctly handles multi-level terrain (stairs, cliffs) — each connected
      region grows from its own seeds rather than draping from a single cloth.
    - Vegetation gaps bridged by smooth Laplacian interpolation from real hits.
"""
from __future__ import annotations
import numpy as np


class TerrainSnake:
    """Cloth-simulation snake for outdoor terrain surface detection (contract mode).

    Starts as a flat grid at z_max, falls under gravity (-Z), Laplacian
    smoothness bridges vegetation gaps, per-column hard floors stop descent.
    XY coordinates are fixed to grid cell centres; only Z is updated.
    """

    def __init__(
        self,
        terrain_z_floor: np.ndarray,          # (nx, ny) float64, NaN = no valid hit
        bounds: tuple,                         # (min_x, min_y, max_x, max_y, min_z, max_z)
        res: float,
        alpha: float = 0.5,                   # Laplacian smoothness weight
        gravity: float = 0.1,                 # downward force per step
        dt: float = 1.0,                      # integration step size
        max_iterations: int = 200,
        convergence_threshold: float = 1e-3,
        plateau_window: int = 20,
        plateau_rtol: float = 0.02,
        cloth_init_z: "float | None" = None,  # uniform absolute Z to start cloth at
        start_height: float = 1.7,            # per-column offset above floor when cloth_init_z unset
    ) -> None:
        self.terrain_z_floor = np.asarray(terrain_z_floor, dtype=np.float64)
        self.bounds = bounds
        self.res = float(res)
        self.alpha = alpha
        self.gravity = gravity
        self.dt = dt
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold
        self.plateau_window = plateau_window
        self.plateau_rtol = plateau_rtol
        self.start_height = float(start_height)

        self.nx, self.ny = self.terrain_z_floor.shape
        min_x, min_y, max_x, max_y, min_z, max_z = bounds

        self.valid_mask = ~np.isnan(self.terrain_z_floor)  # (nx, ny) bool

        xs = min_x + (np.arange(self.nx) + 0.5) * self.res
        ys = min_y + (np.arange(self.ny) + 0.5) * self.res
        XX, YY = np.meshgrid(xs, ys, indexing="ij")

        if cloth_init_z is not None:
            z_init = np.full((self.nx, self.ny), float(cloth_init_z), dtype=np.float64)
        else:
            z_init = np.where(
                self.valid_mask,
                self.terrain_z_floor + self.start_height,
                float(max_z),
            )

        self.vertices = np.column_stack([XX.ravel(), YY.ravel(), z_init.ravel()])
        self.min_z = float(min_z)
        self.max_z = float(max_z)
        self.max_displacements: list[float] = []
        self.iterations_run: int = 0

    def _laplacian_force_z(self) -> np.ndarray:
        """Pull each Z toward the mean of its 4 grid neighbours."""
        Z = self.vertices[:, 2].reshape(self.nx, self.ny)
        lap = np.zeros_like(Z)
        n = np.zeros_like(Z)
        lap[:, :-1] += Z[:, 1:];  n[:, :-1] += 1
        lap[:, 1:]  += Z[:, :-1]; n[:, 1:]  += 1
        lap[:-1, :] += Z[1:, :];  n[:-1, :] += 1
        lap[1:, :]  += Z[:-1, :]; n[1:, :]  += 1
        with np.errstate(invalid="ignore"):
            mean_nbrs = np.where(n > 0, lap / n, Z)
        return (mean_nbrs - Z).ravel()

    def step(self) -> float:
        """One iteration. Returns max absolute Z displacement over valid columns."""
        lap_z = self._laplacian_force_z()
        F_z = self.alpha * lap_z - self.gravity
        delta_z = self.dt * F_z

        z_before = self.vertices[:, 2].copy()
        self.vertices[:, 2] += delta_z

        floor = self.terrain_z_floor.ravel()
        valid_flat = self.valid_mask.ravel()
        self.vertices[valid_flat, 2] = np.maximum(
            self.vertices[valid_flat, 2], floor[valid_flat])
        self.vertices[:, 2] = np.maximum(self.vertices[:, 2], self.min_z)

        self.iterations_run += 1
        diff = np.abs(self.vertices[valid_flat, 2] - z_before[valid_flat])
        max_d = float(np.max(diff)) if diff.size > 0 else 0.0
        self.max_displacements.append(max_d)
        return max_d

    def fit(self) -> "TerrainSnake":
        """Run until convergence or plateau."""
        for _ in range(self.max_iterations):
            max_d = self.step()
            if max_d < self.convergence_threshold:
                break
            pw = self.plateau_window
            if len(self.max_displacements) >= pw * 2:
                w = self.max_displacements
                older = sum(w[-pw * 2:-pw]) / pw
                recent = sum(w[-pw:]) / pw
                if (recent < self.convergence_threshold * 10 and
                        abs(older - recent) / (older + 1e-12) < self.plateau_rtol):
                    break
        return self

    def to_heightmap(self) -> np.ndarray:
        """Return (nx, ny) float64 array of final cloth Z per cell."""
        return self.vertices[:, 2].reshape(self.nx, self.ny).copy()


# ---------------------------------------------------------------------------
# Expand snake (terrain mode only)
# ---------------------------------------------------------------------------

class ExpandSnake:
    """Outward-diffusion snake for terrain surface detection (terrain mode only).

    Instead of draping cloth from above, this snake seeds from known ray-cast
    floor hits and diffuses outward iteratively via Laplacian propagation.

    Algorithm
    ---------
    1. Seed cells: cells with valid ray-cast hits → Z fixed at floor value.
    2. Unknown cells: initialised to NaN.
    3. Each step: for every unknown cell, compute the mean Z of all known
       (non-NaN) 4-neighbours.  If at least one known neighbour exists, the cell
       is "activated" and set to that mean.  Already-known cells are clamped to
       [floor - floor_tolerance, floor + floor_tolerance] when a hit exists, so
       Laplacian smoothing cannot pull them far off the real surface.
    4. Repeat until no unknown cells remain, then run ``smoothing_iterations``
       extra Laplacian passes over the full grid to reduce staircase artefacts
       from the wave-front expansion order.

    Parameters
    ----------
    terrain_z_floor : (nx, ny) float64
        Per-column terrain floor Z from ray-cast.  NaN = no hit (vegetation gap
        or out-of-bounds).
    bounds : (min_x, min_y, max_x, max_y, min_z, max_z)
    res : float
        Grid cell size in Blender units.
    alpha : float
        Laplacian weight for the post-expansion smoothing passes (0–1).
    floor_tolerance : float
        Maximum allowed deviation from a known floor hit (BU).  Prevents
        Laplacian from pulling seed cells away from their ray-cast Z.
    max_iterations : int
        Hard cap on expansion steps (each step can activate multiple cells).
    smoothing_iterations : int
        Extra Laplacian smoothing passes after full coverage is reached.
    convergence_threshold : float
        Stop smoothing when max displacement drops below this value.
    """

    def __init__(
        self,
        terrain_z_floor: np.ndarray,
        bounds: tuple,
        res: float,
        alpha: float = 0.3,
        floor_tolerance: float = 2.0,
        max_iterations: int = 500,
        smoothing_iterations: int = 50,
        convergence_threshold: float = 1e-3,
        seed_filter_percentile: float = 5.0,  # remove seeds below this Z percentile (env-sphere hits)
    ) -> None:
        self.terrain_z_floor = np.asarray(terrain_z_floor, dtype=np.float64)
        self.bounds = bounds
        self.res = float(res)
        self.alpha = alpha
        self.floor_tolerance = float(floor_tolerance)
        self.max_iterations = max_iterations
        self.smoothing_iterations = smoothing_iterations
        self.convergence_threshold = convergence_threshold

        # Filter outlier seeds (env-sphere / scene-floor hits far below real terrain)
        if seed_filter_percentile > 0:
            _valid = ~np.isnan(self.terrain_z_floor)
            if _valid.any():
                _z_lo = float(np.nanpercentile(self.terrain_z_floor[_valid], seed_filter_percentile))
                self.terrain_z_floor = np.where(
                    self.terrain_z_floor <= _z_lo, np.nan, self.terrain_z_floor)

        self.nx, self.ny = self.terrain_z_floor.shape
        self.valid_mask = ~np.isnan(self.terrain_z_floor)

        # Z grid: seeds at floor value, unknown cells → NaN
        self._Z = np.where(self.valid_mask, self.terrain_z_floor, np.nan)

        self.max_displacements: list[float] = []
        self.iterations_run: int = 0
        self._expansion_done: bool = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _neighbour_mean(self, Z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (mean_z, n_known) from the 4 cardinal neighbours.

        NaN cells are ignored in the mean.  n_known counts how many neighbours
        had a valid (non-NaN) value.
        """
        acc = np.zeros((self.nx, self.ny), dtype=np.float64)
        cnt = np.zeros((self.nx, self.ny), dtype=np.int32)

        for src, dst in [
            (Z[:, 1:],  (slice(None), slice(None, -1))),  # right → left
            (Z[:, :-1], (slice(None), slice(1, None))),   # left  → right
            (Z[1:, :],  (slice(None, -1), slice(None))),  # below → above
            (Z[:-1, :], (slice(1, None),  slice(None))),  # above → below
        ]:
            valid = ~np.isnan(src)
            acc[dst][valid] += src[valid]
            cnt[dst][valid] += 1

        with np.errstate(invalid="ignore"):
            mean_z = np.where(cnt > 0, acc / cnt, np.nan)
        return mean_z, cnt

    # ------------------------------------------------------------------
    # Expansion phase
    # ------------------------------------------------------------------

    def _expand_step(self) -> int:
        """Activate all NaN cells that have at least one known neighbour.

        Returns the number of newly activated cells.
        """
        unknown = np.isnan(self._Z)
        if not unknown.any():
            return 0

        mean_z, n_known = self._neighbour_mean(self._Z)
        # Activate cells that are unknown but have known neighbours
        activate = unknown & (n_known > 0)
        self._Z[activate] = mean_z[activate]
        return int(activate.sum())

    # ------------------------------------------------------------------
    # Smoothing phase
    # ------------------------------------------------------------------

    def _smooth_step(self) -> float:
        """One Laplacian smoothing pass over the full grid.

        Seed cells (valid ray-cast hits) are clamped to ±floor_tolerance.
        Returns max absolute displacement.
        """
        mean_z, _ = self._neighbour_mean(self._Z)
        # Only update where we have a valid mean
        updatable = ~np.isnan(mean_z)
        delta = np.zeros((self.nx, self.ny), dtype=np.float64)
        delta[updatable] = self.alpha * (mean_z[updatable] - self._Z[updatable])

        z_before = self._Z.copy()
        self._Z += delta

        # Clamp seed cells to floor ± tolerance
        tol = self.floor_tolerance
        f = self.terrain_z_floor
        self._Z[self.valid_mask] = np.clip(
            self._Z[self.valid_mask],
            f[self.valid_mask] - tol,
            f[self.valid_mask] + tol,
        )

        diff = np.abs(self._Z - z_before)
        return float(np.nanmax(diff)) if not np.all(np.isnan(diff)) else 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self) -> "ExpandSnake":
        """Run expansion then smoothing. Returns self."""
        # Phase 1: wave-front expansion until all cells are filled
        for _ in range(self.max_iterations):
            activated = self._expand_step()
            self.iterations_run += 1
            if activated == 0:
                break

        self._expansion_done = True
        n_unknown = int(np.isnan(self._Z).sum())
        if n_unknown > 0:
            # Isolated islands with no path to any seed — fill with global median
            fallback = float(np.nanmedian(self._Z))
            self._Z = np.where(np.isnan(self._Z), fallback, self._Z)

        # Phase 2: Laplacian smoothing to remove expansion wave-front artefacts
        for _ in range(self.smoothing_iterations):
            max_d = self._smooth_step()
            self.max_displacements.append(max_d)
            self.iterations_run += 1
            if max_d < self.convergence_threshold:
                break

        return self

    def to_heightmap(self) -> np.ndarray:
        """Return (nx, ny) float64 array of final terrain Z per cell."""
        return self._Z.copy()
