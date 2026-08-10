from __future__ import annotations

import threading
import time
import warnings
from pathlib import Path

import pytest

from framework.contrib.recording import FrameRecorder
from framework.interfaces import Action, StampedFrame


class _FrameData:
    def __init__(self, value: int) -> None:
        self.value = value

    def copy(self) -> "_FrameData":
        return _FrameData(self.value)


def _frame(frame_id: int) -> StampedFrame:
    return StampedFrame(frame_id=frame_id, timestamp=frame_id / 60.0, frame=_FrameData(frame_id))


def test_record_enqueue_returns_without_blocking_on_encode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FrameRecorder(tmp_path, max_queue_size=4)
    release_encode = threading.Event()
    encode_threads: list[int] = []

    def _slow_encode(frame: StampedFrame) -> None:
        encode_threads.append(threading.get_ident())
        release_encode.wait(timeout=1.0)

    monkeypatch.setattr(recorder, "_write_frame_jpeg", _slow_encode)

    started = time.perf_counter()
    recorder.record(_frame(0), None)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05

    deadline = time.perf_counter() + 0.5
    while not encode_threads and time.perf_counter() < deadline:
        time.sleep(0.005)

    assert encode_threads
    assert encode_threads[0] != threading.get_ident()

    release_encode.set()
    recorder.close()


def test_full_queue_drops_frames_without_blocking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FrameRecorder(tmp_path, max_queue_size=1)
    release_encode = threading.Event()

    def _blocked_encode(frame: StampedFrame) -> None:
        release_encode.wait(timeout=1.0)

    monkeypatch.setattr(recorder, "_write_frame_jpeg", _blocked_encode)

    recorder.record(_frame(0), None)
    recorder.record(_frame(1), None)
    started = time.perf_counter()
    recorder.record(_frame(2), None)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert recorder.dropped_frames >= 1

    release_encode.set()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        recorder.close()


def test_close_drains_queue_writing_non_dropped_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FrameRecorder(tmp_path, max_queue_size=16)
    written_ids: list[int] = []

    def _capture_write(frame: StampedFrame) -> None:
        written_ids.append(frame.frame_id)

    monkeypatch.setattr(recorder, "_write_frame_jpeg", _capture_write)

    recorder.record(_frame(0), Action(frame_id=0, timestamp=0.0, payload={"a": 1}))
    recorder.record(_frame(1), None)
    recorder.record(_frame(2), None)
    recorder.close()

    assert written_ids == [0, 1, 2]
    assert recorder.dropped_frames == 0
    assert recorder.written_frames == 3


def test_close_warns_once_when_frames_are_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FrameRecorder(tmp_path, max_queue_size=1)
    release_encode = threading.Event()

    def _blocked_encode(frame: StampedFrame) -> None:
        release_encode.wait(timeout=1.0)

    monkeypatch.setattr(recorder, "_write_frame_jpeg", _blocked_encode)

    recorder.record(_frame(0), None)
    recorder.record(_frame(1), None)
    recorder.record(_frame(2), None)

    release_encode.set()
    with pytest.warns(RuntimeWarning, match="FrameRecorder dropped"):
        recorder.close()


def test_close_emits_no_drop_warning_when_no_frames_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = FrameRecorder(tmp_path, max_queue_size=8)

    def _fast_encode(frame: StampedFrame) -> None:
        _ = frame.frame_id

    monkeypatch.setattr(recorder, "_write_frame_jpeg", _fast_encode)

    recorder.record(_frame(0), None)
    recorder.record(_frame(1), None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        recorder.close()

    assert all("FrameRecorder dropped" not in str(item.message) for item in caught)
