from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Optional

from framework.interfaces import Action, StampedFrame

from .registries import CommandRegistry, DetectorRegistry
from .schema import BranchStep, CallStep, CommandStep, LoopDefinition, RepeatStep, Step, WaitStep, WaitVisualStep


InterpreterStatus = Literal["running", "completed", "aborted"]


@dataclass(slots=True)
class ExecutionFrame:
    steps: list[Step]
    position: int = 0
    path_prefix: tuple[str, ...] = ()
    step_state: dict[int, dict[str, Any]] = field(default_factory=dict)


class LoopInterpreter:
    def __init__(
        self,
        loop_definitions: Mapping[str, LoopDefinition],
        command_registry: CommandRegistry,
        detector_registry: DetectorRegistry,
        loop_name: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        try:
            root_definition = loop_definitions[loop_name]
        except KeyError as exc:
            raise KeyError(f"Unknown loop definition: {loop_name}") from exc

        self._loop_definitions = dict(loop_definitions)
        self._command_registry = command_registry
        self._detector_registry = detector_registry
        self._clock = clock
        self._status: InterpreterStatus = "running"
        self._abort_reason: str | None = None
        self._last_command_frame_id: int | None = None
        self._stack: list[ExecutionFrame] = [ExecutionFrame(steps=root_definition.steps, path_prefix=(loop_name,))]

    @property
    def status(self) -> InterpreterStatus:
        return self._status

    @property
    def abort_reason(self) -> str | None:
        return self._abort_reason

    @property
    def current_step_path(self) -> tuple[str, ...]:
        self._trim_completed_frames()
        if self._status != "running" or not self._stack:
            return ()

        frame = self._stack[-1]
        if frame.position >= len(frame.steps):
            return frame.path_prefix
        return frame.path_prefix + (str(frame.position),)

    def tick(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        self._trim_completed_frames()
        if self._status != "running":
            return None
        if not self._stack:
            self._status = "completed"
            return None

        execution_frame = self._stack[-1]
        step = execution_frame.steps[execution_frame.position]

        if isinstance(step, CommandStep):
            return self._tick_command_step(execution_frame, step, frame)
        if isinstance(step, WaitStep):
            return self._tick_wait_step(execution_frame, step)
        if isinstance(step, WaitVisualStep):
            return self._tick_wait_visual_step(execution_frame, step, frame, services)
        if isinstance(step, BranchStep):
            return self._tick_branch_step(execution_frame, step, frame, services)
        if isinstance(step, RepeatStep):
            return self._tick_repeat_step(execution_frame, step, frame, services)
        if isinstance(step, CallStep):
            return self._tick_call_step(execution_frame, step)

        raise TypeError(f"Unsupported step type: {type(step).__name__}")

    def _tick_command_step(
        self,
        execution_frame: ExecutionFrame,
        step: CommandStep,
        frame: StampedFrame,
    ) -> Action:
        payload = self._command_registry.get(step.command)()
        self._last_command_frame_id = frame.frame_id
        self._advance(execution_frame)
        return Action(frame_id=frame.frame_id, timestamp=frame.timestamp, payload=payload)

    def _tick_wait_step(
        self,
        execution_frame: ExecutionFrame,
        step: WaitStep,
    ) -> None:
        state = execution_frame.step_state.setdefault(execution_frame.position, {})
        deadline = state.setdefault("deadline", self._clock() + step.seconds)
        if self._clock() >= deadline:
            self._advance(execution_frame)
        return None

    def _tick_wait_visual_step(
        self,
        execution_frame: ExecutionFrame,
        step: WaitVisualStep,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> None:
        if self._is_latency_gated(frame, services):
            return None

        state = execution_frame.step_state.setdefault(execution_frame.position, {})
        deadline = state.setdefault("deadline", self._clock() + step.timeout_seconds)
        detector = self._detector_registry.get(step.detector)
        if detector(frame.frame):
            self._advance(execution_frame)
            return None

        if self._clock() < deadline:
            return None

        if step.on_timeout == "abort":
            self._abort(f"WaitVisualStep timed out for detector '{step.detector}'")
            return None
        if step.on_timeout == "continue":
            self._advance(execution_frame)
            return None

        fallback_steps = step.on_timeout
        self._advance(execution_frame)
        self._push_steps(fallback_steps, execution_frame.path_prefix + (str(execution_frame.position - 1), "timeout"))
        return None

    def _tick_branch_step(
        self,
        execution_frame: ExecutionFrame,
        step: BranchStep,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> None:
        if self._is_latency_gated(frame, services):
            return None

        condition = self._detector_registry.get(step.condition)
        condition_result = condition(frame.frame)
        branch_steps = step.then_steps if condition_result else step.else_steps
        branch_label = "then" if condition_result else "else"
        self._advance(execution_frame)
        self._push_steps(branch_steps, execution_frame.path_prefix + (str(execution_frame.position - 1), branch_label))
        return None

    def _tick_repeat_step(
        self,
        execution_frame: ExecutionFrame,
        step: RepeatStep,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> None:
        state = execution_frame.step_state.setdefault(execution_frame.position, {})

        if step.count is not None:
            remaining = state.setdefault("remaining", step.count)
            if remaining <= 0:
                self._advance(execution_frame)
                return None

            state["remaining"] = remaining - 1
            self._push_steps(step.steps, execution_frame.path_prefix + (str(execution_frame.position), "repeat"))
            return None

        if self._is_latency_gated(frame, services):
            return None

        condition = self._detector_registry.get(step.while_condition or "")
        if not condition(frame.frame):
            self._advance(execution_frame)
            return None

        self._push_steps(step.steps, execution_frame.path_prefix + (str(execution_frame.position), "repeat"))
        return None

    def _tick_call_step(
        self,
        execution_frame: ExecutionFrame,
        step: CallStep,
    ) -> None:
        try:
            called_loop = self._loop_definitions[step.loop_name]
        except KeyError as exc:
            raise KeyError(f"Unknown loop definition: {step.loop_name}") from exc

        self._advance(execution_frame)
        self._push_steps(called_loop.steps, execution_frame.path_prefix + (str(execution_frame.position - 1), step.loop_name))
        return None

    def _advance(self, execution_frame: ExecutionFrame) -> None:
        execution_frame.step_state.pop(execution_frame.position, None)
        execution_frame.position += 1
        self._trim_completed_frames()

    def _push_steps(self, steps: list[Step], path_prefix: tuple[str, ...]) -> None:
        self._stack.append(ExecutionFrame(steps=steps, path_prefix=path_prefix))
        if self._status == "completed":
            self._status = "running"
        self._trim_completed_frames()

    def _trim_completed_frames(self) -> None:
        while self._stack and self._stack[-1].position >= len(self._stack[-1].steps):
            self._stack.pop()
        if not self._stack and self._status == "running":
            self._status = "completed"

    def _is_latency_gated(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> bool:
        if self._last_command_frame_id is None:
            return False

        capture = services.get("capture")
        latency_frames = getattr(capture, "latency_frames", 0)
        return (frame.frame_id - self._last_command_frame_id) < latency_frames

    def _abort(self, reason: str) -> None:
        self._stack.clear()
        self._status = "aborted"
        self._abort_reason = reason