from __future__ import annotations

import argparse
import math
import time
from contextlib import suppress
from typing import Any, Mapping, Optional

from framework.contrib.hardware import AVerMediaCapture, UDPXboxOutput
from framework.interfaces import Action, FrameProcessor, StampedFrame
from framework.loop import BotLoop
from framework.temporal import FrameHistory


class NoOpProcessor(FrameProcessor):
    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        return None


def main() -> int:
    args = parse_args()
    capture = AVerMediaCapture(device_index=args.device_index)
    output = UDPXboxOutput(udp_ip=args.udp_ip, udp_port=args.udp_port, response_mode=0)
    max_iterations = max(1, math.ceil(args.duration_seconds * capture.fps))
    history = FrameHistory(capacity=max_iterations + capture.latency_frames + 8)
    loop = BotLoop(
        capture=capture,
        output=output,
        processor=NoOpProcessor(),
        history=history,
    )

    wall_start = time.monotonic()
    try:
        iterations = loop.run(max_iterations=max_iterations)
    finally:
        with suppress(Exception):
            capture.close()
        with suppress(Exception):
            output.close()
    wall_elapsed = time.monotonic() - wall_start

    records = list(history)
    frame_ids = [record.frame.frame_id for record in records]
    timestamps = [record.frame.timestamp for record in records]
    wall_fps = iterations / wall_elapsed if wall_elapsed > 0 else 0.0
    stamp_fps = _stamp_fps(timestamps)
    contiguous_ids = _is_contiguous(frame_ids)
    monotonic_timestamps = timestamps == sorted(timestamps)

    print(f"Captured frames: {iterations}")
    print(f"Wall-clock seconds: {wall_elapsed:.3f}")
    print(f"Achieved fps (wall-clock): {wall_fps:.2f}")
    if stamp_fps is not None:
        print(f"Achieved fps (frame stamps): {stamp_fps:.2f}")
    else:
        print("Achieved fps (frame stamps): n/a")
    print(f"Contiguous frame ids: {contiguous_ids}")
    print(f"Monotonic timestamps: {monotonic_timestamps}")
    print(f"Declared latency_frames: {capture.latency_frames}")

    return 0 if contiguous_ids and monotonic_timestamps else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a 10-second hardware smoke test for bot_framework.")
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--udp-ip", default="192.168.1.196")
    parser.add_argument("--udp-port", type=int, default=5005)
    return parser.parse_args()


def _stamp_fps(timestamps: list[float]) -> Optional[float]:
    if len(timestamps) < 2:
        return None
    elapsed = timestamps[-1] - timestamps[0]
    if elapsed <= 0:
        return None
    return (len(timestamps) - 1) / elapsed


def _is_contiguous(frame_ids: list[int]) -> bool:
    if not frame_ids:
        return True
    expected_ids = list(range(frame_ids[0], frame_ids[0] + len(frame_ids)))
    return frame_ids == expected_ids


if __name__ == "__main__":
    raise SystemExit(main())