from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

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