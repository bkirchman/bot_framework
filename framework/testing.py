from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from framework.interfaces import Action, CaptureSource, OutputDevice, StampedFrame


class FakeCapture(CaptureSource):
    def __init__(
        self,
        frames: Sequence[Any],
        *,
        fps: float = 60.0,
        latency_frames: int = 0,
        timestamps: Optional[Sequence[float]] = None,
    ) -> None:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")
        if timestamps is not None and len(timestamps) != len(frames):
            raise ValueError("timestamps must match the number of frames")

        self._frames = list(frames)
        self._fps = fps
        self._latency_frames = latency_frames
        self._timestamps = list(timestamps) if timestamps is not None else None
        self._index = 0
        self.flush_count = 0

    @property
    def latency_frames(self) -> int:
        return self._latency_frames

    @property
    def fps(self) -> float:
        return self._fps

    def flush(self) -> None:
        self.flush_count += 1

    def get_frame(self) -> StampedFrame:
        if self._index >= len(self._frames):
            raise IndexError("FakeCapture has no more frames")

        frame_id = self._index
        timestamp = self._timestamp_for(frame_id)
        frame = self._frames[frame_id]
        self._index += 1
        return StampedFrame(frame_id=frame_id, timestamp=timestamp, frame=frame)

    def remaining_frames(self) -> int:
        return len(self._frames) - self._index

    def _timestamp_for(self, frame_id: int) -> float:
        if self._timestamps is not None:
            return self._timestamps[frame_id]
        if self._fps > 0:
            return frame_id / self._fps
        return float(frame_id)


class FakeOutput(OutputDevice):
    def __init__(self) -> None:
        self.executed_actions: list[Action] = []

    def execute(self, action: Action) -> None:
        self.executed_actions.append(action)

    def payloads(self) -> Iterable[Any]:
        return (action.payload for action in self.executed_actions)