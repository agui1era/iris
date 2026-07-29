from __future__ import annotations

import cv2
import numpy as np
import pytest

from iris.image import (
    ImageProcessingError,
    encode_jpeg,
    resize_with_letterbox,
)


def test_resize_with_letterbox_preserves_aspect_ratio_and_centers_image() -> None:
    frame = np.full((2, 4, 3), (10, 20, 30), dtype=np.uint8)

    resized = resize_with_letterbox(frame, width=4, height=4)

    assert resized.shape == (4, 4, 3)
    np.testing.assert_array_equal(resized[1:3], frame)
    np.testing.assert_array_equal(resized[0], np.zeros((4, 3), dtype=np.uint8))
    np.testing.assert_array_equal(resized[3], np.zeros((4, 3), dtype=np.uint8))


def test_resize_with_letterbox_adds_symmetric_side_bars_for_portrait_frame() -> None:
    frame = np.full((4, 2, 3), 77, dtype=np.uint8)

    resized = resize_with_letterbox(frame, width=4, height=4)

    np.testing.assert_array_equal(resized[:, 1:3], frame)
    np.testing.assert_array_equal(resized[:, 0], np.zeros((4, 3), dtype=np.uint8))
    np.testing.assert_array_equal(resized[:, 3], np.zeros((4, 3), dtype=np.uint8))


def test_encode_jpeg_returns_decodable_image_and_validates_quality() -> None:
    frame = np.full((8, 10, 3), (20, 100, 200), dtype=np.uint8)

    encoded = encode_jpeg(frame, quality=90)
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert encoded.startswith(b"\xff\xd8")
    assert decoded is not None
    assert decoded.shape == frame.shape
    with pytest.raises(ImageProcessingError, match="calidad JPEG"):
        encode_jpeg(frame, quality=0)
