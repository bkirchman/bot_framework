from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class InitProfile:
    name: str
    width: int | None
    height: int | None
    fps: float | None
    fourcc: str | None
    buffer_size: int | None
    warmup_reads: int


@dataclass(frozen=True)
class ProbeResult:
    backend: str
    profile: str
    opened: bool
    first_read_ok: bool
    actual_width: float | None
    actual_height: float | None
    actual_fps: float | None
    actual_buffer_size: float | None
    error: str | None


def main() -> int:
    args = parse_args()
    cv2 = import_cv2()
    backends = resolve_backends(cv2)
    profiles = build_profiles()

    lines = [
        f"Testing device_index={args.device_index}",
        "",
    ]
    found_working_method = False
    for backend_name, backend_value in backends:
        lines.append(f"[{backend_name}]")
        for profile in profiles:
            result = probe_method(
                cv2=cv2,
                device_index=args.device_index,
                backend_name=backend_name,
                backend_value=backend_value,
                profile=profile,
            )
            lines.extend(format_result(result))
            if result.opened and result.first_read_ok:
                found_working_method = True
        lines.append("")

    report = "\n".join(lines).rstrip() + "\n"
    print(report)
    if args.output is not None:
        args.output.write_text(report, encoding="utf-8")
    return 0 if found_working_method else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test capture initialization methods for a device index.")
    parser.add_argument("--device-index", type=int, default=1)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to test capture methods") from exc
    return cv2


def resolve_backends(cv2: Any) -> list[tuple[str, int]]:
    return [
        ("msmf", cv2.CAP_MSMF),
        ("dshow", cv2.CAP_DSHOW),
        ("any", cv2.CAP_ANY),
    ]


def build_profiles() -> list[InitProfile]:
    return [
        InitProfile("bare_open", None, None, None, None, None, 0),
        InitProfile("default_warmup", None, None, None, None, None, 10),
        InitProfile("vga30", 640, 480, 30.0, None, None, 5),
        InitProfile("vga30_mjpg", 640, 480, 30.0, "MJPG", 1, 5),
        InitProfile("hd60", 1920, 1080, 60.0, None, 1, 10),
        InitProfile("hd60_mjpg", 1920, 1080, 60.0, "MJPG", 1, 10),
    ]


def probe_method(
    *,
    cv2: Any,
    device_index: int,
    backend_name: str,
    backend_value: int,
    profile: InitProfile,
) -> ProbeResult:
    capture = None
    try:
        capture = cv2.VideoCapture(device_index, backend_value)
        if not capture.isOpened():
            return ProbeResult(backend_name, profile.name, False, False, None, None, None, None, "failed to open")

        if profile.width is not None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, profile.width)
        if profile.height is not None:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, profile.height)
        if profile.fps is not None:
            capture.set(cv2.CAP_PROP_FPS, profile.fps)
        if profile.fourcc is not None:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*profile.fourcc))
        if profile.buffer_size is not None:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, profile.buffer_size)

        for _ in range(profile.warmup_reads):
            ok, _ = capture.read()
            if not ok:
                return build_result(capture, backend_name, profile.name, True, False, "warmup read failed")

        ok, frame = capture.read()
        if not ok or frame is None:
            return build_result(capture, backend_name, profile.name, True, False, "final read failed")

        return build_result(capture, backend_name, profile.name, True, True, None)
    except Exception as exc:
        return ProbeResult(backend_name, profile.name, False, False, None, None, None, None, str(exc))
    finally:
        if capture is not None:
            capture.release()


def build_result(
    capture: Any,
    backend_name: str,
    profile_name: str,
    opened: bool,
    first_read_ok: bool,
    error: str | None,
) -> ProbeResult:
    cv2 = import_cv2()
    return ProbeResult(
        backend=backend_name,
        profile=profile_name,
        opened=opened,
        first_read_ok=first_read_ok,
        actual_width=float(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        actual_height=float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        actual_fps=float(capture.get(cv2.CAP_PROP_FPS)),
        actual_buffer_size=float(capture.get(cv2.CAP_PROP_BUFFERSIZE)),
        error=error,
    )


def format_result(result: ProbeResult) -> Iterable[str]:
    yield (
        f"  {result.profile}: opened={result.opened} read={result.first_read_ok} "
        f"size={format_dim(result.actual_width)}x{format_dim(result.actual_height)} "
        f"fps={format_float(result.actual_fps)} buffer={format_float(result.actual_buffer_size)}"
    )
    if result.error is not None:
        yield f"    error={result.error}"


def format_dim(value: float | None) -> str:
    if value is None:
        return "n/a"
    return str(int(value))


def format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())