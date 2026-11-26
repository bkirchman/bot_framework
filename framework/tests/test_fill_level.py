from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from framework.contrib.detection import FillLevelDetector, FillLevelResult


ROI = (7, 11, 10, 110)


def make_detector() -> FillLevelDetector:
    return FillLevelDetector(
        roi=ROI,
        hue_range=(160, 25),
        saturation_min=100,
        value_min=100,
        row_fraction=0.5,
        min_consecutive_rows=3,
        full_row=4,
        empty_row=104,
    )


def make_frame() -> np.ndarray:
    import cv2

    hsv = np.zeros((130, 25, 3), dtype=np.uint8)
    hsv[..., 2] = 50
    x, y, w, _ = ROI
    hsv[y + 2, x : x + w] = [110, 255, 255]
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def paint_liquid(frame: np.ndarray, start: int, end: int, hue: int = 0, width: int = 10) -> None:
    import cv2

    hsv = np.zeros((end - start, width, 3), dtype=np.uint8)
    hsv[..., 0] = hue
    hsv[..., 1:] = 255
    color = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    x, y, _, _ = ROI
    frame[y + start : y + end, x : x + width] = color


@pytest.mark.parametrize(("top", "expected"), [(4, 1.0), (41, 0.63), (69, 0.35)])
def test_fill_level_reports_fraction_and_absolute_top(top: int, expected: float) -> None:
    frame = make_frame()
    paint_liquid(frame, top, 105)

    result = make_detector()(frame)

    assert result.liquid_found is True
    assert result.liquid_top_row == top
    assert result.liquid_top_y == ROI[1] + top
    assert result.fill_fraction == pytest.approx(expected)


def test_fill_level_nothing_found_is_unknown() -> None:
    assert make_detector()(make_frame()) == FillLevelResult(False, None, None, None)


@pytest.mark.parametrize("speck_height", [1, 2])
def test_fill_level_ignores_short_specks(speck_height: int) -> None:
    frame = make_frame()
    paint_liquid(frame, 10, 10 + speck_height)
    paint_liquid(frame, 69, 105)
    result = make_detector()(frame)
    assert result.liquid_top_row == 69
    assert result.fill_fraction == pytest.approx(0.35)


@pytest.mark.parametrize("hue", [0, 25, 160, 179])
def test_fill_level_detects_both_sides_of_wrapped_hue(hue: int) -> None:
    frame = make_frame()
    paint_liquid(frame, 41, 50, hue=hue)
    assert make_detector()(frame).liquid_top_row == 41


@pytest.mark.parametrize("hue", [26, 159])
def test_fill_level_excludes_hues_outside_wrapped_range(hue: int) -> None:
    frame = make_frame()
    paint_liquid(frame, 41, 50, hue=hue)
    assert make_detector()(frame) == FillLevelResult(False, None, None, None)


def test_fill_level_row_fraction_is_strictly_greater() -> None:
    frame = make_frame()
    paint_liquid(frame, 10, 13, width=5)
    paint_liquid(frame, 20, 23, width=6)
    assert make_detector()(frame).liquid_top_row == 20
    assert replace(make_detector(), row_fraction=0.6)(frame).liquid_found is False


def test_fill_level_supports_non_wrapping_hue_ranges() -> None:
    frame = make_frame()
    paint_liquid(frame, 41, 50, hue=60)
    assert replace(make_detector(), hue_range=(50, 70))(frame).liquid_top_row == 41
    assert make_detector()(frame).liquid_found is False


@pytest.mark.parametrize(("saturation", "value"), [(99, 255), (255, 99)])
def test_fill_level_respects_saturation_and_value_minima(saturation: int, value: int) -> None:
    import cv2

    frame = make_frame()
    hsv = np.full((3, 10, 3), [0, saturation, value], dtype=np.uint8)
    x, y, w, _ = ROI
    frame[y + 41 : y + 44, x : x + w] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert make_detector()(frame).liquid_found is False


def test_fill_level_uses_first_consecutive_run() -> None:
    frame = make_frame()
    paint_liquid(frame, 10, 13)
    paint_liquid(frame, 41, 50)
    assert make_detector()(frame).liquid_top_row == 10


def test_fill_level_counts_single_row_when_configured() -> None:
    frame = make_frame()
    paint_liquid(frame, 41, 42)
    assert replace(make_detector(), min_consecutive_rows=1)(frame).liquid_top_row == 41


@pytest.mark.parametrize(("top", "expected"), [(0, 1.0), (106, 0.0)])
def test_fill_level_clamps_outside_calibration_rows(top: int, expected: float) -> None:
    frame = make_frame()
    paint_liquid(frame, top, top + 3)
    result = make_detector()(frame)
    assert result.liquid_top_row == top
    assert result.fill_fraction == expected


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"full_row": -1}, "full_row"),
        ({"full_row": 110}, "full_row"),
        ({"empty_row": 4}, "empty_row"),
        ({"empty_row": 3}, "empty_row"),
        ({"empty_row": 110}, "empty_row"),
        ({"roi": (-1, 0, 10, 110)}, "roi"),
        ({"roi": (0, 0, 0, 110)}, "roi"),
        ({"roi": (0, 0, 10.5, 110)}, "roi"),
        ({"hue_range": (-1, 25)}, "hue_range"),
        ({"hue_range": (0, 180)}, "hue_range"),
        ({"saturation_min": 256}, "saturation_min"),
        ({"value_min": -1}, "value_min"),
        ({"row_fraction": -0.1}, "row_fraction"),
        ({"row_fraction": 1.1}, "row_fraction"),
        ({"row_fraction": float("nan")}, "row_fraction"),
        ({"min_consecutive_rows": 0}, "min_consecutive_rows"),
        ({"min_consecutive_rows": 111}, "min_consecutive_rows"),
    ],
)
def test_fill_level_rejects_invalid_configuration(changes: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_detector(), **changes)


@pytest.mark.parametrize("roi", [(24, 11, 10, 110), (7, 21, 10, 110)])
def test_fill_level_rejects_roi_outside_frame(roi: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError, match="roi must be fully within"):
        replace(make_detector(), roi=roi)(make_frame())


def test_fill_level_rejects_non_bgr_frame() -> None:
    with pytest.raises(ValueError, match="frame must be a BGR image"):
        make_detector()(np.zeros((130, 25), dtype=np.uint8))


def test_fill_level_result_is_frozen_and_has_slots() -> None:
    result = make_detector()(make_frame())
    with pytest.raises(FrozenInstanceError):
        result.liquid_found = True
    assert not hasattr(result, "__dict__")


def test_fill_level_is_stateless() -> None:
    frame = make_frame()
    paint_liquid(frame, 41, 50)
    detector = make_detector()
    first = detector(frame)
    assert detector(make_frame()).liquid_found is False
    assert detector(frame) == first
