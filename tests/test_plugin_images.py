"""Decode bounded synthetic artwork without source paths or live rendering."""

from __future__ import annotations

import builtins
import io
import warnings

import pytest

from skills_sdk.validation.plugin_images import inspect_plugin_image


def _raster(image_format: str, size: tuple[int, int] = (48, 48)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    with Image.new("RGB", size, color="white") as image:
        image.save(buffer, format=image_format)
    return buffer.getvalue()


def _svg(
    attributes: str = 'width="48" height="48"', content: str = '<rect width="48" height="48" fill="#fff"/>'
) -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}>{content}</svg>'.encode()


@pytest.mark.parametrize("suffix,image_format", [("png", "PNG"), ("jpg", "JPEG"), ("jpeg", "JPEG"), ("webp", "WEBP")])
def test_raster_complete_decode_and_recovery(suffix: str, image_format: str) -> None:
    payload = _raster(image_format)
    expected = "jpeg" if image_format == "JPEG" else image_format.lower()
    assert inspect_plugin_image("never-opened." + suffix, payload) == (expected, 48.0, 48.0)
    with pytest.raises(ValueError):
        inspect_plugin_image("never-opened." + suffix, payload[: len(payload) // 2])
    assert inspect_plugin_image("never-opened." + suffix, payload) == (expected, 48.0, 48.0)


@pytest.mark.parametrize("size", [(47, 47), (48, 49), (4097, 4097)])
def test_raster_dimensions_block(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        inspect_plugin_image("icon.png", _raster("PNG", size))


def test_raster_extension_and_byte_limits() -> None:
    with pytest.raises(ValueError, match="extension"):
        inspect_plugin_image("icon.jpg", _raster("PNG"))
    for path, payload in [
        ("icon.gif", b"GIF89a"),
        ("icon.png", b"not an image"),
        ("icon.png", b"x" * (5 * 1024 * 1024 + 1)),
    ]:
        with pytest.raises(ValueError):
            inspect_plugin_image(path, payload)


def test_animation_is_unsupported() -> None:
    from PIL import Image

    buffer = io.BytesIO()
    first, second = Image.new("RGB", (48, 48), "white"), Image.new("RGB", (48, 48), "black")
    try:
        first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=10)
    finally:
        first.close()
        second.close()
    with pytest.raises(ValueError):
        inspect_plugin_image("icon.png", buffer.getvalue())


def test_missing_optional_decoder_is_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def missing(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL":
            raise ImportError("optional image decoder unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ImportError):
        inspect_plugin_image("icon.png", b"synthetic")
    assert inspect_plugin_image("icon.svg", _svg()) == ("svg", 48.0, 48.0)


def test_permissive_decoder_globals_block_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import ImageFile

    payload = _raster("JPEG")
    with monkeypatch.context() as settings:
        settings.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
        with pytest.raises(ValueError):
            inspect_plugin_image("icon.jpg", payload)
        assert ImageFile.LOAD_TRUNCATED_IMAGES is True
    assert inspect_plugin_image("icon.jpg", payload) == ("jpeg", 48.0, 48.0)


def test_caller_warning_as_error_is_typed_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    payload = _raster("PNG")
    original = Image.open

    def warned(*args: object, **kwargs: object) -> object:
        warnings.warn("synthetic caller warning", Image.DecompressionBombWarning, stacklevel=1)
        return original(*args, **kwargs)

    monkeypatch.setattr(Image, "open", warned)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with pytest.raises(ValueError, match="complete static image decoding"):
            inspect_plugin_image("icon.png", payload)
    monkeypatch.undo()
    assert inspect_plugin_image("icon.png", payload) == ("png", 48.0, 48.0)


@pytest.mark.parametrize(
    "attributes", ['width="48px" height="48px"', 'viewBox="0 0 48 48"', 'width="64" height="64" viewBox="0 0 24 24"']
)
def test_static_svg_acceptance(attributes: str) -> None:
    result = inspect_plugin_image("icon.svg", _svg(attributes))
    assert result[0] == "svg" and result[1] == result[2] and result[1] >= 48


@pytest.mark.parametrize(
    "content",
    [
        "<script>unsafe()</script>",
        '<rect onload="unsafe()"/>',
        "<foreignObject/>",
        '<image href="https://example.invalid/image"/>',
        '<use href="#shape"/>',
        "<style>rect {fill:url(https://example.invalid)}</style>",
        '<rect fill="url(#shape)"/>',
        '<animate attributeName="x"/>',
        '<g xmlns="http://other.invalid"/>',
        '<rect style="fill:red"/>',
        "<filter/>",
    ],
)
def test_svg_rejects_active_external_and_complex_content(content: str) -> None:
    with pytest.raises(ValueError):
        inspect_plugin_image("icon.svg", _svg(content=content))
    assert inspect_plugin_image("icon.svg", _svg()) == ("svg", 48.0, 48.0)


@pytest.mark.parametrize(
    "attributes",
    [
        "",
        'width="48"',
        'width="48" height="49"',
        'width="47" height="47"',
        'width="NaN" height="NaN"',
        'viewBox="0 0 48 49"',
        'viewBox="0 0 1e999 1e999"',
        'width="48" height="48" viewBox="0 0 48 49"',
    ],
)
def test_svg_dimensions_reject(attributes: str) -> None:
    with pytest.raises(ValueError):
        inspect_plugin_image("icon.svg", _svg(attributes))


def test_svg_parser_and_structural_bounds() -> None:
    for payload in [
        b"\xff",
        b"<svg/>",
        b'<!DOCTYPE svg [<!ENTITY x "expanded">]>' + _svg(),
        b'<?unsafe external="https://example.invalid"?>' + _svg(),
        _svg(content="<g>" * 33 + "</g>" * 33),
        _svg(content="<rect/>" * 2049),
        _svg()[:-4],
    ]:
        with pytest.raises(ValueError):
            inspect_plugin_image("icon.svg", payload)
    assert inspect_plugin_image("icon.svg", _svg()) == ("svg", 48.0, 48.0)


@pytest.mark.parametrize("image_format,suffix", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_landscape_screenshots_decode_reject_corruption_and_recover(image_format: str, suffix: str) -> None:
    payload = _raster(image_format, (96, 48))
    expected_format = "jpeg" if image_format == "JPEG" else image_format.lower()
    path = "screenshot." + suffix
    assert inspect_plugin_image(path, payload, kind="screenshot") == (expected_format, 96.0, 48.0)
    with pytest.raises(ValueError):
        inspect_plugin_image(path, payload)
    with pytest.raises(ValueError):
        inspect_plugin_image(path, payload[: len(payload) // 2], kind="screenshot")
    assert inspect_plugin_image(path, payload, kind="screenshot") == (expected_format, 96.0, 48.0)


def test_screenshot_profile_bounds_and_svg_rejection() -> None:
    assert inspect_plugin_image("tiny.png", _raster("PNG", (1, 2)), kind="screenshot") == ("png", 1.0, 2.0)
    assert inspect_plugin_image("wide.png", _raster("PNG", (4096, 1)), kind="screenshot") == ("png", 4096.0, 1.0)
    for size in ((4097, 1), (1, 4097)):
        with pytest.raises(ValueError):
            inspect_plugin_image("large.png", _raster("PNG", size), kind="screenshot")
    with pytest.raises(ValueError, match="SVG screenshots"):
        inspect_plugin_image("screenshot.svg", _svg(), kind="screenshot")


def test_screenshot_missing_decoder_is_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def missing(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL":
            raise ImportError("optional image decoder unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ImportError):
        inspect_plugin_image("screenshot.png", b"synthetic", kind="screenshot")


@pytest.mark.parametrize("kind", ["other", "", None, True, 1])
def test_invalid_kind_rejected(kind: object) -> None:
    with pytest.raises(ValueError, match="inspection kind"):
        inspect_plugin_image("icon.svg", _svg(), kind=kind)
