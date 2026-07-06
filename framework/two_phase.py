from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Optional, Sequence, TypeVar

from framework.interfaces import CaptureSource, StampedFrame


AnalysisResultT = TypeVar("AnalysisResultT")


@dataclass(frozen=True, slots=True)
class TwoPhaseCaptureResult(Generic[AnalysisResultT]):
    baseline_frame: StampedFrame
    captured_frames: tuple[StampedFrame, ...]
    analysis_result: AnalysisResultT


class TwoPhaseCapture:
    def __init__(self, capture: CaptureSource) -> None:
        self._capture = capture

    def run(
        self,
        *,
        frame_count: int,
        analysis: Callable[[StampedFrame, Sequence[StampedFrame]], AnalysisResultT],
        baseline_verifier: Optional[Callable[[StampedFrame], None]] = None,
        before_capture: Optional[Callable[[StampedFrame], None]] = None,
    ) -> TwoPhaseCaptureResult[AnalysisResultT]:
        if frame_count <= 0:
            raise ValueError("frame_count must be positive")

        self._capture.flush()
        baseline_frame = self._capture.get_frame()

        if baseline_verifier is not None:
            baseline_verifier(baseline_frame)

        self._capture.flush()

        if before_capture is not None:
            before_capture(baseline_frame)

        captured_frames = tuple(self._capture.get_frame() for _ in range(frame_count))
        analysis_result = analysis(baseline_frame, captured_frames)

        self._capture.flush()

        return TwoPhaseCaptureResult(
            baseline_frame=baseline_frame,
            captured_frames=captured_frames,
            analysis_result=analysis_result,
        )