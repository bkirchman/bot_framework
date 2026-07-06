from __future__ import annotations

import time
from typing import Any, Optional

from framework.interfaces import CaptureSource, StampedFrame


class AVerMediaCapture(CaptureSource):
    def __init__(
        self,
        device_index: int = 0,
        *,
        width: int = 1920,
        height: int = 1080,
        fps: float = 60.0,
        latency_frames: int = 3,
        freshness_threshold: int = 1000,
        max_read_attempts: int = 8,
    ) -> None:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")
        if fps <= 0:
            raise ValueError("fps must be positive")
        if freshness_threshold <= 0:
            raise ValueError("freshness_threshold must be positive")
        if max_read_attempts <= 0:
            raise ValueError("max_read_attempts must be positive")

        self._cv2 = self._import_cv2()
        self._device_index = device_index
        self._width = width
        self._height = height
        self._fps = fps
        self._latency_frames = latency_frames
        self._freshness_threshold = freshness_threshold
        self._max_read_attempts = max_read_attempts
        self._capture = self._open_capture()
        self._frame_id = 0
        self._last_raw_frame: Optional[Any] = None

    @property
    def latency_frames(self) -> int:
        return self._latency_frames

    @property
    def fps(self) -> float:
        return self._fps

    def get_frame(self) -> StampedFrame:
        raw_frame = self._read_fresh_frame()
        stamped_frame = StampedFrame(
            frame_id=self._frame_id,
            timestamp=time.monotonic(),
            frame=raw_frame,
        )
        self._frame_id += 1
        self._last_raw_frame = raw_frame.copy()
        return stamped_frame

    def flush(self) -> None:
        if self._last_raw_frame is None:
            self._read_raw_frame(store_as_last=True)
            return

        for _ in range(self._max_read_attempts):
            candidate = self._read_raw_frame(store_as_last=False)
            if self._count_changed_pixels(self._last_raw_frame, candidate) >= self._freshness_threshold:
                self._last_raw_frame = candidate.copy()
                return

        self._last_raw_frame = candidate.copy()

    def close(self) -> None:
        self._capture.release()

    def _open_capture(self) -> Any:
        capture = self._cv2.VideoCapture(self._device_index, self._cv2.CAP_DSHOW)
        if not capture.isOpened():
            raise RuntimeError(f"Could not open capture device {self._device_index}")

        capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        capture.set(self._cv2.CAP_PROP_FPS, self._fps)
        capture.set(self._cv2.CAP_PROP_FOURCC, self._cv2.VideoWriter_fourcc(*"MJPG"))
        return capture

    def _read_fresh_frame(self) -> Any:
        candidate = self._read_raw_frame(store_as_last=False)
        if self._last_raw_frame is None:
            return candidate

        for _ in range(self._max_read_attempts - 1):
            if self._count_changed_pixels(self._last_raw_frame, candidate) >= self._freshness_threshold:
                return candidate
            candidate = self._read_raw_frame(store_as_last=False)

        return candidate

    def _read_raw_frame(self, *, store_as_last: bool) -> Any:
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read frame from AVerMedia capture device")

        if store_as_last:
            self._last_raw_frame = frame.copy()
        return frame

    def _count_changed_pixels(self, previous_frame: Any, current_frame: Any) -> int:
        previous_gray = self._cv2.cvtColor(previous_frame, self._cv2.COLOR_BGR2GRAY)
        current_gray = self._cv2.cvtColor(current_frame, self._cv2.COLOR_BGR2GRAY)
        delta = self._cv2.absdiff(previous_gray, current_gray)
        _, thresholded = self._cv2.threshold(delta, 10, 255, self._cv2.THRESH_BINARY)
        return int(self._cv2.countNonZero(thresholded))

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV is required for AVerMediaCapture. Install opencv-python to use this adapter."
            ) from exc
        return cv2