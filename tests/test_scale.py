#!/usr/bin/env python3
"""
Module kiểm thử cảm biến lực Load Cell (5kg) & ADC HX711 trên Raspberry Pi 4.
Sơ đồ chân mặc định:
  - VCC -> Pin 1 (3.3V)
  - GND -> Pin 6 (GND)
  - DT  -> Pin 29 (GPIO 5)
  - SCK -> Pin 31 (GPIO 6)

Hệ số scale_ratio được lưu vào calibration.json (cùng thư mục với file này),
tự nạp lại ở lần chạy sau nên chỉ cần hiệu chuẩn một lần.
"""

import json
import os
import statistics
import time
try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

# Cấu hình GPIO (BCM numbering)
DT_PIN = 5
SCK_PIN = 6

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
if not os.path.exists(CALIB_FILE):
    root_calib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration.json")
    if os.path.exists(root_calib):
        CALIB_FILE = root_calib

INVERT_SIGNAL = True  # True: đảo chiều để vật nặng -> giá trị DƯƠNG (load cell đang đấu ngược)
ZERO_BAND_G = 0.5  # |khối lượng| nhỏ hơn mức này thì hiển thị 0.0 g (chống nhấp nháy)


class HX711Driver:
    def __init__(self, dt_pin: int, sck_pin: int, gain: int = 128):
        self.dt = dt_pin
        self.sck = sck_pin
        self.gain = gain
        self.offset = 0
        self.scale_ratio = 1.0  # đơn vị raw trên mỗi gram
        self.calibrated = False

        if GPIO is None:
            raise RuntimeError("Thư viện RPi.GPIO không có trên hệ thống này!")

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.sck, GPIO.OUT)
        GPIO.setup(self.dt, GPIO.IN)
        GPIO.output(self.sck, False)

        self.load_calibration()

    # ---------- Lưu / nạp hệ số hiệu chuẩn ----------
    def load_calibration(self):
        try:
            with open(CALIB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ratio = float(data["scale_ratio"])
            if ratio != 0:
                self.scale_ratio = ratio
                self.calibrated = True
                print(f"-> Đã nạp hệ số hiệu chuẩn: {ratio:.4f} (từ {CALIB_FILE})")
        except FileNotFoundError:
            print("-> Chưa có calibration.json: cần hiệu chuẩn (chọn [2]) để hiển thị gram.")
        except (ValueError, KeyError, json.JSONDecodeError):
            print("[CẢNH BÁO] calibration.json bị lỗi, hãy hiệu chuẩn lại.")

    def save_calibration(self):
        with open(CALIB_FILE, "w", encoding="utf-8") as f:
            json.dump({"scale_ratio": self.scale_ratio}, f, indent=2)
        self.calibrated = True
        print(f"-> Đã lưu hệ số vào {CALIB_FILE}")

    # ---------- Đọc HX711 ----------
    def is_ready(self) -> bool:
        """HX711 kéo chân DT xuống mức LOW khi dữ liệu sẵn sàng"""
        return GPIO.input(self.dt) == 0

    def read_raw(self) -> int:
        """Đọc chuỗi 24-bit nhị phân từ chip HX711"""
        timeout = 0.0
        while not self.is_ready():
            time.sleep(0.001)
            timeout += 0.001
            if timeout > 0.3:
                raise TimeoutError("HX711 không phản hồi. Kiểm tra lại dây DT/SCK và nguồn cấp.")

        count = 0
        for _ in range(24):
            GPIO.output(self.sck, True)
            count = count << 1
            GPIO.output(self.sck, False)
            if GPIO.input(self.dt):
                count += 1

        # Xung thứ 25: chốt Gain 128 (Channel A) cho lần đọc sau
        GPIO.output(self.sck, True)
        GPIO.output(self.sck, False)

        # Bù 2 cho số nguyên 24-bit có dấu
        if count & 0x800000:
            count -= 0x1000000

        return -count if INVERT_SIGNAL else count

    def read_average(self, samples: int = 9) -> float:
        """Lọc nhiễu bằng TRUNG VỊ (median) qua N mẫu: loại được các mẫu lỗi bit
        do bit-bang GPIO bị ngắt. Giữ tên hàm cũ để code khác không phải sửa."""
        values = []
        for _ in range(samples):
            try:
                v = self.read_raw()
                # 0x7FFFFF / -0x800000 là giá trị bão hòa hoặc khung lỗi
                if v not in (0x7FFFFF, -0x800000, -1):
                    values.append(v)
            except TimeoutError:
                pass
            time.sleep(0.01)

        if not values:
            raise RuntimeError("Mất kết nối với HX711.")
        return float(statistics.median(values))

    def tare(self, samples: int = 21):
        """Trừ bì (Zero balance): ghi nhận trọng lượng nền hiện tại"""
        print("-> Đang lấy điểm 0 (Tare)... Vui lòng không chạm vào đĩa cân.")
        self.offset = self.read_average(samples)

        # Kiểm tra lại: sau khi tare, độ lệch phải xấp xỉ 0
        check = self.read_average(9) - self.offset
        print(f"-> Hoàn tất Tare! Độ lệch sau tare: {check:.0f} (≈ 0)")

    def get_grams(self, samples: int = 9) -> float:
        """Đọc khối lượng thực tế quy đổi sang Gram (lấy trị tuyệt đối chống âm)"""
        raw = self.read_average(samples)
        if self.scale_ratio == 0:
            grams = 0.0
        else:
            grams = abs((raw - self.offset) / self.scale_ratio)
        if grams < ZERO_BAND_G:
            grams = 0.0
        return float(grams)

    def cleanup(self):
        if GPIO:
            GPIO.cleanup()


def run_interactive_test():
    hx = HX711Driver(dt_pin=DT_PIN, sck_pin=SCK_PIN)
    print("=" * 60)
    print(" HỆ THỐNG KIỂM THỬ LOAD CELL & HX711 (RASPBERRY PI 4)")
    print("=" * 60)

    try:
        hx.tare(samples=21)
        print("-" * 60)

        print("Lựa chọn chế độ:")
        print(" [1] Đo khối lượng (GRAM)  - mặc định")
        print(" [2] Hiệu chuẩn (Calibration) - tìm và lưu hệ số scale")
        print(" [3] Xem giá trị thô (Raw & Delta)")
        print(" [4] Đảo chiều (vật nặng mà số bị âm thì chọn mục này)")
        choice = input("Nhập lựa chọn (1, 2, 3 hoặc 4) [Mặc định: 1]: ").strip()

        if choice == "2":
            calibrate_scale(hx)
        elif choice == "3":
            monitor_raw_signals(hx)
        elif choice == "4":
            hx.scale_ratio = -hx.scale_ratio
            print(f"-> Đã đảo dấu hệ số: {hx.scale_ratio:.4f}")
            hx.save_calibration()
            monitor_grams(hx)
        else:
            if not hx.calibrated:
                print("\n[CẢNH BÁO] Chưa hiệu chuẩn nên số gram chưa chính xác. Hãy chọn [2] trước.")
                ans = input("Hiệu chuẩn ngay bây giờ? (y/N): ").strip().lower()
                if ans == "y":
                    calibrate_scale(hx)
                    return
            monitor_grams(hx)

    except KeyboardInterrupt:
        print("\n[INFO] Đã dừng chương trình kiểm tra.")
    except Exception as e:
        print(f"\n[LỖI] {e}")
    finally:
        hx.cleanup()
        print("[INFO] Đã giải phóng tài nguyên GPIO.")


def monitor_grams(hx: HX711Driver):
    print("\nĐang đo khối lượng (Nhấn Ctrl + C để thoát):")
    while True:
        grams = hx.get_grams(samples=7)
        print(f"Khối lượng: {grams:8.1f} g")
        time.sleep(0.25)


def monitor_raw_signals(hx: HX711Driver):
    print("\nBắt đầu đọc dữ liệu thô (Nhấn Ctrl + C để thoát):")
    print(f"{'Giá trị Raw':>15} | {'Độ lệch (Delta)':>15} | {'Trạng thái lực'}")
    print("-" * 55)

    while True:
        raw = hx.read_average(samples=5)
        delta = raw - hx.offset

        status = "Ổn định"
        if delta > 1000:
            status = "Đang nhấn (+)"
        elif delta < -1000:
            status = "Kéo ngược (-)"

        print(f"{raw:15.0f} | {delta:15.0f} | {status}")
        time.sleep(0.2)


def calibrate_scale(hx: HX711Driver):
    print("\n--- BẮT ĐẦU HIỆU CHUẨN KHỐI LƯỢNG ---")
    try:
        known_weight = float(input("Nhập khối lượng vật mẫu (gram, ví dụ 500): ").strip())
    except ValueError:
        print("[LỖI] Khối lượng không hợp lệ.")
        return
    if known_weight <= 0:
        print("[LỖI] Khối lượng phải lớn hơn 0.")
        return

    input("Đặt vật mẫu lên giữa mặt đĩa cân, sau đó nhấn Enter để đo...")
    print("Đang đo giá trị chịu tải...")
    raw_loaded = hx.read_average(samples=31)
    delta = raw_loaded - hx.offset

    if abs(delta) < 500:
        print("[CẢNH BÁO] Độ lệch quá nhỏ! Kiểm tra vật mẫu đã đặt lên chưa hoặc cơ cấu cân có bị kẹt không.")
        return

    hx.scale_ratio = delta / known_weight
    print("-" * 60)
    print(f"-> HỆ SỐ SCALE_RATIO: {hx.scale_ratio:.4f}")
    hx.save_calibration()
    print("-" * 60)

    print("\nBắt đầu hiển thị khối lượng theo Gram (Nhấn Ctrl + C để thoát):")
    monitor_grams(hx)


if __name__ == "__main__":
    run_interactive_test()

