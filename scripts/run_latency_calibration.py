from __future__ import annotations

import argparse
import statistics
import time
import warnings
from collections import Counter
from contextlib import suppress
from typing import Any, Callable, Optional

from framework.contrib.diagnostics import LatencyCalibrator
from framework.contrib.diagnostics.latency import default_pixel_diff_comparator
from framework.contrib.hardware import AVerMediaCapture, UDPXboxOutput
from framework.interfaces import Action


# Replace these placeholder keys and values with the command shape expected by your Arduino firmware.
IMPULSE_PAYLOAD   = {"move_x": 0, "move_y": -80, "move_duration": 100}  # up
ALTERNATE_PAYLOAD = {"move_x": 0, "move_y":  80, "move_duration": 100}  # down
FRAME_COUNT = 30
TRIALS = 15
TRIAL_PAUSE_S = 1.0
ROI = None  # Optional (x1, y1, x2, y2)
CHANGED_PIXEL_THRESHOLD = 3000
PER_PIXEL_DELTA_THRESHOLD = 20


def main() -> int:
    args = parse_args()
    comparator = build_comparator(ROI)
    capture = AVerMediaCapture(
        device_index=args.device_index,
        backend=args.backend,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    output = UDPXboxOutput(
        udp_ip=args.udp_ip,
        udp_port=args.udp_port,
        response_mode=0,
    )

    try:
        if not run_stability_precheck(capture, comparator):
            return 1

        measured_latencies: list[Optional[int]] = []
        mismatch_warning_count = 0

        for trial_index in range(TRIALS):
            payload = IMPULSE_PAYLOAD if trial_index % 2 == 0 else ALTERNATE_PAYLOAD
            calibrator = LatencyCalibrator(
                capture,
                output,
                impulse_action=Action(frame_id=0, timestamp=0.0, payload=payload),
                frame_count=FRAME_COUNT,
                comparator=comparator,
            )

            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                result = calibrator.measure()

            measured_latencies.append(result.measured_latency_frames)
            mismatch_warning_count += count_mismatch_warnings(caught_warnings)

            print(
                f"trial {trial_index + 1:02d}: payload={'IMPULSE' if trial_index % 2 == 0 else 'ALTERNATE'} "
                f"measured_latency_frames={result.measured_latency_frames} "
                f"warning={result.mismatch_warning}"
            )

            if trial_index < TRIALS - 1:
                time.sleep(TRIAL_PAUSE_S)

        report_results(
            declared_latency_frames=capture.latency_frames,
            measured_latencies=measured_latencies,
            mismatch_warning_count=mismatch_warning_count,
        )
    finally:
        with suppress(Exception):
            capture.flush()
        with suppress(Exception):
            capture.close()
        with suppress(Exception):
            output.close()

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeated latency calibration trials.")
    parser.add_argument("--device-index", type=int, default=1)
    parser.add_argument("--backend", default="dshow")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--udp-ip", default="192.168.1.196")
    parser.add_argument("--udp-port", type=int, default=5005)
    return parser.parse_args()


def build_comparator(
    roi: Optional[tuple[int, int, int, int]],
) -> Callable[[Any, Any], bool]:
    def base_comparator(baseline_frame: Any, candidate_frame: Any) -> bool:
        return default_pixel_diff_comparator(
            baseline_frame,
            candidate_frame,
            changed_pixel_threshold=CHANGED_PIXEL_THRESHOLD,
            per_pixel_delta_threshold=PER_PIXEL_DELTA_THRESHOLD,
        )

    if roi is None:
        return base_comparator

    def roi_comparator(baseline_frame: Any, candidate_frame: Any) -> bool:
        return base_comparator(
            crop_frame(baseline_frame, roi),
            crop_frame(candidate_frame, roi),
        )

    return roi_comparator


def crop_frame(frame: Any, roi: tuple[int, int, int, int]) -> Any:
    x1, y1, x2, y2 = roi
    return frame[y1:y2, x1:x2]


def run_stability_precheck(
    capture: AVerMediaCapture,
    comparator: Callable[[Any, Any], bool],
) -> bool:
    print("Running stability pre-check...")
    capture.flush()
    frames = [capture.get_frame() for _ in range(10)]
    failed_pairs: list[tuple[int, int]] = []

    for index in range(len(frames) - 1):
        previous_frame = frames[index]
        current_frame = frames[index + 1]
        if comparator(previous_frame.frame, current_frame.frame):
            failed_pairs.append((previous_frame.frame_id, current_frame.frame_id))

    if failed_pairs:
        print("Stability pre-check failed; the scene is not static enough.")
        print(f"Differing consecutive frame pairs: {failed_pairs}")
        capture.flush()
        return False

    print("Stability pre-check passed.")
    return True


def count_mismatch_warnings(caught_warnings: list[warnings.WarningMessage]) -> int:
    return sum(
        1
        for warning_message in caught_warnings
        if "LATENCY CALIBRATION WARNING:" in str(warning_message.message)
    )


def report_results(
    *,
    declared_latency_frames: int,
    measured_latencies: list[Optional[int]],
    mismatch_warning_count: int,
) -> None:
    print()
    print(f"Measured latency_frames per trial: {measured_latencies}")

    valid_measurements = [value for value in measured_latencies if value is not None]
    if valid_measurements:
        mode_latency = Counter(valid_measurements).most_common(1)[0][0]
        print(f"Mode latency_frames: {mode_latency}")
    else:
        mode_latency = None
        print("Mode latency_frames: n/a")

    print(f"Mismatch warnings: {mismatch_warning_count}")
    print(f"Declared latency_frames: {declared_latency_frames}")

    passed = (
        mode_latency == declared_latency_frames
        and mismatch_warning_count == 0
        and len(valid_measurements) == len(measured_latencies)
    )
    print(f"Result: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    raise SystemExit(main())