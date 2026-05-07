"""scene_preprocessor.py — detect and neutralise render-hostile scene objects.

Render-hostile = objects whose geometry Blender re-evaluates on every frame,
forcing a full BVH rebuild even when use_persistent_data=True.  Symptoms in
the render log: "Updating Geometry BVH <name> N/M | Building BVH" appearing
every frame, with each frame taking far longer than the actual render.

Known culprits
--------------
* Particle systems (Hair or Emitter type): Blender marks the host object dirty
  on every frame advance regardless of whether the simulation is static.
* Geometry Nodes with frame-dependent input nodes (Scene Time, Input Frame):
  the evaluated mesh changes every frame, so BVH cannot be cached.
* Curve / surface objects with frame-dependent modifiers.

Fix strategy
------------
Convert or apply modifiers so the object becomes a plain static MESH with no
remaining modifier stack.  Blender then treats it as fully clean between
frames, BVH is built once at frame 1, and persistent_data caches it for the
rest of the animation.
"""
from __future__ import annotations

import bpy
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class PreprocessReport:
    particles_converted: list[str] = field(default_factory=list)
    geonodes_applied:    list[str] = field(default_factory=list)
    skipped_linked:      list[str] = field(default_factory=list)
    errors:              list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.particles_converted:
            parts.append(f"particles→mesh: {len(self.particles_converted)} obj")
        if self.geonodes_applied:
            parts.append(f"geonode modifiers applied: {len(self.geonodes_applied)}")
        if self.skipped_linked:
            parts.append(f"skipped (linked/library): {len(self.skipped_linked)}")
        if self.errors:
            parts.append(f"errors: {len(self.errors)}")
        return ", ".join(parts) if parts else "nothing changed"

    @property
    def any_errors(self) -> bool:
        return bool(self.errors)

    @property
    def total_fixed(self) -> int:
        return len(self.particles_converted) + len(self.geonodes_applied)


# ---------------------------------------------------------------------------
# Frame-dependency detection helpers
# ---------------------------------------------------------------------------

_FRAME_DEP_NODE_TYPES = {
    "GeometryNodeInputSceneTime",   # Scene Time node
    "GeometryNodeInputFrame",       # Input Frame node
    "GeometryNodeSimulationInput",  # Simulation Zone input
    "GeometryNodeSimulationOutput", # Simulation Zone output
}


def _geonode_is_frame_dependent(node_group: bpy.types.NodeGroup) -> bool:
    """Return True if a node tree contains any frame-dependent node."""
    if node_group is None:
        return False
    for node in node_group.nodes:
        if node.bl_idname in _FRAME_DEP_NODE_TYPES:
            return True
        # Recurse into nested groups
        if node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None:
            if _geonode_is_frame_dependent(node.node_tree):
                return True
    return False


def _obj_has_frame_dependent_geonode(obj: bpy.types.Object) -> bool:
    for mod in obj.modifiers:
        if mod.type == "NODES" and _geonode_is_frame_dependent(mod.node_group):
            return True
    return False


def _obj_has_particles(obj: bpy.types.Object) -> bool:
    return any(m.type == "PARTICLE_SYSTEM" for m in obj.modifiers)


# Scatter-vegetation particle systems distribute mesh objects/collections as
# instances.  bpy.ops.object.convert(target="MESH") in background mode creates
# only the bare emitter surface — all scattered instances are silently dropped.
# Skip these; only convert Hair-strand and Emitter types which bake cleanly.
_SCATTER_RENDER_TYPES = {"OBJECT", "COLLECTION"}


def _obj_has_only_scatter_particles(obj: bpy.types.Object) -> bool:
    """Return True if every particle system on obj is a scatter type (OBJECT/COLLECTION).

    If *any* system is not scatter (e.g. HALO, PATH, or EMITTER), the object
    is still eligible for full conversion.
    """
    psys_mods = [m for m in obj.modifiers if m.type == "PARTICLE_SYSTEM"]
    if not psys_mods:
        return False
    return all(
        m.particle_system.settings.render_type in _SCATTER_RENDER_TYPES
        for m in psys_mods
    )


def _can_modify(obj: bpy.types.Object) -> bool:
    """False for library-linked objects that cannot be edited in-place."""
    return obj.library is None and not obj.override_library


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ScenePreprocessor:
    """Detect and fix render-hostile objects in a Blender scene.

    Usage (inside a bpy context, e.g. _render_frames.py):

        preprocessor = ScenePreprocessor()
        report = preprocessor.run()
        print(report.summary())

    Or run individual steps:

        preprocessor.scan()                       # inspect only
        preprocessor.convert_particles_to_mesh()  # particles only
        preprocessor.apply_frame_dep_geonodes()   # GN only
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._report = PreprocessReport()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[ScenePreprocessor] {msg}")

    # ------------------------------------------------------------------
    # Scan (non-destructive)
    # ------------------------------------------------------------------

    def scan(self) -> dict[str, list[str]]:
        """Return a mapping of problem type → object names, without modifying anything.

        Keys:
            "particle_systems"        — objects with Particle System modifiers
            "frame_dep_geonodes"      — objects with frame-dependent GN modifiers
            "linked_unmodifiable"     — library-linked objects with the above issues
        """
        issues: dict[str, list[str]] = {
            "particle_systems":    [],
            "scatter_vegetation":  [],
            "frame_dep_geonodes":  [],
            "linked_unmodifiable": [],
        }
        for obj in bpy.context.scene.objects:
            if obj.type not in ("MESH", "CURVE", "SURFACE"):
                continue
            has_ptcl = _obj_has_particles(obj)
            has_gn   = _obj_has_frame_dependent_geonode(obj)
            if not (has_ptcl or has_gn):
                continue
            if not _can_modify(obj):
                issues["linked_unmodifiable"].append(obj.name)
                continue
            if has_ptcl:
                if _obj_has_only_scatter_particles(obj):
                    issues["scatter_vegetation"].append(obj.name)
                else:
                    issues["particle_systems"].append(obj.name)
            if has_gn:
                issues["frame_dep_geonodes"].append(obj.name)
        return issues

    # ------------------------------------------------------------------
    # Fix: particles
    # ------------------------------------------------------------------

    def convert_particles_to_mesh(self) -> int:
        """Apply all modifiers (incl. particle systems) on affected objects.

        bpy.ops.object.convert(target='MESH') applies the full modifier stack
        and produces a plain static MESH.  Blender will then treat the object
        as clean between frames → BVH built once, reused for all frames.

        Scatter-vegetation systems (render_type OBJECT or COLLECTION) are
        skipped: in background mode the scattered instances are not baked into
        the mesh, so converting them silently erases all vegetation.

        Returns: number of objects converted.
        """
        converted = 0
        for obj in list(bpy.context.scene.objects):
            if obj.type not in ("MESH", "CURVE", "SURFACE"):
                continue
            if not _obj_has_particles(obj):
                continue
            if not _can_modify(obj):
                self._log(f"  skip (linked): {obj.name}")
                self._report.skipped_linked.append(obj.name)
                continue
            # Skip scatter vegetation — converting in background mode drops instances
            if _obj_has_only_scatter_particles(obj):
                self._log(f"  skip (scatter vegetation): {obj.name}")
                self._report.skipped_linked.append(f"{obj.name} [scatter]")
                continue
            try:
                bpy.ops.object.select_all(action="DESELECT")
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.convert(target="MESH")
                self._log(f"  particles→mesh: {obj.name}")
                self._report.particles_converted.append(obj.name)
                converted += 1
            except Exception as exc:
                msg = f"{obj.name}: {exc}"
                self._log(f"  ERROR {msg}")
                self._report.errors.append(msg)
        return converted

    # ------------------------------------------------------------------
    # Fix: frame-dependent geometry nodes
    # ------------------------------------------------------------------

    def apply_frame_dep_geonodes(self) -> int:
        """Apply only GN modifiers that are frame-dependent.

        Non-frame-dependent GN modifiers are left intact.  Each modifier is
        applied individually; if the object has other modifiers (e.g. Subdivision),
        they are preserved.

        Returns: number of modifiers applied.
        """
        applied = 0
        for obj in list(bpy.context.scene.objects):
            if obj.type not in ("MESH", "CURVE", "SURFACE"):
                continue
            if not _can_modify(obj):
                continue
            for mod in list(obj.modifiers):
                if mod.type != "NODES":
                    continue
                if not _geonode_is_frame_dependent(mod.node_group):
                    continue
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    # Convert to mesh first if the object is not yet a MESH
                    if obj.type != "MESH":
                        bpy.ops.object.convert(target="MESH")
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    label = f"{obj.name}/{mod.name}"
                    self._log(f"  geonode applied: {label}")
                    self._report.geonodes_applied.append(label)
                    applied += 1
                except Exception as exc:
                    msg = f"{obj.name}/{mod.name}: {exc}"
                    self._log(f"  ERROR {msg}")
                    self._report.errors.append(msg)
        return applied

    # ------------------------------------------------------------------
    # High-level entry point
    # ------------------------------------------------------------------

    def run(self,
            fix_particles: bool = True,
            fix_geonodes:  bool = True) -> PreprocessReport:
        """Scan and fix all render-hostile objects.

        Args:
            fix_particles: convert particle-system objects to static mesh.
            fix_geonodes:  apply frame-dependent Geometry Nodes modifiers.

        Returns: PreprocessReport with names of everything touched.
        """
        self._log("Scanning for render-hostile objects …")
        issues = self.scan()

        n_issues = sum(len(v) for v in issues.values())
        if n_issues == 0:
            self._log("Scene is clean — no render-hostile objects found.")
            return self._report

        for kind, names in issues.items():
            if names:
                self._log(f"  [{kind}] {names}")

        if fix_particles and issues["particle_systems"]:
            n = self.convert_particles_to_mesh()
            self._log(f"Particles: {n} object(s) converted.")

        if fix_geonodes and issues["frame_dep_geonodes"]:
            n = self.apply_frame_dep_geonodes()
            self._log(f"Geometry Nodes: {n} modifier(s) applied.")

        self._log(f"Preprocessing complete — {self._report.summary()}")
        return self._report
