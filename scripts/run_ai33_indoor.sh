#!/usr/bin/env bash
# ============================================================================
# AI33_001 Indoor Walkthrough — Full Pipeline from Scratch
# ============================================================================
#
# Computes snake mesh from scratch (no pre-computed data), then runs
# the complete walkthrough pipeline: voxel grid → walkable → path →
# camera orient → camera animate → render.
#
# Usage:
#   bash scripts/run_ai33_indoor.sh
#   bash scripts/run_ai33_indoor.sh --no-render      # skip rendering
#   bash scripts/run_ai33_indoor.sh --visualize      # include debug overlay
#   bash scripts/run_ai33_indoor.sh --resume          # resume interrupted run
#
# For outdoor/terrain scenes, use scripts/run_outdoor.sh instead.
# All output goes to results/ai33_indoor_walkthrough/
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

BLEND="/home/kingy/Foundation/Assets/SyntheticPlays/AI33_001/AI33_001_280.blend"
OUTPUT="results/ai33_indoor_walkthrough"

python3 scripts/debug_walkthrough.py \
    --blend "$BLEND" \
    --output "$OUTPUT" \
    --width 480 \
    --height 360 \
    --samples 16 \
    --engine BLENDER_WORKBENCH \
    --fps 12 \
    --duration 10 \
    --gaze smooth_adaptive \
    --snake-alpha 0.6 \
    --snake-beta 0.3 \
    --snake-subdiv 2 \
    "$@"

echo ""
echo "============================================"
echo "  Output: $OUTPUT/"
echo "  Frames: $OUTPUT/frames/"
echo "  Snake:  $OUTPUT/snake/snake_mesh.npz"
echo "  Debug:  $OUTPUT/debug_dump.json"
echo "============================================"
