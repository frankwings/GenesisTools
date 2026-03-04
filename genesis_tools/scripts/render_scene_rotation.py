"""Render a 360° orbit animation of a full assembled scene from a .blend file.

Opens an existing .blend file, discards the projection camera, adds a new
orbit camera around the scene bounding box centre, and renders N frames.

Usage:
    blender -b scene_render.blend -P blender_render_scene_rotation.py -- \\
        <output_dir> [--frames 24] [--resolution 640] [--elevation 25]

The output frames are named:  <output_dir>/scene_y_<NN>.png
"""

import math
import os
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        print("[ERROR] Usage: blender -b scene.blend -P script.py -- <output_dir> [opts]")
        sys.exit(1)
    args = argv[argv.index("--") + 1:]
    cfg = {
        "output_dir": args[0] if args else "scene_frames",
        "frames": 24,
        "resolution": 640,
        "elevation": 25,   # camera elevation angle in degrees
    }
    i = 1
    while i < len(args):
        if args[i] == "--frames" and i + 1 < len(args):
            cfg["frames"] = int(args[i + 1]); i += 2
        elif args[i] == "--resolution" and i + 1 < len(args):
            cfg["resolution"] = int(args[i + 1]); i += 2
        elif args[i] == "--elevation" and i + 1 < len(args):
            cfg["elevation"] = float(args[i + 1]); i += 2
        else:
            i += 1
    return cfg


def scene_bounds():
    """Return (center, radius) bounding sphere for all mesh objects."""
    min_co = Vector((1e9, 1e9, 1e9))
    max_co = Vector((-1e9, -1e9, -1e9))
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_co = Vector([min(a, b) for a, b in zip(min_co, world)])
            max_co = Vector([max(a, b) for a, b in zip(max_co, world)])
            found = True
    if not found:
        return Vector((0, 0, 0)), 1.0
    center = (min_co + max_co) / 2.0
    radius = ((max_co - min_co).length) / 2.0
    return center, radius


def setup_orbit_camera(center, radius, elevation_deg):
    """Create (or reuse) a camera that orbits around *center*.

    Returns the camera object. Angle is set per-frame by the caller.
    """
    # Remove any existing camera named OrbitCam
    for obj in list(bpy.data.objects):
        if obj.name == "OrbitCam":
            bpy.data.objects.remove(obj, do_unlink=True)

    bpy.ops.object.camera_add(location=(0, 0, 0))
    cam_obj = bpy.context.active_object
    cam_obj.name = "OrbitCam"
    cam_obj.data.clip_start = 0.01
    cam_obj.data.clip_end = 1000.0
    bpy.context.scene.camera = cam_obj
    return cam_obj


def position_camera(cam_obj, center, radius, azimuth_deg, elevation_deg):
    """Place camera at azimuth + elevation angle around center."""
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    dist = radius * 2.8
    x = center.x + dist * math.cos(el) * math.sin(az)
    y = center.y - dist * math.cos(el) * math.cos(az)
    z = center.z + dist * math.sin(el)
    cam_obj.location = Vector((x, y, z))

    # Point camera at scene center
    direction = center - cam_obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()


def setup_lighting():
    """Add key + fill + rim lights (neutral studio rig)."""
    bpy.ops.object.light_add(type='SUN', location=(10, -10, 15))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(40), 0, math.radians(30))

    bpy.ops.object.light_add(type='AREA', location=(-5, -5, 5))
    fill = bpy.context.active_object
    fill.data.energy = 60.0
    fill.data.size = 4.0


def setup_render(resolution):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    try:
        scene.eevee.taa_render_samples = 32
    except Exception:
        pass


def main():
    cfg = parse_args()
    output_dir = os.path.abspath(cfg["output_dir"])
    os.makedirs(output_dir, exist_ok=True)

    # Remove the pre-existing projection camera (added by render_full_scene.py)
    for obj in list(bpy.data.objects):
        if obj.name == "SceneCam":
            bpy.data.objects.remove(obj, do_unlink=True)

    # Neutralise world background (the saved .blend may have nodes)
    if bpy.context.scene.world is None:
        bpy.context.scene.world = bpy.data.worlds.new("World")
    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.1, 0.1, 0.1, 1.0)
        bg.inputs["Strength"].default_value = 0.5

    setup_lighting()
    setup_render(cfg["resolution"])

    center, radius = scene_bounds()
    print(f"[SCENE] center={center}, radius={radius:.3f}")

    cam = setup_orbit_camera(center, radius, cfg["elevation"])

    n = cfg["frames"]
    for i in range(n):
        azimuth = 360.0 * i / n
        position_camera(cam, center, radius, azimuth, cfg["elevation"])
        frame_path = os.path.join(output_dir, f"scene_y_{i:02d}.png")
        bpy.context.scene.render.filepath = frame_path
        bpy.ops.render.render(write_still=True)
        print(f"[SCENE] Frame {i+1}/{n} ({azimuth:.0f}°): {frame_path}")

    print(f"[SCENE] Done — {n} frames in {output_dir}")


if __name__ == "__main__":
    main()
