from __future__ import annotations

import time
import warnings
from collections import deque
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
        achieved_rate_window_ticks: int = 120,
        achieved_rate_tolerance_fraction: float = 0.10,
        achieved_rate_warning_interval_seconds: float = 5.0,
    ) -> None:
        if achieved_rate_window_ticks < 2:
            raise ValueError("achieved_rate_window_ticks must be at least 2")
        if achieved_rate_tolerance_fraction < 0:
            raise ValueError("achieved_rate_tolerance_fraction must be non-negative")
        if achieved_rate_warning_interval_seconds <= 0:
            raise ValueError("achieved_rate_warning_interval_seconds must be positive")

        self.capture = capture
        self.output = output
        self.processor = processor
        self.history = history
        self._base_services = dict(services or {})
        self._clock = clock
        self._sleeper = sleeper
        self._running = False
        self._achieved_rate_window_ticks = achieved_rate_window_ticks
        self._achieved_rate_tolerance_fraction = achieved_rate_tolerance_fraction
        self._achieved_rate_warning_interval_seconds = achieved_rate_warning_interval_seconds
        self._tick_timestamps: deque[float] = deque(maxlen=self._achieved_rate_window_ticks)
        self._last_rate_warning_at: float | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def achieved_fps(self) -> float | None:
        if len(self._tick_timestamps) < 2:
            return None
        elapsed = self._tick_timestamps[-1] - self._tick_timestamps[0]
        if elapsed <= 0:
            return None
        return (len(self._tick_timestamps) - 1) / elapsed

    def start(self) -> None:
        if self._running:
            raise RuntimeError("BotLoop is already running")

        self.capture.flush()
        self._running = True

    def stop(self) -> None:
        self._warn_if_rate_diverges(now=self._clock(), force=True)
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
        self._tick_timestamps.append(self._clock())
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

                self._warn_if_rate_diverges(now=self._clock(), force=False)

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

    def _warn_if_rate_diverges(self, *, now: float, force: bool) -> None:
        target_fps = self.capture.fps
        if target_fps <= 0:
            return

        achieved_fps = self.achieved_fps
        if achieved_fps is None:
            return

        divergence_fraction = abs(achieved_fps - target_fps) / target_fps
        if divergence_fraction <= self._achieved_rate_tolerance_fraction:
            return

        if not force:
            if self._last_rate_warning_at is not None:
                elapsed = now - self._last_rate_warning_at
                if elapsed < self._achieved_rate_warning_interval_seconds:
                    return

        self._last_rate_warning_at = now
        warnings.warn(
            (
                "BOT LOOP RATE WARNING: achieved_fps="
                f"{achieved_fps:.2f} diverges from target_fps={target_fps:.2f} "
                f"beyond tolerance={self._achieved_rate_tolerance_fraction:.3f}"
            ),
            RuntimeWarning,
            stacklevel=2,
        )