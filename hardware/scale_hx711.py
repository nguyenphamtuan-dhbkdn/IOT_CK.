"""Singleton ScaleManager — Quản lý cảm biến tải trọng Load Cell (5kg) & ADC HX711 trên Raspberry Pi 4.

Tích hợp trực tiếp thuật toán từ tests/test_scale.py:
- Chân BCM DT=GPIO5, SCK=GPIO6 (đọc từ .env: HX711_DT_PIN, HX711_SCK_PIN).
- Đọc 24 bit nhị phân + xung thứ 25 chọn Gain 128 (Channel A), bù 2 số có dấu.
- Lọc nhiễu bằng TRUNG VỊ (statistics.median), loại bỏ giá trị bão hòa/khung lỗi (0x7FFFFF, -0x800000, -1).
- Tare 21 mẫu, kiểm tra lại độ lệch ≈ 0.
- get_grams = (raw - offset) / scale_ratio, dead-zone |g| < ZERO_BAND_G thì trả về 0.0.
- scale_ratio có thể ÂM (load cell đấu ngược), bảo toàn đúng dấu, không lấy abs.
- calibration.json định dạng {"scale_ratio": <float>}, tự nạp khi khởi động.
- Đọc ngầm trong thread riêng (chu kỳ ~100-150ms), State Machine chỉ đọc giá trị đã cache.
- Cơ chế phát hiện cân "chết" sau 2 giây không có mẫu mới.
- Ở HARDWARE_MODE=real: tuyệt đối không tự chuyển sang mock khi lỗi.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from collections import deque
from typing import Any

from config import (
    CALIBRATION_FILE,
    DETECT_WEIGHT_G,
    HARDWARE_MODE,
    HX711_DT_PIN,
    HX711_INVERT_SIGNAL,
    HX711_MEDIAN_SAMPLES,
    HX711_SCK_PIN,
    HX711_ZERO_BAND_G,
    STABILITY_DELTA_G,
    STABILITY_HOLD_S,
)

logger = logging.getLogger("scale")

try:
    import RPi.GPIO as GPIO  # type: ignore

    HAS_RPI_GPIO = True
except ImportError:
    GPIO = None  # type: ignore
    HAS_RPI_GPIO = False


class ScaleManager:
    """Singleton quản lý cảm biến cân HX711 chạy ngầm phi chặn."""

    _instance: ScaleManager | None = None
    _init_lock = threading.Lock()

    def __new__(cls) -> ScaleManager:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.hardware_mode = HARDWARE_MODE
        self.dt_pin = HX711_DT_PIN
        self.sck_pin = HX711_SCK_PIN
        self.invert_signal = HX711_INVERT_SIGNAL
        self.zero_band_g = HX711_ZERO_BAND_G
        self.median_samples = HX711_MEDIAN_SAMPLES

        self._lock = threading.Lock()
        self.offset = 0.0
        self.scale_ratio = 1.0
        self.calibrated = False

        self.last_grams = 0.0
        self.current_weight = 0.0
        self.is_stable = False
        self.scale_online = False
        self.last_sample_time = 0.0
        self.last_error: str | None = None

        self._history: deque[float] = deque(maxlen=20)
        self._stable_since: float | None = None
        self._simulated_weight = 0.0

        # 1. Nạp hệ số hiệu chuẩn từ calibration.json
        self.load_calibration()

        # 2. Khởi tạo phần cứng GPIO nếu ở chế độ real
        self.hardware_available = False
        if self.hardware_mode == "real":
            if not HAS_RPI_GPIO:
                self.last_error = (
                    "HARDWARE_MODE=real nhưng thiếu thư viện RPi.GPIO! "
                    "Vui lòng cài đặt trên Raspberry Pi (sudo apt install python3-rpi.gpio). "
                    "Hệ thống TUYỆT ĐỐI không tự chuyển sang mock."
                )
                print(f"[SCALE ERROR] {self.last_error}")
            else:
                try:
                    GPIO.setwarnings(False)
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setup(self.sck_pin, GPIO.OUT)
                    GPIO.setup(self.dt_pin, GPIO.IN)
                    GPIO.output(self.sck_pin, False)
                    self.hardware_available = True
                    print(f"[SCALE] Đã thiết lập GPIO (DT={self.dt_pin}, SCK={self.sck_pin}, Invert={self.invert_signal})")

                    # Tự động tare khi khởi động (giả định đĩa cân trống)
                    time.sleep(0.2)
                    self.tare(samples=21)
                except Exception as exc:
                    self.last_error = f"Lỗi khởi tạo GPIO HX711: {exc}"
                    self.hardware_available = False
                    print(f"[SCALE ERROR] {self.last_error}. Tuyệt đối không tự chuyển sang mock.")
        else:
            # mock mode
            self.hardware_available = False
            self.scale_online = True
            print("[SCALE] Đang chạy ở chế độ MOCK (Giả lập để test giao diện trên PC)")

        # 3. Khởi động luồng đọc nền liên tục (chu kỳ ~100-150ms)
        self._stop_event = threading.Event()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="hx711-reader", daemon=True)
        self._reader_thread.start()

        self._initialized = True

    # ---------- Nạp / Lưu calibration.json ----------
    def load_calibration(self) -> None:
        """Nạp hệ số scale_ratio từ calibration.json.

        Nếu thiếu file thì cảnh báo rõ ràng trên log và admin, không âm thầm dùng 1.0.
        """
        if not CALIBRATION_FILE.exists():
            self.calibrated = False
            self.scale_ratio = 1.0
            self.last_error = f"Chưa có {CALIBRATION_FILE.name}: cần chạy python calibration.py để hiệu chuẩn."
            print(f"[SCALE CẢNH BÁO] {self.last_error}")
            return

        try:
            with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ratio = float(data.get("scale_ratio", 0))
            if ratio != 0:
                self.scale_ratio = ratio
                self.calibrated = True
                print(f"[SCALE] Đã nạp hệ số hiệu chuẩn scale_ratio = {ratio:.4f} từ {CALIBRATION_FILE.name}")
            else:
                self.calibrated = False
                self.scale_ratio = 1.0
                self.last_error = "calibration.json có scale_ratio = 0. Cần hiệu chuẩn lại!"
                print(f"[SCALE CẢNH BÁO] {self.last_error}")
        except Exception as exc:
            self.calibrated = False
            self.scale_ratio = 1.0
            self.last_error = f"Lỗi đọc {CALIBRATION_FILE.name}: {exc}. Cần hiệu chuẩn lại!"
            print(f"[SCALE CẢNH BÁO] {self.last_error}")

    def save_calibration(self, ratio: float) -> bool:
        """Lưu hệ số hiệu chuẩn vào file calibration.json định dạng {"scale_ratio": <float>}."""
        if ratio == 0:
            return False
        with self._lock:
            self.scale_ratio = float(ratio)
            self.calibrated = True

        payload = {"scale_ratio": round(float(ratio), 4)}
        try:
            with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            print(f"[SCALE] Đã lưu scale_ratio = {self.scale_ratio:.4f} vào {CALIBRATION_FILE.name}")
            return True
        except Exception as exc:
            print(f"[SCALE ERROR] Không thể ghi {CALIBRATION_FILE.name}: {exc}")
            return False

    # ---------- Đọc trực tiếp phần cứng (Port đúng từ test_scale.py) ----------
    def is_ready(self) -> bool:
        """HX711 kéo chân DT xuống mức LOW khi dữ liệu sẵn sàng."""
        if not HAS_RPI_GPIO:
            return False
        return GPIO.input(self.dt_pin) == 0

    def read_raw(self) -> int:
        """Đọc chuỗi 24-bit nhị phân từ chip HX711.

        Port nguyên bản từ test_scale.py.
        """
        if not HAS_RPI_GPIO:
            raise RuntimeError("RPi.GPIO không khả dụng.")

        timeout = 0.0
        while not self.is_ready():
            time.sleep(0.001)
            timeout += 0.001
            if timeout > 0.3:
                raise TimeoutError("HX711 không phản hồi. Kiểm tra lại dây DT/SCK và nguồn cấp.")

        count = 0
        for _ in range(24):
            GPIO.output(self.sck_pin, True)
            count = count << 1
            GPIO.output(self.sck_pin, False)
            if GPIO.input(self.dt_pin):
                count += 1

        # Xung thứ 25: chốt Gain 128 (Channel A) cho lần đọc sau
        GPIO.output(self.sck_pin, True)
        GPIO.output(self.sck_pin, False)

        # Bù 2 cho số nguyên 24-bit có dấu
        if count & 0x800000:
            count -= 0x1000000

        return -count if self.invert_signal else count

    def read_average(self, samples: int = 9) -> float:
        """Lọc nhiễu bằng TRUNG VỊ (statistics.median) qua N mẫu.

        Loại bỏ các giá trị bão hòa hoặc khung lỗi (0x7FFFFF, -0x800000, -1).
        KHÔNG dùng trung bình cộng. Port nguyên bản từ test_scale.py.
        """
        values: list[int] = []
        for _ in range(samples):
            try:
                v = self.read_raw()
                if v not in (0x7FFFFF, -0x800000, -1):
                    values.append(v)
            except TimeoutError:
                pass
            time.sleep(0.01)

        if not values:
            raise RuntimeError("Mất kết nối với HX711 (Không đọc được mẫu hợp lệ nào).")
        return float(statistics.median(values))

    def tare(self, samples: int = 21) -> bool:
        """Trừ bì (Zero balance): ghi nhận trọng lượng nền hiện tại (21 mẫu).

        Sau tare kiểm tra lại độ lệch ≈ 0.
        """
        print("[SCALE] Đang lấy điểm 0 (Tare)... Vui lòng không chạm vào đĩa cân.")
        if self.hardware_mode == "real":
            if not HAS_RPI_GPIO or not self.hardware_available:
                self.last_error = "Không thể tare: Cân phần cứng chưa kết nối hoặc lỗi GPIO."
                print(f"[SCALE ERROR] {self.last_error}")
                return False
            try:
                self.offset = self.read_average(samples)
                check = self.read_average(9) - self.offset
                print(f"[SCALE] Hoàn tất Tare! Offset={self.offset:.1f}, Độ lệch sau tare: {check:.1f} (≈ 0)")
                with self._lock:
                    self.last_grams = 0.0
                    self.current_weight = 0.0
                    self.is_stable = False
                    self._history.clear()
                    self._stable_since = None
                return True
            except Exception as exc:
                self.last_error = f"Tare thất bại: {exc}"
                print(f"[SCALE ERROR] {self.last_error}")
                return False
        else:
            # Mock mode
            self.offset = 0.0
            with self._lock:
                self.last_grams = 0.0
                self.current_weight = 0.0
                self.is_stable = False
                self._history.clear()
            print("[SCALE MOCK] Đã tare về 0.0g")
            return True

    def get_grams(self, samples: int = 9) -> float:
        """Đọc khối lượng thực tế quy đổi sang Gram.

        Dead-zone: |g| < ZERO_BAND_G thì trả về 0.0.
        Luôn lấy giá trị tuyệt đối abs() để không bao giờ ra số âm.
        """
        raw = self.read_average(samples)
        if self.scale_ratio == 0:
            grams = 0.0
        else:
            grams = abs((raw - self.offset) / self.scale_ratio)
        if grams < self.zero_band_g:
            grams = 0.0
        return float(grams)

    # ---------- Luồng đọc nền phi chặn & Cập nhật trạng thái ----------
    def _reader_loop(self) -> None:
        """Luồng đọc ngầm chu kỳ ~100-150ms, cập nhật giá trị gram mới nhất có khóa bảo vệ."""
        while not self._stop_event.is_set():
            loop_start = time.time()
            if self.hardware_mode == "real":
                if self.hardware_available and HAS_RPI_GPIO:
                    try:
                        g = self.get_grams(samples=self.median_samples)
                        now = time.time()
                        with self._lock:
                            self.last_grams = round(abs(g), 1)
                            self.last_sample_time = now
                            self.scale_online = True
                            self._update_stability(self.last_grams, now)
                    except Exception as exc:
                        now = time.time()
                        with self._lock:
                            self.last_error = f"Lỗi đọc HX711: {exc}"
                            # Cơ chế phát hiện cân chết: nếu quá 2 giây không có mẫu mới
                            if now - self.last_sample_time > 2.0:
                                self.scale_online = False
                                self.is_stable = False
                        time.sleep(0.05)
                else:
                    # Chưa kết nối phần cứng trong real mode
                    with self._lock:
                        self.scale_online = False
                        self.is_stable = False
                    time.sleep(0.2)
            else:
                # HARDWARE_MODE=mock
                now = time.time()
                with self._lock:
                    self.last_grams = round(abs(self._simulated_weight), 1)
                    self.last_sample_time = now
                    self.scale_online = True
                    self._update_stability(self.last_grams, now)
                time.sleep(0.1)

            # Đảm bảo chu kỳ lặp ~100-150ms
            elapsed = time.time() - loop_start
            time.sleep(max(0.02, 0.12 - elapsed))

    def _update_stability(self, weight: float, now: float) -> None:
        """Cập nhật độ ổn định khối lượng theo thời gian (giữ nguyên ngưỡng nghiệp vụ)."""
        weight = abs(float(weight))
        self._history.append(weight)
        prev = self._history[-2] if len(self._history) >= 2 else weight
        delta = abs(weight - prev)

        if weight >= DETECT_WEIGHT_G and delta < STABILITY_DELTA_G:
            if self._stable_since is None:
                self._stable_since = now
            self.is_stable = (now - self._stable_since) >= STABILITY_HOLD_S
        else:
            self._stable_since = None
            self.is_stable = False

        self.current_weight = weight

    def read_filtered_weight(self) -> float:
        """State Machine gọi hàm này: CHỈ ĐỌC GIÁ TRỊ ĐÃ CACHE, không gọi read_raw trực tiếp."""
        with self._lock:
            # Kiểm tra cân "chết" nếu quá 2s không có mẫu mới
            now = time.time()
            if self.hardware_mode == "real" and (now - self.last_sample_time > 2.0):
                self.scale_online = False
                self.is_stable = False
                return 0.0

            return abs(float(self.current_weight))

    def set_simulated_weight(self, grams: float) -> None:
        """Chỉ cho phép giả lập khối lượng khi HARDWARE_MODE=mock."""
        if self.hardware_mode == "real":
            print("[SCALE CẢNH BÁO] Từ chối mô phỏng: HARDWARE_MODE=real đang kích hoạt!")
            return
        with self._lock:
            self._simulated_weight = abs(float(grams))

    def cleanup(self) -> None:
        """Giải phóng tài nguyên GPIO khi tắt ứng dụng."""
        self._stop_event.set()
        if HAS_RPI_GPIO and GPIO is not None:
            try:
                GPIO.cleanup()
                print("[SCALE] Đã gọi GPIO.cleanup() thành công.")
            except Exception as exc:
                print(f"[SCALE] Lỗi khi GPIO.cleanup(): {exc}")

    def get_status(self) -> dict[str, Any]:
        """Trả về trạng thái chi tiết của HX711 cho API và Admin."""
        with self._lock:
            grams = self.last_grams
            online = self.scale_online
            stable = self.is_stable
            calibrated = self.calibrated
            ratio = self.scale_ratio
            offset = self.offset
            err = self.last_error
            last_time = self.last_sample_time

        is_alive = online and (time.time() - last_time <= 2.0 if last_time > 0 else False)
        status_str = "PASS" if (self.hardware_mode == "mock" or (is_alive and calibrated)) else "FAIL"

        if self.hardware_mode == "real":
            if not is_alive:
                msg = f"Cân HX711 MẤT KẾT NỐI (Chết tín hiệu > 2s): {err or 'Không có xung DOUT'}"
            elif not calibrated:
                msg = "Cân HX711 hoạt động nhưng CHƯA HIỆU CHUẨN (chạy calibration.py)"
            else:
                msg = f"HX711 Online, đã hiệu chuẩn (ratio={ratio:.4f})"
        else:
            msg = "Đang chạy chế độ MOCK (Giả lập trên PC)"

        return {
            "status": status_str,
            "mode": self.hardware_mode,
            "scale_online": is_alive if self.hardware_mode == "real" else True,
            "scale_calibrated": calibrated,
            "last_grams": grams,
            "message": msg,
            "details": {
                "dt_pin": self.dt_pin,
                "sck_pin": self.sck_pin,
                "invert_signal": self.invert_signal,
                "zero_band_g": self.zero_band_g,
                "scale_ratio": round(ratio, 4),
                "tare_offset": round(offset, 1),
                "is_stable": stable,
                "calibrated": calibrated,
                "last_error": err,
            },
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "weight_gram": self.current_weight,
                "is_stable": self.is_stable,
                "scale_online": self.scale_online,
                "scale_calibrated": self.calibrated,
                "hardware": self.hardware_mode == "real" and self.scale_online,
                "simulated": self.hardware_mode == "mock",
                "mode": self.hardware_mode,
                "last_error": self.last_error,
            }
