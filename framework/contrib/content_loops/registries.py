from __future__ import annotations

from typing import Any, Callable


CommandFactory = Callable[[], Any]
Detector = Callable[[Any], bool]


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandFactory] = {}

    def register(self, name: str, factory: CommandFactory) -> None:
        if not name:
            raise ValueError("command name must be non-empty")
        self._commands[name] = factory

    def get(self, name: str) -> CommandFactory:
        try:
            return self._commands[name]
        except KeyError as exc:
            raise KeyError(f"Unknown command registry entry: {name}") from exc

    def __contains__(self, name: object) -> bool:
        return name in self._commands


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: dict[str, Detector] = {}

    def register(self, name: str, detector: Detector) -> None:
        if not name:
            raise ValueError("detector name must be non-empty")
        self._detectors[name] = detector

    def get(self, name: str) -> Detector:
        try:
            return self._detectors[name]
        except KeyError as exc:
            raise KeyError(f"Unknown detector registry entry: {name}") from exc

    def __contains__(self, name: object) -> bool:
        return name in self._detectors