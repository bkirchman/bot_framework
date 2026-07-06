from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from framework.interfaces import Action, CaptureSource, OutputDevice, StampedFrame
from framework.two_phase import TwoPhaseCapture, TwoPhaseCaptureResult


FrameComparator = Callable[[Any, Any], bool]


@dataclass(frozen=True, slots=True)
class LatencyCalibrationResult:
    declared_latency_frames: int
    measured_latency_frames: Optional[int]
    impulse_reference_frame_id: Optional[int]
    detected_frame_id: Optional[int]
    baseline_frame_id: int
    captured_frame_count: int
    mismatch_warning: Optional[str]


class LatencyCalibrator:
    def __init__(
        self,
        capture: CaptureSource,
        output: OutputDevice,
        impulse_action: Action,
        *,
        frame_count: int,
        comparator: Optional[FrameComparator] = None,
        baseline_verifier: Optional[Callable[[StampedFrame], None]] = None,
    ) -> None:
        if frame_count <= 0:
            raise ValueError("frame_count must be positive")

        self._capture = capture
        self._output = output
        self._impulse_action = impulse_action
        self._frame_count = frame_count
        self._comparator = comparator or default_pixel_diff_comparator
        self._baseline_verifier = baseline_verifier

    def measure(self) -> LatencyCalibrationResult:
        capture_result = TwoPhaseCapture(self._capture).run(
            frame_count=self._frame_count,
            baseline_verifier=self._baseline_verifier,
            before_capture=self._inject_impulse,
            analysis=self._analyze,
        )
        return capture_result.analysis_result

    def _inject_impulse(self, baseline_frame: StampedFrame) -> None:
        self._output.execute(
            Action(
                frame_id=baseline_frame.frame_id,
                timestamp=baseline_frame.timestamp,
                payload=self._impulse_action.payload,
            )
        )

    def _analyze(
        self,
        baseline_frame: StampedFrame,
        captured_frames: Sequence[StampedFrame],
    ) -> LatencyCalibrationResult:
        detected_frame = self._first_detected_frame(baseline_frame, captured_frames)
        measured_latency_frames = self._measured_latency_frames(captured_frames, detected_frame)
        impulse_reference_frame_id = None
        if captured_frames:
            impulse_reference_frame_id = captured_frames[0].frame_id - 1

        mismatch_warning = self._warning_text(measured_latency_frames)
        if mismatch_warning is not None:
            warnings.warn(mismatch_warning, stacklevel=2)

        return LatencyCalibrationResult(
            declared_latency_frames=self._capture.latency_frames,
            measured_latency_frames=measured_latency_frames,
            impulse_reference_frame_id=impulse_reference_frame_id,
            detected_frame_id=None if detected_frame is None else detected_frame.frame_id,
            baseline_frame_id=baseline_frame.frame_id,
            captured_frame_count=len(captured_frames),
            mismatch_warning=mismatch_warning,
        )

    def _first_detected_frame(
        self,
        baseline_frame: StampedFrame,
        captured_frames: Sequence[StampedFrame],
    ) -> Optional[StampedFrame]:
        for candidate_frame in captured_frames:
            if self._comparator(baseline_frame.frame, candidate_frame.frame):
                return candidate_frame
        return None

    @staticmethod
    def _measured_latency_frames(
        captured_frames: Sequence[StampedFrame],
        detected_frame: Optional[StampedFrame],
    ) -> Optional[int]:
        if not captured_frames or detected_frame is None:
            return None
        return detected_frame.frame_id - captured_frames[0].frame_id + 1

    def _warning_text(self, measured_latency_frames: Optional[int]) -> Optional[str]:
        declared_latency_frames = self._capture.latency_frames
        if measured_latency_frames is None:
            return (
                "LATENCY CALIBRATION WARNING: no displacement was detected within "
                f"{self._frame_count} captured frames; declared latency_frames={declared_latency_frames}."
            )
        if measured_latency_frames != declared_latency_frames:
            return (
                "LATENCY CALIBRATION WARNING: measured latency_frames="
                f"{measured_latency_frames} does not match declared latency_frames={declared_latency_frames}."
            )
        return None


def default_pixel_diff_comparator(
    baseline_frame: Any,
    candidate_frame: Any,
    *,
    changed_pixel_threshold: int = 1000,
    per_pixel_delta_threshold: int = 10,
) -> bool:
    try:
        import numpy as np
    except ImportError:
        return baseline_frame != candidate_frame

    baseline_array = np.asarray(baseline_frame)
    candidate_array = np.asarray(candidate_frame)
    if baseline_array.shape != candidate_array.shape:
        return True

    delta = np.abs(candidate_array.astype(np.int16) - baseline_array.astype(np.int16))
    if delta.ndim >= 3:
        delta = delta.max(axis=-1)

    changed_pixels = int(np.count_nonzero(delta > per_pixel_delta_threshold))
    return changed_pixels >= changed_pixel_threshold