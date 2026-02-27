"""Unit tests for genesis_tools.image_encoding."""
from PIL import Image

from genesis_tools.image_encoding import get_image_base64


def test_get_image_base64_png(tmp_path):
    """Create a real tiny 1x1 PNG, verify output starts with correct data URL prefix."""
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    img_path = tmp_path / "test.png"
    img.save(img_path, format="PNG")

    result = get_image_base64(img_path)

    assert result.startswith("data:image/png;base64,")
    # Ensure there is actual base64 content after the prefix
    base64_part = result.split(",", 1)[1]
    assert len(base64_part) > 0


def test_get_image_base64_jpeg(tmp_path):
    """Create a real tiny 1x1 JPEG, verify output starts with correct data URL prefix."""
    img = Image.new("RGB", (1, 1), color=(0, 255, 0))
    img_path = tmp_path / "test.jpg"
    img.save(img_path, format="JPEG")

    result = get_image_base64(img_path)

    assert result.startswith("data:image/jpeg;base64,")
    base64_part = result.split(",", 1)[1]
    assert len(base64_part) > 0


def test_get_image_base64_rgba_to_jpeg(tmp_path):
    """Create a tiny RGBA image saved as .jpg, verify it converts correctly without error."""
    img = Image.new("RGBA", (1, 1), color=(0, 0, 255, 128))
    img_path = tmp_path / "test_rgba.jpg"
    # Pillow cannot save RGBA directly as JPEG, so save as PNG first then rename
    # Actually, just save as PNG to a temp file and rename the path for the function
    # Instead, let the function handle the conversion -- save the raw RGBA data as PNG
    # and give it a .jpg extension so get_image_base64 triggers the JPEG branch.
    png_path = tmp_path / "temp.png"
    img.save(png_path, format="PNG")
    # Rename to .jpg so the function treats it as JPEG
    img_path = tmp_path / "test_rgba.jpg"
    png_path.rename(img_path)

    result = get_image_base64(img_path)

    # The function should convert RGBA->RGB and produce a JPEG data URL
    assert result.startswith("data:image/jpeg;base64,")
    base64_part = result.split(",", 1)[1]
    assert len(base64_part) > 0


def test_get_image_base64_p_mode_png(tmp_path):
    """Create a P-mode (palette) image saved as .png, verify conversion works."""
    img = Image.new("P", (1, 1))
    img.putpalette([i for i in range(256)] * 3)  # Simple palette
    img_path = tmp_path / "test_palette.png"
    img.save(img_path, format="PNG")

    result = get_image_base64(img_path)

    # P-mode PNG gets converted to RGBA internally, then saved as PNG
    assert result.startswith("data:image/png;base64,")
    base64_part = result.split(",", 1)[1]
    assert len(base64_part) > 0
