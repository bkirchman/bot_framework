from __future__ import annotations

import argparse
from contextlib import suppress

import cv2

from framework.contrib.hardware import AVerMediaCapture


def main() -> int:
    args = parse_args()
    capture = AVerMediaCapture(
        device_index=args.device_index,
        backend=args.backend,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )

    active_backend = getattr(capture, "_active_backend_name", args.backend)
    window_name = f"Capture Preview index={args.device_index} backend={active_backend}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    try:
        while True:
            frame = capture.get_frame().frame
            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    finally:
        with suppress(Exception):
            capture.close()
        cv2.destroyAllWindows()

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a live preview window for a capture device.")
    parser.add_argument("--device-index", type=int, default=1)
    parser.add_argument("--backend", default="dshow")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.0)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())