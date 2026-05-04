"""Classify Blender volume-shaded mesh objects.

Used by terrain detection to decide whether ray hits on a given object should
be ignored. Atmospheric volumes (clouds high above the camera) corrupt the
walking-surface detection because downward rays hit them first; ground-level
volumes (vegetation, water, ground fog) are part of the walking environment
and their hits should be kept.

Designed to be loaded directly via importlib.util.spec_from_file_location
so it does not pull in the package __init__.py (which imports scipy and is
not available in Blender's bundled Python).
"""
from __future__ import annotations


class VolumeClassifier:
    """Classify volume-shaded mesh objects in a Blender scene.

    Labels:
      SOLID         — no volume shader (regular mesh, ray hits kept)
      GROUND_VOLUME — volume shader, bbox at or near camera level
                      (vegetation, water, ground fog → ray hits kept)
      ATMOSPHERIC   — volume shader, bbox entirely above camera by margin
                      (clouds, sky, upper fog → ray hits SKIPPED)

    Add new corner-case rules in `_classify` as we encounter scenes that
    break the current heuristic.
    """

    SOLID = "solid"
    GROUND_VOLUME = "ground_volume"
    ATMOSPHERIC = "atmospheric"

    def __init__(self, camera_z: float, atmospheric_offset: float = 10.0):
        """
        Args:
            camera_z: absolute Z of the original scene camera (anchor point)
            atmospheric_offset: a volume object whose bbox bottom sits more
                than this many metres above camera_z is considered atmospheric.
        """
        self.camera_z = float(camera_z)
        self.atmospheric_offset = float(atmospheric_offset)
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def classify(self, obj) -> str:
        """Return one of SOLID / GROUND_VOLUME / ATMOSPHERIC for `obj`."""
        if obj.name in self._cache:
            return self._cache[obj.name]
        label = self._classify(obj)
        self._cache[obj.name] = label
        return label

    def should_skip(self, obj) -> bool:
        """True if ray hits on `obj` should be ignored by terrain detection."""
        return self.classify(obj) == self.ATMOSPHERIC

    def report(self, scene) -> dict:
        """Classify every mesh in `scene`; print summary; return label counts."""
        from collections import Counter
        counts: Counter = Counter()
        atmospheric_names: list[str] = []
        for obj in scene.objects:
            label = self.classify(obj)
            counts[label] += 1
            if label == self.ATMOSPHERIC:
                atmospheric_names.append(obj.name)
        summary = dict(counts)
        print(f"[VolumeClassifier] camera_z={self.camera_z:.2f} m, "
              f"atmospheric_offset={self.atmospheric_offset} m → {summary}")
        if atmospheric_names:
            preview = atmospheric_names[:5]
            extra = "" if len(atmospheric_names) <= 5 else f" (+{len(atmospheric_names)-5} more)"
            print(f"[VolumeClassifier] Atmospheric (ray hits will be skipped): "
                  f"{preview}{extra}")
        return summary

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _classify(self, obj) -> str:
        if obj.type != "MESH":
            return self.SOLID
        if self._volume_shader_kind(obj) is None:
            return self.SOLID
        z_min, _z_max = self._bbox_z_range(obj)
        if z_min > self.camera_z + self.atmospheric_offset:
            return self.ATMOSPHERIC
        return self.GROUND_VOLUME

    def _volume_shader_kind(self, obj) -> "str | None":
        """Return 'scatter' / 'principled' / 'absorption' / 'other' / None."""
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            out = next((n for n in mat.node_tree.nodes
                        if n.bl_idname == "ShaderNodeOutputMaterial"), None)
            if out is None:
                continue
            vol_input = out.inputs.get("Volume")
            if vol_input is None or not vol_input.is_linked:
                continue
            linked_node = vol_input.links[0].from_node.bl_idname
            if "Scatter" in linked_node:
                return "scatter"
            if "Principled" in linked_node:
                return "principled"
            if "Absorption" in linked_node:
                return "absorption"
            return "other"
        return None

    def _bbox_z_range(self, obj) -> tuple:
        from mathutils import Vector
        zs = [(obj.matrix_world @ Vector(c)).z for c in obj.bound_box]
        return min(zs), max(zs)
