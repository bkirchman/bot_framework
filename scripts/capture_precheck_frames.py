from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from framework.contrib.hardware import AVerMediaCapture


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = AVerMediaCapture(device_index=args.device_index)
    try:
        capture.flush()
        frames = []
        for index in range(args.frame_count):
            stamped = capture.get_frame()
            frames.append(stamped.frame.copy())
            cv2.imwrite(str(output_dir / f"frame_{index:02d}.png"), stamped.frame)
    finally:
        capture.close()

    if len(frames) >= 4:
        diff = cv2.absdiff(
            cv2.cvtColor(frames[2], cv2.COLOR_BGR2GRAY),
            cv2.cvtColor(frames[3], cv2.COLOR_BGR2GRAY),
        )
        _, thresholded = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
        cv2.imwrite(str(output_dir / "diff_02_03.png"), diff)
        cv2.imwrite(str(output_dir / "diff_02_03_threshold.png"), thresholded)

    print(output_dir)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and save consecutive frames for manual pre-check inspection.")
    parser.add_argument("--device-index", type=int, default=1)
    parser.add_argument("--frame-count", type=int, default=10)
    parser.add_argument(
        "--output-dir",
        default=r"c:\Users\brian\source\repos\bot_framework\probe_frames\precheck_index_1",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())