from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from framework.interfaces import StampedFrame


@dataclass(slots=True)
class RoiMotionDetector:
    roi: tuple[int, int, int, int]
    diff_threshold: int
    changed_fraction: float
    hysteresis_ticks: int
    _prev_crop: np.ndarray | None = field(default=None, init=False, repr=False)
    _state: bool = field(default=False, init=False, repr=False)
    _pending_state: bool | None = field(default=None, init=False, repr=False)
    _pending_count: int = field(default=0, init=False, repr=False)
    _raw_motion: bool = field(default=False, init=False, repr=False)
    _last_changed_fraction: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        x, y, w, h = self.roi
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ValueError("roi must be (x, y, w, h) with non-negative origin and positive size")
        if self.diff_threshold < 0:
            raise ValueError("diff_threshold must be non-negative")
        if not 0.0 <= self.changed_fraction <= 1.0:
            raise ValueError("changed_fraction must be between 0.0 and 1.0")
        if self.hysteresis_ticks < 1:
            raise ValueError("hysteresis_ticks must be >= 1")

    @property
    def raw_motion(self) -> bool:
        return self._raw_motion

    @property
    def last_changed_fraction(self) -> float:
        return self._last_changed_fraction

    def update(self, frame: StampedFrame) -> bool:
        crop = self._extract_roi(frame)

        if self._prev_crop is None:
            self._prev_crop = crop
            self._raw_motion = False
            self._last_changed_fraction = 0.0
            return self._state

        diff = np.abs(crop.astype(np.int16) - self._prev_crop.astype(np.int16))
        changed = diff > self.diff_threshold
        self._last_changed_fraction = float(changed.mean())
        self._raw_motion = (self._last_changed_fraction > self.changed_fraction)

        self._prev_crop = crop
        self._apply_hysteresis(self._raw_motion)
        return self._state

    def _extract_roi(self, frame: StampedFrame) -> np.ndarray:
        x, y, w, h = self.roi
        region = frame.frame[y : y + h, x : x + w]
        if region.size == 0:
            raise ValueError("roi crop is empty for the current frame")

        if region.ndim == 3:
            gray = (
                0.114 * region[..., 0].astype(np.float32)
                + 0.587 * region[..., 1].astype(np.float32)
                + 0.299 * region[..., 2].astype(np.float32)
            )
            return gray.astype(np.uint8)

        if region.ndim == 2:
            return region.astype(np.uint8)

        raise ValueError("frame must be grayscale or BGR image")

    def _apply_hysteresis(self, raw_state: bool) -> None:
        if raw_state == self._state:
            self._pending_state = None
            self._pending_count = 0
            return

        if self._pending_state != raw_state:
            self._pending_state = raw_state
            self._pending_count = 1
            return

        self._pending_count += 1
        if self._pending_count >= self.hysteresis_ticks:
            self._state = raw_state
            self._pending_state = None
            self._pending_count = 0
