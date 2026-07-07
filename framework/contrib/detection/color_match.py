from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ColorMatchDetector:
    hue_range: tuple[int, int]
    saturation_min: int
    value_min: int
    pixel_threshold: int
    roi: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        hue_start, hue_end = self.hue_range
        if not (0 <= hue_start <= 179 and 0 <= hue_end <= 179):
            raise ValueError("hue_range values must be in [0, 179]")
        if not (0 <= self.saturation_min <= 255):
            raise ValueError("saturation_min must be in [0, 255]")
        if not (0 <= self.value_min <= 255):
            raise ValueError("value_min must be in [0, 255]")
        if self.pixel_threshold < 0:
            raise ValueError("pixel_threshold must be non-negative")
        if self.roi is not None:
            x, y, w, h = self.roi
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                raise ValueError("roi must be (x, y, w, h) with non-negative origin and positive size")

    def __call__(self, frame: Any) -> bool:
        return self.matched_pixel_count(frame) >= self.pixel_threshold

    def matched_pixel_count(self, frame: Any) -> int:
        cv2 = self._import_cv2()

        region = self._crop(frame)
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        mask = self._hue_mask(cv2, hsv)
        return int(cv2.countNonZero(mask))

    def _crop(self, frame: Any) -> Any:
        if self.roi is None:
            return frame
        x, y, w, h = self.roi
        return frame[y : y + h, x : x + w]

    def _hue_mask(self, cv2: Any, hsv_frame: Any) -> Any:
        import numpy as np

        hue_start, hue_end = self.hue_range
        lower_sv = np.array([0, self.saturation_min, self.value_min], dtype=np.uint8)
        upper_sv = np.array([0, 255, 255], dtype=np.uint8)

        if hue_start <= hue_end:
            lower = lower_sv.copy()
            upper = upper_sv.copy()
            lower[0] = hue_start
            upper[0] = hue_end
            return cv2.inRange(hsv_frame, lower, upper)

        # Wrap case, e.g. (170, 10): [170..179] U [0..10]
        lower_a = lower_sv.copy()
        upper_a = upper_sv.copy()
        lower_a[0] = hue_start
        upper_a[0] = 179

        lower_b = lower_sv.copy()
        upper_b = upper_sv.copy()
        lower_b[0] = 0
        upper_b[0] = hue_end

        mask_a = cv2.inRange(hsv_frame, lower_a, upper_a)
        mask_b = cv2.inRange(hsv_frame, lower_b, upper_b)
        return cv2.bitwise_or(mask_a, mask_b)

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for ColorMatchDetector") from exc
        return cv2