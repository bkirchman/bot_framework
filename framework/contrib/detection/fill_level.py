from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .color_match import _hue_mask


@dataclass(frozen=True, slots=True)
class FillLevelResult:
    liquid_found: bool
    liquid_top_row: int | None
    fill_fraction: float | None
    liquid_top_y: int | None


@dataclass(frozen=True, slots=True)
class FillLevelDetector:
    roi: tuple[int, int, int, int]
    hue_range: tuple[int, int]
    saturation_min: int
    value_min: int
    row_fraction: float
    min_consecutive_rows: int
    full_row: int
    empty_row: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.roi, tuple)
            or len(self.roi) != 4
            or any(not isinstance(value, int) or isinstance(value, bool) for value in self.roi)
        ):
            raise ValueError("roi must be (x, y, w, h) with integer values")
        x, y, w, h = self.roi
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ValueError("roi must be (x, y, w, h) with non-negative origin and positive size")
        if (
            not isinstance(self.hue_range, tuple)
            or len(self.hue_range) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 179
                for value in self.hue_range
            )
        ):
            raise ValueError("hue_range must contain two integer values in [0, 179]")
        if (
            not isinstance(self.saturation_min, int)
            or isinstance(self.saturation_min, bool)
            or not 0 <= self.saturation_min <= 255
        ):
            raise ValueError("saturation_min must be an integer in [0, 255]")
        if (
            not isinstance(self.value_min, int)
            or isinstance(self.value_min, bool)
            or not 0 <= self.value_min <= 255
        ):
            raise ValueError("value_min must be an integer in [0, 255]")
        if (
            not isinstance(self.row_fraction, (int, float))
            or isinstance(self.row_fraction, bool)
            or not 0.0 <= self.row_fraction <= 1.0
        ):
            raise ValueError("row_fraction must be between 0.0 and 1.0")
        if (
            not isinstance(self.min_consecutive_rows, int)
            or isinstance(self.min_consecutive_rows, bool)
            or not 1 <= self.min_consecutive_rows <= h
        ):
            raise ValueError("min_consecutive_rows must be an integer between 1 and ROI height")
        if (
            not isinstance(self.full_row, int)
            or isinstance(self.full_row, bool)
            or not 0 <= self.full_row < h
        ):
            raise ValueError("full_row must be an integer within the ROI")
        if (
            not isinstance(self.empty_row, int)
            or isinstance(self.empty_row, bool)
            or not self.full_row < self.empty_row < h
        ):
            raise ValueError("empty_row must be within the ROI and greater than full_row")

    def __call__(self, frame: Any) -> FillLevelResult:
        x, y, w, h = self.roi
        if not hasattr(frame, "shape") or len(frame.shape) != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a BGR image")
        if y + h > frame.shape[0] or x + w > frame.shape[1]:
            raise ValueError("roi must be fully within the current frame")

        cv2 = self._import_cv2()
        region = frame[y : y + h, x : x + w]
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        mask = _hue_mask(cv2, hsv, self.hue_range, self.saturation_min, self.value_min)
        liquid_rows = np.count_nonzero(mask, axis=1) / w > self.row_fraction

        run = 0
        for row, is_liquid in enumerate(liquid_rows):
            run = run + 1 if is_liquid else 0
            if run == self.min_consecutive_rows:
                top = row - run + 1
                fraction = (self.empty_row - top) / (self.empty_row - self.full_row)
                return FillLevelResult(True, top, max(0.0, min(1.0, fraction)), y + top)
        return FillLevelResult(False, None, None, None)

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for FillLevelDetector") from exc
        return cv2
