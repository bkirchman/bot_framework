from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TemplateMatchDetector:
    template: Any
    roi: tuple[int, int, int, int] | None = None
    threshold: float = 0.95
    method: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        if self.roi is not None:
            x1, y1, x2, y2 = self.roi
            if x2 <= x1 or y2 <= y1:
                raise ValueError("roi must define a positive-area rectangle")

    def __call__(self, frame: Any) -> bool:
        cv2 = self._import_cv2()
        match_method = self.method if self.method is not None else cv2.TM_CCOEFF_NORMED

        frame_region = self._crop(frame)
        template_region = self.template

        result = cv2.matchTemplate(frame_region, template_region, match_method)
        _, max_value, _, _ = cv2.minMaxLoc(result)
        return float(max_value) >= self.threshold

    def _crop(self, frame: Any) -> Any:
        if self.roi is None:
            return frame
        x1, y1, x2, y2 = self.roi
        return frame[y1:y2, x1:x2]

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for TemplateMatchDetector") from exc
        return cv2