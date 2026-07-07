from __future__ import annotations

from typing import Callable, Mapping


class _PressAndReleaseCommand:
    def __init__(
        self,
        press_payload: Mapping[str, int],
        release_payload: Mapping[str, int],
        hold_ms: int,
    ) -> None:
        if hold_ms < 0:
            raise ValueError("hold_ms must be non-negative")

        self._press_payload = _normalize_payload(press_payload, name="press_payload")
        self._release_payload = _normalize_payload(release_payload, name="release_payload")
        self.hold_ms = hold_ms
        self._pending_release = False

    def __call__(self) -> dict:
        if not self._pending_release:
            self._pending_release = True
            return dict(self._press_payload)

        self._pending_release = False
        return dict(self._release_payload)

    def reset(self) -> None:
        self._pending_release = False


def press_and_release(
    press_payload: Mapping[str, int],
    release_payload: Mapping[str, int],
    hold_ms: int,
) -> Callable[[], dict]:
    return _PressAndReleaseCommand(
        press_payload=press_payload,
        release_payload=release_payload,
        hold_ms=hold_ms,
    )


def _normalize_payload(payload: Mapping[str, int], *, name: str) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if not isinstance(value, int):
            raise ValueError(f"{name} values must be integers")
        normalized[key] = value
    return normalized