from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from framework.interfaces import CaptureSource, StampedFrame


class ReplayCapture(CaptureSource):
    def __init__(
        self,
        frames_dir: str | Path,
        *,
        fps: float = 60.0,
        latency_frames: int = 0,
        loader: Optional[Callable[[Path], Any]] = None,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")

        self._frames_dir = Path(frames_dir)
        self._fps = fps
        self._latency_frames = latency_frames
        self._loader = loader or self._default_loader
        self._frame_paths = self._discover_frame_paths(self._frames_dir)
        self._frame_id = 0
        self._started_at = time.monotonic()

    @property
    def latency_frames(self) -> int:
        return self._latency_frames

    @property
    def fps(self) -> float:
        return self._fps

    def get_frame(self) -> StampedFrame:
        if self._frame_id >= len(self._frame_paths):
            raise IndexError("ReplayCapture has no more frames")

        path = self._frame_paths[self._frame_id]
        frame = self._loader(path)
        stamped_frame = StampedFrame(
            frame_id=self._frame_id,
            timestamp=self._started_at + (self._frame_id / self._fps),
            frame=frame,
        )
        self._frame_id += 1
        return stamped_frame

    def flush(self) -> None:
        self._started_at = time.monotonic()

    @staticmethod
    def _discover_frame_paths(frames_dir: Path) -> list[Path]:
        if not frames_dir.exists():
            raise FileNotFoundError(f"Replay frames directory does not exist: {frames_dir}")
        if not frames_dir.is_dir():
            raise NotADirectoryError(f"Replay frames path is not a directory: {frames_dir}")

        frame_paths = sorted(path for path in frames_dir.iterdir() if path.is_file())
        if not frame_paths:
            raise ValueError(f"Replay frames directory is empty: {frames_dir}")
        return frame_paths

    @staticmethod
    def _default_loader(path: Path) -> Any:
        try:
            import cv2
        except ImportError:
            return path.read_bytes()

        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            return path.read_bytes()
        return frame