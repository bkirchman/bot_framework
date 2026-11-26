from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ModeRule:
    name: str
    any_of: tuple[tuple[str, Callable[[Any], bool]], ...] = ()
    all_of: tuple[tuple[str, Callable[[Any], bool]], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.any_of, tuple) or not isinstance(self.all_of, tuple):
            raise ValueError("any_of and all_of must be tuples of evidence")
        if not self.any_of and not self.all_of:
            raise ValueError("at least one of any_of and all_of must be non-empty")

        names: set[str] = set()
        for evidence in self.any_of + self.all_of:
            if not isinstance(evidence, tuple) or len(evidence) != 2:
                raise ValueError("evidence must be a (name, predicate) tuple")
            name, predicate = evidence
            if not isinstance(name, str) or not name:
                raise ValueError("evidence name must be a non-empty string")
            if name in names:
                raise ValueError("evidence names must be unique within a rule")
            if not callable(predicate):
                raise ValueError("evidence predicate must be callable")
            names.add(name)


@dataclass(frozen=True, slots=True)
class ScreenModeResult:
    mode: str
    raw_mode: str
    matched: tuple[str, ...]


class ScreenModeClassifier:
    """Classify frames with ordered rules and stateful entry hysteresis.

    Unlike stateless detectors, each call updates the committed mode and entry
    candidate. Call reset() to return to the initial unknown state.
    """

    def __init__(
        self,
        rules: tuple[ModeRule, ...] | list[ModeRule],
        enter_evaluations: int,
        unknown_mode: str = "UNKNOWN",
    ) -> None:
        if not isinstance(unknown_mode, str):
            raise ValueError("unknown_mode must be a string")
        if not isinstance(rules, (tuple, list)) or not rules:
            raise ValueError("rules must be a non-empty tuple or list")
        if any(not isinstance(rule, ModeRule) for rule in rules):
            raise ValueError("rules must contain ModeRule instances")
        names = [rule.name for rule in rules]
        if len(set(names)) != len(names):
            raise ValueError("rule names must be unique")
        if unknown_mode in names:
            raise ValueError("rule names must not equal unknown_mode")
        if (
            not isinstance(enter_evaluations, int)
            or isinstance(enter_evaluations, bool)
            or enter_evaluations < 1
        ):
            raise ValueError("enter_evaluations must be an integer of at least 1")

        self._rules = tuple(rules)
        self._enter_evaluations = enter_evaluations
        self._unknown_mode = unknown_mode
        self.reset()

    @property
    def mode(self) -> str:
        return self._mode

    def reset(self) -> None:
        self._mode = self._unknown_mode
        self._candidate: str | None = None
        self._candidate_count = 0

    def __call__(self, frame: Any) -> ScreenModeResult:
        raw_mode = self._unknown_mode
        matched: tuple[str, ...] = ()
        for rule in self._rules:
            any_results = tuple((name, predicate(frame)) for name, predicate in rule.any_of)
            all_results = tuple((name, predicate(frame)) for name, predicate in rule.all_of)
            if all(value for _, value in all_results) and (
                not any_results or any(value for _, value in any_results)
            ):
                raw_mode = rule.name
                matched = tuple(name for name, value in any_results + all_results if value)
                break

        if raw_mode == self._mode:
            self._candidate = None
            self._candidate_count = 0
        else:
            if self._mode != self._unknown_mode:
                self._mode = self._unknown_mode
            if raw_mode == self._unknown_mode:
                self._candidate = None
                self._candidate_count = 0
            else:
                if raw_mode == self._candidate:
                    self._candidate_count += 1
                else:
                    self._candidate = raw_mode
                    self._candidate_count = 1
                if self._candidate_count >= self._enter_evaluations:
                    self._mode = raw_mode
                    self._candidate = None
                    self._candidate_count = 0

        return ScreenModeResult(self._mode, raw_mode, matched)
