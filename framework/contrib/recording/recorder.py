from __future__ import annotations

import copy
import json
import queue
import threading
import warnings
from pathlib import Path
from typing import Any

from framework.interfaces import Action, StampedFrame


class FrameRecorder:
    def __init__(
        self,
        output_dir: str | Path,
        every_n: int = 1,
        jpeg_quality: int = 90,
        max_queue_size: int = 128,
    ) -> None:
        if every_n <= 0:
            raise ValueError("every_n must be positive")
        if jpeg_quality < 1 or jpeg_quality > 100:
            raise ValueError("jpeg_quality must be between 1 and 100")
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")

        self._output_dir = Path(output_dir)
        self._frames_dir = self._output_dir / "frames"
        self._every_n = every_n
        self._jpeg_quality = jpeg_quality
        self._max_queue_size = max_queue_size

        self._frames_dir.mkdir(parents=True, exist_ok=True)
        self._actions_path = self._output_dir / "actions.jsonl"
        self._actions_handle = self._actions_path.open("a", encoding="utf-8")

        self._frame_queue: queue.Queue[StampedFrame | None] = queue.Queue(maxsize=self._max_queue_size)
        self._dropped_frames = 0
        self._written_frames = 0
        self._closed = False
        self._worker_error: Exception | None = None
        self._worker = threading.Thread(
            target=self._worker_main,
            name="FrameRecorderWorker",
            daemon=True,
        )
        self._worker.start()

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    @property
    def actions_path(self) -> Path:
        return self._actions_path

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def written_frames(self) -> int:
        return self._written_frames

    @property
    def every_n(self) -> int:
        return self._every_n

    def record(self, frame: StampedFrame, action: Action | None) -> None:
        if self._closed:
            raise RuntimeError("FrameRecorder is closed")

        if frame.frame_id % self._every_n == 0:
            try:
                self._frame_queue.put_nowait(_copy_frame_for_async_write(frame))
            except queue.Full:
                self._dropped_frames += 1

        action_payload: Any = None
        if action is not None:
            action_payload = action.payload

        line = {
            "frame_id": frame.frame_id,
            "timestamp": frame.timestamp,
            "action": action_payload,
        }
        self._actions_handle.write(json.dumps(line) + "\n")

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        self._frame_queue.put(None)
        self._worker.join()
        self._actions_handle.flush()
        self._actions_handle.close()

        if self._worker_error is not None:
            raise RuntimeError("FrameRecorder worker failed") from self._worker_error

        if self._dropped_frames > 0:
            warnings.warn(
                (
                    "FrameRecorder dropped "
                    f"{self._dropped_frames} frame(s) and wrote {self._written_frames} frame(s)"
                ),
                RuntimeWarning,
                stacklevel=2,
            )

    def _write_frame_jpeg(self, frame: StampedFrame) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for FrameRecorder JPEG output") from exc

        frame_path = self._frames_dir / f"frame_{frame.frame_id:08d}.jpg"
        ok, encoded = cv2.imencode(
            ".jpg",
            frame.frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
        )
        if not ok:
            raise RuntimeError(f"Failed to encode frame {frame.frame_id} to JPEG")
        frame_path.write_bytes(encoded.tobytes())

    def _worker_main(self) -> None:
        while True:
            queued = self._frame_queue.get()
            if queued is None:
                break

            try:
                self._write_frame_jpeg(queued)
                self._written_frames += 1
            except Exception as exc:  # pragma: no cover - surfaced on close
                if self._worker_error is None:
                    self._worker_error = exc


def _copy_frame_for_async_write(frame: StampedFrame) -> StampedFrame:
    frame_data = frame.frame
    if hasattr(frame_data, "copy") and callable(frame_data.copy):
        frame_copy = frame_data.copy()
    else:
        frame_copy = copy.deepcopy(frame_data)

    return StampedFrame(
        frame_id=frame.frame_id,
        timestamp=frame.timestamp,
        frame=frame_copy,
    )
