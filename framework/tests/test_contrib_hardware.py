from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.contrib.hardware.avermedia import AVerMediaCapture
from framework.contrib.hardware import ReplayCapture, UDPXboxOutput
from framework.interfaces import Action


def test_replay_capture_emits_stamped_frames_at_configured_rate(tmp_path: Path) -> None:
    (tmp_path / "000.txt").write_text("frame-0", encoding="utf-8")
    (tmp_path / "001.txt").write_text("frame-1", encoding="utf-8")
    (tmp_path / "002.txt").write_text("frame-2", encoding="utf-8")

    capture = ReplayCapture(
        tmp_path,
        fps=20.0,
        latency_frames=4,
        loader=lambda path: path.read_text(encoding="utf-8"),
    )

    first = capture.get_frame()
    second = capture.get_frame()
    third = capture.get_frame()

    assert capture.fps == 20.0
    assert capture.latency_frames == 4
    assert first.frame_id == 0
    assert second.frame_id == 1
    assert third.frame_id == 2
    assert first.frame == "frame-0"
    assert second.frame == "frame-1"
    assert third.frame == "frame-2"
    assert first.timestamp < second.timestamp < third.timestamp
    assert second.timestamp - first.timestamp == pytest.approx(0.05)
    assert third.timestamp - second.timestamp == pytest.approx(0.05)

    with pytest.raises(IndexError):
        capture.get_frame()


def test_replay_capture_requires_non_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ReplayCapture(tmp_path)


def test_udp_xbox_output_sends_json_payload_over_udp() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(1.0)
    host, port = receiver.getsockname()

    output = UDPXboxOutput(udp_ip=host, udp_port=port, response_mode=2)
    try:
        action = Action(frame_id=7, timestamp=12.5, payload={"aim_x": 25, "aim_y": -10})
        output.execute(action)

        data, _ = receiver.recvfrom(1024)
        payload = json.loads(data.decode("utf-8").strip())

        assert payload["aim_x"] == 25
        assert payload["aim_y"] == -10
        assert payload["resp"] == 2
        assert payload["seq"] == 1
    finally:
        output.close()
        receiver.close()


def test_udp_xbox_output_requires_mapping_payload() -> None:
    output = UDPXboxOutput(udp_ip="127.0.0.1", udp_port=9)
    try:
        action = Action(frame_id=1, timestamp=1.0, payload="fire")
        with pytest.raises(TypeError):
            output.execute(action)
    finally:
        output.close()


def test_avermedia_capture_uses_configured_backend_and_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    set_calls: list[tuple[int, float]] = []
    sleep_calls: list[float] = []

    class FakeCapture:
        def __init__(self, device_index: int, backend: int) -> None:
            calls.append((device_index, backend))

        def isOpened(self) -> bool:
            return True

        def set(self, prop: int, value: float) -> bool:
            set_calls.append((prop, value))
            return True

        def read(self) -> tuple[bool, object]:
            return True, SimpleNamespace(copy=lambda: SimpleNamespace(copy=lambda: None))

        def release(self) -> None:
            return None

    fake_cv2 = SimpleNamespace(
        CAP_ANY=0,
        CAP_DSHOW=700,
        CAP_MSMF=1400,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        CAP_PROP_FOURCC=6,
        CAP_PROP_BUFFERSIZE=38,
        VideoCapture=FakeCapture,
        VideoWriter_fourcc=lambda *args: 1196444237,
    )
    monkeypatch.setattr(AVerMediaCapture, "_import_cv2", staticmethod(lambda: fake_cv2))
    monkeypatch.setattr("framework.contrib.hardware.avermedia.time.sleep", sleep_calls.append)

    capture = AVerMediaCapture(device_index=1, backend="msmf", buffer_size=1)
    capture.close()

    assert calls == [(1, fake_cv2.CAP_MSMF)]
    assert (fake_cv2.CAP_PROP_BUFFERSIZE, 1) in set_calls
    assert sleep_calls == [0.2]


def test_avermedia_capture_falls_back_from_msmf_to_dshow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    class FakeCapture:
        def __init__(self, device_index: int, backend: int) -> None:
            calls.append((device_index, backend))
            self._backend = backend

        def isOpened(self) -> bool:
            return self._backend != fake_cv2.CAP_MSMF

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, object]:
            return True, SimpleNamespace(copy=lambda: SimpleNamespace(copy=lambda: None))

        def grab(self) -> bool:
            return True

        def release(self) -> None:
            return None

    fake_cv2 = SimpleNamespace(
        CAP_ANY=0,
        CAP_DSHOW=700,
        CAP_MSMF=1400,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        CAP_PROP_FOURCC=6,
        CAP_PROP_BUFFERSIZE=38,
        VideoCapture=FakeCapture,
        VideoWriter_fourcc=lambda *args: 1196444237,
    )
    monkeypatch.setattr(AVerMediaCapture, "_import_cv2", staticmethod(lambda: fake_cv2))

    capture = AVerMediaCapture(device_index=2, backend="msmf")
    capture.close()

    assert calls == [(2, fake_cv2.CAP_MSMF), (2, fake_cv2.CAP_DSHOW)]
    assert capture._active_backend_name == "dshow"


def test_avermedia_capture_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cv2 = SimpleNamespace(
        CAP_ANY=0,
        CAP_DSHOW=700,
        CAP_MSMF=1400,
    )
    instance = object.__new__(AVerMediaCapture)
    instance._cv2 = fake_cv2

    with pytest.raises(ValueError, match="Unsupported capture backend: bogus"):
        instance._resolve_backend("bogus")