from __future__ import annotations

from typing import Any, Mapping, Optional

from framework.interfaces import Action, FrameProcessor, StampedFrame
from framework.loop import BotLoop
from framework.temporal import FrameHistory
from framework.testing import FakeCapture, FakeOutput


class EveryFrameProcessor(FrameProcessor):
    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        return Action(
            frame_id=frame.frame_id,
            timestamp=frame.timestamp,
            payload={"seen": frame.frame},
        )


class EvenFrameProcessor(FrameProcessor):
    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        if frame.frame_id % 2:
            return None

        return Action(
            frame_id=frame.frame_id,
            timestamp=frame.timestamp,
            payload=frame.frame,
        )


class CapturingProcessor(FrameProcessor):
    def __init__(self) -> None:
        self.last_services: Mapping[str, Any] | None = None

    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        self.last_services = dict(services)
        return None


def test_loop_records_monotonic_stamps_and_all_pairs() -> None:
    capture = FakeCapture(
        frames=["f0", "f1", "f2", "f3"],
        timestamps=[1.0, 1.1, 1.2, 1.3],
        fps=60.0,
        latency_frames=2,
    )
    output = FakeOutput()
    history = FrameHistory(capacity=8)
    loop = BotLoop(
        capture=capture,
        output=output,
        processor=EvenFrameProcessor(),
        history=history,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    iterations = loop.run(max_iterations=4)

    assert iterations == 4
    assert not loop.is_running
    assert capture.flush_count == 1
    assert len(history) == 4

    frame_ids = [record.frame.frame_id for record in history]
    timestamps = [record.frame.timestamp for record in history]

    assert frame_ids == [0, 1, 2, 3]
    assert timestamps == [1.0, 1.1, 1.2, 1.3]
    assert frame_ids == sorted(frame_ids)
    assert timestamps == sorted(timestamps)

    assert history.get_action(0) is not None
    assert history.get_action(1) is None
    assert history.get_action(2) is not None
    assert history.get_action(3) is None

    assert [action.frame_id for action in output.executed_actions] == [0, 2]


def test_history_pairs_actions_with_delayed_frames_using_capture_latency() -> None:
    frames = ["f0", "f1", "f2", "f3", "f4", "f5"]
    capture = FakeCapture(
        frames=frames,
        fps=60.0,
        latency_frames=3,
    )
    output = FakeOutput()
    history = FrameHistory(capacity=16)
    loop = BotLoop(
        capture=capture,
        output=output,
        processor=EveryFrameProcessor(),
        history=history,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    loop.run(max_iterations=len(frames))

    observed_frames = [
        history.get_delayed_frame_for_action(action, capture.latency_frames)
        for action in output.executed_actions[:3]
    ]

    assert [frame.frame_id if frame is not None else None for frame in observed_frames] == [3, 4, 5]
    assert [frame.frame if frame is not None else None for frame in observed_frames] == ["f3", "f4", "f5"]
    assert history.get_delayed_frame_for_action(output.executed_actions[3], capture.latency_frames) is None


def test_loop_passes_core_services_to_processor() -> None:
    capture = FakeCapture(
        frames=["f0"],
        fps=60.0,
        latency_frames=2,
    )
    output = FakeOutput()
    history = FrameHistory(capacity=4)
    processor = CapturingProcessor()
    loop = BotLoop(
        capture=capture,
        output=output,
        processor=processor,
        history=history,
        services={"custom": "value"},
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    loop.run(max_iterations=1)

    assert processor.last_services is not None
    assert processor.last_services["capture"] is capture
    assert processor.last_services["output"] is output
    assert processor.last_services["history"] is history
    assert processor.last_services["loop"] is loop
    assert processor.last_services["custom"] == "value"