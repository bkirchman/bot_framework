from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .schema import BranchStep, CallStep, CommandStep, LoopDefinition, RepeatStep, Step, WaitStep, WaitVisualStep


class LoopValidationError(ValueError):
    pass


def load_loops_from_file(path: str | Path) -> dict[str, LoopDefinition]:
    file_path = Path(path)
    return load_loops_from_text(file_path.read_text(encoding="utf-8"))


def load_loops_from_text(text: str) -> dict[str, LoopDefinition]:
    data = _load_yaml(text)
    if not isinstance(data, Mapping):
        raise LoopValidationError("Root YAML document must be a mapping")

    raw_loops = data.get("loops")
    if not isinstance(raw_loops, Mapping):
        raise LoopValidationError("YAML document must define a 'loops' mapping")

    loop_definitions: dict[str, LoopDefinition] = {}
    for loop_name, raw_definition in raw_loops.items():
        if not isinstance(loop_name, str) or not loop_name:
            raise LoopValidationError("Loop names must be non-empty strings")
        loop_definitions[loop_name] = _parse_loop_definition(loop_name, raw_definition)

    _validate_call_targets(loop_definitions)
    return loop_definitions


def _load_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load content loops from YAML") from exc

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LoopValidationError(f"Invalid YAML: {exc}") from exc


def _parse_loop_definition(loop_name: str, raw_definition: Any) -> LoopDefinition:
    if not isinstance(raw_definition, Mapping):
        raise LoopValidationError(f"Loop '{loop_name}' must be a mapping")

    raw_steps = raw_definition.get("steps")
    if not isinstance(raw_steps, list):
        raise LoopValidationError(f"Loop '{loop_name}' must define a 'steps' list")

    return LoopDefinition(name=loop_name, steps=_parse_steps(raw_steps, f"loops.{loop_name}.steps"))


def _parse_steps(raw_steps: list[Any], context: str) -> list[Step]:
    parsed_steps: list[Step] = []
    for index, raw_step in enumerate(raw_steps):
        parsed_steps.append(_parse_step(raw_step, f"{context}[{index}]") )
    return parsed_steps


def _parse_step(raw_step: Any, context: str) -> Step:
    if not isinstance(raw_step, Mapping):
        raise LoopValidationError(f"{context} must be a mapping")
    if len(raw_step) != 1:
        raise LoopValidationError(f"{context} must define exactly one step type")

    step_type, value = next(iter(raw_step.items()))
    if step_type == "command":
        if not isinstance(value, str) or not value:
            raise LoopValidationError(f"{context}.command must be a non-empty string")
        return CommandStep(command=value)

    if step_type == "wait":
        if not isinstance(value, (int, float)):
            raise LoopValidationError(f"{context}.wait must be numeric seconds")
        return WaitStep(seconds=float(value))

    if step_type == "wait_visual":
        return _parse_wait_visual_step(value, context)

    if step_type == "branch":
        return _parse_branch_step(value, context)

    if step_type == "repeat":
        return _parse_repeat_step(value, context)

    if step_type == "call":
        if not isinstance(value, str) or not value:
            raise LoopValidationError(f"{context}.call must be a non-empty string")
        return CallStep(loop_name=value)

    raise LoopValidationError(f"{context} uses unknown step type '{step_type}'")


def _parse_wait_visual_step(value: Any, context: str) -> WaitVisualStep:
    if not isinstance(value, Mapping):
        raise LoopValidationError(f"{context}.wait_visual must be a mapping")

    detector = value.get("detector")
    timeout = value.get("timeout")
    on_timeout = value.get("on_timeout", "abort")

    if not isinstance(detector, str) or not detector:
        raise LoopValidationError(f"{context}.wait_visual.detector must be a non-empty string")
    if not isinstance(timeout, (int, float)):
        raise LoopValidationError(f"{context}.wait_visual.timeout must be numeric seconds")

    parsed_on_timeout: str | list[Step]
    if on_timeout in {"abort", "continue"}:
        parsed_on_timeout = on_timeout
    elif isinstance(on_timeout, list):
        parsed_on_timeout = _parse_steps(on_timeout, f"{context}.wait_visual.on_timeout")
    else:
        raise LoopValidationError(
            f"{context}.wait_visual.on_timeout must be 'abort', 'continue', or a step list"
        )

    return WaitVisualStep(
        detector=detector,
        timeout_seconds=float(timeout),
        on_timeout=parsed_on_timeout,
    )


def _parse_branch_step(value: Any, context: str) -> BranchStep:
    if not isinstance(value, Mapping):
        raise LoopValidationError(f"{context}.branch must be a mapping")

    condition = value.get("condition")
    then_steps = value.get("then", [])
    else_steps = value.get("else", [])

    if not isinstance(condition, str) or not condition:
        raise LoopValidationError(f"{context}.branch.condition must be a non-empty string")
    if not isinstance(then_steps, list):
        raise LoopValidationError(f"{context}.branch.then must be a step list")
    if not isinstance(else_steps, list):
        raise LoopValidationError(f"{context}.branch.else must be a step list")

    return BranchStep(
        condition=condition,
        then_steps=_parse_steps(then_steps, f"{context}.branch.then"),
        else_steps=_parse_steps(else_steps, f"{context}.branch.else"),
    )


def _parse_repeat_step(value: Any, context: str) -> RepeatStep:
    if not isinstance(value, Mapping):
        raise LoopValidationError(f"{context}.repeat must be a mapping")

    raw_steps = value.get("steps")
    count = value.get("count")
    while_condition = value.get("while")

    if not isinstance(raw_steps, list):
        raise LoopValidationError(f"{context}.repeat.steps must be a step list")
    if count is not None and not isinstance(count, int):
        raise LoopValidationError(f"{context}.repeat.count must be an integer")
    if while_condition is not None and (not isinstance(while_condition, str) or not while_condition):
        raise LoopValidationError(f"{context}.repeat.while must be a non-empty string")

    return RepeatStep(
        steps=_parse_steps(raw_steps, f"{context}.repeat.steps"),
        count=count,
        while_condition=while_condition,
    )


def _validate_call_targets(loop_definitions: Mapping[str, LoopDefinition]) -> None:
    for loop_definition in loop_definitions.values():
        _validate_steps(loop_definition.steps, loop_definitions, f"loops.{loop_definition.name}.steps")


def _validate_steps(
    steps: list[Step],
    loop_definitions: Mapping[str, LoopDefinition],
    context: str,
) -> None:
    for index, step in enumerate(steps):
        step_context = f"{context}[{index}]"
        if isinstance(step, CallStep):
            if step.loop_name not in loop_definitions:
                raise LoopValidationError(f"{step_context} references unknown loop '{step.loop_name}'")
        elif isinstance(step, BranchStep):
            _validate_steps(step.then_steps, loop_definitions, f"{step_context}.then")
            _validate_steps(step.else_steps, loop_definitions, f"{step_context}.else")
        elif isinstance(step, RepeatStep):
            _validate_steps(step.steps, loop_definitions, f"{step_context}.repeat")
        elif isinstance(step, WaitVisualStep) and isinstance(step.on_timeout, list):
            _validate_steps(step.on_timeout, loop_definitions, f"{step_context}.on_timeout")