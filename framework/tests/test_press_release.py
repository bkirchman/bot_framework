from __future__ import annotations

from framework.contrib.hardware.press_release import press_and_release


def test_press_and_release_alternates_payloads() -> None:
    command = press_and_release(
        press_payload={"button_1": 1},
        release_payload={"button_1": 0},
        hold_ms=120,
    )

    assert command() == {"button_1": 1}
    assert command() == {"button_1": 0}
    assert command() == {"button_1": 1}
    assert command() == {"button_1": 0}


def test_press_and_release_exposes_hold_ms_for_introspection() -> None:
    command = press_and_release(
        press_payload={"hat_x": -1, "hat_y": 0},
        release_payload={"hat_x": 0, "hat_y": 0},
        hold_ms=75,
    )

    assert hasattr(command, "hold_ms")
    assert command.hold_ms == 75


def test_press_and_release_reset_returns_to_pending_press() -> None:
    command = press_and_release(
        press_payload={"button_2": 1},
        release_payload={"button_2": 0},
        hold_ms=100,
    )

    assert command() == {"button_2": 1}
    command.reset()
    assert command() == {"button_2": 1}
    assert command() == {"button_2": 0}