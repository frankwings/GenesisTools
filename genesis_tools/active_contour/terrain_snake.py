from __future__ import annotations
import numpy as np


class TerrainSnake:
    """Cloth-simulation snake for outdoor terrain surface detection.

    Starts as a flat grid at z_max, falls under gravity (-Z), Laplacian
    smoothness bridges vegetation gaps, per-column hard floors stop descent.
    XY coordinates are fixed to grid cell centres; only Z is updated.
    """

    def __init__(
        self,
        terrain_z_floor: np.ndarray,   # (nx, ny) float64, NaN = no valid hit
        bounds: tuple,                  # (min_x, min_y, max_x, max_y, min_z, max_z)
        res: float,
        alpha: float = 0.5,            # Laplacian smoothness weight
        gravity: float = 0.1,          # downward force per step
        dt: float = 1.0,               # integration step size
        max_iterations: int = 200,
        convergence_threshold: float = 1e-3,
        plateau_window: int = 20,
        plateau_rtol: float = 0.02,
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

        self.nx, self.ny = self.terrain_z_floor.shape
        min_x, min_y, max_x, max_y, min_z, max_z = bounds

        xs = min_x + (np.arange(self.nx) + 0.5) * self.res
        ys = min_y + (np.arange(self.ny) + 0.5) * self.res
        XX, YY = np.meshgrid(xs, ys, indexing="ij")
        z_init = np.full((self.nx, self.ny), float(max_z), dtype=np.float64)

        # vertices: (nx*ny, 3) — XY fixed, only Z updated
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
        """One iteration. Returns max absolute Z displacement."""
        lap_z = self._laplacian_force_z()
        F_z = self.alpha * lap_z - self.gravity
        delta_z = self.dt * F_z
        self.vertices[:, 2] += delta_z

        # Hard floor: cloth cannot pass through terrain
        floor = self.terrain_z_floor.ravel()
        valid = ~np.isnan(floor)
        self.vertices[valid, 2] = np.maximum(self.vertices[valid, 2], floor[valid])
        # Safety lower bound for NaN (sky-only) columns
        self.vertices[:, 2] = np.maximum(self.vertices[:, 2], self.min_z)

        self.iterations_run += 1
        max_d = float(np.max(np.abs(delta_z)))
        self.max_displacements.append(max_d)
        return max_d

    def fit(self) -> "TerrainSnake":
        """Run until convergence or plateau. Returns self."""
        for _ in range(self.max_iterations):
            max_d = self.step()
            if max_d < self.convergence_threshold:
                break
            pw = self.plateau_window
            if len(self.max_displacements) >= pw * 2:
                w = self.max_displacements
                older = sum(w[-pw * 2:-pw]) / pw
                recent = sum(w[-pw:]) / pw
                # Only stop on plateau when displacement is genuinely small
                # (free-fall at constant velocity is not a plateau)
                if (recent < self.convergence_threshold * 100 and
                        abs(older - recent) / (older + 1e-12) < self.plateau_rtol):
                    break
        return self

    def to_heightmap(self) -> np.ndarray:
        """Return (nx, ny) float64 array of final cloth Z per cell."""
        return self.vertices[:, 2].reshape(self.nx, self.ny).copy()
