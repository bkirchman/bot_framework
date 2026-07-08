from __future__ import annotations

import argparse
import json
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from framework.contrib.hardware import UDPXboxOutput
from framework.interfaces import Action


TEST_GAP_SECONDS = 1.0


@dataclass(frozen=True)
class CommandStep:
    payload: dict[str, Any]
    after_delay_seconds: float = 0.0


@dataclass(frozen=True)
class VerificationTest:
    name: str
    group: str
    expected_observation: str
    steps: tuple[CommandStep, ...]
    requires_confirmation: bool = True


@dataclass
class TestResult:
    name: str
    group: str
    status: str
    note: str


def _build_tests() -> list[VerificationTest]:
    return [
        VerificationTest(
            name="aim right 200ms",
            group="existing_behavior",
            expected_observation="Aim should move right briefly, then self-center.",
            steps=(CommandStep({"aim_x": 80, "aim_y": 0, "aim_duration": 200}),),
        ),
        VerificationTest(
            name="move left 200ms",
            group="existing_behavior",
            expected_observation="Move should go left briefly, then self-center.",
            steps=(CommandStep({"move_x": -80, "move_y": 0, "move_duration": 200}),),
        ),
        VerificationTest(
            name="trigger burst 200ms",
            group="existing_behavior",
            expected_observation="Right trigger should engage briefly, then self-release.",
            steps=(CommandStep({"trigger": 100, "trigger_duration": 200}),),
        ),
        VerificationTest(
            name="reload fixed 50ms",
            group="existing_behavior",
            expected_observation="Reload should press button_0 and release automatically after about 50ms.",
            steps=(CommandStep({"reload": 1}),),
        ),
        VerificationTest(
            name="button_2 duration self-release 100ms",
            group="new_behavior",
            expected_observation="button_2 should press, then self-release after about 100ms without a button_2:0 packet.",
            steps=(CommandStep({"button_2": 1, "button_2_duration": 100}),),
        ),
        VerificationTest(
            name="hat up duration self-center 100ms",
            group="new_behavior",
            expected_observation="Hat should move up, then self-center after about 100ms.",
            steps=(CommandStep({"hat_x": 0, "hat_y": -1, "hat_duration": 100}),),
        ),
        VerificationTest(
            name="raw button_2 press/release still works",
            group="regression",
            expected_observation="button_2 should stay pressed during the 500ms gap, then release when button_2:0 is sent.",
            steps=(
                CommandStep({"button_2": 1}, after_delay_seconds=0.5),
                CommandStep({"button_2": 0}),
            ),
        ),
        VerificationTest(
            name="raw hat set/center still works",
            group="regression",
            expected_observation="Hat should stay up during the 500ms gap, then center when hat_x:0,hat_y:0 is sent.",
            steps=(
                CommandStep({"hat_x": 0, "hat_y": -1}, after_delay_seconds=0.5),
                CommandStep({"hat_x": 0, "hat_y": 0}),
            ),
        ),
    ]


def _send_payload(output: UDPXboxOutput, payload: dict[str, Any], frame_id: int) -> None:
    action = Action(frame_id=frame_id, timestamp=time.time(), payload=payload)
    output.execute(action)


def _prompt_confirmation(expected_observation: str) -> tuple[str, str]:
    while True:
        answer = input(f"Observed as expected? [y/n/s] - {expected_observation}\n> ").strip().lower()
        if answer in {"y", "yes"}:
            return "PASS", "confirmed by operator"
        if answer in {"n", "no"}:
            return "FAIL", "operator marked as failed"
        if answer in {"s", "skip"}:
            return "SKIP", "operator skipped confirmation"
        print("Please answer y, n, or s.")


def _print_summary(results: list[TestResult]) -> None:
    print("\n=== Verification Summary ===")
    for result in results:
        print(f"[{result.status}] ({result.group}) {result.name} - {result.note}")

    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    skip_count = sum(1 for r in results if r.status == "SKIP")
    auto_count = sum(1 for r in results if r.status == "AUTO")

    print("\nTotals:")
    print(f"PASS: {pass_count}")
    print(f"FAIL: {fail_count}")
    print(f"SKIP: {skip_count}")
    print(f"AUTO: {auto_count}")

    regression_failed = any(r.group == "regression" and r.status == "FAIL" for r in results)
    if regression_failed:
        print("\nWARNING: Regression check failed. Roll back to the previous firmware immediately.")
    else:
        print("\nReminder: if any regression test failed, roll back to the previous firmware immediately.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual verification harness for Arduino firmware v2.1 duration commands."
    )
    parser.add_argument("--udp-ip", default="192.168.1.196", help="Target Arduino IP address")
    parser.add_argument("--udp-port", type=int, default=5005, help="Target Arduino UDP command port")
    parser.add_argument("--auto", action="store_true", help="Run non-interactively without confirmation prompts")
    parser.add_argument(
        "--debug-responses",
        action="store_true",
        help="Enable UDPXboxOutput debug response logging",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tests = _build_tests()

    print("Firmware v2.1 verification starting.")
    print("Prerequisites: Arduino powered/connected and a visible screen showing controller inputs.")
    print(f"Target: udp_ip={args.udp_ip} udp_port={args.udp_port} auto={args.auto}")

    output = UDPXboxOutput(
        udp_ip=args.udp_ip,
        udp_port=args.udp_port,
        response_mode=0,
        debug_mode=args.debug_responses,
    )

    results: list[TestResult] = []
    frame_id = 1

    try:
        for idx, test in enumerate(tests, start=1):
            print("\n----------------------------------------")
            print(f"Test {idx}/{len(tests)}: {test.name}")
            print(f"Group: {test.group}")
            print(f"Expected: {test.expected_observation}")

            failed_to_send = False
            for step_idx, step in enumerate(test.steps, start=1):
                payload_text = json.dumps(step.payload, separators=(",", ":"))
                print(f"Next command step {step_idx}/{len(test.steps)}: {payload_text}")
                if not args.auto:
                    input("Press Enter to send this command... ")
                print(f"Sending now: {payload_text}")
                try:
                    _send_payload(output, step.payload, frame_id=frame_id)
                    frame_id += 1
                except Exception as exc:  # pragma: no cover - hardware path
                    failed_to_send = True
                    results.append(
                        TestResult(
                            name=test.name,
                            group=test.group,
                            status="FAIL",
                            note=f"send error: {exc}",
                        )
                    )
                    print(f"Send failed: {exc}")
                    break

                if step.after_delay_seconds > 0:
                    print(f"Waiting {step.after_delay_seconds:.3f}s before next step...")
                    time.sleep(step.after_delay_seconds)

            if not failed_to_send:
                if args.auto:
                    results.append(
                        TestResult(
                            name=test.name,
                            group=test.group,
                            status="AUTO",
                            note="ran in auto mode (no operator confirmation)",
                        )
                    )
                else:
                    status, note = _prompt_confirmation(test.expected_observation)
                    results.append(TestResult(name=test.name, group=test.group, status=status, note=note))

            if idx < len(tests):
                print(f"Pausing {TEST_GAP_SECONDS:.1f}s before next test...")
                time.sleep(TEST_GAP_SECONDS)
    finally:
        with suppress(Exception):
            output.close()

    _print_summary(results)
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
