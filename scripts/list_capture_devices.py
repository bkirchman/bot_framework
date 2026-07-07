from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class BackendSpec:
    name: str
    cv2_value: int


def main() -> int:
    args = parse_args()
    cv2 = import_cv2()
    backends = resolve_backends(cv2, args.backends)
    devices = list(probe_devices(cv2, range(args.start_index, args.start_index + args.count), backends))
    windows_devices = list_windows_video_devices()
    report_lines: list[str] = []

    if windows_devices:
        report_lines.append("Windows video devices:")
        for device in windows_devices:
            report_lines.append(device)
    else:
        report_lines.append("Windows video devices: none detected")

    report_lines.append("OpenCV index probe:")

    if not devices:
        report_lines.append("No capture devices were detected by OpenCV.")
        emit_report(report_lines, args.output)
        return 1

    for line in devices:
        report_lines.append(line)
    emit_report(report_lines, args.output)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List OpenCV capture devices that can be opened and read.")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument(
        "--backends",
        nargs="+",
        default=["msmf", "dshow", "any"],
        help="Backends to probe, in order.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def import_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to list capture devices") from exc
    return cv2


def emit_report(lines: Sequence[str], output_path: Path | None) -> None:
    report = "\n".join(lines)
    print(report)
    if output_path is not None:
        output_path.write_text(report + "\n", encoding="utf-8")


def list_windows_video_devices() -> list[str]:
    script = """
$ErrorActionPreference = 'Stop'
$devices = @()
if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
    $devices = Get-PnpDevice | Where-Object {
        $_.Class -in @('Camera', 'Image') -or $_.FriendlyName -match 'AVerMedia|capture|camera|video|webcam'
    } | Select-Object FriendlyName, Class, Status
} elseif (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
    $devices = Get-CimInstance Win32_PnPEntity | Where-Object {
        $_.PNPClass -in @('Camera', 'Image') -or $_.Name -match 'AVerMedia|capture|camera|video|webcam'
    } | Select-Object @{Name='FriendlyName';Expression={$_.Name}}, @{Name='Class';Expression={$_.PNPClass}}, Status
}
$devices | ConvertTo-Json -Compress
""".strip()

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except OSError:
        return []
    except subprocess.TimeoutExpired:
        return []

    raw_output = result.stdout.strip()
    if result.returncode != 0 or not raw_output:
        return []

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return [raw_output]

    if isinstance(parsed, dict):
        parsed = [parsed]

    devices: list[str] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("FriendlyName") or "unknown")
        device_class = str(item.get("Class") or "unknown")
        status = str(item.get("Status") or "unknown")
        devices.append(f"name={name} class={device_class} status={status}")
    return devices


def resolve_backends(cv2: object, backend_names: Sequence[str]) -> list[BackendSpec]:
    backend_map = {
        "any": BackendSpec("any", cv2.CAP_ANY),
        "auto": BackendSpec("any", cv2.CAP_ANY),
        "dshow": BackendSpec("dshow", cv2.CAP_DSHOW),
        "directshow": BackendSpec("dshow", cv2.CAP_DSHOW),
        "msmf": BackendSpec("msmf", cv2.CAP_MSMF),
        "mediafoundation": BackendSpec("msmf", cv2.CAP_MSMF),
    }

    resolved: list[BackendSpec] = []
    for backend_name in backend_names:
        try:
            spec = backend_map[backend_name.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported backend: {backend_name}") from exc
        if spec not in resolved:
            resolved.append(spec)
    return resolved


def probe_devices(cv2: object, indexes: Iterable[int], backends: Sequence[BackendSpec]) -> Iterable[str]:
    for device_index in indexes:
        for backend in backends:
            details = probe_device(cv2, device_index, backend)
            if details is None:
                continue
            yield details
            break


def probe_device(cv2: object, device_index: int, backend: BackendSpec) -> str | None:
    capture = cv2.VideoCapture(device_index, backend.cv2_value)
    try:
        if not capture.isOpened():
            return None

        ok, frame = capture.read()
        if not ok or frame is None:
            return f"index={device_index} backend={backend.name} opened=yes read=no"

        height, width = frame.shape[:2]
        fps = capture.get(cv2.CAP_PROP_FPS)
        return f"index={device_index} backend={backend.name} opened=yes read=yes width={width} height={height} fps={fps:.2f}"
    finally:
        capture.release()


if __name__ == "__main__":
    raise SystemExit(main())