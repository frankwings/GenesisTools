"""Camera-anchored 1-D slice index helpers for terrain visualisations.

────────────────────────────────────────────────────────────────────────
CONVENTION — camera-anchored 1-D slices
────────────────────────────────────────────────────────────────────────
Every 1-D slice / cross-section figure in the GenesisTools terrain stack
is anchored at the original scene camera's XY position (read from
`terrain_snake.npz` → `camera_xyz`).

  - For an XZ slice we pick the row whose `iy` is closest to `camera_xyz[1]`.
  - For a YZ slice we pick the column whose `ix` is closest to `camera_xyz[0]`.

Why: the scene camera marks the canonical "interesting" line — it is
where the walkthrough roughly traverses, so a slice through it is the
most meaningful cross-section. Synthetic flat / mid-bbox / arbitrary-Y
slices are not allowed; only fall back to the scene XY centre when the
npz has no camera anchor.

Use `camera_anchored_iy()` / `camera_anchored_ix()` below — do not
re-derive the slice index inline.
"""
from __future__ import annotations

import numpy as np


def camera_anchored_iy(camera_xyz, min_y: float, res: float, ny: int) -> int:
    """Row index of the XZ slice through the original camera's Y.

    Args:
        camera_xyz: 3-vector (X, Y, Z) of the camera in world coordinates,
                    or `None` to fall back to the centre row.
        min_y, res, ny: bbox origin, cell size, and grid size along Y.

    Returns:
        `iy` clipped to `[0, ny - 1]`. The returned cell's centre Y is
        `min_y + (iy + 0.5) * res`.
    """
    if camera_xyz is None:
        return ny // 2
    return int(np.clip(round((float(camera_xyz[1]) - min_y) / res - 0.5),
                       0, ny - 1))


def camera_anchored_ix(camera_xyz, min_x: float, res: float, nx: int) -> int:
    """Column index of the YZ slice through the original camera's X.

    See `camera_anchored_iy` for argument and return semantics.
    """
    if camera_xyz is None:
        return nx // 2
    return int(np.clip(round((float(camera_xyz[0]) - min_x) / res - 0.5),
                       0, nx - 1))
