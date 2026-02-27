"""Image to base64 data URL conversion with format preservation."""
import base64
import io
import os
from pathlib import Path
from typing import Union

from PIL import Image


def get_image_base64(image_path: Union[str, Path]) -> str:
    """Return a full data URL for the image, preserving original jpg/png format.

    Handles transparency correctly:
    - JPEG: Converts RGBA/LA/P to RGB with white background
    - PNG: Converts P mode to RGBA

    Args:
        image_path: Path to the image file.

    Returns:
        Data URL string (e.g., 'data:image/png;base64,...').
    """
    image_path = str(image_path)
    image = Image.open(image_path)
    img_byte_array = io.BytesIO()
    ext = os.path.splitext(image_path)[1].lower()

    if ext in [".jpg", ".jpeg"]:
        save_format = "JPEG"
        mime_subtype = "jpeg"
        if image.mode in ["RGBA", "LA", "P"]:
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode == "RGBA":
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode == "LA":
                image = image.convert("RGB")
    elif ext == ".png":
        save_format = "PNG"
        mime_subtype = "png"
        if image.mode == "P":
            image = image.convert("RGBA")
    else:
        save_format = image.format or "PNG"
        mime_subtype = save_format.lower() if save_format.lower() in ["jpeg", "png"] else "png"
        if image.mode == "P":
            if save_format == "JPEG":
                image = image.convert("RGB")
            else:
                image = image.convert("RGBA")

    image.save(img_byte_array, format=save_format)
    img_byte_array.seek(0)
    base64enc_image = base64.b64encode(img_byte_array.read()).decode("utf-8")

    # Double-check MIME type from actual encoded content
    if base64enc_image.startswith("/9j/"):
        mime_subtype = "jpeg"
    elif base64enc_image.startswith("iVBOR"):
        mime_subtype = "png"
    elif base64enc_image.startswith("UklGR"):
        mime_subtype = "webp"

    return f"data:image/{mime_subtype};base64,{base64enc_image}"
