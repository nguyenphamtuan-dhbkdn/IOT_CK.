"""State Pattern — IDLE -> STABILIZING -> INSPECTING -> CHECKOUT."""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Callable

import cv2

from config import DETECT_WEIGHT_G, IDLE_WEIGHT_G
from core.pricing import select_pricing
from database import (
    get_product_by_label,
    insert_weighing_log,
    next_log_id,
    upsert_daily_analytics,
    utc_now_iso,
)
from hardware.lcd_i2c import LCDManager


class ScaleState(str, Enum):
    IDLE = "IDLE"
    STABILIZING = "STABILIZING"
    INSPECTING = "INSPECTING"
    CHECKOUT = "CHECKOUT"


class SmartScaleStateMachine:
    def __init__(
        self,
        scale,
        camera,
        ai_predict: Callable[[Any, float], dict[str, Any]],
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        lcd: LCDManager | None = None,
    ) -> None:
        self.state = ScaleState.IDLE
        self.scale = scale
        self.camera = camera
        self.ai_predict = ai_predict
        self.on_event = on_event or (lambda *_: None)
        self.lcd = lcd or LCDManager()
        self.last_result: dict[str, Any] | None = None
        self._lock = threading.Lock()

        # Cập nhật LCD ban đầu
        if self.lcd:
            self.lcd.display_state(self.state.value, 0.0)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        try:
            self.on_event(event, payload)
        except Exception as exc:
            print(f"[STATE] Lỗi emit {event}: {exc}")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state.value,
                "weight_gram": abs(float(self.scale.current_weight)),
                "is_stable": self.scale.is_stable,
                "result": self.last_result,
                "scale_online": self.scale.scale_online,
                "scale_calibrated": getattr(self.scale, "calibrated", False),
                "hardware": {
                    "scale": self.scale.scale_online,
                    "scale_calibrated": getattr(self.scale, "calibrated", False),
                    "camera": self.camera.hardware_available,
                    "lcd": self.lcd.hardware_available if self.lcd else False,
                },
            }

    def update(self) -> str:
        w = self.scale.read_filtered_weight()
        prev = self.state

        if self.state == ScaleState.IDLE:
            if w >= DETECT_WEIGHT_G:
                print(f"[STATE] Phát hiện vật nặng ({w}g) -> STABILIZING")
                self.state = ScaleState.STABILIZING

        elif self.state == ScaleState.STABILIZING:
            if w < IDLE_WEIGHT_G:
                self.state = ScaleState.IDLE
            elif self.scale.is_stable:
                print(f"[STATE] Cân ổn định {w}g -> INSPECTING")
                self.state = ScaleState.INSPECTING

        elif self.state == ScaleState.INSPECTING:
            self._run_inspection(w)
            self.state = ScaleState.CHECKOUT

        elif self.state == ScaleState.CHECKOUT:
            if w < IDLE_WEIGHT_G:
                print("[STATE] Đã lấy hàng -> IDLE")
                with self._lock:
                    self.last_result = None
                self.state = ScaleState.IDLE

        # Cập nhật màn hình LCD (chỉ tốn tài nguyên khi chuỗi thay đổi nhờ dirty-check)
        if self.lcd:
            self.lcd.display_state(self.state.value, w, self.last_result)

        if self.state != prev:
            self._emit("state_change", self.snapshot())
        return self.state.value

    def _run_inspection(self, weight_gram: float) -> None:
        frame = self.camera.get_frame()
        if frame is None:
            result = {
                "detected_class": "Unknown",
                "quality_status": "ROTTEN",
                "confidence": 0.0,
                "inference_time_ms": 0,
                "error": "Không lấy được khung hình camera",
            }
            billing = select_pricing("ROTTEN").quote(weight_gram, 0, "UNKNOWN")
            packed = self._persist(weight_gram, None, result, billing, None)
            with self._lock:
                self.last_result = packed
            if self.lcd:
                self.lcd.display_state("CHECKOUT", weight_gram, packed)
            self._emit("ai_result", packed)
            return

        prediction = self.ai_predict(frame, weight_gram)
        annotated = prediction.pop("annotated_frame", frame)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        rel_url = f"/static/captures/{stamp}.jpg"
        from config import CAPTURE_DIR

        cv2.imwrite(str(CAPTURE_DIR / f"{stamp}.jpg"), annotated)

        label = prediction.get("detected_class", "Unknown")
        quality = prediction.get("quality_status", "ROTTEN")
        product = get_product_by_label(label)
        product_code = product["code"] if product else "UNKNOWN"
        product_name = product["name_vi"] if product else "Không xác định"
        unit_price = int(product["price_per_kg"]) if product else 0

        billing = select_pricing(quality, label).quote(weight_gram, unit_price, product_code)
        prediction["image_url"] = rel_url
        packed = self._persist(weight_gram, product, prediction, billing, rel_url)
        with self._lock:
            self.last_result = packed

        if self.lcd:
            self.lcd.display_state("CHECKOUT", weight_gram, packed)

        print(f"[AI RESULT] {label} {quality} {weight_gram}g")
        self._emit("ai_result", packed)

    def _persist(
        self,
        weight_gram: float,
        product: dict[str, Any] | None,
        ai_result: dict[str, Any],
        billing: dict[str, Any],
        image_url: str | None,
    ) -> dict[str, Any]:
        log_id = next_log_id()
        ai_store = {k: v for k, v in ai_result.items() if k != "detections"}
        if image_url:
            ai_store["image_url"] = image_url
        doc = {
            "_id": log_id,
            "timestamp": utc_now_iso(),
            "product_code": product["code"] if product else None,
            "product_name": product["name_vi"] if product else None,
            "weight_gram": weight_gram,
            "ai_result": ai_store,
            "billing": billing,
        }
        insert_weighing_log(doc)
        revenue = billing["total_amount"] if billing.get("is_sellable") else 0
        analytics = upsert_daily_analytics(ai_result.get("quality_status", "ROTTEN"), weight_gram, revenue)
        packed = {**doc, "state": ScaleState.CHECKOUT.value, "analytics": analytics}
        return packed
