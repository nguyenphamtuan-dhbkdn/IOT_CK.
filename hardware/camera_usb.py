"""Singleton CameraManager — Camera USB V4L2 640x480 @ 30FPS, MJPG, BUFFERSIZE=1.

Chạy thread đọc nền duy nhất (Producer), lưu frame mới nhất dùng chung cho
/video_feed (JPEG quality 80) và suy luận AI (get_frame). Tự động kết nối lại
khi thiết bị bị rút hoặc mất tín hiệu. Không mở camera nhiều lần.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from config import (
    CAMERA_BUFFERSIZE,
    CAMERA_DEVICE,
    CAMERA_FPS,
    CAMERA_FOURCC,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    CAPTURE_DIR,
)

logger = logging.getLogger("camera")


class CameraManager:
    """Singleton quản lý Camera USB duy nhất của hệ thống."""

    _instance: CameraManager | None = None
    _init_lock = threading.Lock()

    def __new__(cls) -> CameraManager:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.camera_index = CAMERA_INDEX
        self.device_path = CAMERA_DEVICE
        self.width = CAMERA_WIDTH
        self.height = CAMERA_HEIGHT
        self.fps = CAMERA_FPS
        self.buffersize = CAMERA_BUFFERSIZE

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._jpeg_bytes: bytes | None = None

        self._cap: cv2.VideoCapture | None = None
        self.hardware_available = False
        self._running = False
        self._thread: threading.Thread | None = None

        self._consecutive_errors = 0
        self._reconnect_attempts = 0
        self._last_reconnect_time = 0.0

        # Mở camera lần đầu
        self._open_capture()

        self._initialized = True
        logger.info(
            f"[CAMERA] Singleton CameraManager đã khởi tạo (Index={self.camera_index}, "
            f"V4L2, {self.width}x{self.height} @ {self.fps}FPS, BUFFERSIZE={self.buffersize})"
        )

    def _open_capture(self) -> bool:
        """Mở VideoCapture với backend V4L2 và cấu hình MJPG 640x480 @ 30fps."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        # Danh sách nguồn thử nghiệm: CAMERA_INDEX, CAMERA_DEVICE, 0, 1
        candidates: list[int | str] = [self.camera_index]
        if self.device_path and self.device_path not in candidates:
            candidates.append(self.device_path)
        for alt in (0, 1):
            if alt not in candidates:
                candidates.append(alt)

        for src in candidates:
            try:
                # Ưu tiên backend CAP_V4L2 trên Linux (Raspberry Pi OS)
                cap = None
                if hasattr(cv2, "CAP_V4L2") and os.name != "nt":
                    try:
                        cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
                    except Exception as e:
                        logger.debug(f"[CAMERA] Thử CAP_V4L2 với {src} thất bại: {e}")
                        cap = None

                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(src)

                if cap is not None and cap.isOpened():
                    # Thiết lập FOURCC = MJPG
                    try:
                        fourcc = cv2.VideoWriter_fourcc(*CAMERA_FOURCC)
                        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                    except Exception as e:
                        logger.warning(f"[CAMERA] Không thể set FOURCC MJPG: {e}")

                    # Thiết lập độ phân giải 640x480
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))

                    # Thiết lập FPS = 30
                    cap.set(cv2.CAP_PROP_FPS, float(self.fps))

                    # Thiết lập BUFFERSIZE = 1 (tránh trễ khung hình trên V4L2)
                    try:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, float(self.buffersize))
                    except Exception:
                        pass

                    # Đọc thử 1 frame kiểm tra
                    ok, test_frame = cap.read()
                    if ok and test_frame is not None and test_frame.size > 0:
                        self._cap = cap
                        self.hardware_available = True
                        self._consecutive_errors = 0
                        print(f"[CAMERA] Kết nối thành công nguồn {src} (CAP_V4L2 / MJPG 640x480 @ 30FPS)")
                        return True
                    else:
                        cap.release()
            except Exception as exc:
                logger.debug(f"[CAMERA] Lỗi khi mở nguồn {src}: {exc}")

        print("[CAMERA] Không mở được Camera phần cứng thật — chuyển sang chế độ chờ kết nối lại")
        self._cap = None
        self.hardware_available = False
        return False

    def _close_capture(self) -> None:
        """Đóng an toàn capture."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self.hardware_available = False

    def start(self) -> None:
        """Khởi động luồng đọc nền (Producer thread)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera-producer", daemon=True)
        self._thread.start()
        print("[CAMERA] Đã bắt đầu thread đọc nền (camera-producer)")

    def stop(self) -> None:
        """Dừng luồng đọc nền và giải phóng camera."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._close_capture()
        print("[CAMERA] Đã giải phóng Camera")

    def _synthetic_standby_frame(self, message: str = "DANG KET NOI LAI CAMERA...") -> np.ndarray:
        """Khung hình giả lập khi mất kết nối hoặc không có camera."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (20, 24, 20)
        t = time.time()
        cx, cy = self.width // 2, self.height // 2

        # Vòng tròn radar hiển thị trạng thái
        pulse = int(12 * np.sin(t * 3))
        cv2.circle(frame, (cx, cy - 20), 70 + pulse, (40, 70, 50), 2)
        cv2.circle(frame, (cx, cy - 20), 40, (50, 120, 60), -1)

        cv2.putText(
            frame,
            "SMART SCALE AI - CAMERA STANDBY",
            (80, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (200, 240, 200),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            message,
            (110, self.height - 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (120, 180, 255) if self.hardware_available else (100, 130, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"V4L2: /dev/video{self.camera_index} | 640x480 @ 30FPS",
            (130, self.height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (140, 160, 140),
            1,
            cv2.LINE_AA,
        )
        return frame

    def _loop(self) -> None:
        """Vòng lặp producer: liên tục đọc frame, nén JPEG 80, và tự kết nối lại nếu bị rút."""
        target_delay = 1.0 / max(10, self.fps)

        while self._running:
            loop_start = time.time()

            if self._cap is not None and self.hardware_available:
                ok, raw_frame = self._cap.read()
                if ok and raw_frame is not None and raw_frame.size > 0:
                    self._consecutive_errors = 0
                    frame = raw_frame
                else:
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= 5:
                        print("[CAMERA] Mất tín hiệu camera USB (thiết bị bị rút hoặc lỗi bus). Đang ngắt kết nối để thử lại...")
                        self._close_capture()
                    frame = self._synthetic_standby_frame("MAT TIN HIEU CAMERA - DANG THU LAI")
            else:
                # Đang không có camera phần cứng: định kỳ 2 giây thử mở lại (reconnect)
                now = time.time()
                if now - self._last_reconnect_time > 2.0:
                    self._last_reconnect_time = now
                    self._reconnect_attempts += 1
                    if self._open_capture():
                        print(f"[CAMERA] Tự động kết nối lại camera thành công sau {self._reconnect_attempts} lần thử!")
                        self._reconnect_attempts = 0
                        continue

                frame = self._synthetic_standby_frame("KHONG TIM THAY CAMERA USB (V4L2)")

            # Nén sẵn JPEG chất lượng 80 cho /video_feed
            ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            jpeg_bytes = buf.tobytes() if ok_enc else None

            # Lưu vào bộ đệm duy nhất dùng chung cho AI và Web stream
            with self._lock:
                self._frame = frame
                self._jpeg_bytes = jpeg_bytes

            elapsed = time.time() - loop_start
            sleep_time = max(0.001, target_delay - elapsed)
            time.sleep(sleep_time)

    def get_frame(self) -> np.ndarray | None:
        """Lấy 1 bản sao khung hình mới nhất cho model AI suy luận (thread-safe)."""
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def mjpeg_bytes(self) -> bytes | None:
        """Lấy luồng bytes JPEG (quality 80) cho /video_feed mà không cần nén lại."""
        with self._lock:
            return self._jpeg_bytes

    def capture_jpeg(self, path: Path | None = None) -> tuple[np.ndarray | None, str | None]:
        """Chụp ảnh từ frame mới nhất và lưu ra file ảnh tĩnh."""
        frame = self.get_frame()
        if frame is None:
            return None, None
        if path is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = CAPTURE_DIR / f"{stamp}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), frame)
        rel = f"/static/captures/{path.name}"
        return frame, rel

    def get_status(self) -> dict:
        """Trả về trạng thái phần cứng của Camera để phục vụ check_hardware và API."""
        return {
            "status": "PASS" if self.hardware_available else "FAIL",
            "available": self.hardware_available,
            "message": "Camera USB V4L2 kết nối và hoạt động bình thường"
            if self.hardware_available
            else "Camera USB chưa kết nối hoặc không tìm thấy thiết bị /dev/video*",
            "details": {
                "index": self.camera_index,
                "device": self.device_path,
                "resolution": f"{self.width}x{self.height}",
                "fps": self.fps,
                "fourcc": CAMERA_FOURCC,
                "buffersize": self.buffersize,
                "is_running": self._running,
                "reconnect_attempts": self._reconnect_attempts,
            },
        }
