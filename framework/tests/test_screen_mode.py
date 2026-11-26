from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Callable

import pytest

from framework.contrib.detection import ModeRule, ScreenModeClassifier, ScreenModeResult


def has(name: str) -> Callable[[set[str]], bool]:
    return lambda frame: name in frame


def make_classifier(enter_evaluations: int = 2) -> ScreenModeClassifier:
    return ScreenModeClassifier(
        [
            ModeRule("A", any_of=(("a", has("a")),)),
            ModeRule("B", any_of=(("b", has("b")),)),
        ],
        enter_evaluations,
    )


def test_priority_and_lower_rules_not_evaluated_after_match() -> None:
    calls: list[str] = []

    def lower(frame: set[str]) -> bool:
        calls.append("lower")
        return True

    classifier = ScreenModeClassifier(
        [
            ModeRule("A", any_of=(("a", has("a")),)),
            ModeRule("B", any_of=(("b", lower),)),
        ],
        1,
    )
    assert classifier({"a"}) == ScreenModeResult("A", "A", ("a",))
    assert calls == []
    assert classifier(set()) == ScreenModeResult("B", "B", ("b",))
    assert calls == ["lower"]


@pytest.mark.parametrize(
    ("present", "matches", "matched"),
    [
        (set(), False, ()),
        ({"x"}, True, ("x",)),
        ({"y"}, True, ("y",)),
        ({"x", "y"}, True, ("x", "y")),
    ],
)
def test_any_of_semantics(present: set[str], matches: bool, matched: tuple[str, ...]) -> None:
    rule = ModeRule("A", any_of=(("x", has("x")), ("y", has("y"))))
    result = ScreenModeClassifier([rule], 1)(present)
    assert result == ScreenModeResult("A" if matches else "UNKNOWN", "A" if matches else "UNKNOWN", matched)


@pytest.mark.parametrize(
    ("present", "matches"),
    [(set(), False), ({"x"}, False), ({"y"}, False), ({"x", "y"}, True)],
)
def test_all_of_semantics(present: set[str], matches: bool) -> None:
    rule = ModeRule("A", all_of=(("x", has("x")), ("y", has("y"))))
    result = ScreenModeClassifier([rule], 1)(present)
    assert result == ScreenModeResult(
        "A" if matches else "UNKNOWN",
        "A" if matches else "UNKNOWN",
        ("x", "y") if matches else (),
    )


@pytest.mark.parametrize(
    ("present", "matched"),
    [
        ({"x", "z"}, ("x", "z")),
        ({"y", "z"}, ("y", "z")),
        ({"x", "y", "z"}, ("x", "y", "z")),
        ({"x", "y"}, ()),
        ({"z"}, ()),
    ],
)
def test_combined_rule_semantics(present: set[str], matched: tuple[str, ...]) -> None:
    rule = ModeRule(
        "A",
        any_of=(("x", has("x")), ("y", has("y"))),
        all_of=(("z", has("z")),),
    )
    result = ScreenModeClassifier([rule], 1)(present)
    expected_mode = "A" if matched else "UNKNOWN"
    assert result == ScreenModeResult(expected_mode, expected_mode, matched)


def test_all_evidence_is_evaluated_in_each_considered_rule() -> None:
    calls: list[str] = []

    def evidence(name: str, value: bool) -> Callable[[object], bool]:
        def predicate(frame: object) -> bool:
            calls.append(name)
            return value

        return predicate

    classifier = ScreenModeClassifier(
        [
            ModeRule("A", all_of=(("a", evidence("a", False)), ("b", evidence("b", True)))),
            ModeRule(
                "B",
                any_of=(("c", evidence("c", True)), ("d", evidence("d", True))),
                all_of=(("e", evidence("e", True)), ("f", evidence("f", True))),
            ),
        ],
        1,
    )
    assert classifier(None) == ScreenModeResult("B", "B", ("c", "d", "e", "f"))
    assert calls == ["a", "b", "c", "d", "e", "f"]


def test_hysteresis_enters_and_changes_modes() -> None:
    classifier = make_classifier()
    assert classifier.mode == "UNKNOWN"
    assert classifier({"a"}) == ScreenModeResult("UNKNOWN", "A", ("a",))
    assert classifier({"a"}) == ScreenModeResult("A", "A", ("a",))
    assert classifier({"b"}) == ScreenModeResult("UNKNOWN", "B", ("b",))
    assert classifier({"b"}) == ScreenModeResult("B", "B", ("b",))
    assert classifier.mode == "B"


def test_alternating_candidates_never_enter_a_mode() -> None:
    classifier = make_classifier()
    for frame in ({"a"}, {"b"}, {"a"}, {"b"}):
        assert classifier(frame).mode == "UNKNOWN"


def test_unknown_raw_leaves_mode_immediately_and_clears_candidate() -> None:
    classifier = make_classifier()
    classifier({"a"})
    classifier({"a"})
    assert classifier(set()) == ScreenModeResult("UNKNOWN", "UNKNOWN", ())
    assert classifier({"a"}).mode == "UNKNOWN"
    assert classifier(set()) == ScreenModeResult("UNKNOWN", "UNKNOWN", ())
    assert classifier({"a"}).mode == "UNKNOWN"
    assert classifier({"a"}).mode == "A"


def test_single_evaluation_enters_and_changes_immediately() -> None:
    classifier = make_classifier(1)
    assert classifier({"a"}) == ScreenModeResult("A", "A", ("a",))
    assert classifier({"b"}) == ScreenModeResult("B", "B", ("b",))
    assert classifier(set()) == ScreenModeResult("UNKNOWN", "UNKNOWN", ())


def test_entry_threshold_counts_consecutive_evaluations() -> None:
    classifier = make_classifier(3)
    assert classifier({"a"}).mode == "UNKNOWN"
    assert classifier({"a"}).mode == "UNKNOWN"
    assert classifier({"a"}).mode == "A"
    assert classifier({"b"}).mode == "UNKNOWN"
    assert classifier({"b"}).mode == "UNKNOWN"
    assert classifier({"b"}).mode == "B"


def test_predicate_errors_propagate_without_changing_state() -> None:
    def predicate(frame: str) -> bool:
        if frame == "error":
            raise RuntimeError("predicate failed")
        return frame == "a"

    classifier = ScreenModeClassifier([ModeRule("A", any_of=(("a", predicate),))], 2)
    assert classifier("a").mode == "UNKNOWN"
    with pytest.raises(RuntimeError, match="predicate failed"):
        classifier("error")
    assert classifier.mode == "UNKNOWN"
    assert classifier("a").mode == "A"


def test_reset_clears_mode_and_pending_candidate() -> None:
    classifier = make_classifier()
    classifier({"a"})
    classifier.reset()
    assert classifier.mode == "UNKNOWN"
    assert classifier({"a"}).mode == "UNKNOWN"
    assert classifier({"a"}).mode == "A"
    classifier.reset()
    assert classifier.mode == "UNKNOWN"
    assert classifier({"a"}).mode == "UNKNOWN"


def test_custom_unknown_mode_and_rules_are_copied() -> None:
    rules = [ModeRule("A", any_of=(("a", has("a")),))]
    classifier = ScreenModeClassifier(rules, 1, unknown_mode="?")
    rules.clear()
    assert classifier.mode == "?"
    assert classifier({"a"}) == ScreenModeResult("A", "A", ("a",))
    classifier.reset()
    assert classifier(set()) == ScreenModeResult("?", "?", ())


def test_mode_is_read_only() -> None:
    classifier = make_classifier()
    with pytest.raises(AttributeError):
        classifier.mode = "A"


@pytest.mark.parametrize(
    "value",
    [ModeRule("A", any_of=(("a", has("a")),)), ScreenModeResult("A", "A", ("a",))],
)
def test_data_classes_are_frozen_and_have_slots(value: ModeRule | ScreenModeResult) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(value, "name" if isinstance(value, ModeRule) else "mode", "B")
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize(
    ("name", "any_of", "all_of", "message"),
    [
        ("", (("a", has("a")),), (), "name"),
        (None, (("a", has("a")),), (), "name"),
        ("A", (), (), "at least one"),
        ("A", (("", has("a")),), (), "evidence name"),
        ("A", ((None, has("a")),), (), "evidence name"),
        ("A", (("a", has("a")), ("a", has("a"))), (), "unique"),
        ("A", (), (("a", has("a")), ("a", has("a"))), "unique"),
        ("A", (("a", has("a")),), (("a", has("a")),), "unique"),
        ("A", [("a", has("a"))], (), "tuples"),
        ("A", (("a",),), (), "evidence must"),
        ("A", (("a", None),), (), "predicate"),
    ],
)
def test_rule_rejects_invalid_configuration(name: str, any_of: tuple, all_of: tuple, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ModeRule(name, any_of=any_of, all_of=all_of)


@pytest.mark.parametrize("enter_evaluations", [0, -1, 1.5, True, None])
def test_classifier_rejects_invalid_entry_threshold(enter_evaluations: int) -> None:
    rule = ModeRule("A", any_of=(("a", has("a")),))
    with pytest.raises(ValueError, match="enter_evaluations"):
        ScreenModeClassifier((rule,), enter_evaluations)


def test_classifier_rejects_invalid_rules_and_unknown_mode() -> None:
    rule = ModeRule("A", any_of=(("a", has("a")),))
    with pytest.raises(ValueError, match="non-empty"):
        ScreenModeClassifier([], 1)
    with pytest.raises(ValueError, match="non-empty"):
        ScreenModeClassifier((), 1)
    with pytest.raises(ValueError, match="ModeRule"):
        ScreenModeClassifier([None], 1)
    with pytest.raises(ValueError, match="unique"):
        ScreenModeClassifier([rule, rule], 1)
    with pytest.raises(ValueError, match="unknown_mode"):
        ScreenModeClassifier([rule], 1, unknown_mode="A")
    with pytest.raises(ValueError, match="unknown_mode"):
        ScreenModeClassifier([rule], 1, unknown_mode=None)
