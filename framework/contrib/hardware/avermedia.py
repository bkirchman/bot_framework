from __future__ import annotations

import time
import warnings
from typing import Any, Optional

from framework.interfaces import CaptureSource, StampedFrame


WARMUP_MEAN_THRESHOLD = 1.0


class AVerMediaCapture(CaptureSource):
    def __init__(
        self,
        device_index: int = 1,
        *,
        width: int = 1920,
        height: int = 1080,
        fps: float = 60.0,
        latency_frames: int = 6,
        backend: str = "dshow",
        buffer_size: int = 1,
        open_settle_seconds: float = 0.2,
        freshness_threshold: int = 1000,
        max_read_attempts: int = 8,
        warmup_timeout_ms: int = 3000,
    ) -> None:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")
        if fps <= 0:
            raise ValueError("fps must be positive")
        if buffer_size < 0:
            raise ValueError("buffer_size must be non-negative")
        if open_settle_seconds < 0:
            raise ValueError("open_settle_seconds must be non-negative")
        if freshness_threshold <= 0:
            raise ValueError("freshness_threshold must be positive")
        if max_read_attempts <= 0:
            raise ValueError("max_read_attempts must be positive")
        if warmup_timeout_ms < 0:
            raise ValueError("warmup_timeout_ms must be non-negative")

        self._cv2 = self._import_cv2()
        self._device_index = device_index
        self._width = width
        self._height = height
        self._fps = fps
        self._latency_frames = latency_frames
        self._backend_name = backend
        self._active_backend_name = backend
        self._buffer_size = buffer_size
        self._open_settle_seconds = open_settle_seconds
        # Keep accepting these legacy parameters for compatibility with earlier
        # adapter versions. Freshness is now determined by the blocking backend
        # read rather than pixel-diff retries in the hot path.
        self._freshness_threshold = freshness_threshold
        self._flush_grabs = max_read_attempts
        self._warmup_timeout_ms = warmup_timeout_ms
        self._warmup_completed = False
        self._warmup_frames_discarded = 0
        self._warmup_elapsed_ms = 0.0
        self._capture = self._open_capture()
        self._warmup_after_open()
        self._frame_id = 0
        self._last_raw_frame: Optional[Any] = None

    @property
    def latency_frames(self) -> int:
        return self._latency_frames

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def warmup_completed(self) -> bool:
        return self._warmup_completed

    @property
    def warmup_frames_discarded(self) -> int:
        return self._warmup_frames_discarded

    @property
    def warmup_elapsed_ms(self) -> float:
        return self._warmup_elapsed_ms

    def get_frame(self) -> StampedFrame:
        raw_frame = self._read_raw_frame(store_as_last=True)
        stamped_frame = StampedFrame(
            frame_id=self._frame_id,
            timestamp=time.monotonic(),
            frame=raw_frame,
        )
        self._frame_id += 1
        return stamped_frame

    def flush(self) -> None:
        # Drain any queued driver frames cheaply. A blocking read in get_frame()
        # is the freshness gate; flush only needs to discard buffered frames.
        for _ in range(self._flush_grabs):
            if not self._capture.grab():
                break
        self._last_raw_frame = None

    def close(self) -> None:
        self._capture.release()

    def _open_capture(self) -> Any:
        attempted_backends: list[str] = []
        for backend_name in self._candidate_backends(self._backend_name):
            attempted_backends.append(backend_name)
            capture_backend = self._resolve_backend(backend_name)
            capture = self._cv2.VideoCapture(self._device_index, capture_backend)
            if not capture.isOpened():
                capture.release()
                continue

            capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self._width)
            capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            capture.set(self._cv2.CAP_PROP_FPS, self._fps)
            capture.set(self._cv2.CAP_PROP_FOURCC, self._cv2.VideoWriter_fourcc(*"MJPG"))
            capture.set(self._cv2.CAP_PROP_BUFFERSIZE, self._buffer_size)
            if self._open_settle_seconds > 0:
                time.sleep(self._open_settle_seconds)
            self._active_backend_name = backend_name
            return capture

        attempted = ", ".join(attempted_backends)
        raise RuntimeError(
            f"Could not open capture device {self._device_index} using backends: {attempted}"
        )

    def _warmup_after_open(self) -> None:
        start = time.perf_counter()
        discarded = 0
        timeout_s = self._warmup_timeout_ms / 1000.0

        while True:
            raw_frame = self._read_raw_frame(store_as_last=False)
            discarded += 1
            elapsed_s = time.perf_counter() - start
            mean_value = float(raw_frame.mean())
            if mean_value > WARMUP_MEAN_THRESHOLD:
                self._warmup_completed = True
                self._warmup_frames_discarded = discarded
                self._warmup_elapsed_ms = elapsed_s * 1000.0
                return

            if elapsed_s >= timeout_s:
                self._warmup_completed = False
                self._warmup_frames_discarded = discarded
                self._warmup_elapsed_ms = elapsed_s * 1000.0
                warnings.warn(
                    (
                        "AVerMediaCapture warm-up timeout after "
                        f"{self._warmup_elapsed_ms:.1f} ms and "
                        f"{self._warmup_frames_discarded} discarded frames; "
                        "capture may be starting on a black screen"
                    ),
                    RuntimeWarning,
                    stacklevel=2,
                )
                return

    def _read_raw_frame(self, *, store_as_last: bool) -> Any:
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read frame from AVerMedia capture device")

        if store_as_last:
            self._last_raw_frame = frame.copy()
        return frame

    def _resolve_backend(self, backend: str) -> int:
        backend_map = {
            "any": self._cv2.CAP_ANY,
            "auto": self._cv2.CAP_ANY,
            "dshow": self._cv2.CAP_DSHOW,
            "directshow": self._cv2.CAP_DSHOW,
            "msmf": self._cv2.CAP_MSMF,
            "mediafoundation": self._cv2.CAP_MSMF,
        }
        try:
            return backend_map[backend.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported capture backend: {backend}") from exc

    def _candidate_backends(self, backend: str) -> list[str]:
        normalized = backend.lower()
        candidates = [normalized]
        if normalized == "msmf":
            candidates.extend(["dshow", "any"])
        elif normalized in {"auto", "any"}:
            candidates.append("dshow")
        return candidates

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV is required for AVerMediaCapture. Install opencv-python to use this adapter."
            ) from exc
        return cv2