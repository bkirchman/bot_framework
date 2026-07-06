from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, Optional

from framework.interfaces import Action, StampedFrame


@dataclass(frozen=True, slots=True)
class FrameRecord:
    frame: StampedFrame
    action: Optional[Action]


class FrameHistory:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self._capacity = capacity
        self._records: Deque[FrameRecord] = deque()
        self._records_by_frame_id: Dict[int, FrameRecord] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterable[FrameRecord]:
        return iter(self._records)

    def record(self, frame: StampedFrame, action: Optional[Action]) -> None:
        record = FrameRecord(frame=frame, action=action)
        self._records.append(record)
        self._records_by_frame_id[frame.frame_id] = record

        if len(self._records) > self._capacity:
            evicted = self._records.popleft()
            self._records_by_frame_id.pop(evicted.frame.frame_id, None)

    def get_record(self, frame_id: int) -> Optional[FrameRecord]:
        return self._records_by_frame_id.get(frame_id)

    def get_frame(self, frame_id: int) -> Optional[StampedFrame]:
        record = self.get_record(frame_id)
        if record is None:
            return None
        return record.frame

    def get_action(self, frame_id: int) -> Optional[Action]:
        record = self.get_record(frame_id)
        if record is None:
            return None
        return record.action

    def get_delayed_frame(
        self,
        action_frame_id: int,
        latency_frames: int,
    ) -> Optional[StampedFrame]:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")

        return self.get_frame(action_frame_id + latency_frames)

    def get_delayed_frame_for_action(
        self,
        action: Action,
        latency_frames: int,
    ) -> Optional[StampedFrame]:
        return self.get_delayed_frame(
            action_frame_id=action.frame_id,
            latency_frames=latency_frames,
        )