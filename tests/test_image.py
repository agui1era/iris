from __future__ import annotations

import cv2
import numpy as np
import pytest

from iris.image import (
    ImageProcessingError,
    encode_jpeg,
    resize_with_letterbox,
    variation_index_percent,
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


def test_variation_index_percent_is_zero_for_identical_frames() -> None:
    frame = np.full((20, 20, 3), (50, 60, 70), dtype=np.uint8)

    variation = variation_index_percent(
        frame, frame, width=10, height=10, pixel_threshold=24
    )

    assert variation == 0.0


def test_variation_index_percent_is_high_for_completely_different_frames() -> None:
    previous = np.zeros((20, 20, 3), dtype=np.uint8)
    current = np.full((20, 20, 3), 255, dtype=np.uint8)

    variation = variation_index_percent(
        previous, current, width=10, height=10, pixel_threshold=24
    )

    assert variation == 100.0


def test_variation_index_percent_ignores_changes_below_pixel_threshold() -> None:
    previous = np.full((10, 10, 3), 100, dtype=np.uint8)
    current = np.full((10, 10, 3), 105, dtype=np.uint8)

    variation = variation_index_percent(
        previous, current, width=10, height=10, pixel_threshold=24
    )

    assert variation == 0.0


def test_variation_index_percent_counts_only_pixels_past_threshold() -> None:
    previous = np.zeros((10, 10, 3), dtype=np.uint8)
    current = np.zeros((10, 10, 3), dtype=np.uint8)
    current[:5, :] = 255  # top half changes drastically, bottom half stays identical

    variation = variation_index_percent(
        previous, current, width=10, height=10, pixel_threshold=24
    )

    assert variation == pytest.approx(50.0, abs=1.0)


def test_variation_index_percent_rejects_invalid_dimensions_and_threshold() -> None:
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with pytest.raises(ImageProcessingError, match="tamaño de comparación"):
        variation_index_percent(frame, frame, width=0, height=10, pixel_threshold=24)
    with pytest.raises(ImageProcessingError, match="pixel_threshold"):
        variation_index_percent(frame, frame, width=10, height=10, pixel_threshold=-1)
