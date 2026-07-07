from __future__ import annotations

from typing import Any, Mapping, Optional

from framework.interfaces import Action, FrameProcessor, StampedFrame

from .interpreter import LoopInterpreter
from .registries import CommandRegistry, DetectorRegistry
from .schema import LoopDefinition


class ContentLoopProcessor(FrameProcessor):
    def __init__(
        self,
        loop_definitions: Mapping[str, LoopDefinition],
        command_registry: CommandRegistry,
        detector_registry: DetectorRegistry,
        loop_name: str,
    ) -> None:
        self._interpreter = LoopInterpreter(
            loop_definitions=loop_definitions,
            command_registry=command_registry,
            detector_registry=detector_registry,
            loop_name=loop_name,
        )

    @property
    def interpreter(self) -> LoopInterpreter:
        return self._interpreter

    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        return self._interpreter.tick(frame, services)