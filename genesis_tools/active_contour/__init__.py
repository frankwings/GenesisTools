"""genesis_tools.active_contour — 3D Active Contour (Snake) module.

Exports
-------
sample_mesh_surface : area-weighted point sampling from triangle mesh faces.
subdivide_mesh      : midpoint subdivision of a triangle mesh.
Snake3D             : 3D snake that contracts to the minimal smooth surface.
"""

from genesis_tools.active_contour.snake_3d import (
    Snake3D,
    sample_mesh_surface,
    subdivide_mesh,
)

__all__ = ["Snake3D", "sample_mesh_surface", "subdivide_mesh"]
