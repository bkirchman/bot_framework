from __future__ import annotations

import numpy as np

from framework.contrib.detection.color_match import ColorMatchDetector


def make_bgr_frame_from_hsv(hsv_frame: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(hsv_frame, cv2.COLOR_HSV2BGR)


def test_color_match_fires_at_pixel_threshold_boundary() -> None:
    hsv = np.zeros((4, 4, 3), dtype=np.uint8)
    hsv[..., 0] = 60
    hsv[..., 1] = 200
    hsv[..., 2] = 200
    frame = make_bgr_frame_from_hsv(hsv)

    detector = ColorMatchDetector(
        hue_range=(50, 70),
        saturation_min=100,
        value_min=100,
        pixel_threshold=16,
    )
    assert detector.matched_pixel_count(frame) == 16
    assert detector(frame)

    detector_above = ColorMatchDetector(
        hue_range=(50, 70),
        saturation_min=100,
        value_min=100,
        pixel_threshold=17,
    )
    assert not detector_above(frame)


def test_color_match_hue_wrap_supports_red_span() -> None:
    hsv = np.zeros((2, 2, 3), dtype=np.uint8)
    hsv[0, 0] = [175, 200, 200]
    hsv[0, 1] = [5, 200, 200]
    hsv[1, 0] = [90, 200, 200]
    hsv[1, 1] = [120, 200, 200]
    frame = make_bgr_frame_from_hsv(hsv)

    detector = ColorMatchDetector(
        hue_range=(170, 10),
        saturation_min=100,
        value_min=100,
        pixel_threshold=2,
    )

    assert detector.matched_pixel_count(frame) == 2
    assert detector(frame)


def test_color_match_roi_crops_included_region_only() -> None:
    hsv = np.zeros((4, 4, 3), dtype=np.uint8)
    hsv[..., 0] = 20
    hsv[..., 1] = 200
    hsv[..., 2] = 200
    hsv[3, 3] = [100, 200, 200]
    frame = make_bgr_frame_from_hsv(hsv)

    inside_roi = ColorMatchDetector(
        hue_range=(10, 30),
        saturation_min=100,
        value_min=100,
        pixel_threshold=4,
        roi=(0, 0, 2, 2),
    )
    outside_roi = ColorMatchDetector(
        hue_range=(90, 110),
        saturation_min=100,
        value_min=100,
        pixel_threshold=1,
        roi=(0, 0, 2, 2),
    )

    assert inside_roi.matched_pixel_count(frame) == 4
    assert inside_roi(frame)
    assert outside_roi.matched_pixel_count(frame) == 0
    assert not outside_roi(frame)


def test_matched_pixel_count_reports_raw_count() -> None:
    hsv = np.zeros((3, 3, 3), dtype=np.uint8)
    hsv[0, 0] = [30, 150, 150]
    hsv[0, 1] = [30, 150, 150]
    hsv[0, 2] = [30, 150, 150]
    hsv[1, 0] = [120, 150, 150]
    hsv[1, 1] = [120, 150, 150]
    hsv[1, 2] = [120, 150, 150]
    hsv[2, :] = [60, 150, 150]
    frame = make_bgr_frame_from_hsv(hsv)

    detector = ColorMatchDetector(
        hue_range=(20, 40),
        saturation_min=100,
        value_min=100,
        pixel_threshold=10,
    )

    assert detector.matched_pixel_count(frame) == 3
    assert not detector(frame)