#!/usr/bin/env bash
# Resize GIFs >50MB in docs/assets to 640x360 using bundled ffmpeg

FFMPEG="/home/kingy/Projects/Genesis/GenesisLilith/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
ASSETS_DIR="$(cd "$(dirname "$0")/../docs/assets" && pwd)"
TARGET_W=640
TARGET_H=360
MAX_MB=50

resize_gif() {
    local input="$1"
    local size_mb=$(du -m "$input" | cut -f1)
    if [ "$size_mb" -le "$MAX_MB" ]; then
        echo "SKIP $input (${size_mb}MB <= ${MAX_MB}MB)"
        return
    fi
    echo "RESIZE $input (${size_mb}MB) → ${TARGET_W}x${TARGET_H}"
    local tmp="${input}.tmp.gif"
    "$FFMPEG" -y -i "$input" \
        -vf "scale=${TARGET_W}:${TARGET_H}:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=bayer" \
        "$tmp" 2>&1 | grep -E "frame=|error|Error" | tail -5
    if [ $? -eq 0 ] && [ -f "$tmp" ]; then
        mv "$tmp" "$input"
        local new_mb=$(du -m "$input" | cut -f1)
        echo "  DONE → ${new_mb}MB"
    else
        echo "  FAILED, removing tmp"
        rm -f "$tmp"
    fi
}

find "$ASSETS_DIR" -name "*.gif" | sort | while read gif; do
    resize_gif "$gif"
done

echo "All done."
