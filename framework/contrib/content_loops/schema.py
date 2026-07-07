from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


TimeoutPolicy: TypeAlias = Literal["abort", "continue"] | list["Step"]


@dataclass(frozen=True, slots=True)
class CommandStep:
    command: str

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must be non-empty")


@dataclass(frozen=True, slots=True)
class WaitStep:
    seconds: float

    def __post_init__(self) -> None:
        if self.seconds < 0:
            raise ValueError("seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class WaitVisualStep:
    detector: str
    timeout_seconds: float
    on_timeout: TimeoutPolicy = "abort"

    def __post_init__(self) -> None:
        if not self.detector:
            raise ValueError("detector must be non-empty")
        if self.timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        if not isinstance(self.on_timeout, list) and self.on_timeout not in {"abort", "continue"}:
            raise ValueError("on_timeout must be 'abort', 'continue', or a fallback step list")


@dataclass(frozen=True, slots=True)
class BranchStep:
    condition: str
    then_steps: list["Step"]
    else_steps: list["Step"]

    def __post_init__(self) -> None:
        if not self.condition:
            raise ValueError("condition must be non-empty")


@dataclass(frozen=True, slots=True)
class RepeatStep:
    steps: list["Step"]
    count: int | None = None
    while_condition: str | None = None

    def __post_init__(self) -> None:
        if self.count is None and self.while_condition is None:
            raise ValueError("repeat requires either count or while_condition")
        if self.count is not None and self.while_condition is not None:
            raise ValueError("repeat cannot define both count and while_condition")
        if self.count is not None and self.count <= 0:
            raise ValueError("repeat count must be positive")
        if self.while_condition is not None and not self.while_condition:
            raise ValueError("while_condition must be non-empty")


@dataclass(frozen=True, slots=True)
class CallStep:
    loop_name: str

    def __post_init__(self) -> None:
        if not self.loop_name:
            raise ValueError("loop_name must be non-empty")


Step: TypeAlias = CommandStep | WaitStep | WaitVisualStep | BranchStep | RepeatStep | CallStep


@dataclass(frozen=True, slots=True)
class LoopDefinition:
    name: str
    steps: list[Step]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must be non-empty")