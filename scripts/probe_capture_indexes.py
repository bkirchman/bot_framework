from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from framework.contrib.hardware import AVerMediaCapture


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    backends = [args.backend] if args.backend is not None else args.backends

    failures = 0
    for device_index in args.indexes:
        try:
            output_path, backend_name = save_probe_frame(
                device_index=device_index,
                output_dir=output_dir,
                backends=backends,
                width=args.width,
                height=args.height,
                fps=args.fps,
            )
        except Exception as exc:
            failures += 1
            print(f"index {device_index}: FAILED ({exc})")
            continue

        print(
            f"index {device_index}: saved {output_path} via backend={backend_name} "
            f"resolution={args.width}x{args.height} fps={args.fps}"
        )

    return 1 if failures == len(args.indexes) else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save one probe frame for each requested capture index.")
    parser.add_argument("--output-dir", default="probe_frames")
    parser.add_argument("--backend")
    parser.add_argument("--backends", nargs="+", default=["msmf", "dshow", "any"])
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("indexes", nargs="*", type=int, default=[0, 1])
    return parser.parse_args()


def save_probe_frame(
    device_index: int,
    output_dir: Path,
    backends: Sequence[str],
    *,
    width: int,
    height: int,
    fps: float,
) -> tuple[Path, str]:
    last_error: Exception | None = None

    for backend_name in backends:
        output_path = output_dir / f"capture_index_{device_index}_{backend_name}.png"
        try:
            capture = AVerMediaCapture(
                device_index=device_index,
                backend=backend_name,
                width=width,
                height=height,
                fps=fps,
            )
            try:
                capture.flush()
                frame = capture.get_frame().frame
                write_image(output_path, frame)
                return output_path, backend_name
            finally:
                capture.close()
        except Exception as exc:
            last_error = exc

    if last_error is None:
        raise RuntimeError(f"No backends were provided for device index {device_index}")
    raise RuntimeError(f"All backends failed for device index {device_index}: {last_error}")


def write_image(output_path: Path, frame: object) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to write probe frames") from exc

    if not cv2.imwrite(str(output_path), frame):
        raise RuntimeError(f"Could not write probe frame to {output_path}")


if __name__ == "__main__":
    raise SystemExit(main())