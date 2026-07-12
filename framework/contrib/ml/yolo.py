from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from framework.interfaces import StampedFrame


@dataclass(frozen=True, slots=True)
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    frame_id: int


class YoloDetector:
    def __init__(
        self,
        weights_path: str | Path,
        class_map: dict[int, str],
        confidence_threshold: float,
        cadence: int = 1,
        roi: tuple[int, int, int, int] | None = None,
        device: str = "cuda",
    ) -> None:
        if cadence < 1:
            raise ValueError("cadence must be >= 1")
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        if roi is not None:
            x, y, w, h = roi
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                raise ValueError("roi must be (x, y, w, h) with non-negative origin and positive size")

        self._weights_path = str(weights_path)
        self._class_map = dict(class_map)
        self._confidence_threshold = float(confidence_threshold)
        self._cadence = int(cadence)
        self._roi = roi
        self._device = self._resolve_device(str(device))

        self._model: Any | None = None
        self._legacy_model: Any | None = None
        self._backend = "ultralytics"
        try:
            self._model = self._load_model(self._weights_path)
        except Exception as exc:
            if not self._should_fallback_to_legacy(exc):
                raise
            self._legacy_model = self._load_legacy_model(self._weights_path, self._device)
            self._backend = "yolov5"
        self._last_result: list[Detection] = []
        self._last_inference_frame_id: int | None = None

    @property
    def last_result(self) -> list[Detection]:
        return list(self._last_result)

    @property
    def last_inference_frame_id(self) -> int | None:
        return self._last_inference_frame_id

    def update(self, frame: StampedFrame) -> list[Detection]:
        if frame.frame_id % self._cadence != 0:
            return list(self._last_result)

        frame_for_model, offset = self._crop_for_model(frame.frame)
        if self._backend == "ultralytics":
            try:
                results = self._model.predict(
                    source=frame_for_model,
                    conf=self._confidence_threshold,
                    verbose=False,
                    device=self._device,
                )
                detections = self._parse_results(results, offset, origin_frame_id=frame.frame_id)
            except Exception as exc:
                if not self._should_fallback_to_legacy(exc):
                    raise
                self._legacy_model = self._load_legacy_model(self._weights_path, self._device)
                self._backend = "yolov5"
                detections = self._predict_legacy(frame_for_model, offset, frame.frame_id)
        else:
            detections = self._predict_legacy(frame_for_model, offset, frame.frame_id)

        self._last_result = detections
        self._last_inference_frame_id = frame.frame_id
        return list(self._last_result)

    def _crop_for_model(self, full_frame: Any) -> tuple[Any, tuple[int, int]]:
        if self._roi is None:
            return full_frame, (0, 0)

        x, y, w, h = self._roi
        cropped = full_frame[y : y + h, x : x + w]
        return cropped, (x, y)

    def _parse_results(
        self,
        results: list[Any],
        offset: tuple[int, int],
        origin_frame_id: int,
    ) -> list[Detection]:
        out: list[Detection] = []
        offset_x, offset_y = offset

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            for box in boxes:
                cls_id = int(box.cls.item())
                if cls_id not in self._class_map:
                    continue

                confidence = float(box.conf.item())
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = [int(round(v)) for v in xyxy]

                width = max(0, x2 - x1)
                height = max(0, y2 - y1)
                bbox = (x1 + offset_x, y1 + offset_y, width, height)

                out.append(
                    Detection(
                        class_name=self._class_map[cls_id],
                        confidence=confidence,
                        bbox=bbox,
                        frame_id=origin_frame_id,
                    )
                )

        return out

    @staticmethod
    def _load_model(weights_path: str) -> Any:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("ultralytics is required for YoloDetector") from exc

        return YOLO(weights_path)

    @staticmethod
    def _resolve_device(device: str) -> str:
        if not device.startswith("cuda"):
            return device

        try:
            import torch
        except ImportError:
            return "cpu"

        if not torch.cuda.is_available():
            return "cpu"
        return device

    def _predict_legacy(
        self,
        frame_for_model: Any,
        offset: tuple[int, int],
        origin_frame_id: int,
    ) -> list[Detection]:
        if self._legacy_model is None:
            raise RuntimeError("legacy YOLOv5 model is not initialized")

        prediction = self._legacy_model(frame_for_model)
        tensor = prediction.xyxy[0]
        rows = tensor.tolist()

        detections: list[Detection] = []
        offset_x, offset_y = offset
        for row in rows:
            x1, y1, x2, y2, confidence, cls_id = row
            class_id = int(cls_id)
            if class_id not in self._class_map:
                continue
            if float(confidence) < self._confidence_threshold:
                continue

            x1_i = int(round(x1))
            y1_i = int(round(y1))
            x2_i = int(round(x2))
            y2_i = int(round(y2))

            detections.append(
                Detection(
                    class_name=self._class_map[class_id],
                    confidence=float(confidence),
                    bbox=(
                        x1_i + offset_x,
                        y1_i + offset_y,
                        max(0, x2_i - x1_i),
                        max(0, y2_i - y1_i),
                    ),
                    frame_id=origin_frame_id,
                )
            )

        return detections

    @staticmethod
    def _should_fallback_to_legacy(exc: Exception) -> bool:
        msg = str(exc)
        markers = (
            "No module named 'yolov5'",
            "BaseModel.fuse() got an unexpected keyword argument 'verbose'",
        )
        return any(marker in msg for marker in markers)

    @staticmethod
    def _load_legacy_model(weights_path: str, device: str) -> Any:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("torch is required for legacy YOLOv5 checkpoint loading") from exc

        repo_override = os.getenv("YOLOV5_REPO_DIR")
        if repo_override:
            repo_path = Path(repo_override)
            if repo_path.exists():
                model = torch.hub.load(str(repo_path), "custom", path=weights_path, source="local")
            else:
                raise RuntimeError(f"YOLOV5_REPO_DIR does not exist: {repo_path}")
        else:
            model = torch.hub.load("ultralytics/yolov5", "custom", path=weights_path, trust_repo=True)

        model.conf = 0.0
        model.to(device)
        return model
