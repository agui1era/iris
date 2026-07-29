from __future__ import annotations

import cv2
import numpy as np

from iris.models import Frame


class ImageProcessingError(ValueError):
    """Raised when a frame cannot be transformed or encoded."""


def resize_with_letterbox(frame: Frame, width: int, height: int) -> Frame:
    """Fit a frame into an exact canvas while preserving its aspect ratio."""

    if frame is None or frame.size == 0:
        raise ImageProcessingError("El frame está vacío.")
    if width <= 0 or height <= 0:
        raise ImageProcessingError("La resolución de destino debe ser positiva.")

    source_height, source_width = frame.shape[:2]
    scale = min(width / source_width, height / source_height)
    resized_width = max(1, round(source_width * scale))
    resized_height = max(1, round(source_height * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(
        frame,
        (resized_width, resized_height),
        interpolation=interpolation,
    )

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x_offset = (width - resized_width) // 2
    y_offset = (height - resized_height) // 2
    canvas[
        y_offset : y_offset + resized_height,
        x_offset : x_offset + resized_width,
    ] = resized
    return canvas


def encode_jpeg(frame: Frame, *, quality: int = 82) -> bytes:
    if not 1 <= quality <= 100:
        raise ImageProcessingError("La calidad JPEG debe estar entre 1 y 100.")
    encoded, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not encoded:
        raise ImageProcessingError("OpenCV no pudo codificar el frame como JPEG.")
    return buffer.tobytes()
