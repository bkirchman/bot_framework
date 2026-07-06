from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping, Optional

from framework.interfaces import Action, CaptureSource, FrameProcessor, OutputDevice, StampedFrame
from framework.temporal import FrameHistory


class BotLoop:
    def __init__(
        self,
        capture: CaptureSource,
        output: OutputDevice,
        processor: FrameProcessor,
        history: FrameHistory,
        services: Optional[Mapping[str, Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.capture = capture
        self.output = output
        self.processor = processor
        self.history = history
        self._base_services = dict(services or {})
        self._clock = clock
        self._sleeper = sleeper
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            raise RuntimeError("BotLoop is already running")

        self.capture.flush()
        self._running = True

    def stop(self) -> None:
        self._running = False

    def step(self) -> tuple[StampedFrame, Optional[Action]]:
        if not self._running:
            raise RuntimeError("BotLoop must be started before stepping")

        frame = self.capture.get_frame()
        services = self._build_services()
        action = self.processor.process(frame, services)

        if action is not None:
            self.output.execute(action)

        self.history.record(frame, action)
        return frame, action

    def run(self, max_iterations: Optional[int] = None) -> int:
        if max_iterations is not None and max_iterations < 0:
            raise ValueError("max_iterations must be non-negative or None")

        self.start()
        iterations = 0
        target_period = self._target_period_seconds()
        next_tick = self._clock()

        try:
            while self._running:
                self.step()
                iterations += 1

                if max_iterations is not None and iterations >= max_iterations:
                    break

                if target_period is None:
                    continue

                next_tick += target_period
                remaining = next_tick - self._clock()
                if remaining > 0:
                    self._sleeper(remaining)
                else:
                    next_tick = self._clock()
        finally:
            self.stop()

        return iterations

    def _build_services(self) -> Dict[str, Any]:
        services = dict(self._base_services)
        services.setdefault("capture", self.capture)
        services.setdefault("output", self.output)
        services.setdefault("history", self.history)
        services.setdefault("loop", self)
        return services

    def _target_period_seconds(self) -> Optional[float]:
        if self.capture.fps <= 0:
            return None
        return 1.0 / self.capture.fps