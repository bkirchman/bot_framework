from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.interfaces import Action, StampedFrame


class FrameRecorder:
    def __init__(self, output_dir: str | Path, every_n: int = 1, jpeg_quality: int = 90) -> None:
        if every_n <= 0:
            raise ValueError("every_n must be positive")
        if jpeg_quality < 1 or jpeg_quality > 100:
            raise ValueError("jpeg_quality must be between 1 and 100")

        self._output_dir = Path(output_dir)
        self._frames_dir = self._output_dir / "frames"
        self._every_n = every_n
        self._jpeg_quality = jpeg_quality

        self._frames_dir.mkdir(parents=True, exist_ok=True)
        self._actions_path = self._output_dir / "actions.jsonl"
        self._actions_handle = self._actions_path.open("a", encoding="utf-8")

    @property
    def frames_dir(self) -> Path:
        return self._frames_dir

    @property
    def actions_path(self) -> Path:
        return self._actions_path

    def record(self, frame: StampedFrame, action: Action | None) -> None:
        if frame.frame_id % self._every_n == 0:
            self._write_frame_jpeg(frame)

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
        self._actions_handle.flush()
        self._actions_handle.close()

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
