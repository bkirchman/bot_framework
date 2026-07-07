from __future__ import annotations

from typing import Any

import pytest

from framework.contrib.content_loops.interpreter import LoopInterpreter
from framework.contrib.content_loops.processor import ContentLoopProcessor
from framework.contrib.content_loops.registries import CommandRegistry, DetectorRegistry
from framework.contrib.content_loops.schema import (
    BranchStep,
    CallStep,
    CommandStep,
    LoopDefinition,
    RepeatStep,
    WaitStep,
    WaitVisualStep,
)
from framework.contrib.content_loops.yaml_loader import LoopValidationError, load_loops_from_text
from framework.interfaces import Action, StampedFrame
from framework.loop import BotLoop
from framework.temporal import FrameHistory
from framework.testing import FakeCapture, FakeOutput


class MutableClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("first", lambda: {"command": "first"})
    registry.register("second", lambda: {"command": "second"})
    registry.register("collect", lambda: {"command": "collect"})
    registry.register("fallback", lambda: {"command": "fallback"})
    return registry


def _detector_registry(**detectors: Any) -> DetectorRegistry:
    registry = DetectorRegistry()
    for name, detector in detectors.items():
        registry.register(name, detector)
    return registry


def _loop(name: str, steps: list[Any]) -> dict[str, LoopDefinition]:
    return {name: LoopDefinition(name=name, steps=steps)}


def test_processor_sequences_commands_through_bot_loop() -> None:
    processor = ContentLoopProcessor(
        loop_definitions=_loop("root", [CommandStep("first"), CommandStep("second")]),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(),
        loop_name="root",
    )
    capture = FakeCapture(frames=[{"frame": 0}, {"frame": 1}], latency_frames=0)
    output = FakeOutput()
    history = FrameHistory(capacity=8)

    iterations = BotLoop(
        capture=capture,
        output=output,
        processor=processor,
        history=history,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run(max_iterations=2)

    assert iterations == 2
    assert [action.payload for action in output.executed_actions] == [
        {"command": "first"},
        {"command": "second"},
    ]
    assert processor.interpreter.status == "completed"


def test_wait_step_uses_injected_clock_without_blocking() -> None:
    clock = MutableClock()
    interpreter = LoopInterpreter(
        loop_definitions=_loop("root", [WaitStep(2.0), CommandStep("collect")]),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(),
        loop_name="root",
        clock=clock,
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    clock.advance(1.5)
    assert interpreter.tick(capture_frame(1), services) is None
    clock.advance(0.5)

    assert interpreter.tick(capture_frame(2), services) is None
    action = interpreter.tick(capture_frame(3), services)

    assert action == Action(frame_id=3, timestamp=3.0 / 60.0, payload={"command": "collect"})


def test_wait_visual_step_completes_when_detector_matches() -> None:
    clock = MutableClock()
    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [WaitVisualStep(detector="ready", timeout_seconds=5.0), CommandStep("collect")],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(ready=lambda frame: bool(frame["ready"])),
        loop_name="root",
        clock=clock,
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0, ready=False), services) is None

    assert interpreter.tick(capture_frame(1, ready=True), services) is None
    action = interpreter.tick(capture_frame(2, ready=True), services)

    assert action == Action(frame_id=2, timestamp=2.0 / 60.0, payload={"command": "collect"})


def test_wait_visual_timeout_abort_sets_aborted_status() -> None:
    clock = MutableClock()
    interpreter = LoopInterpreter(
        loop_definitions=_loop("root", [WaitVisualStep(detector="ready", timeout_seconds=1.0, on_timeout="abort")]),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(ready=lambda frame: False),
        loop_name="root",
        clock=clock,
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    clock.advance(1.1)
    assert interpreter.tick(capture_frame(1), services) is None
    assert interpreter.status == "aborted"


def test_wait_visual_timeout_continue_advances() -> None:
    clock = MutableClock()
    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [
                WaitVisualStep(detector="ready", timeout_seconds=1.0, on_timeout="continue"),
                CommandStep("collect"),
            ],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(ready=lambda frame: False),
        loop_name="root",
        clock=clock,
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    clock.advance(1.1)
    assert interpreter.tick(capture_frame(1), services) is None
    action = interpreter.tick(capture_frame(2), services)

    assert action == Action(frame_id=2, timestamp=2.0 / 60.0, payload={"command": "collect"})


def test_wait_visual_timeout_fallback_steps_run() -> None:
    clock = MutableClock()
    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [
                WaitVisualStep(
                    detector="ready",
                    timeout_seconds=1.0,
                    on_timeout=[CommandStep("fallback")],
                )
            ],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(ready=lambda frame: False),
        loop_name="root",
        clock=clock,
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    clock.advance(1.1)
    assert interpreter.tick(capture_frame(1), services) is None
    action = interpreter.tick(capture_frame(2), services)

    assert action == Action(frame_id=2, timestamp=2.0 / 60.0, payload={"command": "fallback"})


def test_branch_step_selects_then_and_else_paths() -> None:
    then_interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [BranchStep(condition="branch", then_steps=[CommandStep("first")], else_steps=[CommandStep("second")])],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(branch=lambda frame: bool(frame["take_then"])),
        loop_name="root",
    )
    else_interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [BranchStep(condition="branch", then_steps=[CommandStep("first")], else_steps=[CommandStep("second")])],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(branch=lambda frame: bool(frame["take_then"])),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert then_interpreter.tick(capture_frame(0, take_then=True), services) is None
    then_action = then_interpreter.tick(capture_frame(1, take_then=True), services)
    assert else_interpreter.tick(capture_frame(0, take_then=False), services) is None
    else_action = else_interpreter.tick(capture_frame(1, take_then=False), services)

    assert then_action == Action(frame_id=1, timestamp=1.0 / 60.0, payload={"command": "first"})
    assert else_action == Action(frame_id=1, timestamp=1.0 / 60.0, payload={"command": "second"})


def test_branch_detector_is_called_once_per_tick() -> None:
    detector_calls: list[int] = []

    def detector(frame: dict[str, Any]) -> bool:
        detector_calls.append(frame["frame_id"])
        return True

    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [BranchStep(condition="branch", then_steps=[CommandStep("first")], else_steps=[CommandStep("second")])],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(branch=detector),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    assert detector_calls == [0]


def test_repeat_step_runs_fixed_count() -> None:
    interpreter = LoopInterpreter(
        loop_definitions=_loop("root", [RepeatStep(count=3, steps=[CommandStep("collect")])]),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    first = interpreter.tick(capture_frame(1), services)
    assert interpreter.tick(capture_frame(2), services) is None
    second = interpreter.tick(capture_frame(3), services)
    assert interpreter.tick(capture_frame(4), services) is None
    third = interpreter.tick(capture_frame(5), services)

    assert [first, second, third] == [
        Action(frame_id=1, timestamp=1.0 / 60.0, payload={"command": "collect"}),
        Action(frame_id=3, timestamp=3.0 / 60.0, payload={"command": "collect"}),
        Action(frame_id=5, timestamp=5.0 / 60.0, payload={"command": "collect"}),
    ]
    assert interpreter.status == "running"
    assert interpreter.tick(capture_frame(6), services) is None
    assert interpreter.status == "completed"


def test_call_step_composes_nested_loops() -> None:
    loop_definitions = {
        "child": LoopDefinition(name="child", steps=[CommandStep("collect")]),
        "root": LoopDefinition(name="root", steps=[CallStep("child")]),
    }
    interpreter = LoopInterpreter(
        loop_definitions=loop_definitions,
        command_registry=_command_registry(),
        detector_registry=_detector_registry(),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=0)}

    assert interpreter.tick(capture_frame(0), services) is None
    action = interpreter.tick(capture_frame(1), services)

    assert action == Action(frame_id=1, timestamp=1.0 / 60.0, payload={"command": "collect"})


def test_latency_gate_blocks_visual_checks_until_capture_latency_elapses() -> None:
    detector_calls: list[int] = []

    def detector(frame: dict[str, Any]) -> bool:
        detector_calls.append(frame["frame_id"])
        return True

    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [CommandStep("first"), WaitVisualStep(detector="ready", timeout_seconds=5.0), CommandStep("collect")],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(ready=detector),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=2)}

    first_action = interpreter.tick(capture_frame(0), services)
    assert first_action is not None
    assert interpreter.tick(capture_frame(1), services) is None
    assert detector_calls == []

    assert interpreter.tick(capture_frame(2), services) is None
    assert detector_calls == [2]

    second_action = interpreter.tick(capture_frame(3), services)
    assert second_action == Action(frame_id=3, timestamp=3.0 / 60.0, payload={"command": "collect"})


def test_repeat_while_condition_is_not_evaluated_during_latency_gate() -> None:
    detector_calls: list[int] = []

    def while_detector(frame: dict[str, Any]) -> bool:
        detector_calls.append(frame["frame_id"])
        return frame["frame_id"] < 4

    interpreter = LoopInterpreter(
        loop_definitions=_loop(
            "root",
            [
                RepeatStep(
                    while_condition="repeat_ready",
                    steps=[CommandStep("first")],
                ),
                CommandStep("collect"),
            ],
        ),
        command_registry=_command_registry(),
        detector_registry=_detector_registry(repeat_ready=while_detector),
        loop_name="root",
    )
    services = {"capture": FakeCapture(frames=[0], latency_frames=2)}

    assert interpreter.tick(capture_frame(0), services) is None
    assert detector_calls == [0]

    first_action = interpreter.tick(capture_frame(1), services)
    assert first_action == Action(frame_id=1, timestamp=1.0 / 60.0, payload={"command": "first"})

    assert interpreter.tick(capture_frame(2), services) is None
    assert detector_calls == [0]

    assert interpreter.tick(capture_frame(3), services) is None
    assert detector_calls == [0, 3]


def test_yaml_loader_parses_nested_loop_definitions() -> None:
    loaded = load_loops_from_text(
        """
loops:
  skill_and_collect:
    steps:
      - command: first
      - wait: 2.0
      - wait_visual:
          detector: ready
          timeout: 10.0
          on_timeout: continue
      - command: collect
  farm_session:
    steps:
      - repeat:
          count: 2
          steps:
            - call: skill_and_collect
      - branch:
          condition: choose
          then:
            - command: second
          else:
            - command: collect
"""
    )

    assert set(loaded) == {"skill_and_collect", "farm_session"}
    assert isinstance(loaded["skill_and_collect"].steps[0], CommandStep)
    assert isinstance(loaded["skill_and_collect"].steps[1], WaitStep)
    assert isinstance(loaded["skill_and_collect"].steps[2], WaitVisualStep)
    assert isinstance(loaded["farm_session"].steps[0], RepeatStep)
    assert isinstance(loaded["farm_session"].steps[1], BranchStep)


def test_yaml_loader_rejects_unknown_step_and_bad_references() -> None:
    with pytest.raises(LoopValidationError, match="unknown step type"):
        load_loops_from_text(
            """
loops:
  root:
    steps:
      - mystery: value
"""
        )

    with pytest.raises(LoopValidationError, match="wait_visual.detector"):
        load_loops_from_text(
            """
loops:
  root:
    steps:
      - wait_visual:
          timeout: 1.0
"""
        )

    with pytest.raises(LoopValidationError, match="unknown loop 'missing'"):
        load_loops_from_text(
            """
loops:
  root:
    steps:
      - call: missing
"""
        )

        with pytest.raises(LoopValidationError, match="requires exactly one of count or while"):
                load_loops_from_text(
                        """
loops:
    root:
        steps:
            - repeat:
                    steps:
                        - command: first
"""
                )

        with pytest.raises(LoopValidationError, match="cannot define both count and while"):
                load_loops_from_text(
                        """
loops:
    root:
        steps:
            - repeat:
                    count: 2
                    while: repeat_ready
                    steps:
                        - command: first
"""
                )


def capture_frame(frame_id: int, **payload: Any) -> StampedFrame:
    data = {"frame_id": frame_id}
    data.update(payload)
    return StampedFrame(
        frame_id=frame_id,
        timestamp=frame_id / 60.0,
        frame=data,
    )