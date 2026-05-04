"""Classify Blender scene objects for terrain detection.

For every object the downward ray-cast can hit, decide whether its hit
should contribute to the walking-surface (KEEP) or be ignored (SKIP).
Atmospheric clouds, sky domes, OpenVDB fog, hidden helpers etc. would all
otherwise corrupt `max(valid hits)` and place the camera somewhere it
shouldn't be.

Designed to be loaded directly via importlib.util.spec_from_file_location
so it does not pull in the package __init__.py (which imports scipy and is
not available in Blender's bundled Python).

────────────────────────────────────────────────────────────────────────
                 LABELS — implemented vs reserved
────────────────────────────────────────────────────────────────────────
Implemented (classification logic in `_classify`):
  SOLID                — regular geometry, ray hit kept
  ATMOSPHERIC_VOLUME   — VolumeScatter mesh whose bbox bottom is more than
                         `atmospheric_offset` metres above the camera
                         (e.g. KoleClouds at +120 m vs camera at +2.7 m)
  GROUND_VOLUME        — volume-shaded mesh at or near camera level
                         (vegetation, water, ground fog) — ray hit kept
  NON_GEOMETRY         — light, camera, empty, etc. (ray_cast cannot hit)

Reserved / TODO (constants exist; logic to be added per scene that breaks):
  OPENVDB_VOLUME       — `obj.type == "VOLUME"` (OpenVDB), almost always atmospheric
  HIDDEN               — `obj.hide_render` or `obj.hide_viewport`
  SKY_DOME             — large mesh enclosing the entire scene with emission
                         shader (acts as world background)
  ENVIRONMENT_DOME     — non-emissive scene-enclosing mesh (env map carrier)
  PARTICLE_INSTANCE    — particle system / geometry-nodes instance source
                         (often picked up by ray_cast as a giant "ghost" mesh)

Add one branch in `_classify` per category as scenes surface the issue.
"""
from __future__ import annotations


class SceneObjectClassifier:
    """Classify scene objects so terrain detection knows which ray hits to skip."""

    # ----- implemented labels -----
    SOLID = "solid"
    ATMOSPHERIC_VOLUME = "atmospheric_volume"
    GROUND_VOLUME = "ground_volume"
    NON_GEOMETRY = "non_geometry"

    # ----- reserved labels (logic TODO — see module docstring) -----
    OPENVDB_VOLUME = "openvdb_volume"
    HIDDEN = "hidden"
    SKY_DOME = "sky_dome"
    ENVIRONMENT_DOME = "environment_dome"
    PARTICLE_INSTANCE = "particle_instance"

    # Labels whose ray hits should be ignored by terrain detection.
    SKIP_LABELS = frozenset({
        ATMOSPHERIC_VOLUME,
        OPENVDB_VOLUME,
        HIDDEN,
        SKY_DOME,
    })

    def __init__(self, camera_z: float, atmospheric_offset: float = 10.0):
        """
        Args:
            camera_z: absolute Z of the original scene camera (anchor point)
            atmospheric_offset: a volume-shaded mesh whose bbox bottom is more
                than this many metres above camera_z is classified ATMOSPHERIC.
        """
        self.camera_z = float(camera_z)
        self.atmospheric_offset = float(atmospheric_offset)
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def classify(self, obj) -> str:
        """Return one of the label constants for `obj` (cached by obj.name)."""
        if obj.name in self._cache:
            return self._cache[obj.name]
        label = self._classify(obj)
        self._cache[obj.name] = label
        return label

    def should_skip(self, obj) -> bool:
        """True if ray hits on `obj` should be ignored by terrain detection."""
        return self.classify(obj) in self.SKIP_LABELS

    def report(self, scene) -> dict:
        """Classify every object in `scene`; print summary; return label counts."""
        from collections import Counter
        counts: Counter = Counter()
        skip_names: list[str] = []
        for obj in scene.objects:
            label = self.classify(obj)
            counts[label] += 1
            if label in self.SKIP_LABELS:
                skip_names.append(f"{obj.name} ({label})")
        summary = dict(counts)
        print(f"[SceneClassifier] camera_z={self.camera_z:.2f} m, "
              f"atmospheric_offset={self.atmospheric_offset} m → {summary}")
        if skip_names:
            preview = skip_names[:6]
            extra = "" if len(skip_names) <= 6 else f" (+{len(skip_names)-6} more)"
            print(f"[SceneClassifier] Ray hits will be skipped for: "
                  f"{preview}{extra}")
        return summary

    # ------------------------------------------------------------------
    # Internals — extend this method as new corner cases come up.
    # ------------------------------------------------------------------
    def _classify(self, obj) -> str:
        # Non-geometry types can't be ray-hit at all
        if obj.type in {"CAMERA", "LIGHT", "EMPTY", "ARMATURE",
                        "LATTICE", "GPENCIL", "SPEAKER"}:
            return self.NON_GEOMETRY

        # TODO: OPENVDB_VOLUME — obj.type == "VOLUME". Always treat as skip
        #       for terrain detection. Add when first scene needs it.
        # TODO: HIDDEN — obj.hide_render or obj.hide_viewport. Need to verify
        #       whether scene.ray_cast actually hits hidden objects in 4.5.
        # TODO: SKY_DOME — single mesh whose bbox covers ≥ 90 % of scene
        #       bounds AND has emission output. Trips up max(valid).
        # TODO: ENVIRONMENT_DOME — non-emissive enclosing mesh, similar.
        # TODO: PARTICLE_INSTANCE — investigate when first encountered.

        if obj.type != "MESH":
            # CURVE / META / etc. — for now treat as solid
            return self.SOLID

        # Volume-shaded mesh: split into atmospheric vs ground
        if self._volume_shader_kind(obj) is not None:
            z_min, _z_max = self._bbox_z_range(obj)
            if z_min > self.camera_z + self.atmospheric_offset:
                return self.ATMOSPHERIC_VOLUME
            return self.GROUND_VOLUME

        return self.SOLID

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
