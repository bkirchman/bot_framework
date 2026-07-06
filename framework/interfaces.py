from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class StampedFrame:
    frame_id: int
    timestamp: float
    frame: Any


@dataclass(frozen=True, slots=True)
class Action:
    frame_id: int
    timestamp: float
    payload: Any


class CaptureSource(ABC):
    @abstractmethod
    def get_frame(self) -> StampedFrame:
        raise NotImplementedError

    @abstractmethod
    def flush(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def latency_frames(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def fps(self) -> float:
        raise NotImplementedError


class OutputDevice(ABC):
    @abstractmethod
    def execute(self, action: Action) -> None:
        raise NotImplementedError


class FrameProcessor(ABC):
    @abstractmethod
    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        raise NotImplementedError