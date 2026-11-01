"""Generate an illustration image and store it. Owner: Mogith.

The image model only draws the picture: we always ask for NO text in it, because image models
misspell words. The numbered labels come separately from the LLM (decide_visual.py).
"""

import io
from dataclasses import dataclass

from PIL import Image

from ai_service.providers import get_image_generator, get_storage

# How each style card in the app (Figma B10) is described to the image model.
STYLE_PROMPTS = {
    "flat_colour": "flat colour vector illustration, simple clean shapes, soft colours",
    "textbook_line": "clean black-and-white line drawing, like a school biology textbook",
    "cross_section": "scientific cross-section view, cut open to show the inner layers",
}
NO_TEXT = "No text, no letters, no labels, no numbers, no words anywhere in the image."


@dataclass
class StoredImage:
    path: str
    width: int
    height: int


def build_image_prompt(description: str, style: str) -> str:
    """The prompt sent to the image model: what to draw + the style + the no-text rule."""
    style_text = STYLE_PROMPTS.get(style, STYLE_PROMPTS["flat_colour"])
    return (
        f"{description.strip()} "
        f"Style: {style_text}, plain white background, accurate biology for A/L students. "
        f"{NO_TEXT}"
    )


def to_png(data: bytes) -> tuple[bytes, int, int]:
    """Any image (PNG / JPEG...) -> PNG bytes + width + height. Raises ValueError if unreadable."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if image.format == "PNG":
                return data, width, height
            out = io.BytesIO()
            image.convert("RGB").save(out, format="PNG")
            return out.getvalue(), width, height
    except OSError as exc:  # Pillow raises UnidentifiedImageError (an OSError) for bad data
        raise ValueError("The image data could not be read") from exc


async def save_png(path: str, data: bytes) -> StoredImage:
    """Convert to PNG, store it and return the path + size."""
    png, width, height = to_png(data)
    await get_storage().save(path, png, "image/png")
    return StoredImage(path=path, width=width, height=height)


async def create_illustration(description: str, style: str, path: str) -> StoredImage:
    """Draw the picture with the image provider and store it at `path`."""
    image = await get_image_generator().generate_image(build_image_prompt(description, style))
    return await save_png(path, image)
