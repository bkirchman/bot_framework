from __future__ import annotations

import argparse
import statistics
import time
from dataclasses import dataclass
from typing import Any, Iterable


def import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to benchmark capture backends") from exc
    return cv2


@dataclass(frozen=True, slots=True)
class BackendResult:
    backend_name: str
    opened: bool
    width: int | None
    height: int | None
    fps_property: float | None
    buffer_size_property: float | None
    mean_read_ms: float | None
    median_read_ms: float | None
    effective_fps: float | None
    successful_reads: int
    error: str | None


def main() -> int:
    args = parse_args()
    cv2 = import_cv2()
    all_backends = [
        (cv2.CAP_DSHOW, "DirectShow"),
        (cv2.CAP_MSMF, "MediaFoundation"),
        (cv2.CAP_ANY, "AutoDefault"),
    ]
    backends = [
        (backend, backend_name)
        for backend, backend_name in all_backends
        if args.backend in {"all", backend_name.lower()}
    ]

    print("=" * 72)
    print("GC573 Capture Backend Benchmark")
    print("=" * 72)
    print(
        f"device_index={args.device_index} width={args.width} height={args.height} "
        f"fps={args.fps} warmup_frames={args.warmup_frames} sample_reads={args.sample_reads}"
    )

    results: list[BackendResult] = []
    for backend, backend_name in backends:
        print()
        print(f"Testing {backend_name}...")
        result = benchmark_backend(
            cv2=cv2,
            device_index=args.device_index,
            backend=backend,
            backend_name=backend_name,
            width=args.width,
            height=args.height,
            fps=args.fps,
            warmup_frames=args.warmup_frames,
            sample_reads=args.sample_reads,
            set_buffer_size=args.set_buffer_size,
        )
        print_backend_result(result)
        results.append(result)

    print()
    print("=" * 72)
    print("Summary")
    print("=" * 72)
    for result in results:
        print(
            f"{result.backend_name}: opened={result.opened} successful_reads={result.successful_reads} "
            f"mean_read_ms={format_float(result.mean_read_ms)} effective_fps={format_float(result.effective_fps)} "
            f"error={result.error or 'none'}"
        )

    best_result = choose_best_result(results)
    if best_result is None:
        print("No backend produced valid benchmark results.")
        return 1

    print()
    print(
        f"Best backend by mean read time: {best_result.backend_name} "
        f"({format_float(best_result.mean_read_ms)} ms avg read, "
        f"{format_float(best_result.effective_fps)} effective fps)"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark OpenCV capture backends for the GC573.")
    parser.add_argument("--device-index", type=int, default=1)
    parser.add_argument(
        "--backend",
        choices=["all", "directshow", "mediafoundation", "autodefault"],
        default="all",
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--sample-reads", type=int, default=120)
    parser.add_argument("--set-buffer-size", type=int, default=1)
    return parser.parse_args()


def benchmark_backend(
    *,
    cv2: Any,
    device_index: int,
    backend: int,
    backend_name: str,
    width: int,
    height: int,
    fps: float,
    warmup_frames: int,
    sample_reads: int,
    set_buffer_size: int,
) -> BackendResult:
    cap = None
    try:
        cap = cv2.VideoCapture(device_index, backend)
        if not cap.isOpened():
            return BackendResult(
                backend_name=backend_name,
                opened=False,
                width=None,
                height=None,
                fps_property=None,
                buffer_size_property=None,
                mean_read_ms=None,
                median_read_ms=None,
                effective_fps=None,
                successful_reads=0,
                error="failed to open",
            )

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        if set_buffer_size >= 0:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, set_buffer_size)

        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
        actual_buffer_size = float(cap.get(cv2.CAP_PROP_BUFFERSIZE))

        for _ in range(warmup_frames):
            ok, _ = cap.read()
            if not ok:
                return BackendResult(
                    backend_name=backend_name,
                    opened=True,
                    width=actual_width,
                    height=actual_height,
                    fps_property=actual_fps,
                    buffer_size_property=actual_buffer_size,
                    mean_read_ms=None,
                    median_read_ms=None,
                    effective_fps=None,
                    successful_reads=0,
                    error="warmup read failed",
                )

        read_times_ms: list[float] = []
        successful_reads = 0
        sample_start = time.perf_counter()
        for _ in range(sample_reads):
            read_start = time.perf_counter()
            ok, frame = cap.read()
            read_end = time.perf_counter()
            if not ok or frame is None:
                break
            successful_reads += 1
            read_times_ms.append((read_end - read_start) * 1000.0)
        sample_elapsed = time.perf_counter() - sample_start

        if not read_times_ms:
            return BackendResult(
                backend_name=backend_name,
                opened=True,
                width=actual_width,
                height=actual_height,
                fps_property=actual_fps,
                buffer_size_property=actual_buffer_size,
                mean_read_ms=None,
                median_read_ms=None,
                effective_fps=None,
                successful_reads=0,
                error="sample reads failed",
            )

        return BackendResult(
            backend_name=backend_name,
            opened=True,
            width=actual_width,
            height=actual_height,
            fps_property=actual_fps,
            buffer_size_property=actual_buffer_size,
            mean_read_ms=statistics.mean(read_times_ms),
            median_read_ms=statistics.median(read_times_ms),
            effective_fps=(successful_reads / sample_elapsed) if sample_elapsed > 0 else None,
            successful_reads=successful_reads,
            error=None if successful_reads == sample_reads else "did not complete all sample reads",
        )
    except Exception as exc:
        return BackendResult(
            backend_name=backend_name,
            opened=False,
            width=None,
            height=None,
            fps_property=None,
            buffer_size_property=None,
            mean_read_ms=None,
            median_read_ms=None,
            effective_fps=None,
            successful_reads=0,
            error=str(exc),
        )
    finally:
        if cap is not None:
            cap.release()


def print_backend_result(result: BackendResult) -> None:
    print(f"  opened: {result.opened}")
    if result.width is not None and result.height is not None:
        print(f"  resolution: {result.width}x{result.height}")
    if result.fps_property is not None:
        print(f"  fps property: {result.fps_property}")
    if result.buffer_size_property is not None:
        print(f"  buffer size property: {result.buffer_size_property}")
    if result.mean_read_ms is not None:
        print(f"  mean read time: {result.mean_read_ms:.2f} ms")
    if result.median_read_ms is not None:
        print(f"  median read time: {result.median_read_ms:.2f} ms")
    if result.effective_fps is not None:
        print(f"  effective fps: {result.effective_fps:.2f}")
    print(f"  successful reads: {result.successful_reads}")
    if result.error is not None:
        print(f"  error: {result.error}")


def choose_best_result(results: Iterable[BackendResult]) -> BackendResult | None:
    valid_results = [result for result in results if result.mean_read_ms is not None]
    if not valid_results:
        return None
    return min(valid_results, key=lambda result: result.mean_read_ms or float("inf"))


def format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())