"""Image inspection and resizing used when applying artwork.

The gallery already holds the bytes that were downloaded from the Cover Art
Archive, so no second network request is needed when the user presses
"Use this artwork".  This module only decodes those bytes, optionally resizes
them, and returns the exact bytes that should be embedded into the MP3.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage

# Images with a smaller side below this threshold are never upscaled.
MIN_UPSCALE_SIDE = 500


@dataclass(frozen=True)
class PreparedArtwork:
    data: bytes
    extension: str  # without the leading dot: "jpg", "png", ...
    width: int
    height: int
    resized: bool
    source_width: int
    source_height: int
    cropped: bool = False


def format_kb(data: bytes) -> str:
    kb = len(data) / 1024
    if kb >= 100:
        return f"{kb:.0f} KB"
    return f"{kb:.1f} KB"


def detect_extension(data: bytes) -> str:
    """Return the file extension implied by the image bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    return "jpg"


def _untouched(
    image: QImage,
    data: bytes,
    extension: str,
    width: int,
    height: int,
) -> PreparedArtwork:
    """Return the original bytes, converting unsupported formats to JPEG."""
    if extension not in ("jpg", "png"):
        # ID3 APIC MIME handling expects JPEG/PNG; convert anything else.
        encoded = _encode(image, "jpg")
        return PreparedArtwork(
            data=encoded,
            extension="jpg",
            width=width,
            height=height,
            resized=False,
            source_width=width,
            source_height=height,
        )
    return PreparedArtwork(
        data=data,
        extension=extension,
        width=width,
        height=height,
        resized=False,
        source_width=width,
        source_height=height,
    )


def prepare_artwork(data: bytes, target_size: int | None = None) -> PreparedArtwork:
    """Decode artwork bytes and optionally resize them.

    When ``target_size`` is set, the result is a square image: non-square
    artwork is centre-cropped, then the side is limited to ``target_size``.
    Images whose smaller side is below 500 px are never upscaled.  Without a
    target the original bytes are returned untouched.
    """
    if not data:
        raise ValueError("The selected image has no data.")

    image = QImage.fromData(data)
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("The selected file is not a readable image.")

    source_width, source_height = image.width(), image.height()
    extension = detect_extension(data)

    if not target_size or target_size <= 0:
        return _untouched(image, data, extension, source_width, source_height)

    side = min(source_width, source_height)
    cropped = source_width != source_height
    if cropped:
        image = image.copy(
            (source_width - side) // 2,
            (source_height - side) // 2,
            side,
            side,
        )
        if image.isNull():
            raise ValueError("Could not crop the selected image.")

    # The user asked for a 500px minimum: never blow up images whose smaller
    # side is below that.  Larger sources are resized to the exact target,
    # including an explicit upscale if the user selected a bigger size.
    if side < MIN_UPSCALE_SIDE and target_size > side:
        if not cropped:
            return _untouched(image, data, extension, source_width, source_height)
        encoded = _encode(image, extension)
        return PreparedArtwork(
            data=encoded,
            extension="png" if extension == "png" else "jpg",
            width=side,
            height=side,
            resized=False,
            source_width=source_width,
            source_height=source_height,
            cropped=True,
        )

    if side == target_size:
        if not cropped:
            return _untouched(image, data, extension, source_width, source_height)
        encoded = _encode(image, extension)
        return PreparedArtwork(
            data=encoded,
            extension="png" if extension == "png" else "jpg",
            width=side,
            height=side,
            resized=False,
            source_width=source_width,
            source_height=source_height,
            cropped=True,
        )

    scaled = image.scaled(
        target_size,
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        raise ValueError("Could not resize the selected image.")

    encoded = _encode(scaled, extension)
    return PreparedArtwork(
        data=encoded,
        extension="png" if extension == "png" else "jpg",
        width=scaled.width(),
        height=scaled.height(),
        resized=True,
        source_width=source_width,
        source_height=source_height,
        cropped=cropped,
    )


def _encode(image: QImage, extension: str) -> bytes:
    is_png = extension == "png"
    fmt = "PNG" if is_png else "JPEG"
    quality = -1 if is_png else 95

    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("Could not allocate memory for the resized image.")
    try:
        saved = image.save(buffer, fmt, quality)
    finally:
        buffer.close()
    if not saved:
        raise ValueError("Could not encode the resized image.")
    return bytes(payload.data())
