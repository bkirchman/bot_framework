from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.contrib.hardware.avermedia import AVerMediaCapture
from framework.contrib.hardware import CaptureDeviceInfo, ReplayCapture, UDPXboxOutput, list_capture_devices
from framework.interfaces import Action


class _FakeFrame:
    def __init__(self, mean_value: float) -> None:
        self._mean_value = mean_value

    def mean(self) -> float:
        return self._mean_value

    def copy(self) -> "_FakeFrame":
        return _FakeFrame(self._mean_value)


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
            return True, _FakeFrame(255.0)

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
            return True, _FakeFrame(255.0)

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


def test_avermedia_capture_warmup_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCapture:
        def __init__(self, device_index: int, backend: int) -> None:
            self._reads = 0

        def isOpened(self) -> bool:
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, object]:
            self._reads += 1
            if self._reads < 3:
                return True, _FakeFrame(0.0)
            return True, _FakeFrame(10.0)

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

    perf_values = iter([100.0, 100.01, 100.02, 100.03])
    monkeypatch.setattr(AVerMediaCapture, "_import_cv2", staticmethod(lambda: fake_cv2))
    monkeypatch.setattr("framework.contrib.hardware.avermedia.time.perf_counter", lambda: next(perf_values))
    monkeypatch.setattr(AVerMediaCapture, "_measure_achieved_fps", lambda self: 60.0)

    capture = AVerMediaCapture(device_index=1, backend="dshow", open_settle_seconds=0.0)
    try:
        assert capture.warmup_completed is True
        assert capture.warmup_frames_discarded == 3
        assert capture.warmup_elapsed_ms == pytest.approx(30.0)
    finally:
        capture.close()


def test_avermedia_capture_warmup_timeout_warns_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCapture:
        def __init__(self, device_index: int, backend: int) -> None:
            self.read_count = 0

        def isOpened(self) -> bool:
            return True

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, object]:
            self.read_count += 1
            return True, _FakeFrame(0.0)

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

    perf_values = iter([50.0, 50.001])
    monkeypatch.setattr(AVerMediaCapture, "_import_cv2", staticmethod(lambda: fake_cv2))
    monkeypatch.setattr("framework.contrib.hardware.avermedia.time.perf_counter", lambda: next(perf_values))
    monkeypatch.setattr(AVerMediaCapture, "_measure_achieved_fps", lambda self: 60.0)

    with pytest.warns(RuntimeWarning, match="capture may be starting on a black screen"):
        capture = AVerMediaCapture(
            device_index=1,
            backend="dshow",
            open_settle_seconds=0.0,
            warmup_timeout_ms=0,
        )

    try:
        assert capture.warmup_completed is False
        assert capture.warmup_frames_discarded == 1
        assert capture.warmup_elapsed_ms == pytest.approx(1.0)
    finally:
        capture.close()


@pytest.fixture
def fake_named_capture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        time=0.0,
        read_interval=1.0 / 60.0,
        devices={},
        opened=[],
        instances=[],
        enumerated=[],
        failed_backends=set(),
    )

    class FakeCapture:
        def __init__(self, index: int, backend: int) -> None:
            self.index = index
            self.backend = backend
            self.reads = 0
            self.released = False
            state.opened.append((index, backend))
            state.instances.append(self)

        def isOpened(self) -> bool:
            return self.backend not in state.failed_backends

        def set(self, prop: int, value: float) -> bool:
            return True

        def read(self) -> tuple[bool, _FakeFrame]:
            self.reads += 1
            state.time += state.read_interval
            return True, _FakeFrame(10.0)

        def getBackendName(self) -> str:
            return "DSHOW"

        def release(self) -> None:
            self.released = True

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

    def enumerate_cameras(backend: int) -> list[SimpleNamespace]:
        state.enumerated.append(backend)
        return state.devices.get(backend, [])

    state.cv2 = fake_cv2
    monkeypatch.setattr(AVerMediaCapture, "_import_cv2", staticmethod(lambda: fake_cv2))
    monkeypatch.setattr("framework.contrib.hardware.avermedia.time.perf_counter", lambda: state.time)
    monkeypatch.setitem(sys.modules, "cv2_enumerate_cameras", SimpleNamespace(enumerate_cameras=enumerate_cameras))
    return state


def _camera(index: int, name: str, path: str | None) -> SimpleNamespace:
    return SimpleNamespace(index=index, name=name, path=path)


def test_list_capture_devices_preserves_backend_indices(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[700] = [_camera(2, "Capture A", "path-a")]
    fake_named_capture.devices[0] = [_camera(702, "Capture A", "path-a")]
    assert list_capture_devices("dshow") == [CaptureDeviceInfo(2, "Capture A", "path-a", "dshow")]
    assert list_capture_devices("any") == [CaptureDeviceInfo(702, "Capture A", "path-a", "any")]
    assert fake_named_capture.enumerated == [700, 0]


def test_avermedia_capture_selects_name_and_preserves_frame_ids(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[700] = [
        _camera(0, "Other camera", "path-other"),
        _camera(2, "Capture A", "path-a"),
    ]
    capture = AVerMediaCapture(device_name="capture a", fps_check_frames=4, open_settle_seconds=0)
    try:
        assert fake_named_capture.opened == [(2, 700)]
        assert fake_named_capture.instances[0].reads == 5
        assert capture.device_name_resolved == "Capture A"
        assert capture.device_path == "path-a"
        assert capture.device_index_resolved == 2
        assert capture.active_backend == "dshow"
        assert capture.achieved_fps == pytest.approx(60)
        assert capture.get_frame().frame_id == 0
        assert capture.get_frame().frame_id == 1
    finally:
        capture.close()


@pytest.mark.parametrize("names", [["Other", "Unrelated"], ["Capture A", "Capture A second"]])
def test_avermedia_capture_name_mismatch_lists_every_device(
    fake_named_capture: SimpleNamespace, names: list[str]
) -> None:
    fake_named_capture.devices[700] = [
        _camera(index, name, f"path-{index}") for index, name in enumerate(names)
    ]
    with pytest.raises(RuntimeError, match="Enumerated devices") as exc:
        AVerMediaCapture(device_name="capture a", open_settle_seconds=0)
    assert f"matched {0 if names[0] == 'Other' else 2} devices" in str(exc.value)
    for index, name in enumerate(names):
        assert f"index={index}" in str(exc.value)
        assert name in str(exc.value)
        assert f"path-{index}" in str(exc.value)
    assert fake_named_capture.opened == []
    assert fake_named_capture.enumerated == [700]


def test_avermedia_capture_rejects_both_or_neither_selector() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AVerMediaCapture()
    with pytest.raises(ValueError, match="exactly one"):
        AVerMediaCapture(device_index=0, device_name="Capture A")


def test_avermedia_capture_reresolves_name_on_backend_fallback(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[1400] = [_camera(1, "Capture A", "path-msmf")]
    fake_named_capture.devices[700] = [_camera(3, "Capture A", "path-dshow")]
    fake_named_capture.failed_backends.add(1400)
    capture = AVerMediaCapture(device_name="capture", backend="msmf", open_settle_seconds=0)
    try:
        assert fake_named_capture.enumerated == [1400, 700]
        assert fake_named_capture.opened == [(1, 1400), (3, 700)]
        assert fake_named_capture.instances[0].released
        assert capture.device_index_resolved == 3
        assert capture.device_path == "path-dshow"
        assert capture.active_backend == "dshow"
    finally:
        capture.close()


def test_avermedia_capture_backend_fallback_does_not_fall_back_to_index(
    fake_named_capture: SimpleNamespace,
) -> None:
    fake_named_capture.devices[1400] = [_camera(1, "Capture A", "path-msmf")]
    fake_named_capture.devices[700] = [_camera(1, "Other", "path-other")]
    fake_named_capture.failed_backends.add(1400)
    with pytest.raises(RuntimeError, match="matched 0 devices") as exc:
        AVerMediaCapture(device_name="Capture A", backend="msmf", open_settle_seconds=0)
    assert "Other" in str(exc.value)
    assert fake_named_capture.opened == [(1, 1400)]
    assert fake_named_capture.instances[0].released


def test_avermedia_capture_opens_encoded_any_backend_index(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[0] = [_camera(702, "Capture A", "path-a")]
    capture = AVerMediaCapture(device_name="Capture A", backend="any", open_settle_seconds=0)
    try:
        assert fake_named_capture.opened == [(702, 0)]
        assert capture.device_index_resolved == 702
        assert capture.active_backend == "dshow"
    finally:
        capture.close()


def test_avermedia_capture_rejects_degraded_fps_and_releases(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[700] = [_camera(2, "Capture A", "path-a")]
    fake_named_capture.read_interval = 1.0 / 27.0
    with pytest.raises(RuntimeError, match=r"Capture A.*27\.0 fps.*configured 60\.0 fps"):
        AVerMediaCapture(device_name="Capture A", fps_check_frames=5, open_settle_seconds=0)
    assert fake_named_capture.instances[0].reads == 6
    assert fake_named_capture.instances[0].released


@pytest.mark.parametrize(("actual_fps", "passes"), [(53.0, False), (55.0, True)])
def test_avermedia_capture_enforces_fps_fraction(
    fake_named_capture: SimpleNamespace, actual_fps: float, passes: bool
) -> None:
    fake_named_capture.devices[700] = [_camera(2, "Capture A", "path-a")]
    fake_named_capture.read_interval = 1.0 / actual_fps
    if passes:
        capture = AVerMediaCapture(device_name="Capture A", open_settle_seconds=0)
        try:
            assert capture.achieved_fps == pytest.approx(actual_fps)
        finally:
            capture.close()
    else:
        with pytest.raises(RuntimeError, match="minimum 54.0 fps"):
            AVerMediaCapture(device_name="Capture A", open_settle_seconds=0)
        assert fake_named_capture.instances[0].released


def test_avermedia_capture_allows_configured_fps_fraction(fake_named_capture: SimpleNamespace) -> None:
    fake_named_capture.devices[700] = [_camera(2, "Capture A", "path-a")]
    fake_named_capture.read_interval = 1.0 / 27.0
    capture = AVerMediaCapture(device_name="Capture A", min_fps_fraction=0.4, open_settle_seconds=0)
    try:
        assert capture.achieved_fps == pytest.approx(27)
    finally:
        capture.close()


def test_avermedia_capture_index_does_not_import_enumerator(
    fake_named_capture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "cv2_enumerate_cameras", None)
    capture = AVerMediaCapture(device_index=4, open_settle_seconds=0)
    try:
        assert fake_named_capture.opened == [(4, 700)]
        assert capture.device_index_resolved == 4
        assert capture.device_name_resolved == "index 4"
        assert capture.device_path is None
        assert capture.achieved_fps == pytest.approx(60)
    finally:
        capture.close()


def test_avermedia_capture_missing_enumerator_reports_install_command(
    fake_named_capture: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "cv2_enumerate_cameras", None)
    with pytest.raises(RuntimeError, match=r"cv2_enumerate_cameras.*python -m pip install"):
        AVerMediaCapture(device_name="Capture A", open_settle_seconds=0)
    assert fake_named_capture.opened == []


@pytest.mark.parametrize(
    ("fps_check_frames", "min_fps_fraction", "fps", "device_name"),
    [
        (1, 0.9, 60.0, "Capture A"),
        (True, 0.9, 60.0, "Capture A"),
        (60, 0.0, 60.0, "Capture A"),
        (60, float("nan"), 60.0, "Capture A"),
        (60, 0.9, float("nan"), "Capture A"),
        (60, 0.9, 60.0, ""),
    ],
)
def test_avermedia_capture_rejects_invalid_fps_check_configuration(
    fps_check_frames: int, min_fps_fraction: float, fps: float, device_name: str
) -> None:
    with pytest.raises(ValueError):
        AVerMediaCapture(
            device_name=device_name,
            fps_check_frames=fps_check_frames,
            min_fps_fraction=min_fps_fraction,
            fps=fps,
        )