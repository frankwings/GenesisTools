#!/usr/bin/env bash
# ============================================================================
# Outdoor Terrain Walkthrough — Full Pipeline from Scratch
# ============================================================================
#
# Two-phase terrain pipeline:
#   Phase 1 (Step 0b): Fit terrain snake via Blender raycasting
#   Phase 2 (Steps 1-6): Voxel grid → walkable → path → camera → render
#
# Mode is auto-detected from the config's "aerial" field (aerial=false → outdoor).
#
# Usage:
#   bash scripts/run_outdoor.sh
#   bash scripts/run_outdoor.sh --no-render
#   bash scripts/run_outdoor.sh --resume
#
# For a different outdoor scene, override --blend and optionally --config:
#   bash scripts/run_outdoor.sh --blend /path/to/scene.blend
#
# All output goes to results/outdoor_walkthrough/
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

BLEND="/home/kingy/Foundation/Assets/BlenderScenes/in_the_park/in the park.blend"
OUTPUT="results/outdoor_walkthrough"

python3 scripts/debug_walkthrough.py \
    --blend "$BLEND" \
    --output "$OUTPUT" \
    --config configs/terrain_scene.json \
    --width 640 \
    --height 480 \
    --samples 64 \
    --engine CYCLES \
    --fps 12 \
    --duration 83 \
    --gaze waypoint \
    "$@"

echo ""
echo "============================================"
echo "  Output:  $OUTPUT/"
echo "  Frames:  $OUTPUT/frames/"
echo "  Terrain: $OUTPUT/terrain_snake.npz"
echo "  Debug:   $OUTPUT/debug_dump.json"
echo "============================================"
