from __future__ import annotations

import warnings
from typing import Any, Mapping, Optional, Sequence

import pytest

from framework.contrib.diagnostics.latency import LatencyCalibrator
from framework.interfaces import Action, CaptureSource, OutputDevice, StampedFrame
from framework.testing import FakeCapture
from framework.two_phase import TwoPhaseCapture


class EffectFakeCapture(FakeCapture):
    def __init__(
        self,
        *,
        total_frames: int,
        effect_after_frames: int,
        latency_frames: int,
        fps: float = 60.0,
    ) -> None:
        super().__init__(
            frames=[None] * total_frames,
            fps=fps,
            latency_frames=latency_frames,
        )
        self._effect_after_frames = effect_after_frames
        self._impulse_seen = False
        self._frames_since_impulse = 0

    def inject_effect(self) -> None:
        self._impulse_seen = True
        self._frames_since_impulse = 0

    def get_frame(self) -> StampedFrame:
        stamped_frame = super().get_frame()
        effect_visible = False
        if self._impulse_seen:
            effect_visible = self._frames_since_impulse >= (self._effect_after_frames - 1)
            self._frames_since_impulse += 1

        return StampedFrame(
            frame_id=stamped_frame.frame_id,
            timestamp=stamped_frame.timestamp,
            frame={
                "effect": effect_visible,
                "frame_id": stamped_frame.frame_id,
            },
        )


class TriggerOutput(OutputDevice):
    def __init__(self, capture: EffectFakeCapture) -> None:
        self._capture = capture
        self.actions: list[Action] = []

    def execute(self, action: Action) -> None:
        self.actions.append(action)
        self._capture.inject_effect()


class LoggingCapture(CaptureSource):
    def __init__(self) -> None:
        self.events: list[str] = []
        self._frame_id = 0

    @property
    def latency_frames(self) -> int:
        return 0

    @property
    def fps(self) -> float:
        return 60.0

    def flush(self) -> None:
        self.events.append("flush")

    def get_frame(self) -> StampedFrame:
        frame = StampedFrame(
            frame_id=self._frame_id,
            timestamp=self._frame_id / self.fps,
            frame=self._frame_id,
        )
        self.events.append(f"frame:{self._frame_id}")
        self._frame_id += 1
        return frame


def test_two_phase_capture_preserves_flush_discipline_and_post_hoc_analysis() -> None:
    capture = LoggingCapture()

    def analyze(baseline: StampedFrame, captured_frames: Sequence[StampedFrame]) -> tuple[int, int]:
        capture.events.append("analysis")
        return baseline.frame_id, len(captured_frames)

    result = TwoPhaseCapture(capture).run(
        frame_count=3,
        baseline_verifier=lambda frame: capture.events.append(f"verify:{frame.frame_id}"),
        before_capture=lambda frame: capture.events.append(f"before:{frame.frame_id}"),
        analysis=analyze,
    )

    assert result.analysis_result == (0, 3)
    assert capture.events == [
        "flush",
        "frame:0",
        "verify:0",
        "flush",
        "before:0",
        "frame:1",
        "frame:2",
        "frame:3",
        "analysis",
        "flush",
    ]


def test_latency_calibrator_measures_effect_delay_from_fake_capture() -> None:
    capture = EffectFakeCapture(total_frames=12, effect_after_frames=3, latency_frames=3)
    output = TriggerOutput(capture)
    calibrator = LatencyCalibrator(
        capture,
        output,
        impulse_action=Action(frame_id=0, timestamp=0.0, payload={"trigger": 1}),
        frame_count=6,
        comparator=lambda baseline, candidate: candidate["effect"],
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = calibrator.measure()

    assert result.measured_latency_frames == 3
    assert result.declared_latency_frames == 3
    assert result.detected_frame_id == 3
    assert result.mismatch_warning is None
    assert len(output.actions) == 1
    assert not caught


def test_latency_calibrator_warns_on_declared_mismatch() -> None:
    capture = EffectFakeCapture(total_frames=12, effect_after_frames=4, latency_frames=3)
    output = TriggerOutput(capture)
    calibrator = LatencyCalibrator(
        capture,
        output,
        impulse_action=Action(frame_id=0, timestamp=0.0, payload={"trigger": 1}),
        frame_count=6,
        comparator=lambda baseline, candidate: candidate["effect"],
    )

    with pytest.warns(
        UserWarning,
        match="LATENCY CALIBRATION WARNING: measured latency_frames=4 does not match declared latency_frames=3.",
    ):
        result = calibrator.measure()

    assert result.measured_latency_frames == 4
    assert result.declared_latency_frames == 3
    assert result.mismatch_warning is not None