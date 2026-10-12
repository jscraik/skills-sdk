"""Bounded static icon and raster screenshot inspection, never opening paths.

SVG support intentionally excludes gradients, filters, linked resources, CSS,
fonts, text rendering, animation and embedded content. Static geometry with
plain colours is accepted; broader valid SVG requires a separate safe route.
Square icon limits remain separate from the non-square raster screenshot profile.
SVG screenshots are unsupported because this service never renders SVG.
"""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Literal

MAX_IMAGE_BYTES = 5 * 1024 * 1024
_NAMESPACE = "http://www.w3.org/2000/svg"
_EXTENSIONS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".svg": "svg"}
_TAGS = frozenset({"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "title", "desc"})
_ATTRIBUTES = frozenset(
    {
        "width",
        "height",
        "viewBox",
        "version",
        "preserveAspectRatio",
        "id",
        "d",
        "points",
        "transform",
        "x",
        "y",
        "x1",
        "x2",
        "y1",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "fill-rule",
        "clip-rule",
        "opacity",
        "fill-opacity",
        "stroke-opacity",
    }
)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def _dimension(value: str) -> float:
    if re.fullmatch(rf"\s*({_NUMBER})(?:px)?\s*", value) is None:
        raise ValueError("image dimensions require finite numeric values")
    number = float(value.strip().removesuffix("px"))
    if not math.isfinite(number) or number <= 0:
        raise ValueError("image dimensions require finite positive values")
    return number


def _square(width: float, height: float, *, raster: bool = False) -> None:
    if not math.isfinite(width) or not math.isfinite(height) or width != height or width < 48:
        raise ValueError("image requires square dimensions of at least 48")
    if raster and width > 4096:
        raise ValueError("raster dimensions exceed 4096")


def _svg_dimensions(attributes: dict[str, str]) -> tuple[float, float]:
    width, height = attributes.get("width"), attributes.get("height")
    box = attributes.get("viewBox")
    bounds: tuple[float, ...] | None = None
    if box is not None:
        parts = re.split(r"[\s,]+", box.strip())
        if len(parts) != 4 or any(re.fullmatch(_NUMBER, item) is None for item in parts):
            raise ValueError("SVG viewBox requires four finite numeric values")
        bounds = tuple(float(item) for item in parts)
        if any(not math.isfinite(item) for item in bounds) or bounds[2] <= 0 or bounds[2] != bounds[3]:
            raise ValueError("SVG viewBox requires finite square bounds")
    if width is not None or height is not None:
        if width is None or height is None:
            raise ValueError("SVG requires paired dimensions")
        dimensions = _dimension(width), _dimension(height)
    elif bounds is not None:
        dimensions = bounds[2], bounds[3]
    else:
        raise ValueError("SVG requires numeric dimensions or square viewBox")
    _square(*dimensions)
    return dimensions


def _svg_element(element: ET.Element) -> None:
    if not isinstance(element.tag, str) or not element.tag.startswith("{" + _NAMESPACE + "}"):
        raise ValueError("SVG requires its standard namespace")
    tag = element.tag.split("}", 1)[1]
    if tag not in _TAGS or any(key not in _ATTRIBUTES for key in element.attrib):
        raise ValueError("SVG contains unsupported active or complex content")
    for key, value in element.attrib.items():
        if "url" in value.casefold() or "\\" in value or ":" in value:
            raise ValueError("SVG linked resources are unsupported")
        if key in {"fill", "stroke"} and re.fullmatch(r"(?:#[0-9A-Fa-f]{3,8}|[A-Za-z]+)", value) is None:
            raise ValueError("SVG paint requires a plain colour")


def _inspect_svg(payload: bytes) -> tuple[str, float, float]:
    try:
        text = payload.decode("utf-8-sig")
        text = re.sub(r"^\s*<\?xml\s+[^?]*\?>", "", text, count=1)
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)|<\?", text, flags=re.IGNORECASE):
            raise ValueError("SVG declarations and processing instructions are unsupported")
        depth, count, root = 0, 0, None
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "start":
                depth += 1
                count += 1
                if depth > 32 or count > 2048 or len(element.attrib) > 64:
                    raise ValueError("SVG exceeds structural bounds")
                _svg_element(element)
                if root is None:
                    root = element
            else:
                depth -= 1
        if root is None or root.tag != "{" + _NAMESPACE + "}svg":
            raise ValueError("SVG requires a namespaced svg root")
        return "svg", *_svg_dimensions(root.attrib)
    except (UnicodeError, ET.ParseError, OverflowError, ValueError):
        raise ValueError("SVG must satisfy bounded static image requirements") from None


def _inspect_raster(payload: bytes, kind: Literal["icon", "screenshot"]) -> tuple[str, float, float]:
    from PIL import Image, ImageFile

    try:
        if ImageFile.LOAD_TRUNCATED_IMAGES is not False:
            raise ValueError("complete decoding cannot use permissive truncation settings")
        with Image.open(io.BytesIO(payload), formats=["PNG", "JPEG", "WEBP"]) as image:
            image_format = str(image.format).lower()
            width, height = image.size
            if kind == "icon":
                _square(float(width), float(height), raster=True)
            elif not (1 <= width <= 4096 and 1 <= height <= 4096):
                raise ValueError("screenshot dimensions require one through 4096 pixels")
            if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                raise ValueError("animated images are unsupported")
            image.verify()
        with Image.open(io.BytesIO(payload), formats=["PNG", "JPEG", "WEBP"]) as decoded:
            decoded.load()
            if decoded.size != (width, height) or str(decoded.format).lower() != image_format:
                raise ValueError("raster decoding changed its identity")
        return image_format, float(width), float(height)
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("raster must satisfy complete static image decoding requirements") from None


def inspect_plugin_image(
    path: str,
    payload: bytes,
    *,
    kind: Literal["icon", "screenshot"] = "icon",
) -> tuple[str, float, float]:
    """Inspect a named profile; paths select formats only and are never opened."""
    if type(kind) is not str or kind not in {"icon", "screenshot"}:
        raise ValueError("image inspection kind must be icon or screenshot")
    if type(path) is not str or type(payload) is not bytes or not payload or len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("image bytes must be nonempty and within five MiB")
    expected = _EXTENSIONS.get(PurePosixPath(path).suffix.lower())
    if expected is None:
        raise ValueError("image extension is unsupported")
    if kind == "screenshot" and expected == "svg":
        raise ValueError("SVG screenshots require a separate rendering route")
    result = _inspect_svg(payload) if expected == "svg" else _inspect_raster(payload, kind)
    if result[0] != expected:
        raise ValueError("image extension must match decoded format")
    return result


__all__ = ["inspect_plugin_image"]
