"""Strategy Pattern — hoán đổi Mock AI / NCNN / YOLOv8 ONNX mà không đổi State Machine.

Hỗ trợ mô hình NCNN của Ultralytics YOLO (model.ncnn.param + model.ncnn.bin + metadata.yaml),
tối ưu hoá cao độ cho chip ARM Cortex-A72 trên Raspberry Pi 4 với tập lệnh NEON.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from config import (
    AI_CONFIDENCE_THRESHOLD,
    AI_INPUT_SIZE,
    AI_NUM_THREADS,
    AI_STRATEGY,
    MODEL_DIR,
    MODEL_PATH,
    NCNN_BIN_PATH,
    NCNN_METADATA_PATH,
    NCNN_PARAM_PATH,
)

DEFAULT_64_CLASSES: list[str] = [
    "Apple", "Apricot", "Asparagus", "Avocado", "Banana", "Beef", "Beetroot",
    "Bell Pepper", "Berry", "Cabbage", "Cantaloupe", "Carrot", "Cashew Nut",
    "Cauliflower", "Cherry", "Cherry Tomato", "Chestnut", "Chicken", "Coconut",
    "Corn", "Crab", "Cucumber", "Date", "Dragon Fruit", "Egg", "Eggplant",
    "Fig", "Fish", "Garlic", "Ginger", "Grape", "Grapefruit", "Green Beans",
    "Guava", "Kiwi", "Lamb", "Leek", "Lemon", "Lime", "Lobster", "Lychee",
    "Mango", "Mangosteen", "Mushroom", "Nectarine", "Orange", "Passion Fruit",
    "Peach", "Pear", "Pineapple", "Plum", "Pomegranate", "Pork", "Potato",
    "Rambutan", "Red Onion", "Shrimp", "Star Fruit", "Sweet Potato", "Tomato",
    "Walnut", "Watermelon", "White Onion", "Zucchini",
]

CLASS_NAMES: list[str] = DEFAULT_64_CLASSES


def load_metadata_names(metadata_path: Path | None = None) -> dict[int, str]:
    """Tự động đọc danh sách nhãn lớp từ metadata.yaml của Ultralytics YOLO."""
    target = metadata_path or NCNN_METADATA_PATH
    if not target.exists():
        return {i: name for i, name in enumerate(DEFAULT_64_CLASSES)}

    # Cách 1: Thử đọc bằng PyYAML nếu có
    try:
        import yaml

        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            raw_names = data.get("names", {})
            if isinstance(raw_names, dict):
                return {int(k): str(v) for k, v in raw_names.items()}
            elif isinstance(raw_names, list):
                return {i: str(v) for i, v in enumerate(raw_names)}
    except Exception:
        pass

    # Cách 2: Phân tích cú pháp YAML thủ công (không cần thư viện ngoài)
    names: dict[int, str] = {}
    try:
        in_names = False
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("names:"):
                    in_names = True
                    continue
                if in_names:
                    if not line.startswith(" ") and not line.startswith("\t"):
                        break
                    if ":" in stripped:
                        parts = stripped.split(":", 1)
                        try:
                            idx = int(parts[0].strip())
                            name = parts[1].strip().strip("'\"")
                            names[idx] = name
                        except ValueError:
                            continue
        if names:
            return names
    except Exception as exc:
        print(f"[AI] Cảnh báo đọc metadata.yaml: {exc}")

    return {i: name for i, name in enumerate(DEFAULT_64_CLASSES)}


def quality_from_label(label: str) -> str:
    """Xác định chất lượng FRESH (đạt chuẩn bán) hoặc ROTTEN (hư hỏng)."""
    if not label or label == "Unknown":
        return "ROTTEN"
    lower = label.lower()
    rotten_keywords = ("rotten", "bad", "decay", "mold", "hong", "hu_hong", "damaged")
    if any(k in lower for k in rotten_keywords):
        return "ROTTEN"
    return "FRESH"


class AIInferenceStrategy(ABC):
    name = "base"

    @property
    def is_ready(self) -> bool:
        return True

    @abstractmethod
    def predict(self, frame: np.ndarray, weight_gram: float) -> dict[str, Any]:
        raise NotImplementedError


class MockAIStrategy(AIInferenceStrategy):
    """Kết quả giả lập Fresh/Rotten — chạy thử toàn hệ thống trước khi gắn AI thật."""

    name = "mock"

    def __init__(self) -> None:
        self._forced: dict[str, Any] | None = None

    def force_next(self, label: str | None = None, quality: str | None = None) -> None:
        if not label and not quality:
            self._forced = None
            return
        if quality == "ROTTEN" and not label:
            label = "Rotten_Apple"
        if quality == "FRESH" and not label:
            label = "Apple"
        self._forced = {"label": label, "quality": quality_from_label(label or "Apple")}

    def predict(self, frame: np.ndarray, weight_gram: float) -> dict[str, Any]:
        started = time.perf_counter()
        time.sleep(0.08)

        if self._forced:
            label = self._forced["label"]
            quality = self._forced["quality"]
            self._forced = None
        else:
            fruits = ["Apple", "Banana", "Orange", "Mango", "Tomato", "Watermelon"]
            fruit = fruits[int(weight_gram) % len(fruits)]
            rotten = int(round(weight_gram)) % 7 == 0
            label = f"Rotten_{fruit}" if rotten else fruit
            quality = quality_from_label(label)

        h, w = frame.shape[:2]
        box = {
            "x1": int(w * 0.22),
            "y1": int(h * 0.18),
            "x2": int(w * 0.78),
            "y2": int(h * 0.82),
        }
        detections = [
            {
                "label": label,
                "confidence": 0.94 if quality == "FRESH" else 0.88,
                "box": box,
            }
        ]
        annotated = self.draw_detections(frame, detections)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return self._pack_result(detections, annotated, elapsed_ms, strategy="mock")

    @staticmethod
    def draw_detections(frame: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
        out = frame.copy()
        for det in detections:
            box = det["box"]
            quality = quality_from_label(det["label"])
            color = (40, 40, 220) if quality == "ROTTEN" else (40, 200, 80)
            cv2.rectangle(out, (box["x1"], box["y1"]), (box["x2"], box["y2"]), color, 2)
            caption = f"{det['label']} {det['confidence']:.2f}"
            cv2.putText(
                out,
                caption,
                (box["x1"], max(24, box["y1"] - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )
        return out

    @staticmethod
    def _pack_result(
        detections: list[dict[str, Any]],
        annotated: np.ndarray,
        inference_time_ms: int,
        strategy: str = "mock",
    ) -> dict[str, Any]:
        rotten_hits = [
            d
            for d in detections
            if quality_from_label(d["label"]) == "ROTTEN" and d["confidence"] >= AI_CONFIDENCE_THRESHOLD
        ]
        if rotten_hits:
            best = max(rotten_hits, key=lambda d: d["confidence"])
            quality = "ROTTEN"
        elif detections:
            best = max(detections, key=lambda d: d["confidence"])
            quality = quality_from_label(best["label"])
        else:
            best = {"label": "Unknown", "confidence": 0.0}
            quality = "ROTTEN"

        return {
            "detected_class": best["label"],
            "quality_status": quality,
            "confidence": round(float(best["confidence"]), 3),
            "inference_time_ms": inference_time_ms,
            "detections": detections,
            "annotated_frame": annotated,
            "strategy": strategy,
        }


class NCNNStrategy(AIInferenceStrategy):
    """Suy luận mô hình NCNN của Ultralytics YOLO trên CPU ARM NEON (Raspberry Pi 4).

    Hỗ trợ 2 backend thực thi:
    1. Thư viện 'ncnn' thuần: siêu nhẹ, tốc độ cao nhất, không phụ thuộc PyTorch.
    2. Thư viện 'ultralytics': nhận diện tự động thư mục model NCNN.
    Nếu chưa cài thư viện AI nào trên máy dev, tự động ủy thác mượt mà sang Mock.
    """

    name = "ncnn"

    def __init__(self) -> None:
        self.backend = "none"
        self._ncnn_net = None
        self._yolo = None
        self._fallback = MockAIStrategy()
        self.class_names = load_metadata_names(NCNN_METADATA_PATH)
        self.num_classes = len(self.class_names)
        self.input_size = AI_INPUT_SIZE
        self.num_threads = AI_NUM_THREADS

        # 1. Thử nạp bằng thư viện ncnn thuần (Ưu tiên số 1 trên Raspberry Pi 4)
        if NCNN_PARAM_PATH.exists() and NCNN_BIN_PATH.exists():
            try:
                import ncnn

                net = ncnn.Net()
                net.opt.use_vulkan_compute = False
                net.opt.num_threads = self.num_threads
                param_ret = net.load_param(str(NCNN_PARAM_PATH))
                bin_ret = net.load_model(str(NCNN_BIN_PATH))
                if param_ret == 0 and bin_ret == 0:
                    self._ncnn_net = net
                    self.backend = "ncnn"
                    print(
                        f"[AI] Đã nạp NCNN model thành công ({self.num_classes} classes, {self.num_threads} threads): "
                        f"{NCNN_PARAM_PATH.name}"
                    )
                    return
                else:
                    print(f"[AI] Lỗi load param={param_ret} hoặc bin={bin_ret}")
            except ImportError:
                pass
            except Exception as exc:
                print(f"[AI] Lỗi khi nạp ncnn: {exc}")

            # 2. Thử nạp bằng Ultralytics YOLO nếu có
            try:
                from ultralytics import YOLO

                # Ultralytics nhận diện cả folder model lẫn file .param
                model_target = str(MODEL_DIR) if (MODEL_DIR / "model.ncnn.param").exists() else str(NCNN_PARAM_PATH)
                self._yolo = YOLO(model_target, task="detect")
                self.backend = "ultralytics-ncnn"
                print(f"[AI] Đã nạp NCNN qua Ultralytics YOLO: {model_target}")
                return
            except ImportError:
                pass
            except Exception as exc:
                print(f"[AI] Lỗi khi nạp ultralytics: {exc}")

            print(
                "[AI] Phát hiện file model NCNN nhưng chưa có thư viện 'ncnn' hoặc 'ultralytics'.\n"
                "     -> Hệ thống sẽ chạy ở chế độ Mock AI an toàn.\n"
                "     -> Để kích hoạt AI thật trên Raspberry Pi 4, hãy chạy: pip install ncnn"
            )
        else:
            print(f"[AI] Chưa tìm thấy file NCNN ({NCNN_PARAM_PATH.name}) — NCNNStrategy chạy Mock")

    @property
    def is_ready(self) -> bool:
        return self.backend in {"ncnn", "ultralytics-ncnn"}

    def force_next(self, label: str | None = None, quality: str | None = None) -> None:
        self._fallback.force_next(label=label, quality=quality)

    def predict(self, frame: np.ndarray, weight_gram: float) -> dict[str, Any]:
        # Nếu có lệnh giả lập cưỡng bức từ thanh điều khiển sim-bar
        if self._fallback._forced is not None:
            return self._fallback.predict(frame, weight_gram)

        if not self.is_ready:
            res = self._fallback.predict(frame, weight_gram)
            res["strategy"] = "ncnn-fallback-mock"
            return res

        started = time.perf_counter()

        if self.backend == "ncnn":
            detections = self._predict_ncnn(frame)
        elif self.backend == "ultralytics-ncnn":
            detections = self._predict_ultralytics(frame)
        else:
            detections = []

        annotated = MockAIStrategy.draw_detections(frame, detections)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return MockAIStrategy._pack_result(detections, annotated, elapsed_ms, strategy=self.backend)

    def _predict_ncnn(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Suy luận trực tiếp qua C++ ncnn Net với tập lệnh NEON."""
        import ncnn

        h_orig, w_orig = frame.shape[:2]
        mat_in = ncnn.Mat.from_pixels_resize(
            frame,
            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            w_orig,
            h_orig,
            self.input_size,
            self.input_size,
        )
        norm_vals = [1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0]
        mat_in.substract_mean_normalize([], norm_vals)

        ex = self._ncnn_net.create_extractor()
        ex.set_num_threads(self.num_threads)
        ex.input("in0", mat_in)
        ret, mat_out = ex.extract("out0")
        if ret != 0:
            return []

        out = np.array(mat_out)
        return self._postprocess_ncnn(out, (h_orig, w_orig))

    def _postprocess_ncnn(self, output: np.ndarray, frame_shape: tuple[int, int]) -> list[dict[str, Any]]:
        """Hậu xử lý đầu ra NCNN YOLO: (68, 3549) gồm 4 box + 64 class scores."""
        out = np.squeeze(output)
        if out.ndim != 2:
            return []
        # Chuyển về shape (N_anchors, 4 + N_classes)
        if out.shape[0] < out.shape[1]:
            out = out.T

        h_orig, w_orig = frame_shape[:2]
        scale_x = w_orig / float(self.input_size)
        scale_y = h_orig / float(self.input_size)

        boxes: list[list[int]] = []
        confidences: list[float] = []
        class_ids: list[int] = []

        for row in out:
            if row.size < 5:
                continue
            cx, cy, bw, bh = row[:4]
            scores = row[4:]
            if scores.size == 0:
                continue
            cls_id = int(np.argmax(scores))
            conf = float(scores[cls_id])
            if conf < AI_CONFIDENCE_THRESHOLD:
                continue

            x1 = int((cx - bw / 2.0) * scale_x)
            y1 = int((cy - bh / 2.0) * scale_y)
            box_w = int(bw * scale_x)
            box_h = int(bh * scale_y)

            boxes.append([x1, y1, box_w, box_h])
            confidences.append(conf)
            class_ids.append(cls_id)

        if not boxes:
            return []

        # Non-Maximum Suppression chống trùng lặp box
        indices = cv2.dnn.NMSBoxes(boxes, confidences, AI_CONFIDENCE_THRESHOLD, 0.45)
        if len(indices) == 0:
            return []

        detections: list[dict[str, Any]] = []
        for idx in indices:
            i = int(idx[0]) if isinstance(idx, (list, tuple, np.ndarray)) else int(idx)
            x1, y1, box_w, box_h = boxes[i]
            x2 = min(w_orig, max(0, x1 + box_w))
            y2 = min(h_orig, max(0, y1 + box_h))
            x1 = max(0, min(w_orig - 1, x1))
            y1 = max(0, min(h_orig - 1, y1))
            cls_id = class_ids[i]
            label = self.class_names.get(cls_id, f"class_{cls_id}")
            detections.append(
                {
                    "label": label,
                    "confidence": round(confidences[i], 3),
                    "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                }
            )

        detections.sort(key=lambda d: d["confidence"], reverse=True)
        return detections[:8]

    def _predict_ultralytics(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Suy luận thông qua wrapper Ultralytics YOLO."""
        results = self._yolo(
            frame,
            imgsz=self.input_size,
            conf=AI_CONFIDENCE_THRESHOLD,
            verbose=False,
        )
        if not results:
            return []

        res = results[0]
        boxes = res.boxes
        if boxes is None or len(boxes) == 0:
            return []

        detections: list[dict[str, Any]] = []
        for box in boxes:
            cls_id = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].cpu().numpy().astype(int)
            label = self.class_names.get(cls_id, res.names.get(cls_id, f"class_{cls_id}"))
            detections.append(
                {
                    "label": label,
                    "confidence": round(conf, 3),
                    "box": {
                        "x1": int(xyxy[0]),
                        "y1": int(xyxy[1]),
                        "x2": int(xyxy[2]),
                        "y2": int(xyxy[3]),
                    },
                }
            )

        detections.sort(key=lambda d: d["confidence"], reverse=True)
        return detections[:8]


class YOLOv8Strategy(AIInferenceStrategy):
    """Suy luận YOLOv8 ONNX qua onnxruntime. Nếu chưa có model thì ủy thác sang Mock."""

    name = "yolov8"

    def __init__(self) -> None:
        self._session = None
        self._fallback = MockAIStrategy()
        self.class_names = load_metadata_names(NCNN_METADATA_PATH)
        if MODEL_PATH.exists():
            try:
                import onnxruntime as ort

                self._session = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
                print(f"[AI] Đã nạp ONNX: {MODEL_PATH}")
            except Exception as exc:
                print(f"[AI] Lỗi nạp ONNX, dùng Mock: {exc}")
        else:
            print(f"[AI] Chưa có {MODEL_PATH} — YOLOv8Strategy chạy Mock")

    @property
    def is_ready(self) -> bool:
        return self._session is not None

    def force_next(self, label: str | None = None, quality: str | None = None) -> None:
        self._fallback.force_next(label=label, quality=quality)

    def predict(self, frame: np.ndarray, weight_gram: float) -> dict[str, Any]:
        if self._fallback._forced is not None:
            return self._fallback.predict(frame, weight_gram)

        if self._session is None:
            result = self._fallback.predict(frame, weight_gram)
            result["strategy"] = "yolov8-fallback-mock"
            return result

        started = time.perf_counter()
        blob = self._preprocess(frame)
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: blob})
        detections = self._postprocess(outputs[0], frame.shape)
        annotated = MockAIStrategy.draw_detections(frame, detections)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return MockAIStrategy._pack_result(detections, annotated, elapsed_ms, strategy="yolov8")

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        img = cv2.resize(frame, (AI_INPUT_SIZE, AI_INPUT_SIZE))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))
        return np.expand_dims(img, 0)

    def _postprocess(self, output: np.ndarray, frame_shape: tuple[int, int]) -> list[dict[str, Any]]:
        data = np.squeeze(output)
        if data.ndim != 2:
            return []
        if data.shape[0] < data.shape[1]:
            data = data.T
        h, w = frame_shape[:2]
        detections: list[dict[str, Any]] = []
        for row in data:
            if row.size < 5:
                continue
            x, y, bw, bh = row[:4]
            scores = row[4:]
            if scores.size == 0:
                continue
            cls_id = int(np.argmax(scores))
            conf = float(scores[cls_id])
            if conf < AI_CONFIDENCE_THRESHOLD:
                continue
            label = self.class_names.get(cls_id, f"class_{cls_id}")
            detections.append(
                {
                    "label": label,
                    "confidence": round(conf, 3),
                    "box": {
                        "x1": int(max(0, (x - bw / 2) * w / AI_INPUT_SIZE)),
                        "y1": int(max(0, (y - bh / 2) * h / AI_INPUT_SIZE)),
                        "x2": int(min(w, (x + bw / 2) * w / AI_INPUT_SIZE)),
                        "y2": int(min(h, (y + bh / 2) * h / AI_INPUT_SIZE)),
                    },
                }
            )
        detections.sort(key=lambda d: d["confidence"], reverse=True)
        return detections[:8]


def build_ai_strategy(name: str | None = None) -> AIInferenceStrategy:
    """Factory Pattern: Tự động phát hiện và nạp Strategy tối ưu nhất."""
    key = (name or AI_STRATEGY).lower()

    # 1. Chế độ auto hoặc chỉ định ncnn: ưu tiên NCNN model nếu có đủ file
    if key in {"auto", "ncnn"}:
        if NCNN_PARAM_PATH.exists() and NCNN_BIN_PATH.exists():
            strat = NCNNStrategy()
            return strat
        if MODEL_PATH.exists():
            return YOLOv8Strategy()
        return MockAIStrategy()

    # 2. Chế độ ONNX / YOLO
    if key in {"yolo", "yolov8", "onnx"}:
        if MODEL_PATH.exists():
            return YOLOv8Strategy()
        if NCNN_PARAM_PATH.exists() and NCNN_BIN_PATH.exists():
            return NCNNStrategy()
        return MockAIStrategy()

    # 3. Chế độ mock mặc định
    return MockAIStrategy()
